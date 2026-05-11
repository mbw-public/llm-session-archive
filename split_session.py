#!/usr/bin/env python3
"""
Split a session markdown file into chunks of N turns each (default 75).
Usage: python3 split_session.py session-monroe.md
       python3 split_session.py session-monroe.md --turns 25
Output: session-monroe-0001-0075.md, session-monroe-0076-0150.md, ...
"""

import re
import sys
import argparse
from pathlib import Path

TURN_RE = re.compile(r"^\*\*\[(\d+)\] (USER|ASSISTANT)\*\*")


def split_session(src: Path, turns_per_file: int = 75):
    lines = src.read_text().splitlines(keepends=True)

    # Collect (line_index, turn_number) for every turn header
    boundaries = []
    for i, line in enumerate(lines):
        m = TURN_RE.match(line)
        if m:
            boundaries.append((i, int(m.group(1))))

    if not boundaries:
        print("No turn markers found.")
        return

    total_turns = len(boundaries)
    print(f"{total_turns} turns found across {len(lines)} lines")

    stem = src.stem  # e.g. "session-monroe"
    out_dir = src.parent

    chunk_start = 0  # index into boundaries[]
    file_num = 1

    while chunk_start < total_turns:
        chunk_end = min(chunk_start + turns_per_file, total_turns)

        first_turn = boundaries[chunk_start][1]
        last_turn = boundaries[chunk_end - 1][1]

        line_start = boundaries[chunk_start][0]
        line_end = boundaries[chunk_end][0] if chunk_end < total_turns else len(lines)

        out_name = out_dir / f"{stem}-{first_turn:04d}-{last_turn:04d}.md"
        out_name.write_text("".join(lines[line_start:line_end]))
        print(
            f"  {out_name.name}  (turns {first_turn}–{last_turn}, lines {line_start + 1}–{line_end})"
        )

        chunk_start = chunk_end
        file_num += 1


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Split a session markdown file into chunks"
    )
    ap.add_argument(
        "file", nargs="?", default="session-monroe.md", help="Session markdown file"
    )
    ap.add_argument(
        "--turns", type=int, default=75, help="Turns per chunk (default: 75)"
    )
    args = ap.parse_args()
    split_session(Path(args.file), turns_per_file=args.turns)
