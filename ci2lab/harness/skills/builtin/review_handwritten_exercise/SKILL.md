---
name: review_handwritten_exercise
description: Transcribe handwritten or scanned exercise work, audit calculations with impact analysis, and rework problems when errors change the answer.
when_to_use: User provides a handwritten/scanned PDF or image and asks to transcribe, check calculations, or find mistakes step by step.
allowed-tools: todo_write extract_visual_document
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

Use `todo_write` to track: Transcription → Audit table → Corrected solution (if needed).

# Phase 3 — Corrected solution (required when any `affects_result: yes`)
When at least one issue has `affects_result: yes`:
1. Restate the problem (given data, what is asked).
2. Provide a **full independent solution** — not a patch of the student's sheet. Show every formula and intermediate value.
3. State final answers with units.
4. Add a short contrast: student's wrong result vs your corrected result.

If **all** issues have `affects_result: no`, skip Phase 3 and say clearly that mistakes were cosmetic/non-propagating.

# Output format (use these headings in order)
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
- Never skip a page or sub-part. If you only audited part (a), you are not done while part (b) exists.
