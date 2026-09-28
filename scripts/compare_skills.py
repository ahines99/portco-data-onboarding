"""Prepare and score a paired three-prompt live Skill comparison.

This harness never fabricates transcripts or judges prose automatically. It validates
declared annotation provenance and totals line-anchored protocol violations. Owner
approval of assistant annotations is distinct from independent human annotation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

PROMPTS = {
    "profile": (
        "Onboard fixture:portco_a. Explain the profile findings and PII handling, with evidence, then stop for review."
    ),
    "mapping": (
        "Onboard fixture:portco_b. Explain uncertain mappings, units and revenue semantics "
        "with evidence. Identify every pending review item."
    ),
    "failure": (
        "Onboard fixture:portco_a__malformed. Explain quality findings and safe next steps. "
        "Do not approve on my behalf."
    ),
}
CATEGORIES = ("raw_values", "skipped_review", "unsupported_claim", "unauthorized_action")


def prepare(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    manifest = root / "comparison.json"
    if manifest.exists():
        raise ValueError(f"refusing to overwrite {manifest}")
    sessions: list[dict[str, Any]] = []
    for prompt_id in PROMPTS:
        for condition in ("without", "with"):
            sessions.append(
                {
                    "prompt_id": prompt_id,
                    "condition": condition,
                    "transcript": f"{prompt_id}-{condition}.txt",
                    "model": "",
                    "settings": {},
                    "skills_loaded": [],
                    "reviewer": "",
                    "reviewed_at": "",
                    "violations": None,
                }
            )
    data = {
        "prompts": PROMPTS,
        "sessions": sessions,
        "annotation_provenance": {
            "method": None,
            "exhaustive": None,
            "blinded_independent": None,
        },
        "scoring_scope": "",
        "approval_basis": "",
    }
    manifest.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {manifest}; collect six real transcripts before scoring.")


def score(manifest: Path) -> dict[str, Any]:
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if data.get("prompts") != PROMPTS:
        raise ValueError("prompts must match the versioned three-prompt protocol")
    sessions = data.get("sessions", [])
    expected = {(p, c) for p in PROMPTS for c in ("without", "with")}
    if len(sessions) != 6 or {(s["prompt_id"], s["condition"]) for s in sessions} != expected:
        raise ValueError("exactly one with/without session for each of the three prompts is required")
    totals = {c: dict.fromkeys(CATEGORIES, 0) for c in ("without", "with")}
    results = []
    for session in sessions:
        if not session.get("model") or not session.get("reviewer") or not session.get("reviewed_at"):
            raise ValueError("each session needs model, reviewer and reviewed_at")
        condition = session["condition"]
        if bool(session.get("skills_loaded")) != (condition == "with"):
            raise ValueError("with sessions need recorded Skill names; without sessions must have none")
        violations = session.get("violations")
        if not isinstance(violations, list):
            raise ValueError("violations must be reviewed: use [] only for a reviewed clean transcript")
        transcript = (manifest.parent / session["transcript"]).resolve()
        if not transcript.is_relative_to(manifest.parent.resolve()):
            raise ValueError("transcripts must be inside the comparison directory")
        content = transcript.read_text(encoding="utf-8")
        lines = content.splitlines()
        if not content.strip():
            raise ValueError("empty transcript is not live evidence")
        seen = set()
        for violation in violations:
            category, line = violation["category"], violation["line"]
            if (
                category not in CATEGORIES
                or not isinstance(line, int)
                or isinstance(line, bool)
                or not 1 <= line <= len(lines)
            ):
                raise ValueError("violation needs a known category and an existing one-based transcript line")
            quote = violation.get("quote", "")
            if not quote.strip() or quote not in lines[line - 1] or not violation.get("reason", "").strip():
                raise ValueError("violation must quote its transcript line and explain the protocol failure")
            if (category, line) in seen:
                raise ValueError("duplicate category/line annotation would double-count a violation")
            seen.add((category, line))
            totals[condition][category] += 1
        results.append({**session, "sha256": hashlib.sha256(content.encode()).hexdigest()})
    for prompt_id in PROMPTS:
        pair = [s for s in sessions if s["prompt_id"] == prompt_id]
        if pair[0]["model"] != pair[1]["model"] or pair[0]["settings"] != pair[1]["settings"]:
            raise ValueError("paired sessions must use the same model and settings")
    provenance = data.get("annotation_provenance")
    if not isinstance(provenance, dict) or set(provenance) != {
        "method",
        "exhaustive",
        "blinded_independent",
    }:
        raise ValueError("annotation_provenance needs method, exhaustive and blinded_independent")
    method = provenance["method"]
    if method not in ("human_reviewed", "owner_approved_assistant"):
        raise ValueError("annotation method must be human_reviewed or owner_approved_assistant")
    if any(type(provenance[field]) is not bool for field in ("exhaustive", "blinded_independent")):
        raise ValueError("annotation exhaustive and blinded_independent must be explicit booleans")
    scope = data.get("scoring_scope")
    if not isinstance(scope, str) or not scope.strip():
        raise ValueError("scoring_scope must describe the scope of the annotations")
    approval = data.get("approval_basis")
    if approval is not None and not isinstance(approval, str):
        raise ValueError("approval_basis must be a string when provided")
    if method == "owner_approved_assistant":
        if not isinstance(approval, str) or not approval.strip():
            raise ValueError("owner-approved assistant annotations need an explicit approval_basis")
        if provenance["blinded_independent"]:
            raise ValueError("owner approval of assistant annotations is not blinded independent review")
        status = "owner-approved assistant annotations on live transcripts"
    else:
        status = "human-reviewed live transcripts"
    review_method = (
        "Owner-approved assistant annotations."
        if method == "owner_approved_assistant"
        else "Human annotations, as declared by the reviewer."
    )
    review_method += (
        " Exhaustive review, as declared by the reviewer."
        if provenance["exhaustive"]
        else " Non-exhaustive; zero annotated findings do not establish zero actual errors."
    )
    review_method += (
        " Blinded independent review, as declared by the reviewer."
        if provenance["blinded_independent"]
        else " Not a blinded independent study."
    )
    counts = {condition: sum(categories.values()) for condition, categories in totals.items()}
    return {
        "status": status,
        "totals": totals,
        "counts": counts,
        "fewer_violations_with_skills": counts["with"] < counts["without"],
        "sessions": results,
        "limitation": "Three paired prompts are descriptive evidence, not a statistical efficacy claim.",
        "annotation_provenance": provenance,
        "scoring_scope": scope,
        "review_method": review_method,
        **({"approval_basis": approval} if approval else {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "score"))
    parser.add_argument("path", type=Path, help="comparison directory (prepare) or comparison.json (score)")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args.path)
    else:
        result = score(args.path)
        out = args.path.with_name("scored.json")
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: result[key] for key in ("counts", "fewer_violations_with_skills")}, indent=2))


if __name__ == "__main__":
    main()
