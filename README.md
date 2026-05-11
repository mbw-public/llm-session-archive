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

This toolkit gives you plain markdown that you own  — permanently, can search with `grep` or `rg`, and open in any text editor or markdown previewer.

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
# List sessions in the default database
./goose_extract.py --list

# Extract a session to a file
./goose_extract.py 20260503_1 --out session.md

# Extract with long tool results collapsed into <details> blocks
./goose_extract.py 20260503_1 --collapse-results 20 --out session.md

# Export all sessions to a directory
./goose_extract.py --all --out-dir ./transcripts/

# Work with a database copied from another machine
./goose_extract.py --db /path/to/sessions.db --list
./goose_extract.py --db /path/to/sessions.db 20260503_1 --out session.md

# Extract from a Goose JSON export file
./goose_extract.py --json session.json --out session.md

# Stats only (token usage, tool call breakdown)
./goose_extract.py 20260503_1 --stats-only
```

The default database location is `~/.local/share/goose/sessions/sessions.db`.
Override with `--db FILE` or the `GOOSE_DB` environment variable.

### Claude Code

```bash
# Full transcript + token stats (stdout)
./claudecode_extract.py Claude.jsonl > session.md

# Include extended thinking blocks
./claudecode_extract.py Claude.jsonl --show-thinking > session.md

# Stats only — token counts, cache hits, stop reasons per turn
./claudecode_extract.py Claude.jsonl --stats-only

# Transcript only, no stats table
./claudecode_extract.py Claude.jsonl --transcript-only > session.md
```

The stats section shows per-turn input/output tokens, prompt cache reads and
writes, and stop reasons — useful for understanding where tokens are being spent
across a long session.

Claude Code session logs are stored in `~/.claude/projects/<project-path>/`
as `.jsonl` files, one per session.

### LM Studio

LM Studio conversation files can be large due to a `predictionConfig` block
repeated inside every `genInfo` step. Strip these first to reduce file size
before extracting:

```bash
# Strip redundant predictionConfig blocks (saves 50–80% on large files)
./lmstudio_strip.py Qwen.json Qwen_stripped.json

# Extract transcript + performance stats
./lmstudio_extract.py Qwen_stripped.json > session.md

# Stats only — tok/s, time-to-first-token, context length per turn
./lmstudio_extract.py Qwen_stripped.json --stats-only

# Transcript only
./lmstudio_extract.py Qwen_stripped.json --transcript-only > session.md
```

The stats section shows tokens/second, time-to-first-token, total generation
time, prompt and generated token counts, and context length — useful for
benchmarking local model performance.

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

- **Session header** — tool, model, provider, timestamps, working directory,
  token totals
- **Full transcript** — user and assistant turns numbered sequentially with
  role headers
- **Thinking blocks** — collapsible `<details>` sections for extended reasoning
  (Goose and Claude Code with `--show-thinking`)
- **Tool calls and results** — formatted with fenced code blocks; long results
  optionally collapsed with `--collapse-results N` (Goose)
- **Stats section** — token usage (Claude Code) or performance metrics such as
  tokens/second and time-to-first-token (LM Studio)

Transcripts render correctly in [Marked 2](https://marked2app.com),
[MacDown](https://macdown.uranusjr.com), [Obsidian](https://obsidian.md), and
any CommonMark-compatible renderer.

## Sharing sessions across machines

To work with sessions from another machine, copy the database file and point
`--db` at it:

```bash
# Compress for transfer (SQLite compresses well — typically 10:1)
zip sessions.db.zip sessions.db

# On the receiving machine
./goose_extract.py --db ./sessions.db --list
./goose_extract.py --db ./sessions.db 20260503_1 --out session.md
./goose_extract.py --db ./sessions.db --all --out-dir ./transcripts/
```

## License

MIT
