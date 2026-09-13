"""The test that decides whether TypeSafe stays.

Three recordings that pass every count our own code can do -- 40 stops, all
fields populated -- but are still not judgeable. Plus two controls.

FAIRNESS RULE: the reason a recording is unjudgeable is never stated in prose.
It has to be inferable from the shape of the data, because that is all our
recorder would hand over. Writing "the page had not finished loading" into the
state would test nothing except whether the model can read English.

If the gate says NO to the three ambiguous cases and YES to the good one,
TypeSafe catches what our code cannot and the two-model split is real.
If it says YES to everything, or NO to everything, we cut it.
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

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

KEY = os.environ["TYPESAFE_API_KEY"]
URL = "https://api.typesafe.ai/v1/systemone"

QUESTIONS = {
    "judgeable": {
        "type": "choice",
        "instructions": (
            "This is a recording of which elements the keyboard reached, in order, on a web "
            "page. It will be used to decide whether the tab order matches the order a sighted "
            "person would read the page. Is this recording trustworthy enough to make that "
            "judgement?"
        ),
        "criteria": {
            "yes": "The recording describes a fully rendered page and the positions look "
                   "consistent, so tab order can be compared against reading order",
            "no": "The recording cannot support that judgement, because the page was not "
                  "fully rendered, only part of it was reachable, or the positions are not "
                  "internally consistent",
        },
    },
    "trustworthy": {
        "type": "noul",
        "instructions": "The recorded positions describe a stable, fully rendered page",
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
        return json.loads(r.read().decode()) | {"_s": time.perf_counter() - t0}


def render(stops: list[dict]) -> str:
    rows = [f"  {i+1:2d}. <{s['tag']}> name={s['name']!r} x={s['x']} y={s['y']} "
            f"w={s['w']} h={s['h']}" for i, s in enumerate(stops)]
    return ("Elements reached by pressing Tab, in order. Coordinates are CSS pixels "
            "in the 1024x740 viewport.\n\n" + "\n".join(rows))


def stop(tag, name, x, y, w=90, h=32):
    return {"tag": tag, "name": name, "x": x, "y": y, "w": w, "h": h}


# --- CONTROL: a real, fully rendered page. Should be judgeable. ------------
GOOD = [stop("A", "Skip to content", 20, 12, 120, 20)]
GOOD += [stop("A", n, 20 + i * 110, 60) for i, n in
         enumerate(["Home", "Products", "Services", "Pricing", "About", "Contact"])]
GOOD += [stop("INPUT", "Search products", 20, 130, 260, 36),
         stop("BUTTON", "Search", 300, 130, 80, 36)]
for row in range(8):
    y = 200 + row * 64
    GOOD += [stop("A", f"Product {row+1}", 20, y, 200, 24),
             stop("BUTTON", f"Add {row+1} to cart", 260, y, 110, 30),
             stop("BUTTON", f"Save {row+1}", 390, y, 80, 30)]
GOOD += [stop("A", "Privacy", 20, 712, 70, 20),
         stop("A", "Terms", 110, 712, 60, 20),
         stop("A", "Back to top", 190, 712, 100, 20)]
GOOD = GOOD[:40]

# --- 1. Page had not finished rendering when the run started --------------
# Signal in the data: most stops are unnamed DIVs stacked at the origin with
# zero size -- what a half-built DOM looks like mid-hydration.
HALF_LOADED = [stop("A", "Skip to content", 20, 12, 120, 20),
               stop("BUTTON", "Menu", 950, 20, 40, 40)]
HALF_LOADED += [stop("DIV", "", 0, 0, 0, 0) for _ in range(30)]
HALF_LOADED += [stop("A", "", 0, 0, 0, 0) for _ in range(8)]
HALF_LOADED = HALF_LOADED[:40]

# --- 2. Everything reached sits inside a dialog that never opened ----------
# Signal: all 40 stops are crammed into one 300x200 region mid-viewport, with
# sequential generated names, and none of the page's own chrome appears.
DIALOG = [stop("BUTTON", f"Option {i+1}", 362 + (i % 3) * 90, 280 + (i // 3) * 14, 84, 12)
          for i in range(40)]

# --- 3. Layout shifted mid-run, so positions are mutually inconsistent -----
# Signal: the same named elements recur at incompatible coordinates, and y
# values jump backwards and forwards across the full page height.
SHIFTED = []
names = ["Home", "Products", "Search", "Add to cart", "Privacy"]
for i in range(40):
    n = names[i % 5]
    y = (37 * i) % 720          # no stable banding
    x = (211 * i) % 900
    SHIFTED.append(stop("A" if i % 2 else "BUTTON", n, x, y))

# --- CONTROL: empty. Our own code handles this in one line. ---------------
EMPTY: list[dict] = []

CASES = [
    ("CONTROL  fully rendered page", GOOD, "yes"),
    ("1. page not finished rendering", HALF_LOADED, "no"),
    ("2. all stops inside unopened dialog", DIALOG, "no"),
    ("3. layout shifted mid-run", SHIFTED, "no"),
    ("CONTROL  empty recording", EMPTY, "no"),
]

if __name__ == "__main__":
    print(f"{'case':38s} {'stops':>5s} {'gate':>5s} {'conf':>5s} {'noul':>5s} {'expect':>7s}  verdict")
    print("-" * 100)
    score = 0
    for label, stops, expect in CASES:
        state = render(stops) if stops else "No elements were reached. The recording is empty."
        a = ask(state)
        g = a["answers"]["judgeable"]
        got = g["choice"]
        ok = got == expect
        score += ok
        print(f"{label:38s} {len(stops):5d} {got:>5s} {g['confidence']:5.2f} "
              f"{a['answers']['trustworthy']['noul']:5.2f} {expect:>7s}  {'OK' if ok else 'WRONG'}")

    print("-" * 100)
    print(f"gate agreed with the expected answer on {score}/5 cases")
    amb = CASES[1:4]
    print("\nDECISION")
    if score == 5:
        print("  KEEP. The gate separates unjudgeable recordings our own counts would pass.")
    elif score >= 4:
        print("  KEEP, with the failing case handled in code. Mostly discriminating.")
    else:
        print("  CUT. The gate is not separating these, so it duplicates a one-line check.")
