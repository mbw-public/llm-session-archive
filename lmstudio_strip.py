#!/usr/bin/env python3
"""
lmstudio_strip.py — Remove redundant predictionConfig from every genInfo step.
Keeps stats, loadModelConfig, and all conversation content intact.
Extracts one copy of the predictionConfig to the top level for reference.

Usage:
    python3 lmstudio_strip.py Qwen.json Qwen_stripped.json
"""

import json
import sys


def strip(src, dst):
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

    with open(dst, "w") as f:
        json.dump(d, f, indent=2)

    src_size = __import__("os").path.getsize(src)
    dst_size = __import__("os").path.getsize(dst)
    print(f"Before: {src_size / 1024:.0f} KB")
    print(f"After:  {dst_size / 1024:.0f} KB")
    print(
        f"Saved:  {(src_size - dst_size) / 1024:.0f} KB  ({100 * (src_size - dst_size) / src_size:.0f}%)"
    )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: lmstudio_strip.py input.json output.json")
        sys.exit(1)
    strip(sys.argv[1], sys.argv[2])
