"""Head-to-head: which GA W&B Inference model should judge 2.4.3 Focus Order?

The original test used Qwen/Qwen3-30B-A3B-Instruct-2507, which W&B lists as
deprecated. This re-runs the same four fixtures across generally available
models and scores them on the three things that decide it:

  correctness  - 4/4 on clean vs three broken orderings
  union        - a 'failed' verdict MUST carry evidence_refs (rule 5.2)
  latency      - per call, warm
"""

from __future__ import annotations

import os
import sys
import json
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env
from typesafe_sense import CASES, render  # identical fixtures

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

# W&B lists these as generally available (deprecated ones excluded deliberately).
MODELS = [
    "openai/gpt-oss-120b",
    "zai-org/GLM-5.3-Flash",
    "Qwen/Qwen3.8-27B",
    "meta-llama/Llama-3.3-70B-Instruct",
]

SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["passed", "failed", "not_evaluated"]},
        "evidence_refs": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["status"],
    "additionalProperties": False,
}

PROMPT = (
    "You judge WCAG 2.4.3 Focus Order. Given the tab stops below, decide whether the "
    "keyboard order matches the visual reading order (top to bottom, then left to right).\n"
    "Reply as JSON only: {\"status\": \"passed\"} if it matches, "
    "{\"status\": \"failed\", \"evidence_refs\": [\"stop 3\", ...]} if it does not, "
    "or {\"status\": \"not_evaluated\", \"reason\": \"...\"} if you cannot tell.\n\n"
)

EXPECTED = ["passed", "failed", "failed", "failed"]

client = wb_env.openai_client()
print(f"{'model':36s} {'correct':>8s} {'union':>7s} {'warm s':>7s} {'tok':>6s}  verdicts")
print("-" * 104)

for model in MODELS:
    verdicts, times, toks, union_ok = [], [], 0, True
    for (label, stops), expect in zip(CASES, EXPECTED):
        try:
            t0 = time.perf_counter()
            r = client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": PROMPT + render(stops)}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": "Result", "schema": SCHEMA}},
                max_tokens=3000,
            )
            times.append(time.perf_counter() - t0)
            toks += r.usage.total_tokens if r.usage else 0
            obj = json.loads((r.choices[0].message.content or "").strip())
            st = obj.get("status", "?")
            verdicts.append(st)
            if st == "failed" and not obj.get("evidence_refs"):
                union_ok = False
            if st == "not_evaluated" and not obj.get("reason"):
                union_ok = False
        except Exception as exc:
            verdicts.append(f"ERR:{type(exc).__name__}")
            times.append(float("nan"))

    correct = sum(1 for v, e in zip(verdicts, EXPECTED) if v == e)
    warm = sorted(t for t in times[1:] if t == t)
    warm_s = (sum(warm) / len(warm)) if warm else float("nan")
    print(f"{model:36s} {correct}/4{'':>5s} {'OK' if union_ok else 'VIOLATED':>7s} "
          f"{warm_s:7.2f} {toks:6d}  {','.join(verdicts)}")
