#!/usr/bin/env python3
"""
lmstudio_extract.py — Extract readable transcripts + stats from LM Studio conversations

Usage:
    python3 lmstudio_extract.py --list
    python3 lmstudio_extract.py <file>
    python3 lmstudio_extract.py <file> --stats-only
    python3 lmstudio_extract.py <file> --transcript-only
    python3 lmstudio_extract.py <file> --collapse-results
    python3 lmstudio_extract.py <file> --collapse-results=40
    python3 lmstudio_extract.py <file> --out session.md

<file> is a path to a .conversation.json file, or a unique prefix/substring
of the filename stem (e.g. "17769" or "1776881829866").

LM Studio stores conversations under:
  ~/.lmstudio/conversations/<epoch_ms>.conversation.json
Override via --conversations-dir or the LMSTUDIO_CONVERSATIONS env var.
"""

import json
import sys
import os
import re
import argparse
from datetime import datetime
from pathlib import Path


# ── Data location ─────────────────────────────────────────────────────────────


def find_conversations_dir():
    candidates = [
        Path.home() / ".lmstudio/conversations",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not find LM Studio conversations directory. Tried:\n"
        + "\n".join(f"  {p}" for p in candidates)
        + "\nSet LMSTUDIO_CONVERSATIONS env var to override."
    )


def get_conversations_dir(override=None):
    if override:
        p = Path(override)
        if not p.exists():
            raise FileNotFoundError(f"Conversations directory not found: {p}")
        return p
    env = os.environ.get("LMSTUDIO_CONVERSATIONS")
    return Path(env) if env else find_conversations_dir()


def all_conversation_files(conv_dir):
    """Return all .conversation.json files sorted newest-first (by filename epoch)."""
    return sorted(conv_dir.glob("*.conversation.json"), reverse=True)


def stem(f):
    """Return just the epoch portion of a conversation filename."""
    return f.name.split(".")[0]


def resolve_file(arg, conv_dir=None):
    """
    Resolve <arg> to a conversation file path.
    Accepts:
      - an explicit path (absolute or relative) that exists
      - a filename stem or unique prefix/substring matched against the
        conversations directory
    """
    p = Path(arg)
    if p.exists():
        return p

    try:
        cdir = get_conversations_dir(conv_dir)
    except FileNotFoundError:
        print(f"Error: file not found: {arg}", file=sys.stderr)
        sys.exit(1)

    files = all_conversation_files(cdir)
    matches = [f for f in files if arg in stem(f)]
    if not matches:
        print(f"Error: no conversation matching '{arg}'", file=sys.stderr)
        sys.exit(1)
    if len(matches) > 1:
        print(
            f"Error: '{arg}' matches multiple conversations:\n"
            + "\n".join(f"  {f.name}" for f in matches),
            file=sys.stderr,
        )
        sys.exit(1)
    return matches[0]


# ── Formatting helpers ────────────────────────────────────────────────────────


def fmt_ts(ms):
    """Convert millisecond timestamp to readable local datetime."""
    if not ms:
        return "?"
    try:
        return datetime.fromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(ms)


def fence(content, lang=""):
    """Choose backtick or tilde fence depending on content."""
    content = content.rstrip()
    if "```" in content:
        return f"~~~{lang}\n{content}\n~~~"
    return f"```{lang}\n{content}\n```"


# ── Content rendering ─────────────────────────────────────────────────────────


def unescape_text(content_blocks):
    """Extract and unescape text values from a parsed tool result content array."""
    parts = []
    for item in content_blocks:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts) if parts else None


def render_tool_result(name, raw, collapse_results=None):
    """Render a toolCallResult block, with optional collapsing."""
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            unescaped = unescape_text(parsed)
            result_str = (unescaped or "").replace("\n\n", "\n")
            result_str = (
                result_str.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
            )
            result_str = result_str.replace("\n\n", "\n")
            lang = ""
            if result_str.startswith("#!"):
                first_line = result_str.splitlines()[0]
                if "bash" in first_line or "sh" in first_line:
                    lang = "bash"
                elif "python" in first_line:
                    lang = "python"
        elif isinstance(parsed, dict):
            dict_lines = []
            for k, v in parsed.items():
                if isinstance(v, str):
                    v = v.replace("\n\n", "\n").rstrip()
                    if "\n" in v:
                        dict_lines.append(f"{k}: |")
                        for vline in v.splitlines():
                            dict_lines.append(f"  {vline}")
                    else:
                        dict_lines.append(f"{k}: {v}")
                else:
                    dict_lines.append(f"{k}: {json.dumps(v)}")
            result_str = "\n".join(dict_lines)
            lang = ""
        else:
            result_str = json.dumps(parsed, indent=2)
            lang = "json"
    except Exception:
        result_str = raw
        lang = ""

    fenced = fence(result_str, lang)
    n_lines = result_str.count("\n") + 1
    if collapse_results is not None and n_lines > collapse_results:
        preview_lines = [ln for ln in result_str.splitlines() if ln.strip()][:3]
        preview = "\n".join(preview_lines)
        if n_lines > 3:
            preview += "\n\u2026"
        preview_fenced = fence(preview, lang)
        safe_fenced = fence(close_unclosed_fences(result_str), lang)
        summary = f"**[TOOL RESULT \u2190 {name}]**  *({n_lines} lines)*"
        return (
            f"{summary}\n\n{preview_fenced}\n\n"
            f"<details><summary>Show all {n_lines} lines\u2026</summary>"
            f"\n\n{safe_fenced}\n\n</details>"
        )
    return f"**[TOOL RESULT \u2190 {name}]**\n{fenced}"


def flatten_content(content_blocks, collapse_results=None):
    """Render a content block array to markdown."""
    parts = []
    for block in content_blocks:
        t = block.get("type", "")
        if t == "text":
            parts.append(block.get("text", "").strip())

        elif t == "toolCallRequest":
            name = block.get("name", "?")
            params = json.dumps(block.get("parameters", {}), indent=2)
            parts.append(f"**[TOOL CALL \u2192 {name}]**\n{fence(params, 'json')}")

        elif t == "toolCallResult":
            name = block.get("name", "?")
            raw = block.get("content", "")
            parts.append(render_tool_result(name, raw, collapse_results))

    return "\n".join(parts)


def extract_steps_text(steps, collapse_results=None):
    """Walk all steps in a multiStep version, return (text, stats_list)."""
    text_parts = []
    stats_list = []

    for step in steps:
        stype = step.get("type", "")
        if stype == "contentBlock":
            content = step.get("content", [])
            text_parts.append(flatten_content(content, collapse_results))

            gi = step.get("genInfo", {})
            s = gi.get("stats")
            if s:
                ctx = next(
                    (
                        f["value"]
                        for f in gi.get("loadModelConfig", {}).get("fields", [])
                        if f["key"] == "llm.load.contextLength"
                    ),
                    None,
                )
                stats_list.append(
                    {
                        "tokensPerSecond": s.get("tokensPerSecond"),
                        "promptTokens": s.get("promptTokensCount"),
                        "predictedTokens": s.get("predictedTokensCount"),
                        "totalTokens": s.get("totalTokensCount"),
                        "timeToFirstTokenSec": s.get("timeToFirstTokenSec"),
                        "totalTimeSec": s.get("totalTimeSec"),
                        "stopReason": s.get("stopReason"),
                        "numGpuLayers": s.get("numGpuLayers"),
                        "contextLength": ctx,
                    }
                )

    return "\n\n".join(p for p in text_parts if p), stats_list


# ── Core extract ──────────────────────────────────────────────────────────────


def extract(path, show_transcript=True, show_stats=True, collapse_results=None, out_file=None):
    with open(path) as f:
        d = json.load(f)

    last_model = d.get("lastUsedModel", {})
    ctx_fields = last_model.get("instanceLoadTimeConfig", {}).get("fields", [])
    final_ctx = next(
        (f["value"] for f in ctx_fields if f["key"] == "llm.load.contextLength"), "?"
    )
    sys_prompt = d.get("systemPrompt", "").strip()

    lines = [
        f"# {d.get('name', '(unnamed)')}",
        f"File:    {Path(path).name}",
        f"Created: {fmt_ts(d.get('createdAt'))}",
        f"Tokens:  {d.get('tokenCount', '?'):,}",
        f"Model:   {last_model.get('identifier', '?')} (ctx: {final_ctx})",
        f"Plugins: {', '.join(d.get('plugins', []))}",
    ]
    if sys_prompt:
        lines.append(
            f"SysPrompt: {sys_prompt[:120]}{'...' if len(sys_prompt) > 120 else ''}"
        )
    if collapse_results is not None:
        lines.append(f"Collapse threshold: tool results > {collapse_results} lines")
    lines.append("")

    messages = d.get("messages", [])
    all_stats = []

    for i, msg in enumerate(messages):
        versions = msg.get("versions", [])
        selected = msg.get("currentlySelected", 0)
        ver = versions[selected] if versions else {}

        role = ver.get("role", "?").upper()
        vtype = ver.get("type", "")

        if show_transcript:
            lines.append("\n---\n")
            lines.append(f"**[{i + 1}] {role}**\n")

        if vtype == "singleStep":
            text = flatten_content(ver.get("content", []), collapse_results)
            if show_transcript:
                lines.append(text)

        elif vtype == "multiStep":
            steps = ver.get("steps", [])
            text, stats = extract_steps_text(steps, collapse_results)
            if show_transcript:
                lines.append(text)
            for s in stats:
                s["msg_idx"] = i + 1
                all_stats.append(s)

        if show_transcript:
            lines.append("")

    if show_stats and all_stats:
        lines.append("\n## Performance Stats\n")
        lines.append("| Msg | tok/s | TTFT(s) | total(s) | prompt | gen | ctx | stop |")
        lines.append("|----:|------:|--------:|---------:|-------:|----:|----:|------|")
        for s in all_stats:
            tps = f"{s['tokensPerSecond']:.1f}" if s["tokensPerSecond"] is not None else "?"
            ttft = f"{s['timeToFirstTokenSec']:.3f}" if s["timeToFirstTokenSec"] is not None else "?"
            tot = f"{s['totalTimeSec']:.2f}" if s["totalTimeSec"] is not None else "?"
            lines.append(
                f"| {s['msg_idx']} | {tps} | {ttft} | {tot} "
                f"| {s['promptTokens'] or 0:,} | {s['predictedTokens'] or 0:,} "
                f"| {s['contextLength'] or 0:,} | {s['stopReason'] or ''} |"
            )

        tps_vals = [s["tokensPerSecond"] for s in all_stats if s["tokensPerSecond"]]
        ttft_vals = [s["timeToFirstTokenSec"] for s in all_stats if s["timeToFirstTokenSec"]]
        gen_vals = [s["predictedTokens"] for s in all_stats if s["predictedTokens"]]

        lines.append("")
        if tps_vals:
            lines.append(
                f"**tok/s** min={min(tps_vals):.1f} max={max(tps_vals):.1f} avg={sum(tps_vals)/len(tps_vals):.1f}  "
            )
        if ttft_vals:
            lines.append(
                f"**TTFT**  min={min(ttft_vals):.2f}s max={max(ttft_vals):.2f}s avg={sum(ttft_vals)/len(ttft_vals):.2f}s  "
            )
        if gen_vals:
            lines.append(
                f"**Gen**   total={sum(gen_vals):,} tokens  avg={sum(gen_vals)/len(gen_vals):.0f}/step  "
            )

    output = "\n".join(lines)
    if out_file:
        Path(out_file).write_text(output, encoding="utf-8")
        print(f"Written to {out_file}")
    else:
        print(output)


# ── List conversations ────────────────────────────────────────────────────────


def list_conversations(conv_dir_override=None):
    conv_dir = get_conversations_dir(conv_dir_override)
    files = all_conversation_files(conv_dir)

    if not files:
        print("No conversations found.")
        return

    print(f"{'Filename stem':<17}  {'Created':<20}  {'Tokens':>8}  {'Model':<40}  Name")
    print("-" * 115)
    for f in files:
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
            name = (d.get("name") or "(unnamed)")[:45]
            created = fmt_ts(d.get("createdAt"))
            tokens = d.get("tokenCount")
            tok_s = f"{tokens:,}" if tokens else "-"
            model = (d.get("lastUsedModel", {}).get("identifier") or "-")[:40]
            print(f"{stem(f):<17}  {created:<20}  {tok_s:>8}  {model:<40}  {name}")
        except Exception as e:
            print(f"{stem(f):<17}  (error reading file: {e})")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract LM Studio session transcript and stats"
    )

    src = ap.add_mutually_exclusive_group()
    src.add_argument(
        "file",
        nargs="?",
        help="Path to .conversation.json, or a unique substring of the filename stem",
    )
    src.add_argument("--list", action="store_true", help="List all conversations")

    ap.add_argument(
        "--stats-only", action="store_true", help="Stats only, no transcript"
    )
    ap.add_argument(
        "--transcript-only", action="store_true", help="Transcript only, no stats table"
    )
    ap.add_argument("--out", metavar="FILE", help="Write to FILE instead of stdout")
    ap.add_argument(
        "--conversations-dir",
        metavar="DIR",
        help="Override conversations directory (also via LMSTUDIO_CONVERSATIONS env var)",
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
    cdir = args.conversations_dir

    if args.list:
        list_conversations(cdir)

    elif args.file:
        path = resolve_file(args.file, cdir)
        extract(
            path,
            show_transcript=show_t,
            show_stats=show_s,
            collapse_results=args.collapse_results,
            out_file=args.out,
        )

    else:
        ap.print_help()
