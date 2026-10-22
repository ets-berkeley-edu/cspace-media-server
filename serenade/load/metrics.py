"""Prints one service's CPU or memory figures for a replay (./serena aws replay, D287): CloudWatch's
get-metric-statistics answer on standard input, one line out.

    python -m serenade.load.metrics "web CPU" < answer.json"""
from __future__ import annotations

import json
import sys


def line(name: str, answer: dict[str, list[dict[str, float]]]) -> str:
    points = answer.get("Datapoints", [])
    if not points:
        return f"  {name:<14} no figures yet: look again in a few minutes in CloudWatch"
    average = sum(p["Average"] for p in points) / len(points)
    return (f"  {name:<14} average {average:5.1f}  busiest minute {max(p['Average'] for p in points):5.1f}  "
            f"highest {max(p['Maximum'] for p in points):5.1f}  ({len(points)} minutes)")


if __name__ == "__main__":
    print(line(sys.argv[1], json.load(sys.stdin)))
