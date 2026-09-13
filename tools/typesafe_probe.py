"""Empirical probe of the TypeSafe System One API (Jev) for Ally.

Answers, by calling the API rather than reading docs:
  1. how the output shape is specified
  2. whether an OpenAI-shaped request works
  3. the raw response body
  4. what an unanswerable question returns
  5. whether a discriminated union can be enforced
  6. rate limits and their error shape
  7. latency on 40 tab stops
  8. whether the answers on the real job are sensible

Usage:  python tools/typesafe_probe.py
"""

from __future__ import annotations

import os
import sys
import json
import time
import pathlib
import urllib.error
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

KEY = os.environ["TYPESAFE_API_KEY"]
URL = "https://api.typesafe.ai/v1/systemone"


def call(body: dict, url: str = URL) -> tuple[int, str, float]:
    """POST and return (status, raw body text, seconds). Never parses."""
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {KEY}",
            "Content-Type": "application/json",
            "User-Agent": "ally-probe/1.0",
        },
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, r.read().decode(), time.perf_counter() - t0
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), time.perf_counter() - t0
    except Exception as e:
        return -1, f"{type(e).__name__}: {e}", time.perf_counter() - t0


def show(title: str, status: int, raw: str, secs: float, limit: int = 1100) -> None:
    print(f"\n{'=' * 72}\n{title}\n{'=' * 72}")
    print(f"HTTP {status}   {secs:.2f}s   {len(raw)} bytes")
    print("--- RAW BODY ---")
    print(raw[:limit] + ("\n...[truncated]" if len(raw) > limit else ""))


# --------------------------------------------------------------- 1 & 3
TAB_STOPS_SMALL = [
    {"n": 1, "tag": "A", "name": "Logo", "x": 24, "y": 24},
    {"n": 2, "tag": "A", "name": "", "x": 897, "y": 30},
    {"n": 3, "tag": "BUTTON", "name": "Menu", "x": 945, "y": 24},
    {"n": 4, "tag": "INPUT", "name": "", "x": 24, "y": 82},
]
state = ("Tab stops recorded on a page, in the order the keyboard reached them:\n"
         + json.dumps(TAB_STOPS_SMALL, indent=1))

s, raw, t = call({
    "state": state,
    "model": "jev-latest",
    "questions": {
        "order_sensible": {
            "type": "noul",
            "instructions": "The tab order follows the visual reading order of the page",
        },
        "severity": {
            "type": "choice",
            "instructions": "How serious is any focus-order problem here",
            "criteria": {
                "none": "Tab order matches reading order",
                "minor": "Order differs but a user could still cope",
                "major": "Order jumps around and would confuse a keyboard user",
            },
        },
    },
})
show("1+3. Baseline call - how output shape is specified, and the raw body", s, raw, t)

# ------------------------------------------------------------------- 2
s2, raw2, t2 = call({
    "model": "jev-latest",
    "messages": [{"role": "user", "content": "Is the sky blue?"}],
}, url="https://api.typesafe.ai/v1/chat/completions")
show("2. OpenAI-shaped request to /v1/chat/completions", s2, raw2, t2, limit=500)

s2b, raw2b, t2b = call({
    "model": "jev-latest",
    "messages": [{"role": "user", "content": "Is the sky blue?"}],
})
show("2b. OpenAI-shaped body sent to /v1/systemone", s2b, raw2b, t2b, limit=500)

# ------------------------------------------------------------------- 4
s4, raw4, t4 = call({
    "state": "The page recording is empty. No keys were pressed and no elements were captured.",
    "model": "jev-latest",
    "questions": {
        "order_sensible": {
            "type": "noul",
            "instructions": "The tab order follows the visual reading order of the page",
        },
        "evaluable": {
            "type": "choice",
            "instructions": "Is there enough evidence in the state to judge focus order at all",
            "criteria": {
                "yes": "The state contains a recorded tab sequence",
                "no": "The state contains no tab sequence, so focus order cannot be judged",
            },
        },
    },
})
show("4. Unanswerable question - is a not_evaluated branch reachable?", s4, raw4, t4)

# ------------------------------------------------------------------- 5
s5, raw5, t5 = call({
    "state": state,
    "model": "jev-latest",
    "questions": {
        "verdict": {
            "type": "choice",
            "instructions": "Verdict for WCAG 2.4.3 Focus Order on this recording",
            "criteria": {
                "passed": "Tab order matches reading order",
                "failed": "Tab order does not match reading order",
                "not_evaluated": "There is not enough evidence to decide",
            },
        },
    },
    "response_format": {
        "type": "json_schema",
        "json_schema": {
            "name": "Result",
            "schema": {
                "oneOf": [
                    {"properties": {"status": {"const": "passed"}}, "required": ["status"]},
                    {"properties": {"status": {"const": "failed"},
                                    "evidence_refs": {"type": "array", "items": {"type": "string"}}},
                     "required": ["status", "evidence_refs"]},
                    {"properties": {"status": {"const": "not_evaluated"},
                                    "reason": {"type": "string"}},
                     "required": ["status", "reason"]},
                ]
            },
        },
    },
})
show("5. Discriminated union - does it accept a JSON schema / oneOf?", s5, raw5, t5)

# ------------------------------------------------------------------- 7
forty = [
    {"n": i,
     "tag": ["A", "BUTTON", "INPUT", "SELECT"][i % 4],
     "name": f"Control {i}",
     "x": (i * 37) % 960,
     "y": 60 + (i * 23) % 640}
    for i in range(1, 41)
]
s7, raw7, t7 = call({
    "state": "Forty tab stops:\n" + json.dumps(forty),
    "model": "jev-latest",
    "questions": {
        "order_sensible": {"type": "noul",
                           "instructions": "The tab order follows the visual reading order"},
        "has_trap": {"type": "noul",
                     "instructions": "Focus repeats on the same element, indicating a keyboard trap"},
        "severity": {"type": "choice",
                     "instructions": "Severity of any focus order problem",
                     "criteria": {"none": "matches", "minor": "differs slightly",
                                  "major": "jumps around badly"}},
    },
})
show("7. Latency on 40 tab stops (3 questions)", s7, raw7, t7, limit=900)

# ------------------------------------------------------------------- 6
print(f"\n{'=' * 72}\n6. Rate limits - 12 rapid calls\n{'=' * 72}")
codes = []
for i in range(12):
    sc, rb, tt = call({"state": "ping", "model": "jev-latest",
                       "questions": {"q": {"type": "noul", "instructions": "This is a test"}}})
    codes.append(sc)
    if sc != 200:
        print(f"  call {i + 1}: HTTP {sc} in {tt:.2f}s\n  RAW: {rb[:300]}")
        break
    print(f"  call {i + 1}: {sc} ({tt:.2f}s)", flush=True)
print("  status codes:", codes)
