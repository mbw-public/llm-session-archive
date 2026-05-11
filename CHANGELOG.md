# CHANGELOG — goose_extract.py

All changes in reverse chronological order.

---

## 2026-05-10  Added split_session.py to the toolchain

**New script:** `split_session.py` splits a session markdown file into
chunks of N turns each, named by actual turn numbers for self-documentation
(e.g. `session-monroe-0001-0075.md`). Useful for opening large sessions in
markdown previewers that struggle with multi-megabyte files.

Default chunk size is 75 turns; override with `--turns N` for narrower
windows when debugging rendering issues.

**Usage:**
```bash
python3 split_session.py session.md
python3 split_session.py session.md --turns 10
```

---

## 2026-05-10  Strip backtick fence markers from thinking block content

**Problem:** Thinking blocks containing backtick fence markers (e.g. an AI
opening a code block mid-thought and never closing it, or an empty
` ``` `…` ``` ` pair) caused Marked 2 to break rendering at that turn,
swallowing all subsequent content. `close_unclosed_fences` did not help
because the fences were technically balanced — the issue was the combination
of fence markers inside `<details>` blocks, which Marked 2's parser handles
poorly regardless of balance.

**Fix:** Added `strip_fences_from_thinking(text)` which removes all backtick
fence lines from thinking content before it is wrapped in `<details>`. Thinking
blocks are informal prose; they don't need code fence formatting, and removing
the markers has no meaningful effect on readability while eliminating the
parser interaction entirely.

Applied in `render_blocks()` immediately before `close_unclosed_fences()`
in the `thinking` branch. `import re` moved to top-level imports.

---

## 2026-05-10  Added --db option for specifying an alternate database path

**Feature:** `goose_extract.py` previously only read from
`~/.local/share/goose/sessions/sessions.db` (or the `GOOSE_DB` env var).
Added `--db FILE` to point directly at any `sessions.db` on disk — useful
when working with a copy received from another user or stored on an external
drive.

`--db` takes precedence over `GOOSE_DB`, which takes precedence over the
default location. Works with all DB-backed commands: `--list`, `--schema`,
`--all`, and session extraction by ID.

**Usage:**
```bash
python3 goose_extract.py --db ./sessions.db --list
python3 goose_extract.py --db ./sessions.db 20260503_1 --out session.md
python3 goose_extract.py --db ./sessions.db --all --out-dir ./transcripts
```

---

## 2026-05-09  Fixed AttributeError in Pass 2 when consecutive thinking blocks are nulled

**Problem:** `clean_thinking_blocks()` crashed with:

```
AttributeError: 'NoneType' object has no attribute 'get'
```

at `merged[prev_i].get("thinking", "")` in Pass 2.

**Root cause:** When a thinking block at `curr_i` is set to `None` (pure repeat,
dropped by the `trimmed == prev_text` guard), the *next* loop iteration uses
that same index as `prev_i` — and then calls `.get()` on `None` before the
`merged = [b for b in merged if b is not None]` cleanup runs.

**Fix:** Skip any `prev_i` that was nulled in a prior iteration:

```python
if merged[prev_i] is None:  # was nulled in a prior iteration
    continue
```

---

## 2026-05-04  Fixed unclosed fenced code blocks inside <details> elements

**Problem:** Thinking blocks and collapsed tool results containing unclosed
fenced code blocks (e.g. ` ```swift ` without a closing ` ``` `) caused the
markdown parser to treat `</details>` as part of the code block. This silently
swallowed all subsequent turns until the next natural fence close, making large
sections of the transcript disappear.

**Fix:** Added `close_unclosed_fences(content)` helper that walks the content
line by line tracking fence state (` ``` ` or `~~~`). If a block is still open
at the end of the content, the closing fence is appended before the content is
inserted into `<details>`. Applied to both thinking blocks and collapsed tool
results.

---

## 2026-05-04  Tool result collapse: label + 3-line preview format

**Problem:** The previous collapse format appended the first line of content to
the `<details><summary>` line, which was confusing for multi-value content like
`77 files, 40698L, 1449F, 417C (depth=2)` — it read as part of the summary
rather than as a preview of the data.

**Fix:** Replaced the single-line summary hint with a proper 3-line preview
block shown *outside* the `<details>` element, so it renders as a visible code
block before the collapsible section:

```
**[TOOL RESULT ← 856468923]**  *(85 lines)*

```
77 files, 40698L, 1449F, 417C (depth=2)
(17 files skipped: no parser)
rust 100%
…
```

<details><summary>Show all 85 lines…</summary>
[full fenced block]
</details>
```

Blank lines are skipped when collecting preview lines so the 3 slots are always
filled with meaningful content. The `…` suffix is added when the full result
exceeds 3 lines.

Also: `rg` / `sd` suggestions applied; `ruff format` run on the file.

---

## 2026-05-04  Added --collapse-results option

**Feature:** Long TOOL RESULT blocks dominate the output when a session reads
many source files. `--collapse-results N` wraps any TOOL RESULT longer than N
lines in a `<details>` element, keeping the file navigable.

Suggested default: `--collapse-results 20`. From analysis of
`llm_backends_exploration.md`, tool result lengths ranged from 8 to 506 lines;
most substantive results exceeded 20 lines while trivial acknowledgements fell
below it.

The threshold is noted in the session header when active.

---

## 2026-05-04  Added --json support for Goose JSON export files

**Feature:** Goose can export sessions as standalone JSON files (e.g. when
sharing a session or working with older `.jsonl`-era exports). These have the
same logical structure as the SQLite database but different field names and
types.

Key differences handled:
- `content` is an already-parsed list (not a JSON string `content_json`)
- `model_config` is a dict (not a JSON string), with key `model_name`
  instead of `model_id`
- Tool calls use `toolRequest`/`toolResponse` block types instead of
  `tool_use`/`tool_result`, with a nested `toolCall.value` structure
- Messages live in a `conversation` array instead of a separate table

**Refactoring:** `extract()` was split into a pure rendering function that
takes pre-loaded `(session, messages)` dicts, plus two thin loaders:
- `load_session_from_db()` — reads from SQLite, normalises to shared format
- `load_session_from_json()` — reads JSON export, normalises to same format
- `extract_from_db()` / `extract_from_json()` — thin wrappers for the CLI

`render_content_json()` was split into:
- `render_blocks(blocks)` — takes a pre-parsed list; core rendering logic
- `render_content(raw)` — accepts either a JSON string or a pre-parsed list

`count_tools()` updated to handle both `content_json` string and `content`
list, and both `tool_use` and `toolRequest` block types.

**Usage:**
```bash
python3 goose_extract.py --json session.json
python3 goose_extract.py --json session.json --out session.md
python3 goose_extract.py --json session.json --stats-only
```

**Verified** on a 4.5MB / 126K-line JSON export (312 messages, 2.7M tokens),
producing a clean 380KB markdown file — a 12× size reduction with no stripping
step required.

---

## 2026-05-04  Pass 2: drop trimmed block if it equals prev_text

**Problem:** `[4] ASSISTANT` and similar messages still showed two identical
thinking blocks after the previous fix.

**Root cause:** Inspecting the raw `content_json` for message [4] (db id 181)
revealed a mixed storage pattern — not purely individual tokens OR cumulative
snapshots, but both in the same message:

```
blocks 0–17:  individual streaming tokens  → "The user wants me to … structure.\n"
block  18:    empty text block             → ''   (breaks the consecutive run)
blocks 19–20: two identical cumulative     → full sentence, full sentence again
              snapshots
block  21:    toolRequest
```

After Pass 1 (concat consecutive runs):
- `thinking_A` = tokens 0–17 concatenated = full sentence
- `thinking_B` = blocks 19+20 concatenated = full sentence × 2

After Pass 2 prefix trim: `thinking_B` starts with `thinking_A`, so prefix is
stripped, leaving `trimmed` = full sentence (a second copy). Since `trimmed`
was non-empty, it was kept — producing a second identical thinking block.

**Fix:** After trimming the prefix, also drop the block if `trimmed == prev_text`
(the remainder is just another copy of the previous block, not new content):

```python
merged[curr_i] = {"type": "thinking", "thinking": trimmed} \
    if (trimmed and trimmed != prev_text) else None
```

**Verified** using `rg -A 6 -m 8 /details goose-08.md` — all `</details>` tags
correctly followed by tool requests, separators, or opening prose sentences.

---

## 2026-05-04  Reverted Pass 1 to concat; Pass 2 rewritten as prefix trim

**Problem:** `[16] ASSISTANT` had no thinking section at all in the output.

**Root cause:** Inspecting the raw blocks for message [16] (db id 193) showed
1043 individual token blocks with `thinking[-1] = '\n'`. The "replace" approach
from the previous fix kept only the last block — a bare newline — which stripped
to empty and rendered nothing.

The tokens are **individual** (not cumulative), so concatenation is correct for
Pass 1. The doubling seen earlier came from a different mechanism: separate
thinking groups where the second group repeats the content of the first.

**Fix:**
- Reverted Pass 1 to **concatenation** (correct for individual tokens).
- Replaced the removed Pass 2 with a new **prefix-trim** pass: for each pair of
  adjacent thinking groups (after the merge), if the later group's content starts
  with the earlier group's content, strip that prefix from the later group. If
  nothing meaningful remains, drop it entirely.

---

## 2026-05-04  Pass 2 removed; Pass 1 changed to replacement

**Problem:** `[16] ASSISTANT` thinking section missing (no improvement over
previous version).

**Fix (Pass 2 removal):** Pass 2 searched forward for *any* later thinking block
and dropped the current one if the later block started with the same text. This
was too broad — it matched across genuinely separate reasoning steps, silently
discarding legitimate thinking content.

**Fix (Pass 1 replacement):** Changed Pass 1 from concatenation to replacement
(keep last block in each consecutive run), reasoning that llama_swap stored
cumulative snapshots. This turned out to be incorrect — the tokens are individual,
not cumulative — and was reverted in the next fix.

*(Both changes were superseded and replaced in the following revision.)*

---

## 2026-05-04  Three-pass `clean_thinking_blocks()` introduced

Refactored inline thinking-block handling into a named function with three
documented passes:

- **Pass 1** — merge/concat consecutive thinking blocks (streaming tokens)
- **Pass 2** — drop thinking block if its content is a prefix of a later thinking
  block *(later replaced)*
- **Pass 3** — drop thinking block if content exactly matches the next text block

This made the llama_swap quirks explicit and independently testable.

---

## 2026-05-04  Initial thinking block deduplication

**Problem:** Each assistant response rendered dozens or hundreds of
`<details><summary>💭 Thinking</summary>` sections — one per streaming token.

**Root cause:** `llama_swap` stores each streamed response token as a separate
`thinking` content block. A 20-word reply produces 20+ blocks.

**Fix:** Before rendering, merge consecutive thinking blocks by concatenating
their `thinking` strings. Also added Pass 3: drop a thinking block when its
content exactly matches the immediately following text block (the completed
response stored a second time as a `text` block).

---

## 2026-05-04  Initial version

First working release. Correctly reads Goose's SQLite database at
`~/.local/share/goose/sessions/sessions.db` and extracts:

- **Session header:** name, timestamps, working directory, provider, model,
  mode, token totals (`accumulated_*_tokens` from the sessions row)
- **Full transcript** with role headers and per-message token counts
- **Stats section:** per-message token table, tool call breakdown by name
- **All Anthropic content block types:** `text`, `tool_use`, `tool_result`,
  `thinking`; unknown types rendered as fenced JSON so nothing is silently lost

Key fixes discovered during schema inspection:

- Content column is `content_json`, not `content`
- Token data lives on the sessions row (`accumulated_*_tokens`), not per message
- `sqlite3.connect()` with plain path required — `file:?mode=ro` URI syntax
  fails on macOS; `PRAGMA query_only = ON` used instead for read safety
- `fmt_ts()` handles both INTEGER epoch (`created_timestamp`) and ISO string
  (`created_at` / `updated_at`) timestamp formats

**Commands:** `--list`, `--schema`, `--stats-only`, `--transcript-only`,
`--out`, `--all`, `--out-dir`, `-n`
