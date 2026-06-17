# Research Skills

## 1) Goal

Research skills turn base tools (`web_search`, `web_fetch`) into evaluable, deterministic workflows for technical analysis backed by evidence.

The goals are to:
- start from a controlled URL (a local fixture) or a focused search query,
- extract verifiable facts,
- produce structured outputs,
- validate the contract and orchestration in offline tests.

## 2) Tool vs Skill

- `web_search` / `web_fetch` (primitive, read-only tools):
  - `web_search` finds candidate URLs from a plain-text query;
  - `web_fetch` downloads `http/https` content, follows redirects, strips HTML, and truncates long responses;
  - neither modifies files nor runs destructive actions.

- `live_fact_lookup` (factual/live skill):
  - uses `web_search` + `web_fetch`,
  - answers a factual or time-sensitive question from discovered sources,
  - responds in plain text with a `Fuente:` (source) line and a caveat when the source is weak.

- `research_web_doc_review` (evaluable skill):
  - uses `web_fetch`,
  - reviews one controlled web document,
  - requires textual evidence and an explicit list of unverified limits.

- `research_web_vs_repo` (doc-vs-code skill):
  - uses `web_fetch` + `read_file`,
  - compares documentation facts against observations from the local repo,
  - separates matches, gaps/risks, and recommendations.

## 3) Built-in skills

### `live_fact_lookup`

- Allowed tools: `web_search`, `web_fetch`
- Input: a factual/live question (with or without a URL)
- Required workflow:
  1. Interpret the factual question.
  2. If there is no URL, call `web_search` with a focused query.
  3. Pick one or two reliable sources from the results.
  4. Call `web_fetch` on at least one source before stating facts.
  5. Answer only from `web_search`/`web_fetch` content.
- Hard constraints:
  - Do not invent scores, dates, versions, names, or outcomes that are not in the fetched content.
  - Do not use tools other than `web_search` and `web_fetch`.
- Response format:
  - Plain text (not JSON) unless the user explicitly asks for JSON.
  - Always include a `Fuente:` line.
  - Allow a `Advertencia:` (warning) line when the source is weak or conflicting.

### `research_web_doc_review`

- Allowed tools: `web_fetch`
- Input: exactly one URL
- Expected output (JSON):
  - `url`, `title`, `key_points`, `relevant_api_or_concepts`,
  - `constraints_or_warnings`, `quoted_evidence`,
  - `practical_recommendations`, `unknowns_or_not_verified`
- What the test validates:
  - JSON with the exact keys
  - textual evidence taken from the fixture page
  - no invented external sources
  - presence of limits/not-covered items
- Current limitations:
  - semantic evaluation against a real model is not covered in this phase

### `research_web_vs_repo`

- Allowed tools: `web_fetch`, `read_file`
- Input: a URL + one or more local files (current phase: one file)
- Expected output (JSON):
  - `url`, `local_files_reviewed`, `doc_facts`, `repo_observations`,
  - `matches`, `gaps_or_risks`, `recommended_changes`,
  - `changes_not_recommended`, `quoted_evidence`,
  - `unknowns_or_not_verified`
- What the test validates:
  - JSON with the exact keys
  - the URL is present
  - the local file is listed in `local_files_reviewed`
  - documentary evidence + concrete code observations
  - at least one `match`, one `gap_or_risk`, one recommendation, and one not-recommended change
  - no invented external sources
- Current limitations:
  - the test covers the single-file case (multi-file is a later phase)

## 4) Security approach

- Tests are 100% offline/deterministic.
- No internet dependency in CI.
- No file modification during research skills.
- No external sources beyond what the input provides.
- Per-skill restricted toolset (`allowed_tools`).

## 5) Verification commands

```bash
pytest tests/test_research_skills.py -q
pytest tests/ -q
```

## 6) Honest limitations

- The current tests use a deterministic mock LLM.
- They validate the contract/orchestration and structural evidence.
- They do not yet validate the full semantic quality of live models.
- Live evaluation is explicitly left for a later phase.

## 7) Roadmap

- Optional live semantic evaluation (off CI by default).
- Extension to multi-file comparison.
- Multi-source comparison with a controlled corpus.
- State-of-the-art evaluation with a closed corpus.
- Paper extraction as a later capability.
