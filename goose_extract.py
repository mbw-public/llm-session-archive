#!/usr/bin/env python3
"""
goose_extract.py — Extract readable transcripts + stats from Goose sessions

Supports two input formats:
  SQLite database (sessions.db):
    python3 goose_extract.py --list
    python3 goose_extract.py --schema
    python3 goose_extract.py <session_id>
    python3 goose_extract.py <session_id> --show-thinking
    python3 goose_extract.py <session_id> --stats-only
    python3 goose_extract.py <session_id> --transcript-only
    python3 goose_extract.py <session_id> --out session.md
    python3 goose_extract.py <session_id> --collapse-results 20
    python3 goose_extract.py --all --out-dir ./goose_transcripts/
    python3 goose_extract.py --all -n 10 --out-dir ./goose_transcripts/

  JSON export file:
    python3 goose_extract.py --json session.json
    python3 goose_extract.py --json session.json --out session.md
    python3 goose_extract.py --json session.json --collapse-results 20

Session IDs look like  20260503_1  — run --list to see them all.
"""

import re
import sqlite3
import json
import sys
import os
import argparse
from datetime import datetime
from pathlib import Path


# ── DB location ───────────────────────────────────────────────────────────────


def find_db():
    candidates = [
        Path.home() / ".local/share/goose/sessions/sessions.db",
        Path(os.environ.get("APPDATA", "")) / "Block/goose/data/sessions/sessions.db",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not find sessions.db. Tried:\n"
        + "\n".join(f"  {p}" for p in candidates)
        + "\nSet GOOSE_DB env var to override."
    )


def get_db(db_path=None):
    if db_path:
        p = Path(db_path)
        if not p.exists():
            raise FileNotFoundError(f"Database not found: {p}")
        return p
    override = os.environ.get("GOOSE_DB")
    return Path(override) if override else find_db()


def connect(db_path=None):
    db = get_db(db_path)
    con = sqlite3.connect(str(db))
    con.execute("PRAGMA query_only = ON")
    return con


# ── Formatting helpers ────────────────────────────────────────────────────────


def fmt_ts(value):
    """Parse TIMESTAMP string or INTEGER epoch to readable local time."""
    if not value:
        return "?"
    try:
        if isinstance(value, int) or (isinstance(value, str) and value.isdigit()):
            epoch = int(value)
            if epoch > 1e12:
                epoch //= 1000
            return datetime.fromtimestamp(epoch).strftime("%Y-%m-%d %H:%M:%S")
        value = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(value)


def fence(content, lang=""):
    content = content.rstrip()
    if "```" in content:
        return f"~~~{lang}\n{content}\n~~~"
    return f"```{lang}\n{content}\n```"


def detect_lang(text):
    first = (text.strip().splitlines() or [""])[0]
    if "python" in first:
        return "python"
    if "bash" in first or "/sh" in first:
        return "bash"
    return ""


# ── Content rendering ─────────────────────────────────────────────────────────


def clean_thinking_blocks(blocks):
    """
    llama_swap stores assistant responses as individual streaming tokens, each
    as a separate thinking block, followed by a final text block containing the
    complete response. Three passes clean this up:

    Pass 1 — CONCAT consecutive thinking blocks.
              Each token is a separate block; concatenating rebuilds the full text.

    Pass 2 — Trim repeated prefix across separate thinking groups.
              When the model restates its previous thinking at the start of a new
              group, thinking_B starts with thinking_A's content. Strip that prefix
              from thinking_B so each group shows only its new content.
              Also drop the trimmed block if the remainder equals the previous
              block's content (pure repeat, e.g. "A\nA" → drop).

    Pass 3 — Drop thinking block if content matches the next text block.
              llama_swap stores the final response both as the last thinking token
              stream AND as a text block. Drop the thinking copy when identical.
    """
    # Pass 1: concat consecutive thinking blocks (individual tokens → full text)
    merged = []
    for block in blocks:
        if (
            isinstance(block, dict)
            and block.get("type") == "thinking"
            and merged
            and isinstance(merged[-1], dict)
            and merged[-1].get("type") == "thinking"
        ):
            merged[-1] = {
                "type": "thinking",
                "thinking": merged[-1].get("thinking", "") + block.get("thinking", ""),
            }
        else:
            merged.append(block)

    # Pass 2: trim repeated prefix between separate thinking groups.
    thinking_indices = [
        i
        for i, b in enumerate(merged)
        if isinstance(b, dict) and b.get("type") == "thinking"
    ]
    for n in range(1, len(thinking_indices)):
        prev_i = thinking_indices[n - 1]
        curr_i = thinking_indices[n]
        if merged[prev_i] is None:  # was nulled in a prior iteration
            continue
        prev_text = merged[prev_i].get("thinking", "").strip()
        curr_text = merged[curr_i].get("thinking", "").strip()
        if prev_text and curr_text.startswith(prev_text):
            trimmed = curr_text[len(prev_text) :].lstrip("\n").strip()
            merged[curr_i] = (
                {"type": "thinking", "thinking": trimmed}
                if (trimmed and trimmed != prev_text)
                else None
            )
    merged = [b for b in merged if b is not None]

    # Pass 3: drop thinking block if content matches the next text block.
    final = []
    for i, block in enumerate(merged):
        if isinstance(block, dict) and block.get("type") == "thinking":
            this_text = block.get("thinking", "").strip()
            next_text = ""
            for j in range(i + 1, len(merged)):
                nb = merged[j]
                if isinstance(nb, dict) and nb.get("type") == "text":
                    next_text = nb.get("text", "").strip()
                    break
            if this_text and this_text == next_text:
                continue  # drop — duplicate of text block
        final.append(block)

    return final


def strip_fences_from_thinking(text):
    """Remove fence markers from thinking block prose."""
    fence_marker = "`" * 3
    return re.sub(
        r"^" + fence_marker + r"[^\n]*$", "", text, flags=re.MULTILINE
    ).strip()


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
    An unclosed fence inside a <details> block prevents </details> from
    being recognised by the markdown parser, swallowing subsequent turns.
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
            # A closing fence is the fence char alone (possibly with trailing spaces)
            if stripped == fence_char or stripped.rstrip() == fence_char:
                fence_char = None
    if fence_char is not None:
        return content.rstrip() + f"\n{fence_char}"
    return content


def render_blocks(blocks, collapse_results=None, show_thinking=False):
    """
    Render a pre-parsed list of content blocks to markdown.

    collapse_results: if set to an integer N, TOOL RESULT blocks longer than
    N lines are wrapped in a <details> element. The summary shows the tool ID,
    line count, and first line of content so you know what's inside.
    """
    if not isinstance(blocks, list):
        return str(blocks).strip() if blocks else ""

    blocks = clean_thinking_blocks(blocks)

    parts = []
    for block in blocks:
        if not isinstance(block, dict):
            parts.append(str(block))
            continue

        btype = block.get("type", "")

        if btype == "text":
            text = block.get("text", "").strip()
            if text:
                text = close_unclosed_fences(text)
                text = remove_empty_fences(text)
                if text:
                    parts.append(text)

        elif btype in ("tool_use", "toolRequest"):
            # tool_use: Anthropic format  toolRequest: Goose JSON export format
            name = block.get("name") or block.get("toolCall", {}).get("value", {}).get(
                "name", "?"
            )
            inp = block.get("input") or block.get("toolCall", {}).get("value", {}).get(
                "arguments", {}
            )
            inp_s = json.dumps(inp, indent=2) if isinstance(inp, dict) else str(inp)
            parts.append(f"**[TOOL CALL → {name}]**\n{fence(inp_s, 'json')}")

        elif btype in ("tool_result", "toolResponse"):
            # tool_result: Anthropic format  toolResponse: Goose JSON export format
            tool_id = block.get("tool_use_id") or block.get("id", "?")
            is_error = block.get("is_error", False) or block.get("toolResult", {}).get(
                "isError", False
            )
            label = "TOOL ERROR" if is_error else "TOOL RESULT"
            inner = block.get("content") or block.get("toolResult", {}).get(
                "value", {}
            ).get("content", "")

            if isinstance(inner, list):
                texts = [
                    i.get("text", "")
                    for i in inner
                    if isinstance(i, dict) and i.get("type") == "text"
                ]
                result_s = "\n".join(texts)
            elif isinstance(inner, dict):
                result_s = json.dumps(inner, indent=2)
            else:
                result_s = str(inner)

            result_s = (
                result_s.replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .strip()
            )

            lang = detect_lang(result_s) if result_s.startswith("#!") else ""
            fenced = fence(result_s, lang)
            n_lines = result_s.count("\n") + 1

            if collapse_results is not None and n_lines > collapse_results:
                # Show label + 3-line preview, then full content in <details>.
                # Skip blank lines for the preview so it's always meaningful.
                # Close any unclosed fences so </details> isn't swallowed.
                preview_lines = [ln for ln in result_s.splitlines() if ln.strip()][:3]
                preview = "\n".join(preview_lines)
                if n_lines > 3:
                    preview += "\n…"
                preview_fenced = fence(preview, lang)
                safe_fenced = fence(close_unclosed_fences(result_s), lang)
                parts.append(
                    f"**[{label} ← {tool_id}]**  *({n_lines} lines)*\n\n"
                    f"{preview_fenced}\n\n"
                    f"<details><summary>Show all {n_lines} lines…</summary>\n\n"
                    f"{safe_fenced}\n\n</details>"
                )
            else:
                parts.append(f"**[{label} ← {tool_id}]**\n{fenced}")

        elif btype == "thinking":
            if show_thinking:
                thinking = block.get("thinking", "").strip()
                if thinking:
                    thinking = strip_fences_from_thinking(thinking)
                    thinking = close_unclosed_fences(thinking)
                    parts.append(
                        f"<details><summary>💭 Thinking</summary>\n\n{thinking}\n\n*\u2014 end thinking \u2014*\n\n</details>"
                    )

        else:
            parts.append(
                f"**[{btype.upper()} BLOCK]**\n{fence(json.dumps(block, indent=2), 'json')}"
            )

    return "\n\n".join(p for p in parts if p)


def render_content(raw, collapse_results=None, show_thinking=False):
    """
    Render message content to markdown.
    Accepts either a JSON string (from SQLite) or a pre-parsed list (from JSON export).
    """
    if not raw:
        return ""
    if isinstance(raw, list):
        return render_blocks(
            raw, collapse_results=collapse_results, show_thinking=show_thinking
        )
    if isinstance(raw, str) and raw.strip().startswith(("[", "{")):
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                return render_blocks(
                    parsed,
                    collapse_results=collapse_results,
                    show_thinking=show_thinking,
                )
            if isinstance(parsed, str):
                return parsed.strip()
        except json.JSONDecodeError:
            pass
    return raw.strip()


# ── Tool call counting ────────────────────────────────────────────────────────


def count_tools(messages):
    """Count tool calls, handling both SQLite (content_json string) and JSON (content list) formats."""
    counts = {}
    for msg in messages:
        raw = msg.get("content_json") or msg.get("content") or ""
        if not raw:
            continue
        if isinstance(raw, str):
            try:
                blocks = json.loads(raw)
            except Exception:
                continue
        else:
            blocks = raw
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            if not isinstance(b, dict):
                continue
            btype = b.get("type", "")
            if btype == "tool_use":
                n = b.get("name", "unknown")
                counts[n] = counts.get(n, 0) + 1
            elif btype == "toolRequest":
                n = b.get("toolCall", {}).get("value", {}).get("name", "unknown")
                counts[n] = counts.get(n, 0) + 1
    return counts


# ── Session loaders ───────────────────────────────────────────────────────────


def load_session_from_db(con, session_id):
    """Load session and messages from SQLite database."""
    cur = con.cursor()
    cur.execute("SELECT * FROM sessions WHERE id = ?", (session_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(
            f"Session '{session_id}' not found. Run --list to see available sessions."
        )
    session = dict(zip([d[0] for d in cur.description], row))

    cur.execute(
        "SELECT * FROM messages WHERE session_id = ? ORDER BY id ASC", (session_id,)
    )
    rows = cur.fetchall()
    mcols = [d[0] for d in cur.description]
    messages = [dict(zip(mcols, r)) for r in rows]
    return session, messages


def load_session_from_json(json_path):
    """
    Load session and messages from a Goose JSON export file.
    Normalizes to the same dict structure as load_session_from_db so the
    rendering code is shared.
    """
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))

    mc = data.get("model_config") or {}
    session = {
        "name": data.get("name"),
        "description": data.get("description"),
        "created_at": data.get("created_at"),
        "updated_at": data.get("updated_at"),
        "working_dir": data.get("working_dir"),
        "provider_name": data.get("provider_name"),
        "goose_mode": data.get("goose_mode"),
        "accumulated_total_tokens": data.get("accumulated_total_tokens"),
        "accumulated_input_tokens": data.get("accumulated_input_tokens"),
        "accumulated_output_tokens": data.get("accumulated_output_tokens"),
        "total_tokens": data.get("total_tokens"),
        "input_tokens": data.get("input_tokens"),
        "output_tokens": data.get("output_tokens"),
        "_model_name": (
            mc.get("model_name") or mc.get("model_id") or mc.get("model") or ""
        ),
    }

    messages = []
    for msg in data.get("conversation", []):
        messages.append(
            {
                "role": msg.get("role", "?"),
                "content": msg.get("content", []),
                "tokens": msg.get("tokens"),
            }
        )

    return session, messages


# ── Core extract (shared by both DB and JSON paths) ───────────────────────────


def extract(
    session,
    messages,
    show_transcript=True,
    show_thinking=False,
    show_stats=True,
    out_file=None,
    collapse_results=None,
):
    lines = []

    # ── Header ────────────────────────────────────────────────────────────────
    name = session.get("name") or session.get("description") or "Session"
    lines += [
        f"# {name}",
        f"Created:      {fmt_ts(session.get('created_at'))}",
        f"Updated:      {fmt_ts(session.get('updated_at'))}",
    ]
    if session.get("working_dir"):
        lines.append(f"Working dir:  {session['working_dir']}")
    if session.get("provider_name"):
        lines.append(f"Provider:     {session['provider_name']}")

    model_name = session.get("_model_name", "")
    if not model_name and session.get("model_config_json"):
        try:
            mc = json.loads(session["model_config_json"])
            model_name = mc.get("model_id") or mc.get("model") or ""
        except Exception:
            pass
    if model_name:
        lines.append(f"Model:        {model_name}")

    if session.get("goose_mode"):
        lines.append(f"Mode:         {session['goose_mode']}")

    total = session.get("accumulated_total_tokens") or session.get("total_tokens")
    inp = session.get("accumulated_input_tokens") or session.get("input_tokens")
    out = session.get("accumulated_output_tokens") or session.get("output_tokens")
    if total:
        lines.append(f"Tokens:       {total:,}  (in {inp or 0:,}  out {out or 0:,})")

    lines.append(f"Messages:     {len(messages)}")

    tool_counts = count_tools(messages)
    if tool_counts:
        total_calls = sum(tool_counts.values())
        top = sorted(tool_counts.items(), key=lambda x: -x[1])[:5]
        top_str = ", ".join(f"{n}×{c}" for n, c in top)
        lines.append(f"Tool calls:   {total_calls}  ({top_str})")

    if collapse_results is not None:
        lines.append(f"Collapse threshold: tool results > {collapse_results} lines")

    lines.append("")

    # ── Transcript ────────────────────────────────────────────────────────────
    if show_transcript:
        for i, msg in enumerate(messages):
            role = msg.get("role", "?").upper()
            raw = msg.get("content_json") or msg.get("content") or ""
            rendered = render_content(
                raw, collapse_results=collapse_results, show_thinking=show_thinking
            )
            tok = msg.get("tokens")

            lines.append("\n---\n")
            hdr = f"**[{i + 1}] {role}**"
            if tok:
                hdr += f"  *(tokens: {tok:,})*"
            lines.append(hdr + "\n")
            if rendered:
                lines.append(rendered)
            lines.append("")

    # ── Stats ─────────────────────────────────────────────────────────────────
    if show_stats:
        tok_rows = [
            (i + 1, m["role"], m["tokens"])
            for i, m in enumerate(messages)
            if m.get("tokens")
        ]
        if tok_rows:
            lines.append("\n## Token Usage Per Message\n")
            lines.append("| Msg | Role | Tokens |")
            lines.append("|----:|------|-------:|")
            for idx, role, tok in tok_rows:
                lines.append(f"| {idx} | {role} | {tok:,} |")
            lines.append(f"\n**Session total:** {sum(t for _, _, t in tok_rows):,}")
            lines.append("")

        if tool_counts:
            lines.append("\n## Tool Call Breakdown\n")
            lines.append("| Tool | Calls |")
            lines.append("|------|------:|")
            for tname, count in sorted(tool_counts.items(), key=lambda x: -x[1]):
                lines.append(f"| {tname} | {count} |")
            lines.append("")

    output = "\n".join(lines)
    if out_file:
        Path(out_file).write_text(output, encoding="utf-8")
        print(f"Written to {out_file}")
    else:
        print(output)


def extract_from_db(
    session_id,
    show_transcript=True,
    show_thinking=False,
    show_stats=True,
    out_file=None,
    collapse_results=None,
    db_path=None,
):
    con = connect(db_path)
    try:
        session, messages = load_session_from_db(con, session_id)
    finally:
        con.close()
    extract(
        session,
        messages,
        show_transcript,
        show_thinking,
        show_stats,
        out_file,
        collapse_results,
    )


def extract_from_json(
    json_path,
    show_transcript=True,
    show_thinking=False,
    show_stats=True,
    out_file=None,
    collapse_results=None,
):
    session, messages = load_session_from_json(json_path)
    extract(
        session,
        messages,
        show_transcript,
        show_thinking,
        show_stats,
        out_file,
        collapse_results,
    )


# ── List sessions ─────────────────────────────────────────────────────────────


def list_sessions(n=None, db_path=None):
    con = connect(db_path)
    cur = con.cursor()
    cur.execute(
        "SELECT id, name, description, created_at, "
        "accumulated_total_tokens, total_tokens, provider_name, model_config_json "
        "FROM sessions ORDER BY created_at DESC" + (f" LIMIT {n}" if n else "")
    )
    rows = cur.fetchall()
    con.close()

    def trunc(s, n):
        return s if len(s) <= n else s[: n - 1] + "\u2026"

    print(f"{'Session ID':<17}  {'Created':<20}  {'Tokens':>10}  {'Model':<39}  Name")
    print("-" * 122)
    for sid, name, desc, created, acc_tok, tok, provider, mc_json in rows:
        label = trunc(name or desc or "(unnamed)", 28)
        tokens = acc_tok or tok
        tok_s = f"{tokens:,}" if tokens else "-"
        model = "-"
        if mc_json:
            try:
                mc = json.loads(mc_json)
                model = (
                    mc.get("model_id") or mc.get("model_name") or mc.get("model") or "-"
                )
            except Exception:
                pass
        print(
            f"{sid[:17]:<17}  {fmt_ts(created):<20}  {tok_s:>10}  {trunc(model, 39):<39}  {label}"
        )


# ── Schema dump ───────────────────────────────────────────────────────────────


def show_schema(db_path=None):
    db = get_db(db_path)
    print(f"Database: {db}\n")
    con = connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [r[0] for r in cur.fetchall()]

    for t in tables:
        cur.execute(f"PRAGMA table_info({t})")
        cols = cur.fetchall()
        cur.execute(f"SELECT COUNT(*) FROM {t}")
        count = cur.fetchone()[0]
        print(f"Table: {t}  ({count} rows)")
        for c in cols:
            print(f"  {c[1]:40} {c[2]}")

        if t == "messages" and count > 0:
            cur.execute(
                "SELECT role, content_json, tokens, metadata_json FROM messages LIMIT 2"
            )
            for role, raw, tok, meta in cur.fetchall():
                print(f"\n  Sample ({role}, tokens={tok}):")
                try:
                    blocks = json.loads(raw) if raw else []
                    if isinstance(blocks, list):
                        for b in blocks[:3]:
                            btype = b.get("type", "?") if isinstance(b, dict) else "?"
                            bkeys = list(b.keys()) if isinstance(b, dict) else []
                            print(f"    block type={btype!r:<15} keys={bkeys}")
                    else:
                        print(f"    (not a list) type={type(blocks).__name__}")
                except Exception:
                    print(f"    raw: {str(raw)[:120]}")
        print()

    con.close()


# ── Export all ────────────────────────────────────────────────────────────────


def export_all(
    out_dir,
    transcript=True,
    show_thinking=False,
    stats=True,
    collapse_results=None,
    db_path=None,
    n=None,
):
    con = connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT id FROM sessions ORDER BY created_at ASC")
    ids = [r[0] for r in cur.fetchall()]
    con.close()

    if n:
        ids = ids[-n:]  # most recent N, preserving chronological order

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for sid in ids:
        dest = out / f"{sid}.md"
        print(f"  {sid} → {dest}")
        try:
            extract_from_db(
                sid,
                show_transcript=transcript,
                show_thinking=show_thinking,
                show_stats=stats,
                out_file=str(dest),
                collapse_results=collapse_results,
                db_path=db_path,
            )
        except Exception as e:
            print(f"    ERROR: {e}")
    label = f"{len(ids)} most recent" if n else str(len(ids))
    print(f"\nDone. {label} sessions exported to {out}/")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Extract Goose session transcripts and stats"
    )
    src = ap.add_mutually_exclusive_group()
    src.add_argument(
        "session_id",
        nargs="?",
        help="Session ID or unique substring — run --list to see them",
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
        "--show-thinking",
        action="store_true",
        help="Include thinking blocks in transcript",
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
    ap.add_argument("--out", metavar="FILE", help="Write to FILE instead of stdout")
    src.add_argument(
        "--all",
        action="store_true",
        help="Export all sessions (combine with -n to limit)",
    )
    ap.add_argument("--out-dir", metavar="DIR", help="Output directory for --all")
    src.add_argument(
        "--schema",
        action="store_true",
        help="Show DB schema + sample content block structure",
    )
    src.add_argument("--json", metavar="FILE", help="Goose JSON export file")
    ap.add_argument(
        "--db",
        metavar="FILE",
        help="Override default sessions.db location (also via GOOSE_DB env var)",
    )
    args = ap.parse_args()

    show_t = not args.stats_only
    show_s = not args.transcript_only
    collapse = args.collapse_results

    db = args.db

    if args.schema:
        show_schema(db_path=db)
    elif args.list:
        list_sessions(n=args.n, db_path=db)
    elif args.all:
        export_all(
            args.out_dir or "./goose_transcripts",
            transcript=show_t,
            show_thinking=args.show_thinking,
            stats=show_s,
            collapse_results=collapse,
            db_path=db,
            n=args.n,
        )
    elif args.json:
        extract_from_json(
            args.json,
            show_transcript=show_t,
            show_thinking=args.show_thinking,
            show_stats=show_s,
            out_file=args.out,
            collapse_results=collapse,
        )
    elif args.session_id:
        extract_from_db(
            args.session_id,
            show_transcript=show_t,
            show_thinking=args.show_thinking,
            show_stats=show_s,
            out_file=args.out,
            collapse_results=collapse,
            db_path=db,
        )
    else:
        ap.print_help()
