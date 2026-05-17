#!/usr/bin/env python3
"""
jan_extract.py — Extract readable transcripts + stats from Jan app threads

Usage:
    python3 jan_extract.py --list
    python3 jan_extract.py <thread_id>
    python3 jan_extract.py <thread_id> --stats-only
    python3 jan_extract.py <thread_id> --transcript-only
    python3 jan_extract.py <thread_id> --show-thinking
    python3 jan_extract.py <thread_id> --collapse-results
    python3 jan_extract.py <thread_id> --collapse-results=40
    python3 jan_extract.py <thread_id> --out session.md
    python3 jan_extract.py --all --out-dir ./jan_transcripts/

Thread IDs are UUIDs — run --list to see them with their titles.
A unique prefix of the UUID is also accepted.

Jan stores threads under:
  ~/Library/Application Support/Jan/data/threads/<uuid>/
Each thread contains:
  thread.json     — metadata (title, model, engine, timestamps)
  messages.jsonl  — one message per line
"""

import re
import json
import sys
import os
import argparse
from datetime import datetime
from pathlib import Path


# ── Data location ─────────────────────────────────────────────────────────────


def find_threads_dir():
    candidates = [
        Path.home() / "Library/Application Support/Jan/data/threads",
        Path.home() / ".config/Jan/data/threads",
        Path(os.environ.get("APPDATA", "")) / "Jan/data/threads",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not find Jan threads directory. Tried:\n"
        + "\n".join(f"  {p}" for p in candidates)
        + "\nSet JAN_THREADS env var to override."
    )


def get_threads_dir(override=None):
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"Threads directory not found: {p}")
        return p
    env = os.environ.get("JAN_THREADS")
    return Path(env) if env else find_threads_dir()


def list_thread_dirs(threads_dir):
    """Return newest-first list of thread directories that have both required files."""
    result = [
        d
        for d in threads_dir.iterdir()
        if d.is_dir()
        and (d / "thread.json").exists()
        and (d / "messages.jsonl").exists()
    ]

    # Sort by thread.json "created" timestamp descending
    def created_ts(d):
        try:
            return json.loads((d / "thread.json").read_text(encoding="utf-8")).get(
                "created", 0
            )
        except Exception:
            return 0

    return sorted(result, key=created_ts, reverse=True)


# ── Formatting helpers ────────────────────────────────────────────────────────


def fmt_ts(value):
    """Parse millisecond epoch integer to readable local time."""
    if not value:
        return "?"
    try:
        epoch = int(value)
        if epoch > 1e12:
            epoch //= 1000
        return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def fence(content, lang=""):
    content = content.rstrip()
    if "```" in content:
        return f"~~~{lang}\n{content}\n~~~"
    return f"```{lang}\n{content}\n```"


# ── Content rendering ─────────────────────────────────────────────────────────


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


def render_message(msg, show_thinking=False, collapse_results=None):
    """
    Render a Jan message's content array to markdown.

    Jan content blocks have type "text" or "reasoning". Each has a
    .text.value field containing the actual string.

    collapse_results is accepted for API consistency but Jan doesn't currently
    produce tool result blocks in the same structure, so it is a no-op here.
    """
    parts = []
    for block in msg.get("content", []):
        btype = block.get("type", "")
        value = block.get("text", {}).get("value", "").strip()

        if not value:
            continue

        if btype == "text":
            value = close_unclosed_fences(value)
            value = remove_empty_fences(value)
            if value:
                parts.append(value)

        elif btype == "reasoning":
            if show_thinking:
                value = close_unclosed_fences(value)
                parts.append(
                    f"<details><summary>💭 Thinking</summary>\n\n{value}\n\n</details>"
                )

        else:
            # Unknown block type — render as fenced JSON for inspection
            parts.append(
                f"**[{btype.upper()} BLOCK]**\n{fence(json.dumps(block, indent=2), 'json')}"
            )

    return "\n\n".join(p for p in parts if p)


# ── Thread loader ─────────────────────────────────────────────────────────────


def load_thread(thread_dir):
    """
    Load thread metadata and messages from a Jan thread directory.

    Returns (thread_meta dict, messages list).
    Messages are filtered to exclude the ghost empty assistant message that
    Jan writes as a placeholder at thread creation, and sorted by created_at.
    """
    thread_dir = Path(thread_dir)
    thread_meta = json.loads((thread_dir / "thread.json").read_text(encoding="utf-8"))

    messages = []
    for line in (
        (thread_dir / "messages.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        # Skip the ghost empty assistant placeholder Jan creates at thread start
        if msg.get("role") == "assistant":
            content = msg.get("content", [])
            all_empty = all(
                not c.get("text", {}).get("value", "").strip()
                for c in content
                if c.get("type") == "text"
            )
            if all_empty:
                continue
        messages.append(msg)

    messages.sort(key=lambda m: m.get("created_at", 0))
    return thread_meta, messages


# ── Stats helpers ─────────────────────────────────────────────────────────────


def get_token_stats(msg):
    """Return (input_tokens, output_tokens, total_tokens, token_speed) for a message."""
    meta = msg.get("metadata", {})
    usage = meta.get("usage", {})
    speed = meta.get("tokenSpeed", {})
    return (
        usage.get("inputTokens"),
        usage.get("outputTokens"),
        usage.get("totalTokens"),
        speed.get("tokenSpeed"),
    )


# ── Core extract ──────────────────────────────────────────────────────────────


def extract(
    thread_meta,
    messages,
    show_transcript=True,
    show_stats=True,
    show_thinking=False,
    out_file=None,
    collapse_results=None,
):
    lines = []

    # ── Header ────────────────────────────────────────────────────────────────
    title = thread_meta.get("title") or thread_meta.get("id") or "Thread"
    # thread.json stores timestamps as float seconds; convert to ms for fmt_ts
    created = fmt_ts(int(thread_meta.get("created", 0) * 1000))
    updated = fmt_ts(int(thread_meta.get("updated", 0) * 1000))

    assistant = (thread_meta.get("assistants") or [{}])[0]
    model_info = assistant.get("model", {})
    model_id = model_info.get("id") or thread_meta.get("model", {}).get("id", "")
    engine = model_info.get("engine") or thread_meta.get("model", {}).get(
        "provider", ""
    )

    lines += [
        f"# {title}",
        f"Thread ID:    {thread_meta.get('id', '?')}",
        f"Created:      {created}",
        f"Updated:      {updated}",
    ]
    if model_id:
        lines.append(f"Model:        {model_id}")
    if engine:
        lines.append(f"Engine:       {engine}")
    lines.append(f"Messages:     {len(messages)}")

    # Aggregate token totals from assistant messages
    total_in = sum(
        get_token_stats(m)[0] or 0 for m in messages if m.get("role") == "assistant"
    )
    total_out = sum(
        get_token_stats(m)[1] or 0 for m in messages if m.get("role") == "assistant"
    )
    total_tok = sum(
        get_token_stats(m)[2] or 0 for m in messages if m.get("role") == "assistant"
    )
    if total_tok:
        lines.append(
            f"Tokens:       {total_tok:,}  (in {total_in:,}  out {total_out:,})"
        )

    if collapse_results is not None:
        lines.append(f"Collapse threshold: tool results > {collapse_results} lines")

    lines.append("")

    # ── Transcript ────────────────────────────────────────────────────────────
    if show_transcript:
        for i, msg in enumerate(messages):
            role = msg.get("role", "?").upper()
            rendered = render_message(
                msg, show_thinking=show_thinking, collapse_results=collapse_results
            )
            _, out_tok, _, tok_speed = get_token_stats(msg)

            lines.append("\n---\n")
            hdr = f"**[{i + 1}] {role}**"
            if out_tok:
                hdr += f"  *(tokens: {out_tok:,})*"
            if tok_speed:
                hdr += f"  *({tok_speed:.1f} tok/s)*"
            lines.append(hdr + "\n")
            if rendered:
                lines.append(rendered)
            lines.append("")

    # ── Stats ─────────────────────────────────────────────────────────────────
    if show_stats:
        tok_rows = []
        for i, msg in enumerate(messages):
            _, out_tok, _, speed = get_token_stats(msg)
            if out_tok:
                tok_rows.append((i + 1, msg["role"], out_tok, speed))

        if tok_rows:
            lines.append("\n## Token Usage Per Turn\n")
            lines.append("| Msg | Role | Tokens | tok/s |")
            lines.append("|----:|------|-------:|------:|")
            for idx, role, tok, speed in tok_rows:
                speed_s = f"{speed:.1f}" if speed else "-"
                lines.append(f"| {idx} | {role} | {tok:,} | {speed_s} |")
            lines.append(
                f"\n**Session total (output):** {sum(t for _, _, t, _ in tok_rows):,}"
            )
            lines.append("")

    output = "\n".join(lines)
    if out_file:
        Path(out_file).write_text(output, encoding="utf-8")
        print(f"Written to {out_file}")
    else:
        print(output)


# ── List threads ──────────────────────────────────────────────────────────────


def thread_token_total(thread_dir):
    """Sum totalTokens across all assistant messages in a thread."""
    total = 0
    for line in (
        (thread_dir / "messages.jsonl").read_text(encoding="utf-8").splitlines()
    ):
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            if msg.get("role") == "assistant":
                total += msg.get("metadata", {}).get("usage", {}).get("totalTokens", 0)
        except Exception:
            pass
    return total or None


def list_threads(threads_dir_override=None):
    threads_dir = get_threads_dir(threads_dir_override)
    dirs = list_thread_dirs(threads_dir)

    if not dirs:
        print("No threads found.")
        return

    print(f"{'Thread ID':<40}  {'Created':<20}  {'Tokens':>8}  {'Model':<35}  Name")
    print("-" * 120)
    for d in dirs:
        meta = json.loads((d / "thread.json").read_text(encoding="utf-8"))
        title = (meta.get("title") or "(untitled)")[:50]
        created = fmt_ts(int(meta.get("created", 0) * 1000))
        model_id = (meta.get("model", {}).get("id") or "-")[:35]
        tokens = thread_token_total(d)
        tok_s = f"{tokens:,}" if tokens else "-"
        print(f"{d.name:<40}  {created:<20}  {tok_s:>8}  {model_id:<35}  {title}")


# ── Export all ────────────────────────────────────────────────────────────────


def export_all(
    out_dir,
    transcript=True,
    stats=True,
    show_thinking=False,
    collapse_results=None,
    threads_dir_override=None,
):
    threads_dir = get_threads_dir(threads_dir_override)
    dirs = list_thread_dirs(threads_dir)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    for d in dirs:
        dest = out / f"{d.name}.md"
        print(f"  {d.name} → {dest}")
        try:
            meta, messages = load_thread(d)
            extract(
                meta,
                messages,
                show_transcript=transcript,
                show_stats=stats,
                show_thinking=show_thinking,
                out_file=str(dest),
                collapse_results=collapse_results,
            )
        except Exception as e:
            print(f"    ERROR: {e}")

    print(f"\nDone. {len(dirs)} threads exported to {out}/")


# ── Thread resolver ───────────────────────────────────────────────────────────


def resolve_thread(thread_id, threads_dir):
    """Resolve a substring of a thread UUID to a thread directory."""
    matches = [d for d in list_thread_dirs(threads_dir) if thread_id in d.name]
    if not matches:
        print(f"Error: no thread matching '{thread_id}'", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(
            f"Error: '{thread_id}' matches multiple threads:\n"
            + "\n".join(f"  {m.name}" for m in matches),
            file=sys.stderr,
        )
        sys.exit(1)
    return matches[0]


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract Jan session transcripts and stats"
    )

    src = ap.add_mutually_exclusive_group()
    src.add_argument(
        "thread_id",
        nargs="?",
        help="Thread UUID (or unique prefix) — run --list to see them",
    )
    src.add_argument("--list", action="store_true", help="List all threads")
    src.add_argument("--all", action="store_true", help="Export all threads")

    ap.add_argument(
        "--stats-only", action="store_true", help="Stats only, no transcript"
    )
    ap.add_argument(
        "--transcript-only",
        action="store_true",
        help="Transcript only, no stats tables",
    )
    ap.add_argument(
        "--show-thinking",
        action="store_true",
        help="Include reasoning blocks in transcript",
    )
    ap.add_argument("--out", metavar="FILE", help="Write to FILE instead of stdout")
    ap.add_argument("--out-dir", metavar="DIR", help="Output directory for --all")
    ap.add_argument(
        "--threads-dir",
        metavar="DIR",
        help="Override Jan threads directory (also via JAN_THREADS env var)",
    )
    ap.add_argument(
        "--collapse-results",
        metavar="N",
        type=int,
        nargs="?",
        const=20,
        default=None,
        help="Wrap tool result blocks longer than N lines in <details> (default N=20)",
    )

    if len(sys.argv) == 1:
        ap.print_help()
        sys.exit(0)

    args = ap.parse_args()

    show_t = not args.stats_only
    show_s = not args.transcript_only
    collapse = args.collapse_results
    tdir = args.threads_dir

    if args.list:
        list_threads(tdir)

    elif args.all:
        export_all(
            args.out_dir or "./jan_transcripts",
            transcript=show_t,
            stats=show_s,
            show_thinking=args.show_thinking,
            collapse_results=collapse,
            threads_dir_override=tdir,
        )

    elif args.thread_id:
        threads_dir = get_threads_dir(tdir)
        thread_dir = resolve_thread(args.thread_id, threads_dir)
        meta, messages = load_thread(thread_dir)
        extract(
            meta,
            messages,
            show_transcript=show_t,
            show_stats=show_s,
            show_thinking=args.show_thinking,
            out_file=args.out,
            collapse_results=collapse,
        )

    else:
        ap.print_help()
