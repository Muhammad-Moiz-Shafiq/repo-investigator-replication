# ruff: noqa: E501
"""Print one run's Langfuse trace: every model call and tool call, in order.

Uses the observations API (api.observations.get_many), the one that works for
our account; the old single-trace API was never available to it. fields="core,basic,io,usage"
is needed, or inputs and outputs are left out.

Usage:
  uv run --env-file .env python scripts/study/read_trace.py TRACE_ID [--full]
"""

import json
import sys

from langfuse import Langfuse


def main():
    trace_id, full = sys.argv[1], "--full" in sys.argv
    res = Langfuse().api.observations.get_many(trace_id=trace_id, fields="core,basic,io,usage", limit=100)
    rows = sorted(res.data, key=lambda o: str(o.start_time))
    for o in rows:
        cost = getattr(o, "cost_details", None) or {}
        print(f"\n[{o.type}] {o.name}  {o.start_time}  cost={cost.get('total')}")
        for label, value in (("in", o.input), ("out", o.output)):
            if value is None or (o.type == "GENERATION" and label == "in" and not full):
                continue
            text = json.dumps(value, default=str) if not isinstance(value, str) else value
            print(f"  {label}: {text if full else text[:600]}")


if __name__ == "__main__":
    main()
