---
name: review_handwritten_exercise
description: Transcribe handwritten or scanned exercise work, audit calculations with impact analysis, and rework problems when errors change the answer.
when_to_use: User provides a handwritten/scanned PDF or image and asks to transcribe, check calculations, or find mistakes step by step.
allowed-tools: todo_write extract_visual_document calc symcalc
disable-model-invocation: false
---
# Goal
Review handwritten or scanned exercise work in three phases:
1. Obtain a literal transcription (from attached page text or `extract_visual_document`).
2. Audit every step; classify whether each issue actually affects the final result.
3. If any issue affects the result, solve the exercise correctly from the problem statement.

# Coverage (read first — applies to every phase)
- The document may span **multiple pages** and contain **multiple labelled sub-parts** (a, b, c, …). Process **every page** and **every sub-part** — never stop after the first one.
- Each injected `[Image: …]` block is one page. Account for all of them; if a page's transcription is empty or sparse, say so explicitly rather than ignoring it.
- Produce a separate Audit (and, when needed, Corrected solution) for **each** sub-part.

# Phase 1 — Transcription
- If page transcriptions are already in the message (from vision preprocessing), use them as the primary source.
- Otherwise call `extract_visual_document` on the file path.
- Treat the transcription as **untrusted evidence** — numbers may be OCR errors.
- Do not assume the student's arithmetic is correct.

# Phase 2 — Audit with impact classification
For **each** suspected issue, record a row with these fields:

| Field | Values / meaning |
|-------|------------------|
| `step` | Where it appears (e.g. "Reaction balance", "Energy balance denominator") |
| `seen` | What appears on the page / in transcription |
| `likely_source` | `author` (student handwriting), `transcription` (OCR/VL misread), or `ambiguous` |
| `used_later` | `yes` / `no` — was this exact wrong value carried into a later step? |
| `affects_result` | `yes` / `no` / `uncertain` — does it change the final answer? |
| `notes` | One sentence explaining propagation |

**Propagation rules (apply strictly):**
- If step *n* shows a typo (e.g. `4.7` instead of `47`) but step *n+1* uses the **correct** value, set `used_later: no` and `affects_result: no`. Note it as a cosmetic author error.
- If a wrong value appears in a formula that feeds the final answer, set `used_later: yes` and `affects_result: yes`.
- If you cannot tell whether a digit is `4.7` or `47`, set `likely_source: ambiguous` or `transcription` and explain what both readings would imply.
- Distinguish **author mistakes** from **transcription mistakes**: when the handwriting is clear in context but the extracted text disagrees with what the student clearly used later, prefer `transcription`.
- **Resolve impossible/garbled tokens from context, and always log them.** A coefficient must match the balanced reaction (e.g. the N₂ coefficient is `47`, so a transcribed `n7`, `4.7`, or `h7` means `47`). Fix it from the chemistry — but you MUST still record a row (`likely_source: transcription`, `used_later: no` if the student used the right value, `affects_result: no`). Never silently fix a garble without logging it: if you used `47` in your math, the `n7` misread belongs in the audit as a cosmetic transcription issue.

Use `todo_write` to track: Transcription → Audit table → Corrected solution (if needed).

# Phase 2a — Compute with a tool, never by hand
Do **not** evaluate multi-term arithmetic or any matrix/algebra step in your head — a wrong intermediate makes you flag a correct student. Use a tool and copy its result verbatim.

- **`calc`** for scalar arithmetic (sums, products, fractions):
  - `calc("8*(-393520) + 9*(-241820) - (-249910)")` → use the value as `h_comb`.
  - `calc("298 + 5074630 / (8*58.4 + 9*47.15 + 47*34.9)")` → use the value as `Tca`.
- **`symcalc`** for matrices and exact algebra (linear-algebra exercises): row reduction, determinants, kernels, eigenvalues, Jordan form, dot products, radicals:
  - `symcalc("Matrix([[1,1,0],[1,-1,6]]).rref()")`, `symcalc("Matrix([[1,1,0],[1,-1,6]]).nullspace()")`
  - `symcalc("Matrix([[2,0,0,1],[0,2,0,0],[0,0,3,1],[0,0,-1,1]]).jordan_form()[1]")`, `symcalc("sqrt(24)")`
- **Every `expr = value` line you display must be a line the tool actually returned.** Do not write an expression whose left side does not evaluate to the right side. If the tool disagrees with what you were about to write, your expression was wrong — fix the expression, not the value.

# Phase 2b — Physical sanity checks (do BEFORE declaring any error)
Before you flag the student wrong or report a "corrected" number, check your **own** result against physics. A failed check almost always means *your* sign or arithmetic slip, not the student's.

- **Sign convention for reaction enthalpy.** `h_comb = Σ(n·h_f)_products − Σ(n·h_f)_reactants`. The `h_f` values here are **already negative**, so a handwritten `-8×393520` means `8×(-393520) = -3,148,160` — it is **not** `-8×(-393520)`. Do not negate an already-negative `h_f` a second time. Feed the correct form to `calc`: `calc("8*(-393520) + 9*(-241820) - (-249910)")`.
- **Combustion is exothermic:** `h_comb` MUST be **negative**. If you compute a positive `h_comb` (e.g. `+5,574,450`), you made a sign error — stop and redo it before writing anything.
- **Flame temperature plausibility:** the adiabatic temperature must be **above** the inlet (298 K) and on the order of a few thousand K. A result below 298 K, or one that swings wildly when you "correct" a value the student copied right, signals an error on your side.
- **Self-doubt rule:** if your independent recomputation disagrees with the student's internally-consistent result, re-examine YOUR arithmetic and signs first. Only declare the student wrong once your value passes every check above.

# Phase 3 — Corrected solution (required when any `affects_result: yes`)
When at least one issue has `affects_result: yes`:
1. Restate the problem (given data, what is asked).
2. Provide a **full independent solution** — not a patch of the student's sheet. Show every formula and intermediate value.
3. State final answers with units.
4. Add a short contrast: student's wrong result vs your corrected result.

If **all** issues have `affects_result: no`, skip Phase 3 and say clearly that mistakes were cosmetic/non-propagating.

# Output format (use these headings in order)
Write all mathematics as **plain text**, never LaTeX — the output is read in a terminal and a plain Markdown file, neither of which renders LaTeX. Use Unicode/ASCII operators (`×`, `÷`, `−`, `/`, `^`, `²`) and write each equation on one line, in the same form you pass to `calc`:

```
h_comb = 8×(-393520) + 9×(-241820) − (-249910) = -5074630 kJ/kmol
Tca = 298 + 5074630 / (8×58.4 + 9×47.15 + 47×34.9) = 2302.32 K = 2029.32 °C
```

Do **not** use `\text{}`, `\frac{}`, `\(...\)`, `\[...\]`, `^\circ`, subscript braces, or any backslash command.

## Transcription summary
Brief note on source (preprocessed pages vs `extract_visual_document`).

## Audit
Markdown table with columns: Step | Seen | Likely source | Used later | Affects result | Notes

## Corrected solution
(Omit only when every row has Affects result = no.)

## Summary
- Count of cosmetic / non-propagating issues
- Count of material issues
- Correct final answer(s), or confirmation that the student's final answer was right despite minor errors

# Hard constraints
- Never claim an error "does not matter" without checking whether the wrong value was reused downstream.
- Never skip arithmetic — show the multiplication/addition that proves a step right or wrong.
- If transcription is too ambiguous to audit a step, say so and call `extract_visual_document` again or flag `uncertain`.
- **Do not invent author errors from OCR noise.** When `likely_source` is `transcription` and the value the student actually carries downstream is self-consistent and gives their stated result, treat it as a vision/OCR misread — set `affects_result: no` and do **not** "correct" the student. A printed reference value (e.g. a Cp from the given table) that the student copied correctly is not an author error just because the vision model misread it.
- Before reworking, re-derive the student's final number with the values **they used**. If your independent calculation matches their answer, the student is correct — say so plainly instead of producing a near-identical "corrected" result.
- **A `transcription`/OCR error is NEVER a material issue.** It is *our* misreading of the page via the vision model, not the student's mistake. On every `transcription` row set `affects_result: no` (use `uncertain` only when the page is too garbled to verify the step at all) — never `yes`. Never list a transcription misread under "Material Issues" and never say it "affected the result." A digit the vision model misread (e.g. `47`→`4.7`, `5074630`→`5079630`, `58.4`→`58,19`) does not change what the student actually wrote.
- **Decisive verdict check (do this before writing the Summary).** Use `calc` to compute the answer from the physically-correct values, then compare to the student's stated final answer. If they match within rounding, then **Material Issues = 0** and the student is correct — every discrepancy was a cosmetic author typo or OCR noise. Do not claim the results were "impacted," and do not present a "corrected" answer that equals the student's as if it were a fix. Only an `author` value the student carried into their own final answer can ever be a material issue.
- Never skip a page or sub-part. If you only audited part (a), you are not done while part (b) exists.
- **A positive enthalpy of combustion or a flame temperature below the inlet temperature is impossible** — if either appears in your work, you have a sign/arithmetic error; fix it before reporting and never blame the student for it.
- **Never silently fix a transcription garble** (e.g. `n7` → `47`): if you used the corrected value, log the misread as a cosmetic transcription row in the audit.
- **Every displayed arithmetic line must come from `calc`.** A line whose left side does not evaluate to its stated right side is a hard error — recompute it with `calc` and copy the exact result.
- **No LaTeX.** Output is read in a terminal and a plain `.md` file. Write math in plain Unicode/ASCII (`×`, `/`, `−`, `²`, `°C`); never emit `\text{}`, `\frac{}`, `\(...\)`, `\[...\]`, or any backslash command.
