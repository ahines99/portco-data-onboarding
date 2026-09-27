# MetricFlow compatibility investigation

2026-09-27. Outcome: **deferred; not runtime-certified**. The application's working environment was
not changed to install MetricFlow. An isolated `uv tool run` environment installed `dbt-metricflow`
0.15.0 and `dbt-duckdb`, resolving dbt-core 1.12.5. The actual generated fixture-A sandbox project and
its warehouse/source paths were used; no model API or external warehouse was involved.

Following the [official command documentation](https://docs.getdbt.com/docs/build/metricflow-commands),
the experiment ran `dbt parse`, then `mf validate-configs --skip-dw`. After supplying the required
`PORTCO_DBT_WAREHOUSE`, `PORTCO_DBT_SOURCE` and `DBT_PROFILES_DIR`, parsing generated the manifest.
MetricFlow validation then failed while loading it:

```text
Exception found when parsing manifest from dbt project
(cannot use a string pattern on a bytes-like object)
```

The earlier invocation without sandbox variables failed for missing `PORTCO_DBT_WAREHOUSE`; that
setup error was corrected before the result above. The suggested `duckdb` package extra was absent
in 0.15.0, so the adapter was supplied with `--with dbt-duckdb` instead.

No warehouse validation or MetricFlow query succeeded, and the cause of the bytes/string failure
was not conclusively isolated. This is a bounded compatibility investigation, not proof that the
generated YAML is either universally invalid or compatible. Next work would isolate the CLI/parser
failure with a minimal manifest and a pinned version matrix, then validate and compare actual queries.

The release supports dbt parse/build plus its own YAML-driven monthly simple/derived metric executor.
It does not advertise MetricFlow runtime support. Keep this optional investigation separate from the
passing frozen application environment until a supported runtime combination is demonstrated.
