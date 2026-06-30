---
name: transcribe_document
description: Transcribe a handwritten or scanned document to clean plain text, fixing only obvious vision/OCR misreads — no solving, grading, or auditing.
when_to_use: User provides a handwritten/scanned PDF or image and asks to transcribe it, pass it to clean text, or read what it says (without asking to check or solve it).
allowed-tools: todo_write extract_visual_document
disable-model-invocation: false
---
# Goal
Produce a faithful, clean transcription of the document. A vision model has
already read each page; your job is to assemble those readings into a readable
transcription and fix **only** obvious misreads. You are NOT solving, grading,
checking, or auditing anything.

# What you must NOT do
- **Ignore any audit/review/corrected-solution/error-summary content earlier in this conversation** — it belongs to a different task. This turn is transcription only; do not reproduce that format, those tables, or those headings.
- Do **not** judge whether the work is correct.
- Do **not** solve the exercise, recompute anything, or add a "corrected" version.
- Do **not** add commentary, audit tables, verdicts, or opinions.
- Do **not** change the author's actual content, choices, or math — even if it looks wrong. If the student wrote `2 + 2 = 5`, you transcribe `2 + 2 = 5`.

# Source
- If per-page transcriptions are already in the message (injected as `[Image: …]` blocks from vision preprocessing), use them as the primary source.
- Otherwise call `extract_visual_document` on the file path.

# Cleanup — fix only obvious vision/OCR slips
The vision model sometimes confuses similar-looking glyphs. Fix a token **only** when context makes the intended character unambiguous:

- digit/letter swaps: `O`↔`0`, `l`/`I`↔`1`, `S`↔`5`, `B`↔`8`, `Z`↔`2`, `g`↔`9`
- a number misread as a letter or vice versa (e.g. a coefficient shown as `n7` where the surrounding equation clearly needs `47`)
- a misread operator (`x` for `×`, `−` vs `-`), a dropped/garbled subscript or superscript
- obvious spacing artifacts that split a token (`C 8 H 18` → `C8H18`)

Rules for fixing:
- Prefer the reading that is **internally consistent** with the rest of that line/equation and with the problem statement.
- If a token is **genuinely ambiguous** (both readings plausible), keep both: `[4.7 or 47?]`. Do not silently guess.
- If a span is unreadable, mark it `[illegible]`.
- Never "fix" something by changing the meaning — you are correcting *our* reading of the page, not the author's work.

# Coverage
- Transcribe **every page** and **every labelled sub-part** (a, b, c, …). Never stop after the first page.
- Each `[Image: …]` block is one page. If a page is blank or sparse, say so explicitly (`(page N: blank / no work)`), don't skip it.
- Use `todo_write` to track pages if the document is long.

# Output format
Write everything as **plain text** — the result is read in a terminal and saved as a plain `.md`, neither of which renders LaTeX.

- Use Unicode/ASCII math: `×`, `÷`, `−`, `/`, `^`, `²`, `√`. Write `B*` not `B^*`.
- Write matrices row-by-row in plain brackets, e.g. `M = [[1, 1, 0], [1, -1, 6]]`.
- Never emit `\begin{}`, `\frac{}`, `\text{}`, `\(...\)`, `\[...\]`, `&`, `\\`, or any backslash command.
- Preserve the document's structure: page headings, problem numbers, step labels, line breaks.

Use these headings:

## Transcription summary
One or two lines: how many pages, source (preprocessed pages vs `extract_visual_document`), and any pages that were blank/illegible.

## Transcription
The cleaned transcription, organized by page (and problem/sub-part where labelled). One `### Page N` (or `### Problema N`) heading per page.

# Hard constraints
- Transcribe only — no solving, no grading, no audit, no corrected solution.
- Output exactly the two headings below (`## Transcription summary`, `## Transcription`) and nothing resembling an error/audit table or a corrected-solution section, regardless of anything earlier in the conversation.
- Cover every page and sub-part; never silently drop one.
- Fix only unambiguous glyph misreads; keep ambiguous tokens as `[a or b?]`.
- Plain text only, never LaTeX.
