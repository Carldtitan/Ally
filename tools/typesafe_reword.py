"""Does a reworded gate question accept a real recording?

The shipped question asks whether the recording "describes a fully rendered
page". That phrasing rejected all four real recordings of the clean app at
0.96-0.99 confidence, and it flips the synthetic control from yes to no purely
by truncating it to nine stops. A nine-element page is short by nature, not by
fault, so "fully rendered" is asking the wrong thing.

This asks only about internal consistency of the positions, which is the thing
we actually need to know before deriving reading order from them.

Condition for keeping TypeSafe: the reworded question accepts the real
recordings AND still rejects the three unjudgeable ones. Anything less and we
cut it and say we tested it.

Usage:  python tools/typesafe_reword.py
"""

from __future__ import annotations

import os
import sys
import json
import time
import pathlib
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env
import typesafe_gate as G

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

KEY = os.environ["TYPESAFE_API_KEY"]
URL = "https://api.typesafe.ai/v1/systemone"

# Reworded. No mention of rendering, completeness, or how much was reached --
# only whether the coordinates can all be true of one page at one moment.
QUESTIONS = {
    "consistent": {
        "type": "choice",
        "instructions": (
            "Each row is one element the keyboard reached, with where it sits on the page. "
            "We are about to derive reading order from these positions. Are the positions "
            "internally consistent, meaning they could all be true of a single page laid out "
            "at one moment?"
        ),
        "criteria": {
            "yes": "Each element has a plausible distinct position and the set describes one "
                   "coherent layout. The number of elements does not matter; a short list is "
                   "fine if the positions are sound.",
            "no": "The positions contradict each other. Elements stacked at the origin with no "
                  "size, or every element crammed into one small region, or the same element "
                  "recurring at incompatible coordinates.",
        },
    },
}


def ask(state: str) -> dict:
    req = urllib.request.Request(
        URL,
        data=json.dumps({"state": state, "model": "jev-latest",
                         "questions": QUESTIONS}).encode(),
        headers={"Authorization": f"Bearer {KEY}", "Content-Type": "application/json",
                 "User-Agent": "ally-probe/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def render(stops: list[dict]) -> str:
    rows = [f"  {i+1:2d}. <{s['tag']}> name={s['name']!r} x={s['x']} y={s['y']} "
            f"w={s['w']} h={s['h']}" for i, s in enumerate(stops)]
    return ("Elements reached by pressing Tab, in order, with their position on the "
            "page in CSS pixels.\n\n" + "\n".join(rows))


rec = json.loads(pathlib.Path("artifacts/real-recording.json").read_text(encoding="utf-8"))


def real(state: str) -> list[dict]:
    return [{"tag": s["tag"], "name": s["name"] or "", "x": s["x"], "y": s["y"],
             "w": s["w"], "h": s["h"]}
            for s in rec[state]["stops"] if s["tag"] != "BODY"]


CASES = [
    # The four that matter. These are real recordings of a page with no defects.
    ("REAL loaded",                 real("loaded"),        "yes"),
    ("REAL dialog-open",            real("dialog-open"),   "yes"),
    ("REAL menu-open",              real("menu-open"),     "yes"),
    ("REAL tabs-focused",           real("tabs-focused"),  "yes"),
    # Length must not decide the verdict.
    ("synthetic GOOD, 36 stops",    G.GOOD,                "yes"),
    ("synthetic GOOD, first 9",     G.GOOD[:9],            "yes"),
    # The three it must still reject.
    ("1. not finished rendering",   G.HALF_LOADED,         "no"),
    ("2. inside unopened dialog",   G.DIALOG,              "no"),
    ("3. layout shifted mid-run",   G.SHIFTED,             "no"),
]

print(f"{'case':30s} {'n':>3s} {'gate':>5s} {'conf':>6s} {'expect':>7s}  verdict")
print("-" * 74)
reals_ok = bads_ok = 0
for label, stops, expect in CASES:
    if not stops:
        continue
    t0 = time.perf_counter()
    a = ask(render(stops))
    g = a["answers"]["consistent"]
    ok = g["choice"] == expect
    if expect == "yes" and label.startswith("REAL") and ok:
        reals_ok += 1
    if expect == "no" and ok:
        bads_ok += 1
    print(f"{label:30s} {len(stops):3d} {g['choice']:>5s} {g['confidence']:6.2f} "
          f"{expect:>7s}  {'OK' if ok else 'WRONG'}  ({time.perf_counter()-t0:.2f}s)")

print("-" * 74)
print(f"real recordings accepted: {reals_ok}/4      unjudgeable still rejected: {bads_ok}/3")
print("\nDECISION")
if reals_ok == 4 and bads_ok == 3:
    print("  KEEP TypeSafe. The reworded question accepts real pages and still")
    print("  rejects the three unjudgeable recordings.")
elif reals_ok == 4:
    print("  PARTIAL. Real pages accepted but it no longer rejects everything it should.")
    print("  A gate that accepts unjudgeable recordings is worse than no gate.")
else:
    print("  CUT TypeSafe. It still rejects real recordings of a page with no defects.")
    print("  Record that we tested it and what it did.")
