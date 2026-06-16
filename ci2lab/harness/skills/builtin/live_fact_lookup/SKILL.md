---
name: live_fact_lookup
description: Answer factual or time-sensitive questions using web search and fetched sources.
when_to_use: Recent facts, live data, news, versions, events, or docs without a known URL.
allowed_tools: web_search web_fetch
disable-model-invocation: false
---
# Goal

Answer the user's factual question using only information discovered via `web_search` and read via `web_fetch`. Do not rely on memory or unstated assumptions for live facts.

# Required workflow

1. Interpret the user's factual question (what fact, entity, or event they need).
2. If the user did not provide a concrete URL, call `web_search` with a focused query.
3. From search results, pick one or two reliable sources (official sites, recognized media, primary documentation).
4. Call `web_fetch` on at least one chosen URL before stating facts.
5. Answer using only what search and fetch returned.

# Hard constraints

- Do not invent scores, dates, versions, names, or outcomes not present in search/fetch output.
- Do not cite sources you did not fetch or see in `web_search` results for this turn.
- Do not use tools other than `web_search` and `web_fetch` for this workflow.
- If the source does not clearly verify the answer, say so explicitly.

# Response format (default: plain text)

Unless the user explicitly asked for JSON, respond in **plain text**, not JSON.

**Do not** wrap normal answers in `{"text": "..."}` or any JSON envelope.

Use this structure:

```
<direct answer in one or more sentences>

Fecha/contexto: <date, competition, version, or time context from the source, if available>
Fuente: <page title or domain of the fetched source>
```

If something cannot be verified from the fetched source:

```
No lo puedo verificar con claridad en la fuente consultada.
```

Optional short caveat when the source is weak or ambiguous:

```
Advertencia: <brief note if the source is unofficial, incomplete, or conflicting>
```

# When search or fetch fails

- If `web_search` returns no useful results, say so and suggest refining the question.
- If `web_fetch` fails, try another result from search or report that sources could not be read.
- Never guess to fill gaps.

# Validation checklist before final answer

- Used `web_search` when no URL was given.
- Used `web_fetch` on at least one source URL before stating facts.
- Answer is plain text (unless user requested JSON).
- Includes a `Fuente:` line naming the source read.
- No fabricated data beyond search/fetch content.
