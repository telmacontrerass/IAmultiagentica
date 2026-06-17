# Work report — live_fact_lookup, web search, and 403 fallback

_Historical snapshot; may not reflect the current implementation. Some mechanisms described here (e.g. forced docx→pdf conversion) were later removed when the agent loop was made task-agnostic._

Date: 2026-06-16

## Initial state

- The harness already had `web_search` and `web_fetch` tools, but the CLI help and the fenced tools guide did not explain them well.
- The research skills (`research_web_doc_review`, `research_web_vs_repo`) existed as built-ins, but there was no explicit skill for simple factual/live lookup.
- The agent loop (`run_agent`) gave no clear push toward `web_search` when the model replied "I do not have internet access".
- There was no specific documentation about the expected behavior on HTTP errors (including `403`) from `web_fetch`.

## Work done

- Added a built-in `live_fact_lookup` skill for simple factual/live queries.
- Aligned the CLI help and the fenced tools documentation to include `web_search` as the first stop for live searches without a URL.
- Added a nudge in the agent loop so that, when the model says it has no internet access and the tools allow it, it is explicitly reminded that it can use `web_search` and then `web_fetch`.
- Added a specific nudge when `web_fetch` fails with typical HTTP errors (including `403`), redirecting the model toward `web_search` instead of repeating fetches or inventing URLs.
- Adjusted/added harness tests to cover the new logic, including the push toward `web_search` and the docx→pdf flow on Windows.

## Technical changes

### CLI and tool documentation

- `ci2lab/cli/parser.py`: the global help now explicitly lists `web_search` alongside `web_fetch` and adds a guiding sentence:
  - If the user asks for live information without a URL, use `web_search` first and then `web_fetch` to read specific sources.
- `ci2lab/harness/prompts/fenced_tools.md`:
  - Documented `web_search` with a fenced-block example for live searches.
  - Updated the list of available tools to include `web_search` alongside `web_fetch`.

### Agent loop and web nudges

In `ci2lab/harness/query/loop.py`:

- Added `_NO_INTERNET_RE`, a regex that detects model messages such as "I have no internet access / I cannot search in real time".
- During each round's preparation:
  - `web_search_available` is computed by checking whether `web_search` is among the tools allowed for the current model.
- In the answer-finalization phase:
  - If the model returns a final answer with no tool calls, `web_search` is available, no nudge has been sent yet, and the text matches `_NO_INTERNET_RE`, a system-style message is inserted:
    - "You can use `web_search` for live info without a URL, then `web_fetch` for selected sources."
  - This nudge is sent only once per run to avoid loops.
- In the tool-execution phase:
  - The `web_fetch_failed_nudge(results)` function detects `web_fetch` HTTP errors (including `403`) and adds a user instruction that explicitly states:
    - that the likely URL is wrong or blocked;
    - that new URLs should not be guessed;
    - that the model should go back to `web_search` with a text query and, from there, use `web_fetch` on specific results.

This complements the general tool-loop detection (`stuck_rounds`) which, after repetitions, forces an instruction to the model along the lines of "Stop repeating the same tool… Answer the original request now using the tool results already available".

### Built-in `live_fact_lookup` skill

- Added `ci2lab/harness/skills/builtin/live_fact_lookup/SKILL.md` with:
  - `allowed_tools: web_search web_fetch`.
  - A required workflow:
    1. Interpret the factual/live question.
    2. If there is no URL, call `web_search` with a specific query.
    3. Pick one or two reliable sources from the results.
    4. Call `web_fetch` at least once before stating facts.
    5. Answer only with information derived from `web_search`/`web_fetch`.
  - Hard constraints:
    - Do not invent scores/dates/outcomes/versions not present in the snippets.
    - Do not use tools other than `web_search` and `web_fetch` within this workflow.
  - Response format:
    - Plain text (not JSON) unless the user explicitly asks for JSON.
    - Always include a `Fuente:` line.
    - Allow an `Advertencia:` (warning) line to qualify when the source is weak or ambiguous.
  - A "When search or fetch fails" section that already points to:
    - Not guessing when there are no useful results.
    - Trying another source when `web_fetch` fails.
    - Explaining that the fact could not be verified if nothing works.

### Harness tests

- `tests/test_skills.py`:
  - `test_builtin_research_skills_available` now verifies that `live_fact_lookup` is available as a built-in skill.
  - `test_live_fact_lookup_skill_contract` ensures that:
    - `allowed_tools` is limited to `web_search` and `web_fetch`.
    - The generated prompt explicitly mentions:
      - combined use of `web_search` + `web_fetch`;
      - a plain-text response;
      - the `Fuente:` line in the output format;
      - the prohibition on inventing data not present in `search/fetch`.
- `tests/test_harness_loop.py`:
  - `test_run_agent_prints_model_text_before_tool_execution` covers that the model text is printed before running tools.
  - `test_run_agent_nudges_web_search_once_after_no_internet_reply` validates that:
    - a first turn with "I have no real-time internet access" without tools triggers a single nudge toward `web_search`;
    - the model's second turn sees that nudge and is expected to mention that it will use `web_search`.
  - `test_run_agent_forces_docx_conversion_after_repeated_discovery` was adjusted to be portable on Windows:
    - Instead of simulating `bash` with `ls Prueba`, it now uses the `ls` tool with `{"path": "Prueba"}`.
    - This let the harness detect the `.docx` and force `docx_to_pdf` even in environments where `ls` as a shell command does not exist.

## Manual tests performed

### `/live_fact_lookup result of Spain vs Cape Verde`

- Run via the slash skill:
  - The agent used `web_search` with a reasonable query about the Spain–Cape Verde match.
  - The UX was good: a fast response, no detours to `ask_user`, `tree`, `ls`, or invented `mcp_call`.
- Issue observed:
  - The skill explicitly requires calling `web_fetch` on at least one source before stating facts.
  - In the observed run, the agent used `web_search` only and answered directly with the search-snippet result, violating the skill contract.

### Natural search without a slash: "find the result between Spain and Cape Verde"

- Observed flow (undesired):
  - An initial `web_search`.
  - A `web_fetch` to a YouTube result.
  - An unnecessary `ask_user` despite having enough context.
  - Poor finalization and a new search attempt.
  - A `web_fetch` to a predictions page, not a real result page.
  - An invented `mcp_call` with a generic name `MCP_SERVER_NAME`.
  - Subsequent drift to the filesystem: `tree` / `ls`, entirely off-focus for a factual/web task.
- Conclusion:
  - The agent tends to mix in irrelevant tools (filesystem, invented MCP) when the web/factual task is not scoped for it.
  - The new skill and the `web_search` nudges go in the direction of scoping this space, but stricter fallback logic for these natural non-slash cases was still missing.

### Bitcoin price query (Coinbase)

- A current Bitcoin price query was tested, using as one of the sources:
  - `https://www.coinbase.com/en-es/converter/btc/usd`
- Result:
  - `web_fetch` returned `HTTP 403`.
  - This 403 is reasonable: sites like Coinbase are expected to block automated traffic, so it should not be automatically interpreted as a fetcher bug.
  - The real problem is how the agent responds to this situation.
- Observed behavior (generally undesired):
  - A tendency to repeat similar searches or fetches.
  - Possible invention of MCP tools or drift to the filesystem.
  - A lack of clean closure when fetch errors accumulate.

## Automated tests run

- Focused run:
  - `pytest tests/test_skills.py tests/test_harness_loop.py -q`
    - Result: all relevant tests pass, including the new ones on `live_fact_lookup` and the `web_search` nudge.
- Full suite:
  - `pytest tests/ -q`
    - Result: 669 tests passed, 10 skipped in the current environment.
    - No new failures were observed after integrating the remote multi-agent work and the local loop changes.

## Result of `/live_fact_lookup result of Spain vs Cape Verde`

- UX:
  - Good: a reasonably fast response, no detours to irrelevant tools.
  - The output was plain text with consistent information about the score.
- Contract problem:
  - The observed flow used `web_search` only.
  - The skill explicitly requires:
    - running `web_fetch` on at least one concrete URL;
    - basing the answer only on `web_search` + `web_fetch` content.
  - So, even with a good UX, there is a violation of the skill's internal contract that must be fixed:
    - when URLs are available in the search results, `live_fact_lookup` must select at least one and run `web_fetch` before the final answer.

## Result of a natural search without a slash command

- Input type: "find the result between Spain and Cape Verde".
- Without the explicit skill restriction, the agent ended up:
  - visiting YouTube via `web_fetch`;
  - raising an unnecessary `ask_user`;
  - visiting prediction pages;
  - inventing a `mcp_call` with `MCP_SERVER_NAME`;
  - drifting to filesystem commands (`tree`, `ls`).
- Conclusion:
  - For natural queries without a slash, the harness should guide the model to:
    - stay in the web/factual tool space (`web_search`, `web_fetch`);
    - avoid the filesystem unless the user explicitly asks;
    - not introduce fictional MCP as a form of "creative output".

## Bitcoin / Coinbase / HTTP 403 case

- Context:
  - The current Bitcoin price was searched, and Coinbase was tried as one of the sources.
- Key observation:
  - `web_fetch` against `https://www.coinbase.com/en-es/converter/btc/usd` returned `HTTP 403`.
- Interpretation:
  - Many financial and exchange sites block automated scraping or non-interactive traffic.
  - A `403` here is not necessarily a bug in the fetcher or the harness infrastructure.
  - The problem is the agent's strategy after receiving the `403`.

## 403 diagnosis and the real bug

- `HTTP 403` from Coinbase:
  - Is consistent with anti-bot and anti-scraping policies.
  - The harness already detects and propagates the error in the `web_fetch` result.
- Real bug (at the agent/harness level):
  - There was no sufficiently robust fallback logic:
    - the agent could:
      - repeat the same query or minor variations with no added value;
      - invent MCP tools or alternate URLs;
      - drift to the filesystem (`ls`, `tree`) in a purely web/factual task;
      - ask the user "what to do" even with enough partial snippet information.
- State after the changes:
  - `web_fetch_failed_nudge`:
    - Detects HTTP errors such as `400`, `401`, `403`, `404`, `429`, `500`, `502`, `503`.
    - Inserts a message that:
      - explains the URL may be wrong or blocked;
      - forbids guessing other URLs;
      - instructs the model to go back to `web_search` with a text query.
  - This does not fully solve all repetition patterns, but:
    - it steers the flow toward "one reasonable additional attempt" rather than open loops;
    - it scopes the tool to the web space rather than jumping to the filesystem or invented MCP.

## Need for robust fallback

Even with these improvements, the fallback logic for factual/live queries still needed reinforcement:

- At most one reasonable alternate search:
  - On `web_fetch` with `403` (or other hard HTTP errors), it should allow:
    - at most one alternate `web_search`;
    - selecting one or two additional plausible sources;
    - if those also fail or are weak, closing the answer.
- Do not repeat the same query:
  - The harness already has tool-loop detection (`stuck_rounds`).
  - For web/factual tasks, the "same `web_search` query + same kind of failed `web_fetch`" pattern should count as a strong loop and trigger closure.
- Do not use invented MCP:
  - Responses must be restricted to real, declared MCP servers.
  - Any placeholder (`MCP_SERVER_NAME`, etc.) should be explicitly forbidden for this kind of task.
- Do not use the filesystem in web/factual tasks:
  - For queries like "match result", "current price", "latest stable version", etc.:
    - the preferred tools are `web_search` and `web_fetch`;
    - filesystem tools (`ls`, `tree`, `read_file`, etc.) should be off-limits unless the user explicitly asks to inspect local files.
- Answer with a caveat if there are only snippets:
  - If only partial `web_search` snippets were obtained (or if `web_fetch` keeps failing):
    - the answer must explicitly state that the fact could not be verified from full sources;
    - the `live_fact_lookup` format already covers a text like:
      - "No lo puedo verificar con claridad en la fuente consultada."
  - An incomplete but honest answer backed by snippets is preferable to inventing a "plausible" value.
- Obey "stop tools / answer with what you know":
  - When the user explicitly asks to stop using tools:
    - the loop must:
      - stop queueing new `web_search`/`web_fetch` calls (or any other tool);
      - give a final answer based only on the results already gathered.

## Pending risks

- The `web_search` nudge and the failed-`web_fetch` nudge improve behavior, but by themselves do not guarantee:
  - that the model stops suggesting invented MCP;
  - that it never drifts to the filesystem if the system prompts are not clear enough about "web tasks".
- The `live_fact_lookup` contract can still be violated at runtime if:
  - the model decides to "shortcut" and answer with `web_search` snippets only, without going through `web_fetch`.
- The general loop logic (`stuck_rounds`) is tool-type agnostic:
  - it remains possible for combinations of `web_search` and `web_fetch` to repeat non-trivially without crossing the configured threshold.
- Without an explicit per-task-type "tool budget" policy, there is always some room for the model to "wander" before converging.

## Prioritized next steps

1. **Harden the `live_fact_lookup` skill:**
   - Add validation logic in the harness that:
     - verifies that, if `web_search` found URLs, `web_fetch` was called at least once before accepting a final answer from the skill;
     - explicitly flags as a contract error any final answer without `web_fetch` when `web_fetch` was available.
2. **Specific fallback for `403` and hard HTTP errors:**
   - Extend the tests to cover:
     - a single additional `web_search` attempt on `403`;
     - a controlled closure with a caveat if the second source fails again.
3. **Tool control for natural web/factual queries:**
   - Add a light intent-classification layer that:
     - detects queries of the type "result/score/price/version/event date";
     - automatically limits the tool space to `web_search` and `web_fetch` in those cases.
4. **Strong obedience to "stop repeating" and "answer with what you know":**
   - Add tests that simulate users explicitly asking to "stop repeating tools / answer with what you already know" and verify:
     - that no more tools run after that instruction;
     - that a final answer based on the snippet history is returned.
5. **Guards against irrelevant MCP and filesystem:**
   - Add extra checks in the loop to:
     - block `mcp_call` with placeholder names;
     - block the filesystem in tasks marked as web/factual unless the user explicitly overrides.

## Proposed regression tests

Not all of these tests are implemented yet, but they are proposed as desired regression coverage to close the gap observed that day:

- `test_live_fact_lookup_requires_fetch_before_final_when_fetch_available`
  - Verifies that `live_fact_lookup` cannot finalize without at least one `web_fetch` when URLs are available in the `web_search` results.
- `test_live_fact_lookup_fetch_403_fallback_does_not_repeat_search`
  - Simulates a `web_fetch` with `HTTP 403` and checks that:
    - at most one additional `web_search` is performed;
    - the same query is not repeated indefinitely.
- `test_live_fact_lookup_fetch_403_answers_with_snippet_caveat`
  - Checks that, if after `403` there are only `web_search` snippets, the answer:
    - uses those snippets explicitly;
    - includes a warning that it could not be clearly verified.
- `test_user_stop_repeating_tools_forces_final_answer`
  - Verifies that, after an explicit user instruction to stop using tools:
    - the agent closes the loop;
    - no more tool calls are generated.
- `test_no_duplicate_web_search_same_query_in_single_fact_task`
  - Ensures that, for a specific factual task, the same `web_search` query is not repeated more than once except for significant changes.
- `test_natural_fact_query_does_not_use_filesystem`
  - Checks that natural queries of the type "match result / current price / latest version" do not activate filesystem tools unless explicitly requested.
- `test_natural_fact_query_does_not_call_placeholder_mcp`
  - Verifies that `mcp_call` with generic or placeholder names is never executed for this kind of task.
- `test_slash_skill_inside_ask_user_not_treated_as_plain_text`
  - Ensures that, if during an `ask_user`-mediated interaction the user types a slash command, it is not "lost" as plain text but interpreted correctly per the skills logic.
