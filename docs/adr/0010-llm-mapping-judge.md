# ADR-0010: Optional LLM mapping judge (off by default)

- Status: accepted (ships opt-in)
- Date: 2026-09-23

## Context
The handoff requires documenting why a deterministic rule is not enough whenever a model is
introduced, and defining how that model-dependent decision is evaluated.

## Why deterministic scoring is not enough
Technical source names with no synonym entry (SAP `KUNAG`, "sold-to party") and context-dependent
meanings score LOW even when a human would know the answer at once. The deterministic mapper routes
these to review. That is safe, but it costs reviewer time.

## Decision
`src/services/judge.py` (`ClaudeJudge`, default model `claude-opus-5`) is consulted only for
proposals below HIGH confidence that have alternatives.

- **Input:** aggregates and ontology definitions only, never row values or source comments. The
  prompt is PII-scanned and withheld entirely on any hit.
- **Output:** constrained by a JSON schema whose `choice` enum is exactly the candidates plus
  `ABSTAIN`. Answers must cite evidence ids that were provided.
- **Limits:** the mapper only reorders. `requires_review` stays true and confidence is capped at MEDIUM.
- **Refusals:** requests use server-side refusal fallbacks; a refusal becomes `ABSTAIN`.
- **Accounting:** every call records model, prompt version, tokens, latency and cost.
- **Replay:** the default `replay` mode answers only from recorded cassettes, so CI never calls the
  network.

## Alternatives considered
- Letting the model propose free-form targets: rejected. It could invent fields outside the
  ontology, and its answers could not be scored.
- Always on: rejected until the comparison below shows a gain.
- Fine-tuning or embeddings: out of scope for the MVP.

## Consequences
With the judge on, a run costs tokens and gains a network dependency. Replay cassettes keep CI
deterministic, and the judge can never remove a review.

## Evaluation
`python -m evals.judge_eval --mode record` compares top-1 accuracy, abstention and calibration with
the deterministic baseline on fixtures A and B. The rule is to enable the judge by default only if
accuracy improves with no calibration regression.

Status at the time of writing: the deterministic baseline already scores 1.00 top-1 on both fixtures,
and no live comparison has been recorded (the build environment has no credentials). The judge
therefore stays opt-in; see `evals/reports/judge_comparison.md`.
