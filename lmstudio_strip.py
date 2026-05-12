#!/usr/bin/env python3
"""
lmstudio_strip.py — Remove redundant predictionConfig from every genInfo step.
Keeps stats, loadModelConfig, and all conversation content intact.
Extracts one copy of the predictionConfig to the top level for reference.

Usage:
    python3 lmstudio_strip.py Qwen.json Qwen_stripped.json
    python3 lmstudio_strip.py Qwen.json > Qwen_stripped.json
"""

import json
import io
import os
import sys
import argparse


def strip(src, dst=None):
    with open(src) as f:
        d = json.load(f)

    saved_prediction_config = None

    for msg in d.get("messages", []):
        for ver in msg.get("versions", []):
            for step in ver.get("steps", []):
                gi = step.get("genInfo")
                if not gi:
                    continue
                pc = gi.pop("predictionConfig", None)
                if pc and saved_prediction_config is None:
                    saved_prediction_config = pc

    if saved_prediction_config:
        d["_predictionConfig"] = saved_prediction_config

    if dst:
        with open(dst, "w") as f:
            json.dump(d, f, indent=2)
        dst_size = os.path.getsize(dst)
    else:
        buf = io.StringIO()
        json.dump(d, buf, indent=2)
        output = buf.getvalue()
        sys.stdout.write(output)
        dst_size = len(output.encode())

    src_size = os.path.getsize(src)
    print(f"Before: {src_size / 1024:.0f} KB", file=sys.stderr)
    print(f"After:  {dst_size / 1024:.0f} KB", file=sys.stderr)
    print(
        f"Saved:  {(src_size - dst_size) / 1024:.0f} KB  ({100 * (src_size - dst_size) / src_size:.0f}%)",
        file=sys.stderr,
    )


if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Strip redundant predictionConfig blocks from an LM Studio .json log"
    )
    ap.add_argument("input", nargs="?", help="Input LM Studio .json file")
    ap.add_argument(
        "output", nargs="?", default=None, help="Output .json file (default: stdout)"
    )
    args = ap.parse_args()

    if not args.input:
        ap.print_help()
        sys.exit(0)

    strip(args.input, args.output)
