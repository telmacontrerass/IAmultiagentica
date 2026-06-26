# Grounded scientific peer review

CI2Lab can run a multi-agent **peer review** of a manuscript. The defining
constraint is groundedness: the review must be based only on the actual paper —
the model must not invent or hallucinate anything, every point must be correctly
referenced to the manuscript, and external references must be verifiable.

## Researchers and per-paper projects

- **Researchers** (`ci2lab/ui/researchers.py`, stored in `~/.ci2lab/researchers.json`):
  login-less profiles with a name, field(s) of expertise, default venues, a
  reviewing style, and per-lens emphasis. The review **adapts** its depth and
  tone to the selected researcher (it never licenses inventing content).
- **Paper-review projects**: a knowledge project (`ci2lab/ui/projects.py`) with
  `kind = "paper_review"` and metadata (`field`, `target_venue`, `article_type`,
  `owner_id`, …). Put **one paper per project** and upload the manuscript as a
  source; everything centers on that manuscript. Projects are scoped to the
  selected researcher in the UI.

Selecting a paper-review project (or sending `mode: "paper_review"`) routes the
chat to the grounded flow; the researcher is sent as `researcher_id`.

## How groundedness is enforced — the model proposes, the code disposes

1. **Addressable source of truth** (`multiagent/manuscript.py`): the manuscript
   is normalized, segmented, and given stable `[A#]` anchors. Reviewers may only
   cite these anchors and must quote verbatim from this text.
2. **Structured findings**: every reviewer emits findings as JSON —
   `{claim, evidence_type (manuscript|absence|external), evidence_quote, anchor,
   absence_terms, external_url, severity, reviewer_judgment}`.
3. **Deterministic verification** (`multiagent/grounding.py`), no model in the
   loop, sorting every finding into one of four dispositions:
   - **verified** — `manuscript` quote occurs in the text / `absence` terms truly
     absent / `external` URL was actually fetched (via `web_fetch`). Goes in the
     review.
   - **refuted** — the manuscript *contradicts* the claim (e.g. "no baseline" but
     there is one). The model was wrong and the paper is fine, so it is removed
     and listed under *auto-filtered to avoid unfair criticism*.
   - **needs_check** — could not be verified because of a **tool/model limit, not
     the paper's fault** (see below). Goes to a *"Could not verify — check
     manually"* section, never condemned.
   - **quarantined** — genuinely unsubstantiated (a quote that is simply not there
     with no innocent explanation) → *"Unsubstantiated — DO NOT send"*.
4. **Re-ground once, then sort**: a *quarantined* manuscript/absence finding is
   sent back once for an exact quote/terms; if it still fails it stays
   quarantined. `needs_check` and `refuted` are never re-grounded (re-grounding a
   paywall or a figure-based claim cannot help).
5. **Adversarial groundedness verifier**: checks that each surviving quote
   actually *supports* its claim (catches over-readings).
6. **Honest degradation**: if no manuscript can be read, the flow **refuses** to
   review rather than reviewing from the title/abstract/memory.

### "Could not verify" — attributing failures honestly

Not every failed check is the paper's fault. `needs_check` findings carry a
category so the human knows *why* and that the underlying reference/claim may be
perfectly valid:

- External references: `paywalled_or_login` (401/403), `dead_or_moved`
  (404/410/DNS), `timeout_or_network` (incl. no web access), `rate_limited`
  (429), `blocked` (robots/captcha), `not_attempted`. A paywalled source is
  *"may be valid, verify manually"*, never *"bad reference"*.
- Manuscript claims about `non_text_content` (figures/tables/equations) — text
  extraction routinely drops these, so an unfindable quote about "Figure 3" is an
  extraction gap, not a hallucination → *"verify against the original PDF"*.
- `coverage_truncated` — a long manuscript exceeded the prompt budget, so later
  sections were not reviewed and are flagged for manual review.

## Context window: plan-divide-conquer, or refuse

A local model has a finite context window, and an overflowed window silently
drops manuscript text — which produces an *incomplete* (i.e. wrong) review. We
never ship that. `multiagent/context_budget.py` handles this:

1. From the model's real window (`selection.context_length`, which CI2Lab loads
   into Ollama via `num_ctx`), compute how much manuscript fits in **one**
   reviewer call: reserve tokens for output, use only ~60% of the window
   (effective context is well below nominal — "lost in the middle"), and
   subtract the fixed prompt overhead (~4 chars/token).
2. **Divide** the manuscript into chunks that each fit that budget, keeping
   segments/anchors whole.
3. **Conquer**: every lens runs once per chunk, so the window is never exceeded;
   findings are merged across chunks (the deterministic verifier checks each
   quote against the *full* index, so chunk-local false "X is missing" claims are
   still refuted). The reduce-stage prompts (groundedness verifier, revision
   planner) carry only findings, never the manuscript, so they never overflow.
4. **Refuse instead of guessing**: if even one usable chunk will not fit, or the
   paper would need more than `MAX_CHUNKS` chunks, the run **aborts before doing
   any work** and recommends a larger-context model (with the minimum context it
   needs and `ci2lab models recommend`).

### When to recommend a bigger model

- **Pre-flight (feasibility):** per-chunk manuscript budget `< ~500 tokens`
  (model too small for even one section) **or** `> 12` chunks needed (too
  fragmented). Roughly, an 8k-context model is the floor for short papers and
  chunking covers longer ones; 2k/4k models are usually told to upgrade.
- **Post-flight (quality gate):** after the run, the result is **dropped** and a
  stronger model recommended if the model clearly failed — it ignored the
  structured-output contract on >75% of calls, fabricated >60% of its quotes, or
  produced no usable grounded content. Better no review than a misleading one.

All thresholds are named constants in `context_budget.py` / `paper_review.py`.

## The lenses

`intake → scope → novelty (contribution audit) → methodology → field-expert →
adversarial (Reviewer 2) → format → groundedness-verifier → revision-planner`
(see `multiagent/state.py`, `roles.py`, `orchestrator.py`). The revision planner
assembles only verified findings into a stable `PAPER REVIEW REPORT`, always
followed by a grounded-findings list (with anchors), the quarantine appendix, and
a coverage note (manuscript source, segments indexed, truncation, fetch count).

## External references

A citation is asserted as **verified only if the source was actually fetched**
during the run. But an unfetched/unreachable citation is **not** condemned: it is
routed to *"Could not verify"* with the reason (paywall, dead link, offline,
not attempted), because a valid reference behind a paywall is still valid. The
novelty lens is told to fetch sources first; if a fetch fails it still reports
the citation so the failure can be attributed instead of the reference dropped.

## Tests

- `tests/test_paper_review_grounding.py` — indexer + verifier (real quote passes,
  invented quote rejected, false absence refuted, external-fetch gate).
- `tests/test_paper_review_flow.py` — end-to-end orchestration (verified kept,
  hallucination quarantined, missing manuscript refused).
- `tests/test_ui_researchers.py`, `tests/test_ui_projects.py` — data layer.
- `tests/test_multiagent_intent.py` — routing into the paper-review flow.
