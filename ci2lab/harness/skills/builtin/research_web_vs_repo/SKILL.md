---
name: research_web_vs_repo
description: Compare one fetched web document against local repository files.
when_to_use: Deterministic doc-vs-code review from controlled inputs.
allowed_tools: web_fetch read_file
disable-model-invocation: false
---
# Goal
Compare technical documentation from one provided URL with one or more local files and produce a structured review.

# Required workflow
1. Accept one URL and one or more local file paths.
2. Call `web_fetch` for the URL.
3. Read listed local files with `read_file`.
4. Produce comparison output based only on fetched and local content.

# Hard constraints
- Do not use external sources, search, or unstated assumptions.
- Do not modify files.
- Do not invent documentation or repository behavior.
- Separate documentation facts, repository observations, and recommendations.
- Every recommendation must tie to documentation evidence or concrete code observation.
- Include at least one `changes_not_recommended` item.
- Include unknowns when coverage is incomplete.

# Output contract (JSON)
Return valid JSON with exactly these keys:
- `url`
- `local_files_reviewed`
- `doc_facts`
- `repo_observations`
- `matches`
- `gaps_or_risks`
- `recommended_changes`
- `changes_not_recommended`
- `quoted_evidence`
- `unknowns_or_not_verified`
