"""Step 6 — dbt project and semantic-layer generation (POD-307).

Only approved or auto-accepted mappings are used. Output is deterministic: the same
`ResolvedMapping` always produces byte-identical files and therefore the same manifest hash.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from src.domain.errors import ApprovalRequired
from src.domain.hashing import content_hash, sha256_text
from src.domain.models import Confidence, Finding, FindingType, ReviewGate, StepName
from src.domain.ontology import Ontology
from src.domain.project_models import (
    AcceptedMapping,
    ArtifactBundle,
    ArtifactFile,
    ResolvedMapping,
    SchemaProfile,
    SemanticType,
)
from src.services.approvals import is_valid
from src.settings import PROJECT_ROOT
from src.workflows.contracts import StepContext, StepResult, make_evidence

TEMPLATES = PROJECT_ROOT / "templates" / "dbt"
CAST = {
    "string": "varchar",
    "integer": "bigint",
    "decimal": "decimal(18, 2)",
    "date": "date",
    "timestamp": "timestamp",
    "boolean": "boolean",
}


def _env() -> Environment:
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        undefined=StrictUndefined,
        variable_start_string="[[",
        variable_end_string="]]",
        block_start_string="[%",
        block_end_string="%]",
        trim_blocks=True,
        lstrip_blocks=True,
        keep_trailing_newline=True,
        autoescape=False,  # noqa: S701 - renders SQL/YAML, never HTML
    )


def _q(ident: str) -> str:
    return '"' + ident.replace('"', '""') + '"'


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", name.lower()).strip("_")


def _yaml(data: Any) -> str:
    return yaml.safe_dump(data, sort_keys=False, width=110, allow_unicode=False)


@dataclass
class OutCol:
    name: str
    expr: str
    field: str | None  # canonical field (None for derived)
    ftype: str
    source: str  # source column


@dataclass
class TableModel:
    table: str
    schema: str
    name: str
    entity: str
    stg: str
    int_: str
    columns: list[OutCol] = field(default_factory=list)
    field_names: dict[str, str] = field(default_factory=dict)  # canonical field -> output column
    notes: list[str] = field(default_factory=list)
    parents: list[dict[str, str]] = field(default_factory=list)


class Generator:
    def __init__(
        self, resolved: ResolvedMapping, profile: SchemaProfile, ontology: Ontology, company_id: str, as_of: date | None
    ) -> None:
        self.r = resolved
        self.profile = profile
        self.ont = ontology
        self.company_id = company_id
        self.as_of = as_of or date.today()
        self.env = _env()
        self.files: dict[str, str] = {}
        self.tables: dict[str, TableModel] = {}
        self.marts: dict[str, dict[str, Any]] = {}  # entity -> {name, columns}
        self.not_generated: dict[str, str] = {}
        self.generated_metrics: list[str] = []

    # ------------------------------------------------------------------ helpers

    def _expr(self, m: AcceptedMapping) -> tuple[str, str]:
        fdef = self.ont.field(m.canonical_entity, m.canonical_field)
        col = _q(m.source_column)
        if m.pii_handling == "hash":
            return f"sha256(cast({col} as varchar))", f"{m.canonical_field}_hash"
        if m.transform == "cents_to_major":
            return f"cast(cast({col} as decimal(18, 2)) / 100 as decimal(18, 2))", m.canonical_field
        if m.transform == "parse_mixed_date":
            return (
                f"cast(coalesce(try_strptime(cast({col} as varchar), '%Y-%m-%d'), "
                f"try_strptime(cast({col} as varchar), '%m/%d/%Y')) as date)"
            ), m.canonical_field
        return f"cast({col} as {CAST[fdef.type]})", m.canonical_field

    def _filter_expr(self, table: str) -> str:
        parts = []
        for f in self.r.filters:
            if f.table != table:
                continue
            if f.kind == "exclude_true":
                parts.append(f"coalesce(cast({_q(f.column)} as boolean), false)")
            else:
                value = (f.value or "").replace("'", "''")
                parts.append(f"coalesce(starts_with(cast({_q(f.column)} as varchar), '{value}'), false)")
        return "(" + " or ".join(parts) + ")" if parts else "false"

    def _source_col(self, table: str, column: str) -> str | None:
        """Canonical output name of a source column, if it was accepted and not dropped."""
        tm = self.tables.get(table)
        if tm is None:
            return None
        for c in tm.columns:
            if c.source == column and not c.name.endswith("_hash"):
                return c.name
        return None

    # ------------------------------------------------------------------ staging

    def build_staging(self) -> None:
        by_table: dict[str, list[AcceptedMapping]] = {}
        for m in self.r.accepted:
            by_table.setdefault(m.source_table, []).append(m)
        for table in sorted(by_table):
            schema, name = table.split(".", 1)
            entity = self.r.entity_tables[table]
            tm = TableModel(
                table=table,
                schema=schema,
                name=name,
                entity=entity,
                stg=f"stg_{_slug(schema)}__{_slug(name)}",
                int_=f"int_{_slug(schema)}__{_slug(name)}",
            )
            tp = self.profile.table(table)
            for m in sorted(by_table[table], key=lambda m: tp.column(m.source_column).ordinal):
                if m.pii_handling == "exclude":
                    tm.notes.append(f"{m.source_column} -> {m.canonical_field}: excluded (PII, never materialized)")
                    continue
                expr, out = self._expr(m)
                if m.transform:
                    tm.notes.append(f"{m.source_column} -> {out}: reviewed transform {m.transform}")
                if m.pii_handling == "hash":
                    tm.notes.append(f"{m.source_column} -> {out}: PII hashed with sha256")
                ftype = self.ont.field(m.canonical_entity, m.canonical_field).type
                tm.columns.append(OutCol(out, expr, m.canonical_field, ftype, m.source_column))
                if m.pii_handling != "hash":
                    tm.field_names[m.canonical_field] = out
            if not tm.columns:
                continue
            self.tables[table] = tm
            sql = self.env.get_template("staging.sql.j2").render(
                schema=schema,
                table=name,
                entity=entity,
                notes=tm.notes,
                columns=[{"name": c.name, "expr": c.expr} for c in tm.columns],
                excluded_expr=self._filter_expr(table),
            )
            self.files[f"models/staging/{_slug(schema)}/{tm.stg}.sql"] = sql

        for schema in sorted({tm.schema for tm in self.tables.values()}):
            tables = sorted((tm for tm in self.tables.values() if tm.schema == schema), key=lambda t: t.name)
            src = {
                "version": 2,
                "sources": [
                    {
                        "name": schema,
                        "database": "src",
                        "schema": schema,
                        "description": f"Read-only source schema {schema} of {self.company_id} (sandbox attach).",
                        "tables": [
                            {"name": tm.name, "description": f"Profiled source table; entity {tm.entity}."}
                            for tm in tables
                        ],
                    }
                ],
            }
            self.files[f"models/staging/{_slug(schema)}/_sources.yml"] = _yaml(src)
            models = [self._staging_yaml(tm) for tm in tables]
            self.files[f"models/staging/{_slug(schema)}/_models.yml"] = _yaml({"version": 2, "models": models})

    def _staging_yaml(self, tm: TableModel) -> dict[str, Any]:
        tp = self.profile.table(tm.table)
        cand_pk = self._pk_fields(tm)
        cols: list[dict[str, Any]] = []
        for c in tm.columns:
            tests: list[Any] = []
            src_col = next(
                (
                    m.source_column
                    for m in self.r.for_table(tm.table)
                    if m.canonical_field == c.field and m.pii_handling != "exclude"
                ),
                None,
            )
            prof = tp.column(src_col) if src_col else None
            if len(cand_pk) == 1 and c.name == cand_pk[0]:
                tests += ["unique", "not_null"]
            elif (
                prof is not None
                and c.field
                and self.ont.field(tm.entity, c.field).required
                and prof.non_null_count == prof.row_count
                and prof.row_count
            ):
                tests.append("not_null")
            if (
                prof is not None
                and c.ftype in {"decimal", "integer"}
                and (prof.inferred_semantic_type in {SemanticType.MONEY, SemanticType.QUANTITY})
            ):
                tests.append("non_negative")
            if prof is not None and prof.category_values and c.ftype == "string" and not c.name.endswith("_hash"):
                tests.append({"accepted_values": {"arguments": {"values": list(prof.category_values)}}})
            for j in self.r.joins:
                if j.left_table == tm.table and prof is not None and j.left_columns[0] == prof.column:
                    parent = self.tables.get(j.right_table)
                    pf = parent and self._source_col(j.right_table, j.right_columns[0])
                    if parent and pf:
                        test: dict[str, Any] = {
                            "relationships": {"arguments": {"to": f"ref('{parent.stg}')", "field": pf}}
                        }
                        if j.orphan_rate > 0:
                            test["relationships"]["config"] = {"severity": "warn"}
                        tests.append(test)
            entry: dict[str, Any] = {"name": c.name}
            if tests:
                entry["data_tests"] = tests
            cols.append(entry)
        model: dict[str, Any] = {
            "name": tm.stg,
            "description": f"Staging for {tm.table} ({tm.entity}).",
            "columns": cols,
        }
        if len(cand_pk) > 1:
            model["data_tests"] = [{"portco_unique_combination": {"arguments": {"combination_of_columns": cand_pk}}}]
        return model

    def _pk_fields(self, tm: TableModel) -> list[str]:
        id_fields = self.ont.entities[tm.entity].id_fields
        present = [tm.field_names[f] for f in id_fields if f in tm.field_names]
        return present if len(present) == len(id_fields) else []

    # ------------------------------------------------------------------ scoping (intermediate)

    def build_intermediate(self) -> None:
        edges: dict[str, list[dict[str, str]]] = {t: [] for t in self.tables}
        for j in self.r.joins:
            child, parent = self.tables.get(j.left_table), self.tables.get(j.right_table)
            if not child or not parent or child.entity == parent.entity or j.cardinality not in {"N:1", "1:1"}:
                continue
            cf = self._source_col(j.left_table, j.left_columns[0])
            pf = self._source_col(j.right_table, j.right_columns[0])
            if cf and pf:
                edges[child.table].append({"parent": parent.table, "child_field": cf, "parent_field": pf})
        order = self._topo(edges)
        for table in order:
            tm = self.tables[table]
            tm.parents = [
                {
                    "parent_model": self.tables[e["parent"]].int_,
                    "parent_field": e["parent_field"],
                    "child_field": e["child_field"],
                }
                for e in edges[table]
            ]
            sql = self.env.get_template("intermediate.sql.j2").render(
                table=table, staging_model=tm.stg, parents=tm.parents
            )
            self.files[f"models/intermediate/{tm.int_}.sql"] = sql

    @staticmethod
    def _topo(edges: dict[str, list[dict[str, str]]]) -> list[str]:
        order: list[str] = []
        state: dict[str, int] = {}

        def visit(node: str) -> None:
            state[node] = 1
            keep = []
            for e in edges[node]:
                if state.get(e["parent"]) == 1:
                    continue  # break cycles by dropping the back edge
                keep.append(e)
                if state.get(e["parent"]) is None:
                    visit(e["parent"])
            edges[node] = keep
            state[node] = 2
            order.append(node)

        for node in sorted(edges):
            if node not in state:
                visit(node)
        return order

    # ------------------------------------------------------------------ marts

    def build_marts(self) -> None:
        marts_yaml = []
        for entity, primary in sorted(self.r.primary_tables.items()):
            ptm = self.tables.get(primary)
            if ptm is None:
                continue
            edef = self.ont.entities[entity]
            fields = [c.name for c in ptm.columns]
            present = set(fields)
            enrich, enrich_joins = [], []
            for j in self.r.joins:
                if j.left_table != primary:
                    continue
                other = self.tables.get(j.right_table)
                if not other or other.entity != entity:
                    continue
                lf = self._source_col(primary, j.left_columns[0])
                rf = self._source_col(j.right_table, j.right_columns[0])
                if not lf or not rf:
                    continue
                alias = str(len(enrich_joins) + 1)
                enrich_joins.append({"model": other.int_, "alias": alias, "left_field": lf, "right_field": rf})
                for c in other.columns:
                    if c.name not in present:
                        enrich.append({"alias": alias, "field": c.name})
                        present.add(c.name)
            lookups, lookup_joins = [], []
            for lk in edef.lookups:
                qtable = self.r.primary_tables.get(lk.from_entity)
                qtm = self.tables.get(qtable) if qtable else None
                if not qtm or lk.field not in qtm.field_names or lk.join_on not in ptm.field_names:
                    continue
                if self._pk_fields(qtm) != [qtm.field_names.get(lk.join_on)]:
                    continue
                alias = str(len(lookup_joins) + 1)
                lookup_joins.append(
                    {
                        "model": qtm.int_,
                        "alias": alias,
                        "left_field": ptm.field_names[lk.join_on],
                        "right_field": qtm.field_names[lk.join_on],
                    }
                )
                lookups.append({"alias": alias, "field": qtm.field_names[lk.field]})
                present.add(qtm.field_names[lk.field])
            sql = self.env.get_template("mart.sql.j2").render(
                mart=edef.mart,
                entity=entity,
                primary_table=primary,
                fields=fields,
                enrich=enrich,
                lookups=lookups,
                scoped_model=ptm.int_,
                enrich_joins=enrich_joins,
                lookup_joins=lookup_joins,
            )
            pk = self._pk_fields(ptm)
            if len(pk) > 1:
                sql = sql.replace(
                    "    true as _in_scope",
                    "    "
                    + " || '|' || ".join(f"cast(p.{c} as varchar)" for c in pk)
                    + f" as {entity}_key,\n    true as _in_scope",
                )
                present.add(f"{entity}_key")
            self.files[f"models/marts/{edef.mart}.sql"] = sql
            self.marts[entity] = {"name": edef.mart, "columns": present, "pk": pk}
            cols = []
            if len(pk) == 1:
                cols.append({"name": pk[0], "data_tests": ["unique", "not_null"]})
            elif len(pk) > 1:
                cols.append({"name": f"{entity}_key", "data_tests": ["unique", "not_null"]})
            marts_yaml.append(
                {"name": edef.mart, "description": f"{edef.description} Source of record: {primary}.", "columns": cols}
            )

        sub = self.marts.get("subscription")
        if sub and {"mrr", "start_date", "end_date", "currency", "customer_id"} <= sub["columns"]:
            self.files["models/marts/fct_mrr_monthly.sql"] = self.env.get_template("mrr_monthly.sql.j2").render()
            self.marts["_mrr"] = {
                "name": "fct_mrr_monthly",
                "columns": {"mrr_snapshot_id", "month_end", "customer_id", "currency", "mrr"},
                "pk": ["mrr_snapshot_id"],
            }
            marts_yaml.append(
                {
                    "name": "fct_mrr_monthly",
                    "description": "Month-end MRR per customer and currency.",
                    "columns": [
                        {"name": "mrr_snapshot_id", "data_tests": ["unique", "not_null"]},
                        {"name": "mrr", "data_tests": ["non_negative"]},
                    ],
                }
            )
        self.files["models/marts/metricflow_time_spine.sql"] = self.env.get_template("time_spine.sql.j2").render()
        marts_yaml.append(
            {
                "name": "metricflow_time_spine",
                "description": "Daily time spine for the semantic layer.",
                "time_spine": {"standard_granularity_column": "date_day"},
                "columns": [{"name": "date_day", "granularity": "day"}],
            }
        )
        self.files["models/marts/_marts.yml"] = _yaml({"version": 2, "models": marts_yaml})

    # ------------------------------------------------------------------ semantic layer

    SEMANTIC_MODELS = {
        "fct_invoice": {
            "entity": "invoice",
            "primary": ("invoice", "invoice_id"),
            "time": "invoice_date",
            "dims": ["currency", "status"],
            "foreign": [("customer", "customer_id")],
        },
        "fct_mrr_monthly": {
            "entity": "_mrr",
            "primary": ("mrr_snapshot", "mrr_snapshot_id"),
            "time": "month_end",
            "dims": ["currency"],
            "foreign": [("customer", "customer_id")],
        },
        "fct_gl_entry": {
            "entity": "gl_entry",
            "primary": ("gl_entry", "gl_entry_key"),
            "time": "posting_date",
            "dims": ["account_type", "entity_code"],
            "foreign": [],
        },
    }

    def build_semantic(self) -> None:
        mart_cols = {m["name"]: m["columns"] for m in self.marts.values()}
        accepted = {(m.canonical_entity, m.canonical_field) for m in self.r.accepted if m.pii_handling != "exclude"}
        measures: dict[str, list[dict[str, Any]]] = {}
        simple_ok: set[str] = set()
        for name, mdef in sorted(self.ont.metrics.items()):
            sem = mdef.semantic
            missing = [ref for ref in mdef.requires if tuple(ref.split(".", 1)) not in accepted]
            if name in self.r.metrics_needing_evidence or missing:
                self.not_generated[name] = "NEEDS_EVIDENCE: no approved mapping for " + ", ".join(
                    missing or ["required fields"]
                )
                continue
            if sem.kind == "reference_only":
                self.not_generated[name] = "reference_only: computed by the reference service, not the semantic layer"
                continue
            if sem.kind == "simple":
                assert sem.model
                assert sem.measure
                assert sem.agg
                if sem.model not in mart_cols:
                    self.not_generated[name] = f"NEEDS_EVIDENCE: model {sem.model} was not generated"
                    continue
                measures.setdefault(sem.model, []).append(
                    {
                        "name": sem.measure,
                        "agg": sem.agg,
                        "expr": sem.expr or sem.measure,
                        "description": mdef.description,
                    }
                )
                simple_ok.add(name)
        for name, mdef in sorted(self.ont.metrics.items()):
            if mdef.semantic.kind == "derived" and name not in self.not_generated:
                if all(d in simple_ok for d in mdef.semantic.depends_on):
                    simple_ok.add(name)
                else:
                    self.not_generated[name] = "NEEDS_EVIDENCE: depends on metrics that were not generated"

        sms = []
        for model, spec in self.SEMANTIC_MODELS.items():
            if model not in measures:
                continue
            cols = mart_cols[model]
            ent_name, ent_expr = spec["primary"]
            sm: dict[str, Any] = {
                "name": f"sm_{model}",
                "model": f"ref('{model}')",
                "defaults": {"agg_time_dimension": spec["time"]},
                "entities": [{"name": ent_name, "type": "primary", "expr": ent_expr}]
                + [{"name": n, "type": "foreign", "expr": e} for n, e in spec["foreign"] if e in cols],
                "dimensions": [{"name": spec["time"], "type": "time", "type_params": {"time_granularity": "day"}}]
                + [{"name": d, "type": "categorical"} for d in spec["dims"] if d in cols],
                "measures": measures[model],
            }
            sms.append(sm)
        metrics = []
        for name in sorted(simple_ok):
            mdef = self.ont.metrics[name]
            entry: dict[str, Any] = {
                "name": name,
                "label": name.replace("_", " ").title(),
                "description": mdef.description + (f" Pitfall: {mdef.pitfall}" if mdef.pitfall else ""),
            }
            if mdef.semantic.kind == "simple":
                entry |= {"type": "simple", "type_params": {"measure": mdef.semantic.measure}}
            else:
                entry |= {
                    "type": "derived",
                    "type_params": {
                        "expr": mdef.semantic.expr,
                        "metrics": [{"name": d} for d in mdef.semantic.depends_on],
                    },
                }
            metrics.append(entry)
            self.files[f"models/semantic/metrics/{name}.yml"] = _yaml({"metrics": [entry]})
        if sms:
            self.files["models/semantic/semantic_models.yml"] = _yaml({"semantic_models": sms})
        self.generated_metrics = sorted(simple_ok)

    # ------------------------------------------------------------------ project

    def build(self) -> dict[str, str]:
        self.build_staging()
        self.build_intermediate()
        self.build_marts()
        self.build_semantic()
        project_name = f"portco_{_slug(self.company_id)}"
        as_of_month = date(self.as_of.year, self.as_of.month, 1).isoformat()
        self.files["dbt_project.yml"] = self.env.get_template("dbt_project.yml.j2").render(
            company_id=self.company_id,
            project_name=project_name,
            mapping_hash=self.r.mapping_hash,
            as_of_month=as_of_month,
        )
        self.files["profiles.yml"] = (TEMPLATES / "profiles.yml.j2").read_text(encoding="utf-8")
        for macro in sorted((TEMPLATES / "macros").glob("*.sql")):
            self.files[f"macros/{macro.name}"] = macro.read_text(encoding="utf-8")
        self.files["README.md"] = self._readme(project_name)
        return dict(sorted(self.files.items()))

    def _readme(self, project_name: str) -> str:
        lines = [
            f"# {project_name}",
            "",
            "Generated by portco-data-onboarding from a human-reviewed mapping. Do not edit by hand.",
            "",
            f"- Mapping hash: `{self.r.mapping_hash}`",
            f"- Reviewed mapping approvals: {', '.join(str(a) for a in self.r.approval_ids) or 'none required'}",
            f"- Generated metrics: {', '.join(self.generated_metrics) or 'none'}",
            "",
            "## Metrics not generated",
            "",
        ]
        lines += [f"- `{m}`: {why}" for m, why in sorted(self.not_generated.items())]
        return "\n".join(lines) + "\n"


def _kind(path: str) -> str:
    if path.startswith("models/staging"):
        return "staging"
    if path.startswith("models/intermediate"):
        return "intermediate"
    if path.startswith("models/marts"):
        return "mart"
    if path.startswith("models/semantic"):
        return "semantic"
    if path.startswith("macros"):
        return "macro"
    return "project"


def generate_artifacts(ctx: StepContext) -> StepResult:
    resolved = ctx.get(StepName.MAPPING_REVIEW, ResolvedMapping)
    profile = ctx.get(StepName.SCHEMA_PROFILING, SchemaProfile)
    # Fail closed: every approval the reviewed mapping relies on must still be valid (ADR-0004).
    by_id = {a.approval_id: a for a in ctx.approvals}
    for approval_id in resolved.approval_ids:
        a = by_id.get(approval_id)
        if a is None or a.gate != ReviewGate.MAPPING_REVIEW or not is_valid(a, resolved.mapping_hash):
            raise ApprovalRequired("the mapping approval this bundle depends on is missing, revoked or stale")
    gen = Generator(resolved, profile, ctx.ontology, ctx.run.company_id, ctx.adapter().spec.as_of)
    files = gen.build()
    entries = []
    for path, text in files.items():
        ref = ctx.blobs.put_bytes(text.encode("utf-8"))
        entries.append(ArtifactFile(path=path, sha256=ref, kind=_kind(path), size=len(text.encode("utf-8"))))
    manifest_hash = content_hash([(f.path, f.sha256) for f in entries])
    models = sorted(p.rsplit("/", 1)[1][:-4] for p in files if p.endswith(".sql") and p.startswith("models/"))
    bundle = ArtifactBundle(
        mapping_hash=resolved.content_hash(),
        files=entries,
        manifest_hash=manifest_hash,
        generated_metrics=gen.generated_metrics,
        not_generated=gen.not_generated,
        models=models,
    )
    payload = {
        "manifest_hash": manifest_hash,
        "files": [(f.path, f.sha256) for f in entries],
        "mapping_hash": resolved.mapping_hash,
    }
    ev = make_evidence(ctx, f"bundle://{ctx.run.run_id}/{manifest_hash}", "artifact_bundle", payload)
    findings = [
        Finding(
            code="ARTIFACTS_GENERATED",
            title="dbt project and semantic layer generated",
            finding_type=FindingType.CALCULATION,
            statement=(
                f"{len(models)} models, {len(gen.generated_metrics)} metrics generated; "
                f"{len(gen.not_generated)} metrics not generated (reasons recorded). Manifest {manifest_hash[:12]}."
            ),
            confidence=Confidence.HIGH,
            evidence=[ev.ref()],
            metadata={"manifest_hash": manifest_hash},
        )
    ]
    return StepResult(
        output=bundle,
        evidence=[ev],
        findings=findings,
        audit=[
            (
                "artifacts_generated",
                {
                    "manifest_hash": manifest_hash,
                    "files": len(entries),
                    "metrics": gen.generated_metrics,
                    "sha256_readme": sha256_text(files["README.md"]),
                },
            )
        ],
    )
