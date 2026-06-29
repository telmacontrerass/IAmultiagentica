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

# CRITICAL — the examples in this skill are illustrations of METHOD, not findings
Every concrete number, formula, or topic in the examples below (combustion, enthalpy, flame temperature, `393520`, `58.4`, `47`, `Tca`, matrices, etc.) exists **only to show you how to apply a rule**. They are NOT content from the exercise you are reviewing.

- **Never** put any of these example numbers, steps, units, or topics in your Audit or Corrected solution.
- Your output must describe **only** what actually appears in THIS exercise's transcription. If the exercise is linear algebra, your audit rows are about vectors/matrices/bases — never about combustion or temperatures.
- Before writing each audit row, ask: "Does this token appear in the transcription I was given?" If not, do not write it.

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
| `step` | Where it appears, named from THIS exercise (e.g. "Part b) row reduction", "Eigenvalue") |
| `seen` | What appears on the page / in transcription |
| `likely_source` | `author` (student handwriting), `transcription` (OCR/VL misread), or `ambiguous` |
| `used_later` | `yes` / `no` — was this exact wrong value carried into a later step? |
| `affects_result` | `yes` / `no` / `uncertain` — does it change the final answer? |
| `notes` | One sentence explaining propagation |

**Propagation rules (apply strictly):**
- If a step shows a typo but the next step uses the **correct** value, set `used_later: no` and `affects_result: no`. Note it as a cosmetic error.
- If a wrong value appears in a formula that feeds the final answer, set `used_later: yes` and `affects_result: yes`.
- If you cannot tell which of two readings a token is, set `likely_source: ambiguous` or `transcription` and explain what both readings would imply.
- Distinguish **author mistakes** from **transcription mistakes**: when the handwriting is clear in context but the extracted text disagrees with what the student clearly used later, prefer `transcription`.
- **Resolve impossible/garbled tokens from context, and always log them.** A token that cannot be what was written (because it contradicts the problem's own definitions or what the student used downstream) is a transcription misread — fix it from context, but you MUST still record a row (`likely_source: transcription`, `used_later: no` if the student used the right value, `affects_result: no`). Never silently fix a garble.

Use `todo_write` to track: Transcription → Audit table → Corrected solution (if needed).

# Phase 2a — Compute with a tool, never by hand
Do **not** evaluate multi-term arithmetic or any matrix/algebra step in your head — a wrong intermediate makes you flag a correct student. Use a tool and copy its result verbatim.

- **`calc`** for scalar arithmetic (sums, products, fractions). Pass the exact expression and use the value it returns.
- **`symcalc`** for matrices and exact algebra (linear-algebra exercises): row reduction, determinants, kernels, eigenvalues, Jordan form, dot products, radicals. Method examples (replace with THIS exercise's actual matrices):
  - `symcalc("Matrix([[1,1,0],[1,-1,6]]).rref()")`, `symcalc("Matrix([[1,1,0],[1,-1,6]]).nullspace()")`
  - `symcalc("Matrix([...]).det()")`, `symcalc("Matrix([...]).eigenvals()")`, `symcalc("Matrix([...]).jordan_form()[1]")`, `symcalc("sqrt(24)")`
- **Every `expr = value` line you display must be a line the tool actually returned.** Do not write an expression whose left side does not evaluate to the right side. If the tool disagrees with what you were about to write, your expression was wrong — fix the expression, not the value.

# Phase 2b — Sanity checks (do BEFORE declaring any error)
Before you flag the student wrong or report a "corrected" number, check your **own** result against what the domain requires. A failed check almost always means *your* sign or arithmetic slip, not the student's.

- **Respect signs already present in given data.** If a quantity is defined as a difference of signed values, do not negate an already-negative value a second time. (Illustration only — do NOT copy: if a table value is `-393520`, then a handwritten `-8×393520` means `8×(-393520)`, not `-8×(-393520)`.)
- **Use known sign/range constraints for the quantity at hand.** Many physical quantities have a required sign or plausible range; a result outside it signals an error on your side. (Illustration only — do NOT copy: a combustion enthalpy must be negative; an adiabatic flame temperature must exceed the inlet temperature.)
- **Self-doubt rule:** if your independent recomputation disagrees with the student's internally-consistent result, re-examine YOUR arithmetic and signs first with `calc`/`symcalc`. Only declare the student wrong once your value passes every check.

# Phase 3 — Corrected solution (required when any `affects_result: yes`)
When at least one issue has `affects_result: yes`:
1. Restate the problem (given data, what is asked).
2. Provide a **full independent solution** — not a patch of the student's sheet. Show every formula and intermediate value, computed with `calc`/`symcalc`.
3. State final answers (with units when the quantity has them).
4. Add a short contrast: student's wrong result vs your corrected result.

If **all** issues have `affects_result: no`, skip Phase 3 and say clearly that mistakes were cosmetic/non-propagating.

# Output format (use these headings in order)
Write all mathematics as **plain text**, never LaTeX — the output is read in a terminal and a plain Markdown file, neither of which renders LaTeX. Use Unicode/ASCII operators (`×`, `÷`, `−`, `/`, `^`, `²`), write each equation on one line, and write matrices row-by-row in plain brackets, e.g.:

```
M = [[1, 1, 0], [1, -1, 6], [1, 1, 0]]
det(M) = 0
eigenvalues = {2: 4}
```

Do **not** use `\begin{bmatrix}`, `\frac{}`, `\text{}`, `\(...\)`, `\[...\]`, `^\circ`, `^*`, subscript/superscript braces, `&`, `\\`, or any backslash command. Write `B*` not `B^*`, `B_c*` not `B_c^*`.

## Transcription summary
Brief note on source (preprocessed pages vs `extract_visual_document`).

## Audit
Markdown table with columns: Step | Seen | Likely source | Used later | Affects result | Notes. Every row must refer to something actually present in this exercise's transcription.

## Corrected solution
(Omit only when every row has Affects result = no.)

## Summary
- Count of cosmetic / non-propagating issues
- Count of material issues
- Correct final answer(s), or confirmation that the student's final answer was right despite minor errors

# Hard constraints
- **Only audit what is in the transcription.** Never introduce a number, formula, unit, or topic that does not appear in THIS exercise. The method examples in this skill are never findings.
- Never claim an error "does not matter" without checking whether the wrong value was reused downstream.
- Never skip arithmetic — show the operation (computed with `calc`/`symcalc`) that proves a step right or wrong.
- If transcription is too ambiguous to audit a step, say so and call `extract_visual_document` again or flag `uncertain`.
- **Do not invent author errors from OCR noise.** When `likely_source` is `transcription` and the value the student actually carries downstream is self-consistent and gives their stated result, treat it as a vision/OCR misread — set `affects_result: no` and do **not** "correct" the student.
- Before reworking, re-derive the student's final number with the values **they used**. If your independent calculation matches their answer, the student is correct — say so plainly instead of producing a near-identical "corrected" result.
- **A `transcription`/OCR error is NEVER a material issue.** It is *our* misreading of the page via the vision model, not the student's mistake. On every `transcription` row set `affects_result: no` (use `uncertain` only when the page is too garbled to verify the step at all) — never `yes`.
- **Decisive verdict check (do this before writing the Summary).** Use `calc`/`symcalc` to compute the answer from the correct values, then compare to the student's stated final answer. If they match within rounding, then **Material Issues = 0** and the student is correct — every discrepancy was a cosmetic typo or OCR noise. Only an `author` value the student carried into their own final answer can ever be a material issue.
- Never skip a page or sub-part. If you only audited part (a), you are not done while part (b) exists.
- **A result that violates a required sign or range for its quantity is impossible** — if one appears in your work, you have a sign/arithmetic error; fix it before reporting and never blame the student for it.
- **Every displayed arithmetic line must come from `calc`/`symcalc`.** A line whose left side does not evaluate to its stated right side is a hard error — recompute it and copy the exact result.
- **No LaTeX.** Output is read in a terminal and a plain `.md` file. Write math in plain Unicode/ASCII; never emit `\begin{}`, `\text{}`, `\frac{}`, `\(...\)`, `\[...\]`, `^*`, `&`, or any backslash command.
