#!/usr/bin/env python3
"""
claudecode_extract.py — Extract readable transcript + token stats from a Claude Code .jsonl log.

Usage:
    python3 claudecode_extract.py Claude.jsonl
    python3 claudecode_extract.py Claude.jsonl --show-thinking
    python3 claudecode_extract.py Claude.jsonl --stats-only
    python3 claudecode_extract.py Claude.jsonl --transcript-only
"""

import json
import sys
import argparse
from datetime import datetime


def ts(iso):
    """Convert ISO timestamp to readable datetime."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def fence(content, lang=""):
    """Use tilde fences if content contains backticks, otherwise backtick fences."""
    if "```" in content:
        return f"~~~{lang}\n{content}\n~~~"
    return f"```{lang}\n{content}\n```"


def flatten_content(blocks, show_thinking=False, collapse_results=None):
    """Render a content block array to markdown."""
    parts = []
    for block in blocks:
        t = block.get("type", "")

        if t == "thinking":
            if show_thinking:
                text = block.get("thinking", "").strip()
                parts.append(f"*[thinking]*\n{fence(text)}")

        elif t == "text":
            text = block.get("text", "").strip()
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
                    f"{summary}\n\n<details><summary>Show all {n_lines} lines\u2026</summary>\n\n{fenced}\n\n</details>"
                )
            else:
                parts.append(f"**[TOOL RESULT ← {name}]**\n{fenced}")

    return "\n\n".join(p for p in parts if p)


def extract(
    path,
    show_transcript=True,
    show_thinking=False,
    show_stats=True,
    collapse_results=None,
):
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    # Pull session metadata from first records
    session_id = None
    cwd = None
    version = None
    model = None
    started = None
    for r in records:
        if not session_id:
            session_id = r.get("sessionId")
        if not cwd and r.get("cwd"):
            cwd = r["cwd"]
        if not version and r.get("version"):
            version = r["version"]
        if not started and r.get("timestamp"):
            started = r["timestamp"]
        if not model and r.get("type") == "assistant":
            model = r.get("message", {}).get("model")
        if all([session_id, cwd, version, started, model]):
            break

    if show_transcript:
        header = [
            f"# Claude Code Session",
            f"Started:  {ts(started) if started else '?'}",
            f"Model:    {model or '?'}",
            f"Version:  {version or '?'}",
            f"CWD:      {cwd or '?'}",
            f"Session:  {session_id or '?'}",
        ]
        print("  \n".join(header))
        print()

    msg_num = 0
    usage_totals = {"input": 0, "output": 0, "cache_read": 0, "cache_created": 0}
    per_turn_usage = []

    for r in records:
        rtype = r.get("type")

        if rtype == "system":
            if show_transcript:
                content = r.get("message", {}).get("content", "")
                if content:
                    msg_num += 1
                    print(f"\n---\n")
                    print(f"**[{msg_num}] SYSTEM**\n")
                    print(content.strip())

        elif rtype == "user":
            msg = r.get("message", {})
            content = msg.get("content", "")
            if not content:
                continue
            msg_num += 1
            if show_transcript:
                print(f"\n---\n")
                print(f"**[{msg_num}] USER**\n")
                if isinstance(content, list):
                    print(flatten_content(content, show_thinking, collapse_results))
                else:
                    print(content.strip())

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
                    print(f"\n---\n")
                    print(f"**[{msg_num}] ASSISTANT**\n")
                    print(rendered)

    if show_stats and per_turn_usage:
        print(f"\n{'=' * 60}")
        print("TOKEN USAGE\n")
        print(
            f"{'Turn':>4}  {'Timestamp':<19}  {'Input':>7}  {'Output':>7}  {'CacheR':>7}  {'CacheW':>7}  Stop"
        )
        print(
            f"{'─' * 4}  {'─' * 19}  {'─' * 7}  {'─' * 7}  {'─' * 7}  {'─' * 7}  {'─' * 12}"
        )
        for u in per_turn_usage:
            t = ts(u["timestamp"]) if u["timestamp"] else "?"
            print(
                f"{u['msg_num']:>4}  {t:<19}  "
                f"{u['input']:>7,}  {u['output']:>7,}  "
                f"{u['cache_read']:>7,}  {u['cache_created']:>7,}  "
                f"{u['stop_reason']}"
            )
        print(f"\n{'─' * 60}")
        print(f"Total input:         {usage_totals['input']:>10,}")
        print(f"Total output:        {usage_totals['output']:>10,}")
        print(f"Total cache reads:   {usage_totals['cache_read']:>10,}")
        print(f"Total cache writes:  {usage_totals['cache_created']:>10,}")
        print(f"Grand total:         {sum(usage_totals.values()):>10,}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract Claude Code session transcript and stats"
    )
    ap.add_argument("file", nargs="?", help="Path to Claude Code .jsonl log")
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
        "--collapse-results",
        metavar="N",
        type=int,
        nargs="?",
        const=20,
        default=None,
        help="Wrap TOOL RESULT blocks longer than N lines in <details> (default N=20)",
    )
    args = ap.parse_args()

    if not args.file:
        ap.print_help()
        sys.exit(0)

    show_t = not args.stats_only
    show_s = not args.transcript_only

    if args.out:
        sys.stdout = open(args.out, "w")

    extract(
        args.file,
        show_transcript=show_t,
        show_thinking=args.show_thinking,
        show_stats=show_s,
        collapse_results=args.collapse_results,
    )

    if args.out:
        sys.stdout.close()
