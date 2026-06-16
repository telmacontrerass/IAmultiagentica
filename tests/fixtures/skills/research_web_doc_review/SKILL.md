---
name: research_web_doc_review
description: Review one provided web doc URL using only fetched evidence.
when_to_use: Deterministic technical review from a controlled URL.
allowed_tools: web_fetch
disable-model-invocation: false
---
# Goal
Produce a structured technical review for one provided URL using only the content fetched from that URL.

# Required workflow
1. Accept exactly one URL argument from the user.
2. Call `web_fetch` for that URL.
3. Build the review only from fetched content.

# Hard constraints
- Do not use internet search, memory, or external sources.
- Do not cite any source other than the provided URL.
- Separate facts from recommendations.
- Explicitly list unknown or not-verified items.
- Include short verbatim quotes from the fetched text as evidence.

# Output contract (JSON)
Return valid JSON with exactly these top-level keys:
- `url` (string)
- `title` (string)
- `key_points` (array of strings; factual)
- `relevant_api_or_concepts` (array of strings)
- `constraints_or_warnings` (array of strings)
- `quoted_evidence` (array of short strings copied verbatim from the fetched page)
- `practical_recommendations` (array of strings; recommendations only)
- `unknowns_or_not_verified` (array of strings)

# Validation checklist before final answer
- Evidence exists and each quote appears in fetched content.
- No external URL/source appears other than input `url`.
- Unknowns section includes items explicitly not covered by the document.
