#!/usr/bin/env python3
"""
pi_extract.py — Extract readable transcripts + stats from Pi agent sessions

Usage:
    python3 pi_extract.py --list
    python3 pi_extract.py --list -n 5
    python3 pi_extract.py <session_id>
    python3 pi_extract.py <session_id> --stats-only
    python3 pi_extract.py <session_id> --transcript-only
    python3 pi_extract.py <session_id> --no-thinking
    python3 pi_extract.py <session_id> --collapse-results
    python3 pi_extract.py <session_id> --collapse-results=40
    python3 pi_extract.py <session_id> --out session.md
    python3 pi_extract.py --all --out-dir ./pi_transcripts/
    python3 pi_extract.py --all -n 10 --out-dir ./pi_transcripts/

<session_id> is a unique substring of the session UUID, timestamp, or full
filename matched across all sessions — run --list to see them.  An explicit
file path is also accepted.

Pi stores sessions under:
  ~/.pi/agent/sessions/<encoded-project-path>/<timestamp>_<uuid>.jsonl
Override via --sessions-dir or the PI_SESSIONS env var.

Session file format (one JSON object per line):
  session             — header: id, version, cwd, timestamp
  model_change        — provider, modelId
  thinking_level_change — thinkingLevel
  message             — role: "user" | "assistant" | "toolResult"

Assistant content block types: text, thinking, toolCall
toolResult records are first-class messages (not embedded in user turns).
"""

import re
import json
import sys
import os
import argparse
from datetime import datetime
from pathlib import Path


# ── Data location ─────────────────────────────────────────────────────────────


def find_sessions_dir():
    candidates = [
        Path.home() / ".pi/agent/sessions",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not find Pi sessions directory. Tried:\n"
        + "\n".join(f"  {p}" for p in candidates)
        + "\nSet PI_SESSIONS env var to override."
    )


def get_sessions_dir(override=None):
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"Sessions directory not found: {p}")
        return p
    env = os.environ.get("PI_SESSIONS")
    if env:
        p = Path(env)
        if not p.exists():
            raise FileNotFoundError(f"Sessions directory not found: {p}")
        return p
    return find_sessions_dir()


def all_session_files(sessions_dir):
    """Return all .jsonl session files across all project subdirectories, newest-first.

    Filenames start with an ISO 8601 timestamp, so lexicographic sort on the
    filename gives chronological order — no stat() call needed.
    """
    files = []
    for project_dir in sessions_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for f in project_dir.glob("*.jsonl"):
            files.append(f)
    return sorted(files, key=lambda f: f.name, reverse=True)


def decode_project_dir(encoded):
    """
    Decode Pi's encoded project-path directory name to a readable path.
    Pi encodes /Users/monroe/Projects/llm as --Users-monroe-Projects-llm--
    (leading and trailing slashes become '--'; internal slashes become '-').
    This decoding is approximate: hyphens in real directory names are ambiguous.
    """
    s = encoded
    if s.startswith("--"):
        s = "/" + s[2:]
    if s.endswith("--"):
        s = s[:-2]
    return s.replace("-", "/")


def short_project(encoded_dir_name):
    """Return last two readable path components of a Pi-encoded project dir."""
    decoded = decode_project_dir(encoded_dir_name)
    parts = [p for p in decoded.split("/") if p]
    return "/".join(parts[-2:]) if len(parts) >= 2 else decoded or encoded_dir_name


def parse_session_filename(filename):
    """
    Parse '<ISO-timestamp>_<uuid>.jsonl' into (timestamp_str, uuid_str).
    Returns (None, stem) if the filename doesn't contain an underscore separator.
    """
    stem = Path(filename).stem  # strip .jsonl
    idx = stem.find("_")
    if idx == -1:
        return None, stem
    return stem[:idx], stem[idx + 1 :]


def resolve_session(arg, sessions_dir_override=None):
    """
    Resolve <arg> to a session .jsonl path.
    Accepts:
      - an explicit path that exists on disk
      - a unique substring of any session filename matched across all sessions
    """
    p = Path(arg)
    if p.exists():
        return p

    try:
        sdir = get_sessions_dir(sessions_dir_override)
    except FileNotFoundError:
        print(f"Error: file not found: {arg}", file=sys.stderr)
        sys.exit(1)

    matches = [f for f in all_session_files(sdir) if arg in f.name]
    if not matches:
        print(f"Error: no session matching '{arg}'", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(
            f"Error: '{arg}' matches multiple sessions:\n"
            + "\n".join(f"  {f}" for f in matches),
            file=sys.stderr,
        )
        sys.exit(1)
    return matches[0]


# ── Formatting helpers ────────────────────────────────────────────────────────


def fmt_ts(iso):
    """Convert ISO 8601 timestamp string to readable local datetime."""
    if not iso:
        return "?"
    try:
        return (
            datetime.fromisoformat(iso.replace("Z", "+00:00"))
            .astimezone()
            .strftime("%Y-%m-%d %H:%M:%S")
        )
    except Exception:
        return str(iso)


def fence(content, lang=""):
    """Use tilde fences if content contains backticks, otherwise backtick fences."""
    content = content.rstrip()
    if "```" in content:
        return f"~~~{lang}\n{content}\n~~~"
    return f"```{lang}\n{content}\n```"


# ── Content rendering ─────────────────────────────────────────────────────────


def close_unclosed_fences(content):
    """
    Detect and close any unclosed fenced code blocks in content.
    Tracks backtick (```) and tilde (~~~) fences independently — a single
    fence_char variable fails to close both if mixed fence types appear.
    """
    backtick_open = False
    tilde_open = False
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):
            backtick_open = not backtick_open
        elif stripped.startswith("~~~"):
            tilde_open = not tilde_open
    closers = []
    if backtick_open:
        closers.append("```")
    if tilde_open:
        closers.append("~~~")
    if closers:
        return content.rstrip() + "\n" + "\n".join(closers)
    return content


def remove_empty_fences(text):
    """
    Remove empty fenced code blocks (opener immediately followed by closer).
    Marked 2 misrenders empty fences, swallowing subsequent document structure.
    Empty fences carry no content so removing them loses nothing.
    """
    text = re.sub(r"^```[^\n]*\n```[ \t]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^~~~[^\n]*\n~~~[ \t]*$", "", text, flags=re.MULTILINE)
    return text.strip()


def render_assistant_content(blocks, show_thinking=False, collapse_results=None):
    """
    Render an assistant message's content block array to markdown.

    Pi assistant content block types:
      type="text"      — response text in "text" field
      type="thinking"  — thinking block in "thinking" field
      type="toolCall"  — tool invocation; has "id", "name", "arguments" (dict)
    """
    parts = []
    for block in blocks:
        btype = block.get("type", "")

        if btype == "thinking":
            if show_thinking:
                text = block.get("thinking", "").strip()
                if text:
                    parts.append(
                        f"<details><summary>\U0001f4ad Thinking</summary>\n\n"
                        f"{fence(text)}\n\n*\u2014 end thinking \u2014*\n\n</details>"
                    )

        elif btype == "text":
            text = block.get("text", "").strip()
            if text:
                text = close_unclosed_fences(text)
                text = remove_empty_fences(text)
                if text:
                    parts.append(text)

        elif btype == "toolCall":
            name = block.get("name", "?")
            args = block.get("arguments", {})
            args_s = json.dumps(args, indent=2) if isinstance(args, dict) else str(args)
            parts.append(f"**[TOOL CALL \u2192 {name}]**\n{fence(args_s, 'json')}")

        else:
            # Unknown block type — render as fenced JSON for inspection
            parts.append(
                f"**[{btype.upper()} BLOCK]**\n{fence(json.dumps(block, indent=2), 'json')}"
            )

    return "\n\n".join(p for p in parts if p)


def render_tool_results(result_records, collapse_results=None):
    """
    Render a batch of consecutive toolResult records to markdown.

    Pi surfaces each tool result as its own top-level message record
    (role="toolResult") with fields: toolCallId, toolName, content, isError.
    Multiple toolResult records may appear back-to-back when the preceding
    assistant turn issued multiple toolCall blocks.
    """
    parts = []
    for r in result_records:
        msg = r.get("message", {})
        name = msg.get("toolName", "?")
        is_error = msg.get("isError", False)
        prefix = "TOOL ERROR" if is_error else "TOOL RESULT"
        content_blocks = msg.get("content", [])
        raw = "\n".join(
            item.get("text", "")
            for item in content_blocks
            if item.get("type") == "text"
        )
        raw = raw.replace("\n\n", "\n")

        if not raw.strip():
            parts.append(f"**[{prefix} \u2190 {name}]**  *(empty)*")
            continue

        # Infer a language hint for syntax highlighting: bash if shebang present.
        first_line = raw.lstrip().splitlines()[0] if raw.strip() else ""
        lang = ""
        if first_line.startswith("#!"):
            if "bash" in first_line or "/sh" in first_line:
                lang = "bash"
            elif "python" in first_line:
                lang = "python"

        n_lines = raw.count("\n") + 1
        if collapse_results is not None and n_lines > collapse_results:
            preview_lines = [ln for ln in raw.splitlines() if ln.strip()][:3]
            preview = "\n".join(preview_lines)
            if n_lines > 3:
                preview += "\n\u2026"
            safe_fenced = fence(close_unclosed_fences(raw), lang)
            parts.append(
                f"**[{prefix} \u2190 {name}]**  *({n_lines} lines)*\n\n"
                f"{fence(preview, lang)}\n\n"
                f"<details><summary>Show all {n_lines} lines\u2026</summary>"
                f"\n\n{safe_fenced}\n\n</details>"
            )
        else:
            parts.append(f"**[{prefix} \u2190 {name}]**\n{fence(raw, lang)}")

    return "\n\n".join(p for p in parts if p)


# ── Session loader ─────────────────────────────────────────────────────────────


def load_session(path):
    """Load all records from a Pi session .jsonl file into a list."""
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except Exception:
            pass
    return records


def scan_session(path):
    """
    Quick metadata scan for --list output.
    Reads the whole file but parses only what's needed for the listing.
    """
    path = Path(path)
    ts_str, uuid_str = parse_session_filename(path.name)

    cwd = None
    model = None
    total_output = 0
    session_ts = (
        None  # from session record (proper ISO); fall back to filename fragment
    )

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        rtype = r.get("type")
        if rtype == "session":
            cwd = r.get("cwd")
            session_ts = r.get("timestamp") or ts_str
        elif rtype == "model_change" and not model:
            model = r.get("modelId")
        elif rtype == "message":
            msg = r.get("message", {})
            if msg.get("role") == "assistant":
                total_output += msg.get("usage", {}).get("output", 0)

    return {
        "path": path,
        "timestamp": session_ts or ts_str,
        "session_id": uuid_str or path.stem,
        "cwd": cwd,
        "model": model or "-",
        "output_tokens": total_output,
    }


# ── Core extract ──────────────────────────────────────────────────────────────


def extract(
    path,
    show_transcript=True,
    show_thinking=False,
    show_stats=True,
    collapse_results=None,
    out_file=None,
):
    path = Path(path)
    records = load_session(path)

    # ── Session-level metadata (first pass) ────────────────────────────────────
    ts_str, uuid_str = parse_session_filename(path.name)
    session_id = uuid_str or path.stem
    started = None  # prefer session record timestamp; fall back to filename fragment
    cwd = None
    version = None
    model = None
    provider = None
    thinking_level = None

    for r in records:
        rtype = r.get("type")
        if rtype == "session":
            cwd = r.get("cwd")
            version = r.get("version")
            started = r.get("timestamp") or ts_str
        elif rtype == "model_change" and not model:
            model = r.get("modelId")
            provider = r.get("provider")
        elif rtype == "thinking_level_change" and not thinking_level:
            thinking_level = r.get("thinkingLevel")

    # ── Header (always shown) ──────────────────────────────────────────────────
    if cwd:
        parts = [p for p in Path(cwd).parts if p]
        title = "/".join(parts[-2:]) if len(parts) >= 2 else cwd
    else:
        title = (
            short_project(path.parent.name)
            if path.parent.name != "uploads"
            else session_id
        )

    lines = [
        f"# {title}",
        f"Session:   {session_id}",
        f"Started:   {fmt_ts(started)}",
    ]
    if model:
        lines.append(f"Model:     {model}")
    if provider:
        lines.append(f"Provider:  {provider}")
    if thinking_level:
        lines.append(f"Thinking:  {thinking_level}")
    if version is not None:
        lines.append(f"Version:   {version}")
    if cwd:
        lines.append(f"CWD:       {cwd}")
    if collapse_results is not None:
        lines.append(f"Collapse threshold: tool results > {collapse_results} lines")
    lines.append("")

    # ── Transcript (second pass over message records) ──────────────────────────
    msg_num = 0
    usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    per_turn_usage = []

    message_records = [r for r in records if r.get("type") == "message"]

    i = 0
    while i < len(message_records):
        r = message_records[i]
        msg = r.get("message", {})
        role = msg.get("role", "?")

        if role == "user":
            msg_num += 1
            if show_transcript:
                content_blocks = msg.get("content", [])
                text = "\n\n".join(
                    b.get("text", "").strip()
                    for b in content_blocks
                    if b.get("type") == "text" and b.get("text", "").strip()
                )
                lines += ["\n---\n", f"**[{msg_num}] USER**\n"]
                if text:
                    lines.append(text)
                lines.append("")
            i += 1

        elif role == "assistant":
            usage = msg.get("usage", {})
            inp = usage.get("input", 0)
            out = usage.get("output", 0)
            cr = usage.get("cacheRead", 0)
            cw = usage.get("cacheWrite", 0)
            usage_totals["input"] += inp
            usage_totals["output"] += out
            usage_totals["cache_read"] += cr
            usage_totals["cache_write"] += cw

            msg_num += 1
            per_turn_usage.append(
                {
                    "msg_num": msg_num,
                    "timestamp": r.get("timestamp"),
                    "input": inp,
                    "output": out,
                    "cache_read": cr,
                    "cache_write": cw,
                    "stop_reason": msg.get("stopReason", ""),
                }
            )

            if show_transcript:
                rendered = render_assistant_content(
                    msg.get("content", []),
                    show_thinking=show_thinking,
                    collapse_results=collapse_results,
                )
                hdr = f"**[{msg_num}] ASSISTANT**"
                if out:
                    hdr += f"  *(tokens: {out:,})*"
                lines += ["\n---\n", hdr + "\n"]
                if rendered:
                    lines.append(rendered)
                lines.append("")
            i += 1

        elif role == "toolResult":
            # Collect all consecutive toolResult records into one section.
            # When an assistant issues N toolCall blocks, N toolResult records
            # follow immediately — all share the same parent assistant record.
            batch = []
            while (
                i < len(message_records)
                and message_records[i].get("message", {}).get("role") == "toolResult"
            ):
                batch.append(message_records[i])
                i += 1

            msg_num += 1
            if show_transcript:
                rendered = render_tool_results(batch, collapse_results=collapse_results)
                lines += ["\n---\n", f"**[{msg_num}] TOOL RESULTS**\n"]
                if rendered:
                    lines.append(rendered)
                lines.append("")

        else:
            i += 1

    # ── Stats ──────────────────────────────────────────────────────────────────
    if show_stats and per_turn_usage:
        lines += [
            "",
            "## Token Usage Per Turn",
            "",
            "| Turn | Timestamp | Input | Output | CacheR | CacheW | Stop |",
            "|-----:|-----------|------:|-------:|-------:|-------:|------|",
        ]
        for u in per_turn_usage:
            lines.append(
                f"| {u['msg_num']} | {fmt_ts(u['timestamp'])} "
                f"| {u['input']:,} | {u['output']:,} "
                f"| {u['cache_read']:,} | {u['cache_write']:,} "
                f"| {u['stop_reason']} |"
            )
        lines += [
            "",
            f"**Total input:** {usage_totals['input']:,}  ",
            f"**Total output:** {usage_totals['output']:,}  ",
            f"**Total cache reads:** {usage_totals['cache_read']:,}  ",
            f"**Total cache writes:** {usage_totals['cache_write']:,}  ",
            f"**Grand total:** {sum(usage_totals.values()):,}  ",
        ]

    output = "\n".join(lines)
    if out_file:
        Path(out_file).write_text(output, encoding="utf-8")
        print(f"Written to {out_file}")
    else:
        print(output)


# ── List sessions ──────────────────────────────────────────────────────────────


def list_sessions(n=None, sessions_dir_override=None):
    try:
        sessions_dir = get_sessions_dir(sessions_dir_override)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    files = all_session_files(sessions_dir)
    if n:
        files = files[:n]

    if not files:
        print("No sessions found.")
        return

    sessions = [scan_session(f) for f in files]

    def trunc(s, width):
        return s if len(s) <= width else s[: width - 1] + "\u2026"

    print(
        f"{'Session ID':<17}  {'Created':<20}  {'Tokens':>10}  {'Model':<39}  Project"
    )
    print("-" * 110)
    for s in sessions:
        tok_s = f"{s['output_tokens']:,}" if s["output_tokens"] else "-"
        model = trunc(s["model"], 39)
        cwd = s.get("cwd") or ""
        if cwd:
            parts = [p for p in Path(cwd).parts if p]
            project = trunc("/".join(parts[-2:]), 28) if len(parts) >= 2 else cwd
        else:
            project = trunc(short_project(s["path"].parent.name), 28)
        print(
            f"{s['session_id'][:17]:<17}  {fmt_ts(s['timestamp']):<20}  "
            f"{tok_s:>10}  {model:<39}  {project}"
        )


# ── Export all ─────────────────────────────────────────────────────────────────


def export_all(
    out_dir,
    transcript=True,
    show_thinking=False,
    stats=True,
    collapse_results=None,
    sessions_dir_override=None,
    n=None,
):
    try:
        sessions_dir = get_sessions_dir(sessions_dir_override)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    files = all_session_files(sessions_dir)
    if n:
        files = files[:n]

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for f in files:
        dest = out / f"{f.stem}.md"
        print(f"  {f.name} \u2192 {dest}")
        try:
            extract(
                f,
                show_transcript=transcript,
                show_thinking=show_thinking,
                show_stats=stats,
                collapse_results=collapse_results,
                out_file=str(dest),
            )
        except Exception as e:
            print(f"    ERROR: {e}")

    label = f"{len(files)} most recent" if n else str(len(files))
    print(f"\nDone. {label} sessions exported to {out}/")


# ── CLI ───────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract Pi agent session transcripts and stats"
    )

    src = ap.add_mutually_exclusive_group()
    src.add_argument(
        "session_id",
        nargs="?",
        help="Session UUID, timestamp substring, or filename fragment — run --list to see them",
    )
    src.add_argument("--list", action="store_true", help="List all sessions")
    ap.add_argument(
        "-n", type=int, help="Limit --list or --all to N most recent sessions"
    )
    ap.add_argument(
        "--stats-only", action="store_true", help="Stats only, no transcript"
    )
    ap.add_argument(
        "--transcript-only",
        action="store_true",
        help="Transcript only, no stats tables",
    )
    ap.add_argument(
        "--no-thinking",
        dest="show_thinking",
        action="store_false",
        help="Exclude thinking blocks from transcript",
    )
    ap.set_defaults(show_thinking=True)
    ap.add_argument(
        "--collapse-results",
        metavar="N",
        type=int,
        nargs="?",
        const=20,
        default=20,
        help="Wrap TOOL RESULT blocks longer than N lines in <details> (default 20)",
    )
    ap.add_argument(
        "--no-collapse",
        action="store_true",
        help="Show all TOOL RESULT blocks untruncated",
    )
    ap.add_argument("--out", metavar="FILE", help="Write to FILE instead of stdout")
    src.add_argument(
        "--all",
        action="store_true",
        help="Export all sessions (combine with -n to limit)",
    )
    ap.add_argument("--out-dir", metavar="DIR", help="Output directory for --all")
    ap.add_argument(
        "--sessions-dir",
        metavar="DIR",
        help="Override default Pi sessions directory (also via PI_SESSIONS env var)",
    )

    if len(sys.argv) == 1:
        ap.print_help()
        sys.exit(0)

    args = ap.parse_args()

    show_t = not args.stats_only
    show_s = not args.transcript_only
    collapse = None if args.no_collapse else args.collapse_results
    sdir = args.sessions_dir

    if args.list:
        list_sessions(n=args.n, sessions_dir_override=sdir)

    elif args.all:
        export_all(
            args.out_dir or "./pi_transcripts",
            transcript=show_t,
            show_thinking=args.show_thinking,
            stats=show_s,
            collapse_results=collapse,
            sessions_dir_override=sdir,
            n=args.n,
        )

    elif args.session_id:
        path = resolve_session(args.session_id, sdir)
        extract(
            path,
            show_transcript=show_t,
            show_thinking=args.show_thinking,
            show_stats=show_s,
            collapse_results=collapse,
            out_file=args.out,
        )

    else:
        ap.print_help()
