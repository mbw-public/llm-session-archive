#!/usr/bin/env python3
"""
lmstudio_extract.py — Extract readable transcript + performance stats from an LM Studio .json log.

Usage:
    python3 lmstudio_extract.py Qwen.json
    python3 lmstudio_extract.py Qwen.json --stats-only
    python3 lmstudio_extract.py Qwen.json --transcript-only
"""

import json
import sys
import argparse
from datetime import datetime


def ts(ms):
    """Convert millisecond timestamp to readable datetime."""
    return datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S")


def fence(content, lang=""):
    """Choose backtick or tilde fence depending on content."""
    if "```" in content:
        return f"~~~{lang}\n{content}\n~~~"
    return f"```{lang}\n{content}\n```"


def unescape_text(content_blocks):
    """Extract and unescape text values from a parsed tool result content array."""
    parts = []
    for item in content_blocks:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts) if parts else None


def flatten_content(content_blocks):
    """Extract plain text from a content array."""
    parts = []
    for block in content_blocks:
        t = block.get("type", "")
        if t == "text":
            parts.append(block.get("text", "").strip())
        elif t == "toolCallRequest":
            name = block.get("name", "?")
            params = json.dumps(block.get("parameters", {}), indent=2)
            parts.append(f"**[TOOL CALL → {name}]**\n{fence(params, 'json')}")
        elif t == "toolCallResult":
            name = block.get("name", "?")
            raw = block.get("content", "")
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    # Text block array — extract and unescape
                    unescaped = unescape_text(parsed)
                    result_str = (unescaped or "").replace("\n\n", "\n")
                    # Second pass: decode any remaining literal \n \t \" escape sequences
                    result_str = (
                        result_str.replace("\\n", "\n")
                        .replace("\\t", "\t")
                        .replace('\\"', '"')
                    )
                    result_str = result_str.replace(
                        "\n\n", "\n"
                    )  # collapse doubles introduced above
                    lang = ""
                    if result_str.startswith("#!"):
                        first_line = result_str.splitlines()[0]
                        if "bash" in first_line or "sh" in first_line:
                            lang = "bash"
                        elif "python" in first_line:
                            lang = "python"
                    parts.append(
                        f"**[TOOL RESULT ← {name}]**\n{fence(result_str, lang)}"
                    )
                elif isinstance(parsed, dict):
                    # Structured result (e.g. exit_code/stdout/stderr) — unescape string values
                    lines = []
                    for k, v in parsed.items():
                        if isinstance(v, str):
                            v = v.replace("\n\n", "\n").rstrip()
                            if "\n" in v:
                                lines.append(f"{k}: |")
                                for vline in v.splitlines():
                                    lines.append(f"  {vline}")
                            else:
                                lines.append(f"{k}: {v}")
                        else:
                            lines.append(f"{k}: {json.dumps(v)}")
                    result_str = "\n".join(lines)
                    parts.append(f"**[TOOL RESULT ← {name}]**\n{fence(result_str)}")
                else:
                    result_str = json.dumps(parsed, indent=2)
                    parts.append(
                        f"**[TOOL RESULT ← {name}]**\n{fence(result_str, 'json')}"
                    )
            except Exception:
                parts.append(f"**[TOOL RESULT ← {name}]**\n{fence(raw)}")
    return "\n".join(parts)


def extract_steps_text(steps):
    """Walk all steps in a multiStep version, return (text, stats_list)."""
    text_parts = []
    stats_list = []

    for step in steps:
        stype = step.get("type", "")
        if stype == "contentBlock":
            content = step.get("content", [])
            text_parts.append(flatten_content(content))

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


def extract(path, show_transcript=True, show_stats=True):
    with open(path) as f:
        d = json.load(f)

    last_model = d.get("lastUsedModel", {})
    ctx_fields = last_model.get("instanceLoadTimeConfig", {}).get("fields", [])
    final_ctx = next(
        (f["value"] for f in ctx_fields if f["key"] == "llm.load.contextLength"), "?"
    )
    sys_prompt = d.get("systemPrompt", "").strip()

    header_lines = [
        f"# {d.get('name', '(unnamed)')}",
        f"Created: {ts(d['createdAt'])}",
        f"Tokens: {d.get('tokenCount', '?'):,}",
        f"Model: {last_model.get('identifier', '?')} (final ctx: {final_ctx})",
        f"Plugins: {', '.join(d.get('plugins', []))}",
    ]
    if sys_prompt:
        header_lines.append(
            f"SysPrompt: {sys_prompt[:120]}{'...' if len(sys_prompt) > 120 else ''}"
        )
    print("  \n".join(header_lines))
    print()

    messages = d.get("messages", [])
    all_stats = []

    for i, msg in enumerate(messages):
        versions = msg.get("versions", [])
        selected = msg.get("currentlySelected", 0)
        ver = versions[selected] if versions else {}

        role = ver.get("role", "?").upper()
        vtype = ver.get("type", "")

        if show_transcript:
            print(f"\n---\n")
            print(f"**[{i + 1}] {role}**\n")

        if vtype == "singleStep":
            text = flatten_content(ver.get("content", []))
            if show_transcript:
                print(text)

        elif vtype == "multiStep":
            steps = ver.get("steps", [])
            text, stats = extract_steps_text(steps)
            if show_transcript:
                print(text)
            for s in stats:
                s["msg_idx"] = i + 1
                all_stats.append(s)

        if show_transcript:
            print()

    if show_stats and all_stats:
        print(f"\n## Performance Stats\n")
        print("| Msg | tok/s | TTFT(s) | total(s) | prompt | gen | ctx | stop |")
        print("|----:|------:|--------:|---------:|-------:|----:|----:|------|")
        for s in all_stats:
            tps = (
                f"{s['tokensPerSecond']:.1f}"
                if s["tokensPerSecond"] is not None
                else "?"
            )
            ttft = (
                f"{s['timeToFirstTokenSec']:.3f}"
                if s["timeToFirstTokenSec"] is not None
                else "?"
            )
            tot = f"{s['totalTimeSec']:.2f}" if s["totalTimeSec"] is not None else "?"
            print(
                f"| {s['msg_idx']} | {tps} | {ttft} | {tot} "
                f"| {s['promptTokens'] or 0:,} | {s['predictedTokens'] or 0:,} "
                f"| {s['contextLength'] or 0:,} | {s['stopReason'] or ''} |"
            )

        tps_vals = [s["tokensPerSecond"] for s in all_stats if s["tokensPerSecond"]]
        ttft_vals = [
            s["timeToFirstTokenSec"] for s in all_stats if s["timeToFirstTokenSec"]
        ]
        gen_vals = [s["predictedTokens"] for s in all_stats if s["predictedTokens"]]

        print()
        if tps_vals:
            print(
                f"**tok/s** min={min(tps_vals):.1f} max={max(tps_vals):.1f} avg={sum(tps_vals) / len(tps_vals):.1f}  "
            )
        if ttft_vals:
            print(
                f"**TTFT**  min={min(ttft_vals):.2f}s max={max(ttft_vals):.2f}s avg={sum(ttft_vals) / len(ttft_vals):.2f}s  "
            )
        if gen_vals:
            print(
                f"**Gen**   total={sum(gen_vals):,} tokens  avg={sum(gen_vals) / len(gen_vals):.0f}/step  "
            )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract LM Studio session transcript and stats"
    )
    ap.add_argument("file", nargs="?", help="Path to LM Studio .json log")
    ap.add_argument(
        "--stats-only", action="store_true", help="Stats only, no transcript"
    )
    ap.add_argument(
        "--transcript-only", action="store_true", help="Transcript only, no stats table"
    )
    ap.add_argument("--out", metavar="FILE", help="Write to FILE instead of stdout")
    args = ap.parse_args()

    if not args.file:
        ap.print_help()
        sys.exit(0)

    show_t = not args.stats_only
    show_s = not args.transcript_only

    if args.out:
        sys.stdout = open(args.out, "w")

    extract(args.file, show_transcript=show_t, show_stats=show_s)

    if args.out:
        sys.stdout.close()
