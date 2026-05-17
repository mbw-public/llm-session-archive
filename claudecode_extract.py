#!/usr/bin/env python3
"""
claudecode_extract.py — Extract readable transcripts + stats from Claude Code sessions

Usage:
    python3 claudecode_extract.py --list
    python3 claudecode_extract.py <session>
    python3 claudecode_extract.py <session> --show-thinking
    python3 claudecode_extract.py <session> --stats-only
    python3 claudecode_extract.py <session> --transcript-only
    python3 claudecode_extract.py <session> --collapse-results
    python3 claudecode_extract.py <session> --collapse-results=40
    python3 claudecode_extract.py <session> --out session.md

<session> is a path to a .jsonl file, or a unique substring of the session UUID.

Claude Code stores sessions under:
  ~/.claude/projects/<encoded-project-path>/<uuid>.jsonl
Override via --projects-dir or the CLAUDE_PROJECTS env var.
"""

import re
import json
import sys
import os
import argparse
from datetime import datetime
from pathlib import Path


# ── Data location ─────────────────────────────────────────────────────────────


def find_projects_dir():
    candidates = [
        Path.home() / ".claude/projects",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not find Claude Code projects directory. Tried:\n"
        + "\n".join(f"  {p}" for p in candidates)
        + "\nSet CLAUDE_PROJECTS env var to override."
    )


def get_projects_dir(override=None):
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"Projects directory not found: {p}")
        return p
    env = os.environ.get("CLAUDE_PROJECTS")
    return Path(env) if env else find_projects_dir()


def all_session_files(projects_dir):
    """Return all .jsonl session files across all projects, newest-first."""
    files = []
    for project_dir in projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        for f in project_dir.glob("*.jsonl"):
            files.append(f)
    return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)


def resolve_session(arg, projects_dir=None):
    """
    Resolve <arg> to a session .jsonl path.
    Accepts:
      - an explicit path that exists
      - a unique substring of the session UUID matched across all sessions
    """
    p = Path(arg)
    if p.exists():
        return p

    try:
        pdir = get_projects_dir(projects_dir)
    except FileNotFoundError:
        print(f"Error: file not found: {arg}", file=sys.stderr)
        sys.exit(1)

    matches = [f for f in all_session_files(pdir) if arg in f.stem]
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


def short_project(cwd):
    """Return the last 2 components of a cwd path for display."""
    if not cwd:
        return "-"
    parts = Path(cwd).parts
    return "/".join(parts[-2:]) if len(parts) >= 2 else cwd


# ── Formatting helpers ────────────────────────────────────────────────────────


def fmt_ts(iso):
    """Convert ISO timestamp to readable local datetime."""
    if not iso:
        return "?"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime(
            "%Y-%m-%d %H:%M:%S"
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
    An unclosed fence swallows subsequent turns in the markdown renderer.
    """
    fence_char = None
    for line in content.splitlines():
        stripped = line.strip()
        if fence_char is None:
            if stripped.startswith("```"):
                fence_char = "```"
            elif stripped.startswith("~~~"):
                fence_char = "~~~"
        else:
            if stripped == fence_char or stripped.rstrip() == fence_char:
                fence_char = None
    if fence_char is not None:
        return content.rstrip() + f"\n{fence_char}"
    return content


def remove_empty_fences(text):
    """
    Remove empty fenced code blocks (opener immediately followed by closer,
    no content between them). Both backtick and tilde variants are handled.
    Marked 2 misrenders empty fences — treating the closer as content and
    swallowing subsequent document structure. Empty fences carry no content
    so removing them loses nothing.
    """
    text = re.sub(r"^```[^\n]*\n```[ \t]*$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^~~~[^\n]*\n~~~[ \t]*$", "", text, flags=re.MULTILINE)
    return text.strip()


def flatten_content(blocks, show_thinking=False, collapse_results=None):
    """Render a content block array to markdown."""
    parts = []
    for block in blocks:
        t = block.get("type", "")

        if t == "thinking":
            if show_thinking:
                text = block.get("thinking", "").strip()
                if text:
                    parts.append(
                        f"<details><summary>💭 Thinking</summary>\n\n{fence(text)}\n\n</details>"
                    )

        elif t == "text":
            text = block.get("text", "").strip()
            if text:
                text = close_unclosed_fences(text)
                text = remove_empty_fences(text)
                if text:
                    parts.append(text)

        elif t == "tool_use":
            name = block.get("name", "?")
            params = json.dumps(block.get("input", {}), indent=2)
            parts.append(f"**[TOOL CALL → {name}]**\n{fence(params, 'json')}")

        elif t == "tool_result":
            name = block.get("name", "?")
            raw = block.get("content", "")
            if isinstance(raw, list):
                texts = [i.get("text", "") for i in raw if i.get("type") == "text"]
                raw = "\n".join(texts)
            raw = raw.replace("\n\n", "\n")
            fenced = fence(raw)
            n_lines = raw.count("\n") + 1
            if collapse_results is not None and n_lines > collapse_results:
                label = f"TOOL RESULT ← {name}"
                summary = f"**[{label}]**  *({n_lines} lines)*"
                parts.append(
                    f"{summary}\n\n<details><summary>Show all {n_lines} lines\u2026</summary>"
                    f"\n\n{fenced}\n\n</details>"
                )
            else:
                parts.append(f"**[TOOL RESULT ← {name}]**\n{fenced}")

    return "\n\n".join(p for p in parts if p)


# ── Session scanner (for --list) ──────────────────────────────────────────────


def scan_session(jsonl_path):
    """
    Quick scan of a session file to extract metadata for --list.
    Reads the whole file but only parses what's needed.
    """
    title = None
    cwd = None
    model = None
    started = None
    total_output = 0

    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except Exception:
            continue
        rtype = r.get("type")
        if not cwd and r.get("cwd"):
            cwd = r["cwd"]
        if not started and r.get("timestamp"):
            started = r["timestamp"]
        if rtype == "ai-title" and not title:
            title = r.get("aiTitle")
        if rtype == "assistant":
            if not model:
                model = r.get("message", {}).get("model")
            total_output += r.get("message", {}).get("usage", {}).get("output_tokens", 0)

    return {
        "session_id": jsonl_path.stem,
        "path": jsonl_path,
        "title": title or "(untitled)",
        "cwd": cwd,
        "model": model or "-",
        "started": started,
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
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    records.append(json.loads(line))
                except Exception:
                    pass

    # Pull session metadata from records
    session_id = None
    cwd = None
    version = None
    model = None
    started = None
    title = None
    for r in records:
        if not session_id:
            session_id = r.get("sessionId")
        if not cwd and r.get("cwd"):
            cwd = r["cwd"]
        if not version and r.get("version"):
            version = r["version"]
        if not started and r.get("timestamp"):
            started = r["timestamp"]
        if r.get("type") == "ai-title" and not title:
            title = r.get("aiTitle")
        if not model and r.get("type") == "assistant":
            model = r.get("message", {}).get("model")

    lines = []

    if show_transcript:
        lines += [
            f"# {title or 'Claude Code Session'}",
            f"Session:  {session_id or Path(path).stem}",
            f"Started:  {fmt_ts(started)}",
            f"Model:    {model or '?'}",
            f"Version:  {version or '?'}",
            f"CWD:      {cwd or '?'}",
            "",
        ]

    msg_num = 0
    usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_created": 0}
    per_turn_usage = []

    for r in records:
        rtype = r.get("type")

        if rtype == "system":
            content = r.get("message", {}).get("content", "") or r.get("content", "")
            if content and show_transcript:
                msg_num += 1
                lines += ["\n---\n", f"**[{msg_num}] SYSTEM**\n", content.strip(), ""]

        elif rtype == "user":
            msg = r.get("message", {})
            content = msg.get("content", "")
            if not content:
                continue
            msg_num += 1
            if show_transcript:
                lines.append("\n---\n")
                lines.append(f"**[{msg_num}] USER**\n")
                if isinstance(content, list):
                    rendered = flatten_content(content, show_thinking, collapse_results)
                    if rendered:
                        lines.append(rendered)
                else:
                    lines.append(content.strip())
                lines.append("")

        elif rtype == "assistant":
            msg = r.get("message", {})
            blocks = msg.get("content", [])
            if not blocks:
                continue

            usage = msg.get("usage", {})
            if usage:
                inp = usage.get("input_tokens", 0)
                out = usage.get("output_tokens", 0)
                cr = usage.get("cache_read_input_tokens", 0)
                cc = usage.get("cache_creation_input_tokens", 0)
                usage_totals["input"] += inp
                usage_totals["output"] += out
                usage_totals["cache_read"] += cr
                usage_totals["cache_created"] += cc
                per_turn_usage.append(
                    {
                        "msg_num": msg_num + 1,
                        "timestamp": r.get("timestamp"),
                        "input": inp,
                        "output": out,
                        "cache_read": cr,
                        "cache_created": cc,
                        "stop_reason": msg.get("stop_reason", ""),
                    }
                )

            msg_num += 1
            if show_transcript:
                rendered = flatten_content(blocks, show_thinking, collapse_results)
                if rendered:
                    lines += ["\n---\n", f"**[{msg_num}] ASSISTANT**\n", rendered, ""]

    if show_stats and per_turn_usage:
        lines += [
            "",
            "## Token Usage Per Turn",
            "",
            "| Turn | Timestamp | Input | Output | CacheR | CacheW | Stop |",
            "|-----:|-----------|------:|-------:|-------:|-------:|------|"
        ]
        for u in per_turn_usage:
            t = fmt_ts(u["timestamp"])
            lines.append(
                f"| {u['msg_num']} | {t} | {u['input']:,} | {u['output']:,} "
                f"| {u['cache_read']:,} | {u['cache_created']:,} | {u['stop_reason']} |"
            )
        lines += [
            "",
            f"**Total input:** {usage_totals['input']:,}  ",
            f"**Total output:** {usage_totals['output']:,}  ",
            f"**Total cache reads:** {usage_totals['cache_read']:,}  ",
            f"**Total cache writes:** {usage_totals['cache_created']:,}  ",
            f"**Grand total:** {sum(usage_totals.values()):,}  ",
        ]

    output = "\n".join(lines)
    if out_file:
        Path(out_file).write_text(output, encoding="utf-8")
        print(f"Written to {out_file}")
    else:
        print(output)


# ── List sessions ─────────────────────────────────────────────────────────────


def list_sessions(projects_dir_override=None):
    projects_dir = get_projects_dir(projects_dir_override)
    files = all_session_files(projects_dir)

    if not files:
        print("No sessions found.")
        return

    sessions = [scan_session(f) for f in files]

    print(f"{'Session ID':<36}  {'Created':<20}  {'Tokens':>8}  {'Model':<35}  {'Project':<30}  Name")
    print("-" * 145)
    for s in sessions:
        tok_s = f"{s['output_tokens']:,}" if s["output_tokens"] else "-"
        project = short_project(s["cwd"])[:30]
        model = s["model"][:35]
        title = s["title"][:45]
        print(
            f"{s['session_id']:<36}  {fmt_ts(s['started']):<20}  {tok_s:>8}  "
            f"{model:<35}  {project:<30}  {title}"
        )


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract Claude Code session transcript and stats"
    )

    src = ap.add_mutually_exclusive_group()
    src.add_argument(
        "session",
        nargs="?",
        help="Path to .jsonl file, or unique substring of session UUID — run --list to see them",
    )
    src.add_argument("--list", action="store_true", help="List all sessions")

    ap.add_argument(
        "--show-thinking", action="store_true", help="Include extended thinking blocks"
    )
    ap.add_argument(
        "--stats-only", action="store_true", help="Stats only, no transcript"
    )
    ap.add_argument(
        "--transcript-only", action="store_true", help="Transcript only, no stats table"
    )
    ap.add_argument("--out", metavar="FILE", help="Write to FILE instead of stdout")
    ap.add_argument(
        "--projects-dir",
        metavar="DIR",
        help="Override Claude Code projects directory (also via CLAUDE_PROJECTS env var)",
    )
    ap.add_argument(
        "--collapse-results",
        metavar="N",
        type=int,
        nargs="?",
        const=20,
        default=None,
        help="Wrap TOOL RESULT blocks longer than N lines in <details> (default N=20)",
    )

    if len(sys.argv) == 1:
        ap.print_help()
        sys.exit(0)

    args = ap.parse_args()

    show_t = not args.stats_only
    show_s = not args.transcript_only
    pdir = args.projects_dir

    if args.list:
        list_sessions(pdir)

    elif args.session:
        path = resolve_session(args.session, pdir)
        extract(
            path,
            show_transcript=show_t,
            show_thinking=args.show_thinking,
            show_stats=show_s,
            collapse_results=args.collapse_results,
            out_file=args.out,
        )

    else:
        ap.print_help()
