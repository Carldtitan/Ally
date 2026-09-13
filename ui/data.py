"""Every number the UI shows, read from artifacts on disk. Nothing is computed here.

The screens used to be empty on purpose, because a benchmark screen showing a
figure nothing measured is worse than one that says it has nothing yet. The runs
exist now, so this reads them.

One rule: if a number is not in an artifact, this module does not invent it. A
missing artifact makes a row read "not run", never zero.
"""

from __future__ import annotations

import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
ART = ROOT / "artifacts"
CRITERIA = ["2.1.1", "2.1.2", "2.4.3", "2.4.7", "2.4.11"]
PAGE_OF = {"2.1.1": "2-1-1", "2.1.2": "2-1-2", "2.4.3": "2-4-3",
           "2.4.7": "2-4-7", "2.4.11": "2-4-11"}
ENTITY_PROJECT = "carldtytan-minerva-university/ally"
WEAVE_URL = f"https://wandb.ai/{ENTITY_PROJECT}/weave"


def _load(name: str) -> dict | None:
    p = ART / f"{name}.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


# --------------------------------------------------------------------------
# The fixture benchmark: 15 defects, five criteria, three instances each
# --------------------------------------------------------------------------

#: What changed between each run and the one before it. A delta with no cause
#: attached means nothing, and neither of these two deltas was the checks
#: getting better, which is the part worth saying out loud.
CHANGED = {
    "baseline5": ("First recorded. The 2.4.11 fixture had just been corrected so "
                  "each cover sits over a single control rather than a container."),
    "baseline6": ("The scorer changed, not the checks. Matching moved from "
                  "selector strings to element identity collected from the DOM, "
                  "with an ancestor counting as a match. Six of the seven new "
                  "finds were already being detected and could not be matched; "
                  "the seventh came from replacing a 2.4.3 fixture that was "
                  "unobservable by construction. No part of this delta is a "
                  "detection improvement."),
    "ikea-before": ("First recorded. Run before Stage 4 deliberately: if "
                    "precision collapsed on a page nobody built for us, the "
                    "checks would have to change, and Stage 4 would be measured "
                    "against checks that no longer exist."),
    "ikea-after": ("Eight changes to the recorder and checks: a visibility gate "
                   "on candidates, tabindex=-1 honoured anywhere, containers "
                   "with a focusable descendant excluded, candidates re-checked "
                   "after the sequence, coverage gating every pass, consent "
                   "dialogs dismissed, truncation no longer reported as a "
                   "keyboard trap, and column-aware reading order."),
}


def axe_for(page: str, tag: str = "baseline6") -> dict:
    """What axe-core found on one broken page, split by whether it is WCAG.

    This column is the argument. axe 4.13.0 ran on every page and reported no
    WCAG violation on any of them, on pages carrying fifteen planted WCAG
    keyboard defects. The two things it did report are tagged `best-practice`,
    which is axe's own label for "not a success criterion", and both describe
    something other than the defect: `tabindex` on the switch that carries a
    positive tabindex, and `region` on the three cover elements, as content
    outside a landmark rather than as something obscuring focus.
    """
    run = _load(f"{tag}-{page}")
    if not run:
        return {"ran": False, "wcag": 0, "best_practice": 0, "items": []}
    ax = run.get("axe") or {}
    items = []
    for v in ax.get("violations") or []:
        tags = v.get("tags") or []
        items.append({
            "id": v.get("id", ""),
            "help": v.get("help", ""),
            "nodes": v.get("nodes", 0),
            "targets": v.get("targets") or [],
            "wcag": any(t.startswith("wcag") for t in tags),
            "best_practice": "best-practice" in tags,
        })
    return {
        "ran": bool(ax.get("ran")),
        "version": ax.get("version", ""),
        "wcag": sum(1 for i in items if i["wcag"]),
        "best_practice": sum(1 for i in items if not i["wcag"]),
        "items": items,
    }


def fixture_run(tag: str) -> dict | None:
    """One scored run over the 15 defects, per criterion."""
    score = _load(f"{tag}-score")
    if not score:
        return None
    per = score.get("per_criterion") or {}
    rows = []
    for crit in CRITERIA:
        v = per.get(crit)
        if not v:
            rows.append({"criterion": crit, "run": False})
            continue
        ax = axe_for(PAGE_OF[crit], tag)
        rows.append({
            "criterion": crit,
            "run": True,
            "planted": v.get("planted", 0),
            "found": v.get("found", 0),
            "reported": v.get("reported", 0),
            "true_positives": v.get("true_positives", 0),
            "false_positives": v.get("false_positives", 0),
            "not_evaluated": v.get("not_evaluated", 0),
            "missed": v.get("missed") or [],
            "fp_targets": v.get("fp_targets") or [],
            "axe_wcag": ax["wcag"],
            "axe_best_practice": ax["best_practice"],
            "axe_ran": ax["ran"],
            "axe_items": ax["items"],
        })
    live = [r for r in rows if r.get("run")]
    return {
        "tag": tag,
        "rows": rows,
        "planted": sum(r["planted"] for r in live),
        "found": sum(r["found"] for r in live),
        "not_evaluated": sum(r["not_evaluated"] for r in live),
        "false_positives": sum(r["false_positives"] for r in live),
        "true_positives": sum(r["true_positives"] for r in live),
        "reported": sum(r["reported"] for r in live),
        "axe_wcag": sum(r["axe_wcag"] for r in live),
        "axe_best_practice": sum(r["axe_best_practice"] for r in live),
        "changed": CHANGED.get(tag, ""),
    }


# --------------------------------------------------------------------------
# The unknown site: no manifest, so correctness came from inspection by hand
# --------------------------------------------------------------------------

UNKNOWN = [
    {"key": "ikea-before", "artifact": "wild-ikea-local", "label": "before the fixes",
     "checked": 39, "correct": 0},
    {"key": "ikea-after", "artifact": "ikea-fixed2-local", "label": "after the fixes",
     "checked": 33, "correct": 0},
]


def unknown_run(spec: dict) -> dict | None:
    """One run against a real commercial site.

    There is no manifest here, so there is no recall to compute. The honest
    numbers are how many elements were named, how much of the page was examined,
    and how many of the named elements survived being opened one by one.
    """
    data = _load(spec["artifact"])
    if not data:
        return None
    targets: list[str] = []
    per_criterion: dict[str, dict] = {}
    for f in data.get("findings", []):
        crit = f.get("criterion", "")
        cen = f.get("census") or {}
        row = per_criterion.setdefault(crit, {
            "criterion": crit, "examined": 0, "failed": 0, "passed": 0,
            "undecided": 0, "inapplicable": 0, "excluded": 0, "statuses": [],
            "targets": []})
        row["examined"] += cen.get("examined", 0)
        row["failed"] += cen.get("failed", 0)
        row["passed"] += cen.get("passed", 0)
        row["undecided"] += cen.get("undecided", 0)
        row["inapplicable"] += cen.get("inapplicable", 0)
        row["excluded"] += cen.get("excluded", 0)
        row["statuses"].append(f.get("status", ""))
        if f.get("status") == "failed":
            targets.extend(f.get("targets") or [])
            row["targets"].extend(f.get("targets") or [])
    for row in per_criterion.values():
        row["targets"] = list(dict.fromkeys(row["targets"]))
    return {
        "key": spec["key"],
        "label": spec["label"],
        "url": data.get("url", ""),
        "rows": [per_criterion.get(c, {"criterion": c, "examined": 0, "failed": 0,
                                       "passed": 0, "undecided": 0,
                                       "inapplicable": 0, "excluded": 0,
                                       "statuses": [], "targets": []})
                 for c in CRITERIA],
        "targets": list(dict.fromkeys(targets)),
        "checked": spec["checked"],
        "correct": spec["correct"],
        "changed": CHANGED.get(spec["key"], ""),
    }


# --------------------------------------------------------------------------
# Stage 4: does writing patch outcomes down lower the effort per fix?
# --------------------------------------------------------------------------

def _trace_index() -> dict:
    """(criterion, component, lesson ids) -> a real Weave call id.

    Read from the traces the Stage 4 run already produced. Every patch call
    carries the ids of the prior cases that went into its prompt, which is what
    turns "effort per fix fell" into something with a mechanism behind it.
    """
    links = _load("trace-links") or {}
    index: dict[tuple, str] = {}
    for call in links.get("calls") or []:
        key = (call.get("criterion"), call.get("component"),
               tuple(call.get("lesson_ids") or ()))
        index.setdefault(key, call.get("id", ""))
    return index


def trace_url(call_id: str) -> str:
    return f"https://wandb.ai/{ENTITY_PROJECT}/r/call/{call_id}"


def stage4_arm(tag: str, arm: str, changed: str) -> dict | None:
    data = _load(f"{tag}-stage4")
    if not data:
        return None
    index = _trace_index()
    closed = []
    for row in data.get("closed_in_order") or []:
        ids = tuple(row.get("lesson_ids") or ())
        call = (index.get((row.get("criterion"), row.get("component"), ids))
                or index.get((row.get("criterion"), row.get("component"), ())))
        closed.append(dict(row, call_id=call or "",
                           trace=trace_url(call) if call else ""))
    attempts = [r["patch_attempts"] for r in closed]
    half = len(attempts) // 2
    first, second = attempts[:half], attempts[half:]
    trend = None
    if first and second:
        trend = round(sum(second) / len(second) - sum(first) / len(first), 2)
    return {
        "tag": tag,
        "arm": arm,
        "lessons": data.get("lessons", ""),
        "rows": data.get("rows") or [],
        "closed": closed,
        "n_closed": len(closed),
        "created": sum(r.get("created", 0) for r in data.get("rows") or []),
        "mean_attempts": round(sum(attempts) / len(attempts), 2) if attempts else None,
        "one_attempt": sum(1 for a in attempts if a == 1),
        "trend": trend,
        "retrieved_total": sum(r.get("retrieved", 0) for r in data.get("rows") or []),
        "changed": changed,
    }


def stage4() -> dict:
    control = stage4_arm(
        "s4c", "control",
        "Lessons table off. The same five pages in the same order with nothing "
        "retrieved. This is the arm that matters: a falling line with the table "
        "on proves nothing by itself, because the later pages might simply be "
        "easier.")
    treatment = stage4_arm(
        "s4t", "treatment",
        "Lessons table on. Every patch outcome is written down, and the matching "
        "rows for this criterion go into the next prompt, failures included and "
        "labelled as failures.")
    both = [a for a in (control, treatment) if a]
    return {
        "control": control,
        "treatment": treatment,
        "total_closed": sum(a["n_closed"] for a in both),
        "total_one_attempt": sum(a["one_attempt"] for a in both),
    }


# --------------------------------------------------------------------------
# Everything the benchmark screen shows, in one call
# --------------------------------------------------------------------------

def benchmark() -> dict:
    return {
        "fixture": [r for r in (fixture_run("baseline5"), fixture_run("baseline6")) if r],
        "unknown": [r for r in (unknown_run(UNKNOWN[0]), unknown_run(UNKNOWN[1])) if r],
        "weave": WEAVE_URL,
    }
