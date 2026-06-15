# CHANGELOG — llm-session-archive

All changes in reverse chronological order.

---

## 2026-06-15  extract_sessions: preserve dots in auto-generated filenames

The `name_slug` sanitization in the menu/auto-name logic used the same
`[A-Za-z0-9_-]` allowlist that `rename-extract-files.sh` had before its
2026-06-10 fix, so `-a` auto-named output files turned dots in model names
into underscores (e.g. `Qwen3.5-9B-MTP` -> `Qwen3_5_9B_MTP`). Widened to
`[A-Za-z0-9._-]` to match `rename-extract-files.sh`, so dots in model-name
stems are preserved in both tools.

---

## 2026-06-10  rename-extract-files.sh: preserve dots in sanitised filenames

The character allowlist in `process_file()` was `[A-Za-z0-9_-]`, which
replaced dots with underscores — turning e.g. `Qwen3.5-9B-MTP` into
`Qwen3_5_9B_MTP`.  Dots are valid and meaningful in model-name stems
(version numbers), so the allowlist is widened to `[A-Za-z0-9._-]`.
Characters that are genuinely problematic in filenames (spaces, colons,
slashes, glob chars, etc.) are still replaced.

Updated the inline comment and the file-header description to match.

---

## 2026-06-08  pi_extract.py: branch detection guard; session_info name support

**Branch detection guard** — `detect_branches(records)` counts parent nodes
with more than one child by running a `Counter` over all non-null `parentId`
values.  Any count > 0 means the session has been branched and sequential
extraction will interleave content from multiple paths.  When triggered:
- A `Warning:` line is printed to stderr at extraction time.
- A `⚠️ WARNING:` line is embedded in the output header so the alert is
  preserved in any extracted `.md` file.
Linear sessions (all `parentId` values unique) produce no output change.

**`session_info` name support** — both `scan_session` and `extract` now scan
for `type == "session_info"` records and read the `name` field (falling back
to `displayName`).  When found:
- `extract`: the name becomes the `#` heading and a `Name:` metadata line is
  added to the header; the cwd-derived fallback title is still used when no
  `session_info` record is present.
- `--list`: the trailing column header changes from `Project` to `Name`; the
  session name is shown when available (up to 40 chars), otherwise the
  cwd-derived project path is shown as before.
Monroe's current sessions have no `session_info` record, so `--list` output
is unchanged until Pi generates one.

---

## 2026-06-08  pi_extract.py: new extractor for Pi agent (experimental)

Added `pi_extract.py`, an experimental extractor for
[Pi](https://pi.dev), a local AI coding agent.

Pi stores sessions under `~/.pi/agent/sessions/<encoded-project-path>/`
as `<timestamp>_<uuid>.jsonl` files.  The format is structurally distinct
from the other extractors:

- **Linked-list record structure** — every record carries `id` and `parentId`
  fields; extraction follows file order, which matches the chain for linear
  sessions.
- **Three message roles** — `user`, `assistant`, and `toolResult`; tool
  results are first-class records (not embedded in user turns as in Claude
  Code), and consecutive `toolResult` records from a multi-call assistant
  turn are batched into a single `[N] TOOL RESULTS` section.
- **Session-level metadata records** — `session`, `model_change`, and
  `thinking_level_change` carry provenance data parsed into the header.
- **Thinking blocks** — rendered in collapsible `<details>` by default;
  suppress with `--no-thinking`.
- **Token usage** — `input`, `output`, `cacheRead`, `cacheWrite` per
  assistant turn (camelCase, unlike Claude Code’s snake_case fields).

Features consistent with the other extractors: `--list`, `--all`, `-n`,
`--no-thinking`, `--stats-only`, `--transcript-only`, `--collapse-results`,
`--no-collapse`, `--out`, `--out-dir`, `--sessions-dir` / `PI_SESSIONS`.

Post-review fixes (Monroe Williams):
- `load_session()`: removed redundant `Path()` wrapping.
- `render_tool_results()`: added shebang-based language inference (`bash`,
  `python`) so preview and full fenced blocks carry the same lang hint.
- `get_sessions_dir()`: `PI_SESSIONS` env-var path now validated for
  existence, consistent with `--sessions-dir`.
- `list_sessions()` and `export_all()`: `FileNotFoundError` (Pi not
  installed) now caught and printed as a plain one-line message; no traceback.

`pi_extract.py` added to `extract_sessions`; silently skipped when Pi is
not installed.

---

## 2026-06-08  extract_sessions: fix unbound-array crash and claudecode column mismatch

- **`flags[@]: unbound variable`** — with `set -u` active, expanding an empty
  array as `"${flags[@]}"` is treated as unbound in bash. Changed to the
  safe pattern `${flags[@]+"${flags[@]}"}` on the final `exec` line.
- **claudecode normalization removed** — the normalization block that widened
  Model 30→39 and dropped Project was written for a now-defunct list format.
  The current `claudecode_extract.py --list` format already uses Model=39 and
  puts Name(28) before Project, matching all other tools. The normalization
  was mangling the columns instead of fixing them. Replaced with a simple
  `if/else` that bounds the name slug to 28 chars for claudecode (to exclude
  the trailing Project) and uses the full remaining line for other tools.

---

## 2026-06-08  split_session: fix turn regex; close_unclosed_fences: dual-fence tracking

Two fixes from a third-party code review.

`split_session.py` — `TURN_RE` only matched `USER` and `ASSISTANT`, missing
`SYSTEM` and `TOOL RESULTS` turns produced by `claudecode_extract`. Sessions
with those turns would have incorrect chunk boundaries. Regex expanded to:
`(USER|ASSISTANT|SYSTEM|TOOL RESULTS)`.

`close_unclosed_fences` in `claudecode_extract`, `goose_extract`, and
`jan_extract` — the previous single `fence_char` variable failed when both
backtick and tilde fences appeared in the same block: opening a tilde fence
while a backtick fence was already open would go undetected. Replaced with
the dual-tracking pattern from `lmstudio_extract` (`backtick_open` and
`tilde_open` toggled independently), which correctly closes both types when
either or both are unclosed.

---

## 2026-06-08  extract_sessions: overhaul auto-naming and UX

- **Name-based auto-naming** — `-a` filenames now use the sanitized session
  title (`YYYYMMDD-TOOL-Name.md`) instead of the session ID prefix.
- **Whitelist sanitization** — name slugs restricted to `[A-Za-z0-9_-]`;
  spaces, slashes, quotes, `?`, and all other characters replaced with `_`,
  with runs collapsed. Same sanitization applied to `rename-extract-files.sh`.
- **`-n 1 -a` skips confirmation** — when exactly one session is shown and
  auto-naming is active, the pick prompt is bypassed.
- **`?` date → `unknown`** — sessions with no stored timestamp produce
  `unknown-TOOL-Name.md` instead of `?-TOOL-Name.md`.
- **Display fixes** — leading spaces trimmed from Name column for sessions
  where the title starts with whitespace (common in Claude Code sessions
  with no explicit title).
- **`--out-dir` removed** — meaningless for single-session extraction.
- **Opt-out defaults aligned** — `SHOW_THINKING` → `NO_THINKING=false`,
  `COLLAPSE` default changed to `""` (defer to extractor's built-in 20-line
  default); `--no-thinking` and `--no-collapse` added.
- README updated with an `extract_sessions` usage section.

---

## 2026-06-07  claudecode_extract: deduplicate split-record assistant messages

Claude Code stores a single API response as multiple JSONL records sharing
the same message `id` (one per content block type — typically a
thinking-only record followed by a text/tool_use record). The extractor
was counting the usage data from every record, inflating token totals by
2-3× for sessions that use thinking.

Fix: `extract()` and `scan_session()` now track seen message IDs in a
`seen_msg_ids` set and only accumulate usage for the first occurrence of
each `id`. Transcript rendering is unaffected — both records are still
shown so thinking blocks and response text both appear.

---

## 2026-06-07  claudecode_extract: fix tool_result label and name lookup

Tool results in Claude Code sessions are stored as `user`-role messages
(Anthropic API convention). Two rendering problems fixed:

- **`[N] USER` label on tool-result-only messages** — when a user message
  contains only `tool_result` blocks (no human text), it is now labelled
  `[N] TOOL RESULTS` instead of `[N] USER`.
- **Tool name showing as `?`** — `tool_result` blocks carry a `tool_use_id`
  but not the tool name; the name lives in the preceding assistant's
  `tool_use` block. `extract()` now does a first pass over all records to
  build a `tool_use_id → name` map, which is passed through to
  `flatten_content()` for both user and assistant messages.
- **`is_tool_results_only` check** — uses `not any(non-empty text block)` rather
  than `all(type == tool_result)`, so stray metadata blocks in the content
  list don't prevent the `TOOL RESULTS` label. Mixed messages that contain
  both a `tool_result` block and genuine human text correctly stay as `USER`.
- **`is_error` flag** — `tool_result` blocks with `is_error: true` now
  render as `TOOL ERROR` rather than `TOOL RESULT`.

---

## 2026-06-07  rename-extract-files.sh: files, validation, truncation, -d

- **Multiple path arguments** — accepts any mix of files and directories;
  directories are still processed non-recursively. Enables `*.md` globs and
  multi-directory passes in one invocation.
- **`is_extract()` guard** — files without a `# Title` first line and a
  recognised metadata field on line 2 are skipped with a `NOT EXTRACT`
  warning and counted in the summary.
- **Filename truncation** — stems longer than `MAX_STEM` (default 64) are
  sliced at the last word boundary (underscore) before the limit; a
  `(truncated)` flag appears on the rename line.
- **`-d` short option** added as alias for `--dry-run`.
- README updated with a dedicated `rename-extract-files.sh` usage section.

---

## 2026-06-06  rename-extract-files.sh: promote to reusable tool

Originally `rename-jan-tests-01.sh`, a one-shot script for renaming Jan
test exports. Proved equally useful on LM Studio exports, so promoted to
a proper reusable tool as `rename-extract-files.sh`.

- Directory taken as a required positional argument (was hardcoded to
  `JanTests` via a `JANTEST_DIR` env var fallback)
- `--help` / `-h` added with `usage()` function
- Proper option parsing loop — `--dry-run` and the directory accepted in
  either order; unknown options error with usage
- Dry run now reports a count (`N would rename | N already correct | N
  conflicts`) instead of just "Dry run complete"
- `moved` counter incremented during dry run so the summary is accurate
- Phonemes special-case removed (was Jan-specific; general rule handles it)
- No `.md` files found now exits 0 (not an error)
- Output labels aligned (`SKIP`, `DRY RUN`, `MOVED`, `CONFLICT`)

---

## 2026-06-06  jan_extract: fix ghost-placeholder filter swallowing reasoning-only responses

`load_thread()` skipped assistant messages whose text blocks were all empty,
intended to drop Jan's ghost placeholder created at thread start. The check
used `all(... for c in content if c.get("type") == "text")` — when an
assistant response contained *only* a `"reasoning"` block (no text block),
the filtered generator was empty and Python's `all()` returned `True`
vacuously, causing the real response to be silently dropped.

Fix: replaced the `all_empty` text-only check with a `has_renderable` check
across all three known renderable block types (`text`, `reasoning`,
`tool_call`). A ghost placeholder has only empty text blocks and will
correctly produce `has_renderable=False`; a reasoning-only response will
now correctly produce `has_renderable=True` and be kept.

Affected sessions: any Jan thread where the assistant responded with only
a reasoning block and no plain text block (observed with Hermes-4-14B).

---

## 2026-06-06  jan_extract: handle tool_call blocks

Jan's `"type": "tool_call"` blocks combine a tool call and its result in
a single content block (with `tool_name`, `input`, `output` fields and no
`text.value`). The previous `render_message()` gated on `text.value` and
silently dropped these blocks entirely, so tool-enabled sessions (e.g.
Qwen3.5-9B with web search) were missing all search calls and results.

- Added `tool_call` handling before the `text.value` gate in
  `render_message()`: renders the input as `TOOL CALL`, then the
  concatenated `output[].text` values as `TOOL RESULT`, with full
  collapse/expand support respecting `collapse_results`.
- Updated `render_message()` docstring to document all three block types.

Note: Qwen2.5-Coder-14B's "thinking" content is stored as a plain
`"text"` block with no `<think>` tags or `"reasoning"` wrapper — Jan
does not classify it as a reasoning block, so it cannot be detected or
collapsed by the extractor.

---

## 2026-06-06  Flip thinking and collapse to opt-out defaults

Both features are now on by default — a bare `<session_id>` is all
you need to get a fully rendered transcript.

- `--show-thinking` removed; replaced by `--no-thinking` across all
  four extractors (`claudecode`, `goose`, `jan`, `lmstudio`).  The
  argparse implementation uses `dest="show_thinking"`,
  `action="store_false"` + `set_defaults(show_thinking=True)`.
- `--collapse-results` default changed from `None` to `20` across all
  four extractors.  `--collapse-results=N` still overrides the
  threshold; `--no-collapse` added as the escape hatch (sets
  `collapse_results=None`, showing all TOOL RESULT blocks untruncated).

---

## 2026-05-30  Widen Model column to 39

Model width increased from 25 to 39.  Models longer than 39 chars
can be told apart by renaming the session. Plain right-truncation
with `trunc()` is used; `trunc_mid()` was considered and rejected
as visually distracting. Separator lines updated to 122 (goose,
jan, lmstudio) and 144 (claudecode).

---

## 2026-05-29  Add end-of-thinking marker inside thinking `<details>` blocks

When a thinking block is expanded, its content blended visually into the
assistant response that follows. Initially a `---` rule was added before
`</details>`, but this produced a double hairline when the thinking block
was the last element in a turn (the turn separator `---` already follows
every `**[N] ROLE**` header). Replaced with `*— end thinking —*` in
italics: clearly labelled, survives copy-paste as readable text, and cannot
be confused with a turn separator. Applied to all four extractors.

---

## 2026-05-26  Fix help text wording and line-break consistency in override/collapse options

When scripts are run through a pipe (e.g. `fd ... | sh -c '{} -h'`), argparse
loses tty detection and falls back to ~80-char terminal width, giving ~54 chars
for help text. Strings were adjusted so all four `--*-dir` / `--db` overrides
line-break consistently after `via`:

- `--threads-dir`: "Override **default** Jan threads directory (also via
  JAN_THREADS env var)" — "default" added to push `JAN_THREADS` onto the
  next line
- `--db` (goose): rewritten from the divergent "Path to sessions.db (overrides
  default location and GOOSE_DB env var)" to "Override default sessions.db
  location (also via GOOSE_DB env var)" — now matches the pattern of the
  other three
- `--collapse-results`: removed `; use --collapse-results=N to set threshold`
  suffix — made the help line too long and the `=N` advice is already implied
  by the metavar and docstring examples

---

## 2026-05-26  Refine option order and help text

- `--show-thinking` moved before `--collapse-results` so all output-shaping
  options are grouped together: `--stats-only`, `--transcript-only`,
  `--show-thinking`, `--collapse-results`
- `--collapse-results` help updated to note that `--collapse-results=N` is
  the safe form when a session_id follows (with `nargs='?'`, a bare space-
  separated value may be consumed as the positional argument)
- `--all` help updated to `Export all sessions (combine with -n to limit)`,
  since `-n` appears well above `--all` in the options list

Applied identically to all four extractors.

---

## 2026-05-26  Standardise argparse option order and positional argument naming

All four extractors now present options in the same order and use the same
positional argument name:

**Positional renamed to `session_id`** in lmstudio (was `file`) — help text
updated to `Session ID or unique substring — run --list to see them` across
all four. goose's positional help was also updated to match (previously
`Session ID from sessions.db (e.g. 20260503_1)`).

**Option order** now matches the canonical order from the pre-existing
`*_help.txt` spec files, with `--show-thinking` slotted in after `--out-dir`
(it wasn't in the spec files as they predate today's changes):

```
session_id (positional)
--list
-n
--stats-only
--transcript-only
--collapse-results
--out
--all
--out-dir
--show-thinking
<tool-specific>  (--projects-dir / --threads-dir / --conversations-dir)
                 (goose only: --schema, --json, --db)
```

The `--list` / `--all` members of the mutually exclusive group are now added
to the group at their intended positions in the help output rather than all
upfront, taking advantage of argparse preserving insertion order.

---

## 2026-05-26  Tighten `--list` column widths; add truncation with `…`

All four extractors now use identical column widths and a shared `trunc(s, n)`
helper that appends `…` when a value is cut short:

| Column     | Width | Notes |
|------------|------:|-------|
| Session ID | 17    | unchanged |
| Created    | 20    | unchanged |
| Tokens     | 10    | widened from 8 to fit `3,069,334` |
| Model      | 25    | narrowed; `…` on overflow — distinguishable at 25 chars for all known model families |
| Project    | 30    | claudecode only; unchanged |
| Name       | 28    | sized to fit "Extraction Script Timestamps"; `…` on overflow |

Name and Project column order swapped in claudecode so Name appears before
Project (more useful at a glance; Project is trailing and unpadded).

Separator lines: 108 chars (goose, jan, lmstudio); 130 chars (claudecode,
which has the extra Project column).

---

## 2026-05-26  Standardise `--list` column headers and ID width to 17 chars

All four extractors now show `Session ID` as the first column header and
display at most 17 characters of the ID. This fits goose (`20260526_1`,
10 chars) and lmstudio (13-char epoch) in full, and truncates claudecode/jan
UUIDs to their first 17 characters — enough to be unique in any personal
collection, and consistent with the substring-match behaviour both scripts
already support. Separator line lengths updated accordingly.

---

## 2026-05-26  Add `--show-thinking` to `goose_extract.py`; add thinking support to `lmstudio_extract.py`

**`goose_extract.py`** — thinking blocks were always rendered; now opt-in with
`--show-thinking` for consistency with the other extractors. `show_thinking=False`
propagates through `render_blocks()`, `render_content()`, `extract()`,
`extract_from_db()`, `extract_from_json()`, and `export_all()`.

**`lmstudio_extract.py`** — thinking support added. LM Studio stores Qwen3/thinking
content as a `contentBlock` step with `style.type == "thinking"` and a
`style.title` (e.g. "Thought for 1.14 seconds"). `extract_steps_text()` now
checks this field: thinking steps are skipped by default and wrapped in
`<details><summary>💭 {title}</summary>` when `--show-thinking` is active.
Stats gathering (genInfo) is correctly skipped for thinking steps since they
carry no `genInfo`.

---

## 2026-05-26  Standardise help text wording across all four extractors

Six inconsistencies fixed:

- **`--list`/`--all`/`-n`**: "threads" (jan) and "conversations" (lmstudio) → "sessions" everywhere; tool-specific terminology is already clear from the positional argument help
- **Description**: "transcript" → "transcripts" in `claudecode_extract.py` and `lmstudio_extract.py`
- **`--list`**: "List all sessions in sessions.db" → "List all sessions" in `goose_extract.py`
- **`--all`**: "Export all sessions from sessions.db" → "Export all sessions" in `goose_extract.py`
- **`--transcript-only`**: "no stats table" → "no stats tables" in `claudecode_extract.py` and `lmstudio_extract.py`
- **`--collapse-results`**: "tool result blocks" → "TOOL RESULT blocks" in `jan_extract.py` and `lmstudio_extract.py`
- **`--show-thinking`**: "Include extended thinking blocks" / "Include reasoning blocks in transcript" → "Include thinking blocks in transcript" in `claudecode_extract.py` and `jan_extract.py`

---

## 2026-05-26  Add `--all` to `claudecode_extract.py` and `lmstudio_extract.py`

`--all --out-dir DIR` batch-exports all sessions/conversations to markdown files,
consistent with `goose_extract.py` and `jan_extract.py` which already had this.
`-n` applies to `--all` from the start, so `--all -n 10` is safe by default.

Changed in each script:
- `export_all()` added, following the same structure as the other two extractors
- `--all` added to the mutually exclusive source group in argparse
- `--out-dir DIR` added
- `-n` help text updated to "Limit --list or --all to N most recent …"
- `--all` and `--all -n 10` examples added to the module docstring
- Default output directories: `./claude_transcripts/` and `./lmstudio_transcripts/`

---

## 2026-05-26  Add `-n` to `--all` in `goose_extract.py` and `jan_extract.py`

`--all -n N` now exports only the N most recent sessions/threads instead of
everything, making it safe to use without accidentally filling disk with
hundreds of exports.

`-n` already applied to `--list`; it now applies to `--all` as well.
`--all` without `-n` is unchanged.

Changed in each script:
- `export_all()` gains `n=None`; slices the session/thread list to the most
  recent N before iterating (goose: `ids[-n:]` since list is ASC;
  jan: `dirs[:n]` since `list_thread_dirs()` is newest-first)
- Done message says "N most recent" when n is set
- `-n` help text updated from "Limit --list" to "Limit --list or --all"
- `--all -n 10 --out-dir` example added to each module docstring

---

## 2026-05-26  Add `-n` to `--list` in `claudecode_extract.py`, `jan_extract.py`, `lmstudio_extract.py`

`--list -n N` now limits output to the N most recent sessions/threads/conversations,
consistent with `goose_extract.py` which already had this option.

Changed in each script:
- `list_*()` function gains an `n=None` parameter; slices the sorted file list
  with `[:n]` before iterating
- `-n N` argument added to argparse
- `--list -n 5` example added to the module docstring Usage block

---

## 2026-05-25  Fix `--list` timestamps in `claudecode_extract.py` to local time

**`claudecode_extract.py`**

`fmt_ts()` now converts UTC timestamps to the system's local timezone before
rendering. Previously, `datetime.fromisoformat()` returned a timezone-aware
UTC datetime, but `.strftime()` was called on it without converting — so the
UTC time was formatted as-is, displaying GMT times instead of PDT.

Added `.astimezone()` between `fromisoformat()` and `strftime()`:

```python
# Before (UTC displayed as local)
datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime(...)

# After (converted to local first)
datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime(...)
```

Now all four extractors (`claudecode`, `goose`, `jan`, `lmstudio`) display
`--list` timestamps in the same local timezone.

---

## 2026-05-17  Add 3-line preview to collapsed tool results

**`lmstudio_extract.py`** and **`claudecode_extract.py`**

Collapsed tool result blocks (via `--collapse-results`) now show a 3-line
preview above the `<details>` element, skipping blank lines so the preview
is always meaningful. This matches the existing behaviour in `goose_extract.py`
and lets you see what's inside without having to click to expand.

Format is now consistent across all three extractors:

    **[TOOL RESULT ← name]**  (N lines)

    ```
    first meaningful line
    second line
    third line
    …
    ```

    <details><summary>Show all N lines…</summary>
    ...
    </details>

---

## 2026-05-16  README overhaul

- Jan added to supported tools table and given its own full usage section
- Claude Code section rewritten to use `--list` and UUID substring matching
  instead of explicit file paths
- LM Studio section updated with `--list` and `--collapse-results`
- All `--collapse-results 40` examples corrected to `--collapse-results=40`
- Output format section updated to reflect all four tools accurately
- MacDown removed from renderer list
- "Sharing sessions across machines" section removed (not relevant for
  typical users)
- GitHub URL corrected to `https://github.com/mbw-public/llm-session-archive.git`

---

## 2026-05-16  lmstudio_extract.py: add --collapse-results

**`lmstudio_extract.py`**

`--collapse-results[=N]` added (default N=20): wraps `toolCallResult` blocks
longer than N lines in a `<details>` element, consistent with the other
extractors. Tool result rendering refactored into `render_tool_result()` so
collapse logic is applied uniformly across list, dict, and raw string results.

---

## 2026-05-16  Standardize stats heading and --list column names

**`jan_extract.py`**
- Stats heading renamed from `## Token Usage Per Message` to
  `## Token Usage Per Turn` (consistent with `claudecode_extract.py`;
  "per turn" is the standard LLM community term)
- `--list` column heading `Title` renamed to `Name` (consistent with
  all other extractors)

**`claudecode_extract.py`**
- `--list` column headings `Started` → `Created` and `Title` → `Name`
  (consistent with all other extractors)

---

## 2026-05-16  claudecode_extract.py: add --list, rewrite CLI

**`claudecode_extract.py`**

- `--list` added: shows all sessions across all projects under
  `~/.claude/projects/`, newest-first, with session UUID, started time,
  output token total, model, project (last 2 cwd path components), and
  the AI-generated session title from the `ai-title` record
- `--projects-dir DIR` / `CLAUDE_PROJECTS` env var to override default
- `session` positional now accepts a unique substring of the UUID in
  addition to an explicit path
- `--out FILE` now uses `Path.write_text()` instead of replacing
  `sys.stdout` (was fragile)
- Prints full `--help` when run with no arguments
- Fixed missing `import re` (caused `NameError` in `remove_empty_fences`)
- Thinking blocks now rendered in `<details>` with 💭 summary, consistent
  with `goose_extract.py` and `jan_extract.py`
- Session header uses `ai-title` as the `#` heading when available
- `file` positional renamed to `session` for clarity
- Stats section rewritten as a markdown table (`## Token Usage Per Turn`)
  with bold totals underneath, consistent with `goose_extract.py`,
  `jan_extract.py`, and `lmstudio_extract.py`
- `Started` column heading renamed to `Created` in `--list` output
- `Title` column heading renamed to `Name` in `--list` output

---

## 2026-05-16  goose_extract.py: show model in --list

**`goose_extract.py`**

`--list` now shows the model name (from `model_config_json`) instead of
the provider name, in a 45-character column. Provider was redundant with
the session header; model is more useful for comparing sessions.

---

## 2026-05-16  lmstudio_extract.py: add --list and tidy CLI

**`lmstudio_extract.py`**

- `--list` added: shows all conversations in `~/.lmstudio/conversations/`
  with filename stem, created date, token count, model, and name;
  sorted newest-first (consistent with `goose_extract.py --list`)
- Filename stem in `--list` now correctly shows just the epoch number
  (was showing `<epoch>.conversation` due to double extension on the file)
- `--conversations-dir DIR` / `LMSTUDIO_CONVERSATIONS` env var to override
  the default conversations directory
- `file` positional now also accepts a unique substring of the filename stem
  (e.g. `17769` resolves to `1776881829866.conversation.json`), in addition
  to explicit paths
- `--out FILE` now uses `Path.write_text()` instead of replacing `sys.stdout`
- Prints full `--help` when run with no arguments (was missing)
- File header now includes the filename for easier reference

---

## 2026-05-16  Add jan_extract.py

**`jan_extract.py`** — new extractor for the Jan app (jan.ai).

Jan stores threads under `~/Library/Application Support/Jan/data/threads/`,
one UUID-named directory per thread, each containing `thread.json` (metadata)
and `messages.jsonl` (one message object per line).

Features consistent with the other extractors:
- `--list` to show all threads with title, model, timestamp, and token total;
  sorted newest-first (consistent with other extractors)
- `--show-thinking` to include `reasoning` blocks (Jan's thinking output)
- `--stats-only` / `--transcript-only`
- `--collapse-results` (no-op for now; Jan doesn't produce tool result blocks
  in the same structure, but the flag is wired up for future use)
- `--out FILE` to write to a file
- `--all --out-dir DIR` to batch-export all threads
- `--threads-dir DIR` / `JAN_THREADS` env var to override the default path
- Substring matching for thread ID (e.g. `63e1` or `f61c` resolves to the
  full UUID — any unique fragment works, not just a leading prefix)
- Ghost empty assistant placeholder messages are silently skipped
- `close_unclosed_fences()` and `remove_empty_fences()` applied to text blocks
- Token speed (tok/s) shown in transcript headers and stats table
- Token total in `--list` summed from `metadata.usage.totalTokens` across
  assistant messages in `messages.jsonl` (not available in `thread.json`)

---

## 2026-05-15  Fix unclosed and empty fences in text blocks

**`goose_extract.py`** and **`claudecode_extract.py`**

`close_unclosed_fences()` is now applied to plain text blocks in
`render_blocks()` / `flatten_content()`, not just thinking and collapsed
tool-result blocks. An unclosed fence left by the model in a text response
(e.g. an unterminated ` ```scss ` block) was swallowing all subsequent turns
in the markdown renderer.

`remove_empty_fences()` added and applied after `close_unclosed_fences()`
on text blocks. Removes empty fenced code blocks (opener immediately followed
by closer with no content between them, e.g. ` ```scss\n``` `). Marked 2
misrenders these — treating the closer as content and swallowing subsequent
document structure. Both backtick and tilde variants are handled. Empty fences
carry no content so removing them loses nothing.

`close_unclosed_fences()` added to `claudecode_extract.py` (previously only
lived in `goose_extract.py`).

---

## 2026-05-11  Consistency pass across all scripts

**All extractors** (`goose_extract.py`, `claudecode_extract.py`,
`lmstudio_extract.py`) and utilities (`split_session.py`,
`lmstudio_strip.py`) now behave consistently:

- Print full `--help` when run with no arguments (previously some scripts
  printed a bare usage error or a hand-rolled usage line)
- Use `ap` for the argparse instance
- Uniform description format: `"Extract <Tool> session transcript and stats"`
- `--stats-only` and `--transcript-only` have help text in all scripts

**`claudecode_extract.py`**
- Added `--out FILE` to write directly to a file instead of stdout
- Added `--collapse-results [N]` (default N=20) to wrap long tool result
  blocks in `<details>` — same behaviour as `goose_extract.py`

**`lmstudio_extract.py`**
- Added `--out FILE` to write directly to a file instead of stdout

**`lmstudio_strip.py`**
- Output now defaults to stdout; stats (before/after/saved) go to stderr
  so the script composes correctly with shell redirection and pipes
- Explicit output file still works: `lmstudio_strip.py in.json out.json`
- Replaced `__import__("os")` hack with a proper top-level `import os`;
  moved `import io` to top-level imports
- Converted hand-rolled `sys.argv` parsing to `argparse` with `-h` support

**`split_session.py`**
- Fixed `file` argument missing `nargs="?"`, which caused argparse to error
  before the no-args help check could fire
- Removed references to `session-monroe` example filenames

**`README.md`** updated to reflect all new options and stdout behaviour.

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

**Bugfix:** `--all --db FILE` was listing sessions correctly but then failing
to extract each one with "Session not found", because `export_all` was not
passing `db_path` through to `extract_from_db`. Fixed.

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
