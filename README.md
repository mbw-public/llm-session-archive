# llm-session-archive

A toolkit for extracting AI chat session transcripts from local storage into
readable, portable markdown files.

AI coding assistants store your conversation history locally — in SQLite
databases, JSON files, or JSONL logs — but these formats are opaque and
tool-specific. This toolkit converts them into clean markdown you can read,
search, and archive, even after the tool has been updated, the remote model
has been retired, or the service has gone offline.

## Supported tools

| Tool | Source format | Script |
|------|--------------|--------|
| [Goose](https://github.com/block/goose) | SQLite (`sessions.db`) or JSON export | `goose_extract.py` |
| [Claude Code](https://claude.ai/code) | JSONL session log (`.jsonl`) | `claudecode_extract.py` |
| [LM Studio](https://lmstudio.ai) | JSON conversation file (`.json`) | `lmstudio_extract.py` |
| [Jan](https://jan.ai) | JSONL thread log (`messages.jsonl`) | `jan_extract.py` |

`split_session.py` is a utility for splitting large session transcripts into
smaller chunks — useful when a markdown previewer struggles with multi-megabyte
files.

## Why this exists

Local AI tools accumulate valuable context: debugging sessions, design
discussions, long refactoring runs. That context lives in proprietary local
formats that are:

- **Opaque** — not human-readable without the original tool
- **Fragile** — tied to a specific schema version or tool release
- **Transient** — lost if the tool is updated, the model retired, or the
  service shut down

This toolkit gives you plain markdown that you own — permanently readable,
searchable with `grep` or `rg`, and openable in any text editor or markdown
previewer.

## Requirements

- Python 3.8+
- No external dependencies — only the standard library

## Installation

```bash
git clone https://github.com/mbw-public/llm-session-archive.git
cd llm-session-archive
chmod +x *.py
```

## Usage

### Goose

```bash
# List sessions
./goose_extract.py --list
./goose_extract.py --list -n 10

# Extract a session by ID
./goose_extract.py 20260503_1 > session.md

# Include thinking blocks
./goose_extract.py 20260503_1 --show-thinking > session.md

# Extract with long tool results collapsed into <details> blocks
./goose_extract.py 20260503_1 --collapse-results > session.md
./goose_extract.py 20260503_1 --collapse-results=40 > session.md

# Export most recent N sessions to a directory
./goose_extract.py --all -n 10 --out-dir ./transcripts/
./goose_extract.py --all --out-dir ./transcripts/

# Work with a database copied from another machine
./goose_extract.py --db /path/to/sessions.db --list
./goose_extract.py --db /path/to/sessions.db 20260503_1 > session.md

# Extract from a Goose JSON export file
./goose_extract.py --json session.json > session.md

# Stats only (token usage, tool call breakdown)
./goose_extract.py 20260503_1 --stats-only
```

The default database location is `~/.local/share/goose/sessions/sessions.db`.
Override with `--db FILE` or the `GOOSE_DB` environment variable.

### Claude Code

```bash
# List all sessions across all projects
./claudecode_extract.py --list
./claudecode_extract.py --list -n 10

# Extract a session by UUID (or unique substring)
./claudecode_extract.py 70e31d > session.md

# Include thinking blocks
./claudecode_extract.py 70e31d --show-thinking > session.md

# Collapse tool results longer than N lines (default N=20)
./claudecode_extract.py 70e31d --collapse-results > session.md
./claudecode_extract.py 70e31d --collapse-results=40 > session.md

# Stats only — token counts, cache hits, stop reasons per turn
./claudecode_extract.py 70e31d --stats-only

# Transcript only, no stats table
./claudecode_extract.py 70e31d --transcript-only > session.md

# Write directly to a file
./claudecode_extract.py 70e31d --out session.md

# Export most recent N sessions to a directory
./claudecode_extract.py --all -n 10 --out-dir ./claude_transcripts/
./claudecode_extract.py --all --out-dir ./claude_transcripts/
```

The stats section shows per-turn input/output tokens, prompt cache reads and
writes, and stop reasons — useful for understanding where tokens are being spent
across a long session.

Claude Code session logs are stored in `~/.claude/projects/<project-path>/`
as `.jsonl` files, one per session. Override with `--projects-dir DIR` or the
`CLAUDE_PROJECTS` environment variable.

### LM Studio

```bash
# List all conversations
./lmstudio_extract.py --list
./lmstudio_extract.py --list -n 10

# Extract by filename stem (or unique substring)
./lmstudio_extract.py 1777912439851 > session.md

# Include thinking blocks (Qwen3 and other reasoning models)
./lmstudio_extract.py 1777912439851 --show-thinking > session.md

# Collapse tool results longer than N lines (default N=20)
./lmstudio_extract.py 1777912439851 --collapse-results > session.md
./lmstudio_extract.py 1777912439851 --collapse-results=40 > session.md

# Stats only — tok/s, time-to-first-token, context length per turn
./lmstudio_extract.py 1777912439851 --stats-only

# Transcript only
./lmstudio_extract.py 1777912439851 --transcript-only > session.md

# Export most recent N conversations to a directory
./lmstudio_extract.py --all -n 10 --out-dir ./lmstudio_transcripts/
./lmstudio_extract.py --all --out-dir ./lmstudio_transcripts/
```

The stats section shows tokens/second, time-to-first-token, total generation
time, prompt and generated token counts, and context length — useful for
benchmarking local model performance.

Conversations are stored in `~/.lmstudio/conversations/`. Override with
`--conversations-dir DIR` or the `LMSTUDIO_CONVERSATIONS` environment variable.

### Jan

```bash
# List all sessions
./jan_extract.py --list
./jan_extract.py --list -n 10

# Extract a session by UUID (or unique substring)
./jan_extract.py 63e1 > session.md

# Include thinking blocks
./jan_extract.py 63e1 --show-thinking > session.md

# Stats only
./jan_extract.py 63e1 --stats-only

# Transcript only
./jan_extract.py 63e1 --transcript-only > session.md

# Write directly to a file
./jan_extract.py 63e1 --out session.md

# Export most recent N sessions to a directory
./jan_extract.py --all -n 10 --out-dir ./jan_transcripts/
./jan_extract.py --all --out-dir ./jan_transcripts/
```

Jan sessions are stored in `~/Library/Application Support/Jan/data/threads/`
(macOS) as UUID-named directories, each containing `thread.json` and
`messages.jsonl`. Override with `--threads-dir DIR` or the `JAN_THREADS`
environment variable.

### Splitting large files

```bash
# Split into 75-turn chunks (default)
./split_session.py session.md

# Narrower chunks for debugging rendering issues
./split_session.py session.md --turns 10
```

Output files are named by actual turn numbers, e.g.
`session-0001-0075.md`, `session-0076-0150.md`, making them self-documenting.

## Output format

Each transcript includes:

- **Session header** — tool, model, timestamps, working directory, token totals
- **Full transcript** — user and assistant turns numbered sequentially with
  role headers
- **Thinking blocks** — collapsible `<details>` sections for extended reasoning
  (Goose, Claude Code, and Jan with `--show-thinking`)
- **Tool calls and results** — formatted with fenced code blocks; long results
  optionally collapsed with `--collapse-results` (Goose, Claude Code, LM Studio)
- **Stats section** — token usage per turn (Claude Code, Jan) or performance
  metrics such as tokens/second and time-to-first-token (LM Studio), or tool
  call breakdown (Goose)

Transcripts render correctly in [Marked 2](https://marked2app.com),
[Obsidian](https://obsidian.md), and any CommonMark-compatible renderer.

## License

MIT
