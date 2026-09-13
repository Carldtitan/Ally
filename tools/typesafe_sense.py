"""Does Jev actually discriminate good focus order from bad?

Shape-correctness is not usefulness. This feeds matched pairs where only the
ordering differs and checks whether the answers move. If a clean order and a
scrambled order score the same, the model is not measuring what we need.
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

QUESTIONS = {
    "matches": {
        "type": "noul",
        "instructions": "The order the keyboard reached these elements matches the order a "
                        "sighted person would read them, which is top to bottom then left to right",
    },
    "severity": {
        "type": "choice",
        "instructions": "How serious is the focus order problem on this page",
        "criteria": {
            "none": "Tab order matches reading order; a keyboard user is not disadvantaged",
            "minor": "Order differs from reading order but a user could still cope",
            "major": "Order jumps unpredictably and would disorient a keyboard user",
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
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode()) | {"_secs": time.perf_counter() - t0}


def render(stops: list[dict]) -> str:
    lines = [f"  {i + 1}. <{s['tag']}> {s['name']!r} at x={s['x']} y={s['y']}"
             for i, s in enumerate(stops)]
    return ("Elements in the order the keyboard reached them (Tab pressed repeatedly).\n"
            "Coordinates are the element's position on screen in CSS pixels.\n\n"
            + "\n".join(lines))


# A clean page: eight controls, reading order top-to-bottom, left-to-right.
CLEAN = [
    {"tag": "A", "name": "Skip to content", "x": 20, "y": 12},
    {"tag": "A", "name": "Home", "x": 20, "y": 60},
    {"tag": "A", "name": "Products", "x": 120, "y": 60},
    {"tag": "A", "name": "About", "x": 230, "y": 60},
    {"tag": "INPUT", "name": "Search", "x": 20, "y": 130},
    {"tag": "BUTTON", "name": "Go", "x": 300, "y": 130},
    {"tag": "A", "name": "First result", "x": 20, "y": 220},
    {"tag": "BUTTON", "name": "Add to cart", "x": 20, "y": 300},
]

# Same page, one element yanked to the front with tabindex="5" (the planted 2.4.3 defect)
TABINDEX = [CLEAN[6]] + [s for i, s in enumerate(CLEAN) if i != 6]

# Same page, visually reordered with CSS `order` so DOM order no longer matches layout
CSS_ORDER = [CLEAN[3], CLEAN[1], CLEAN[2], CLEAN[0], CLEAN[5], CLEAN[4], CLEAN[7], CLEAN[6]]

# Deliberately chaotic: focus ping-pongs top to bottom repeatedly
CHAOS = [CLEAN[7], CLEAN[0], CLEAN[6], CLEAN[1], CLEAN[5], CLEAN[2], CLEAN[4], CLEAN[3]]

CASES = [
    ("CLEAN     (should be none / high noul)", CLEAN),
    ("TABINDEX=5 defect (should be minor-major)", TABINDEX),
    ("CSS order defect  (should be minor-major)", CSS_ORDER),
    ("CHAOS     (should be major / low noul)", CHAOS),
]

if __name__ == "__main__":
    print(f"{'case':44s} {'noul':>6s} {'severity':>10s} {'conf':>6s}  probabilities")
    print("-" * 104)
    rows = []
    for label, stops in CASES:
        a = ask(render(stops))
        ans = a["answers"]
        noul = ans["matches"]["noul"]
        sev = ans["severity"]["choice"]
        conf = ans["severity"]["confidence"]
        probs = ans["severity"]["probabilities"]
        rows.append((label, noul, sev, conf))
        print(f"{label:44s} {noul:6.2f} {sev:>10s} {conf:6.2f}  "
              f"{ {k: round(v, 2) for k, v in probs.items()} }")

    print("\n--- does it discriminate? ---")
    clean_noul = rows[0][1]
    worst_noul = min(r[1] for r in rows[1:])
    print(f"clean noul={clean_noul:.2f}   worst-defect noul={worst_noul:.2f}   "
          f"spread={clean_noul - worst_noul:+.2f}")
    if rows[0][2] != "none":
        print("WARNING: the clean page was not judged 'none'. That is a false positive on the "
              "one case where the correct answer is certain.")
    if clean_noul - worst_noul < 0.25:
        print("WARNING: clean and broken score within 0.25. The signal does not separate them.")
