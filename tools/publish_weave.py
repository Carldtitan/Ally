"""Put the things this project already has into Weave: datasets, prompts,
scorers, and the two evaluations we ran and never recorded.

Only Ops had anything in it. The content for everything else was already in the
repo, which is the worst version of thin usage: not missing work, just
unrecorded work.

  1. **Two datasets.** The 24 frozen recordings that the recall gate replays,
     and the 15-defect manifest. Everything else runs against these, so they are
     the things a reader needs first.
  2. **Two evaluations, backfilled.** baseline5 at 8 of 15 and baseline6 at 15
     of 15; ikea at 41 findings and then 34. Each carries one line saying what
     changed since the one before, because a delta with no cause attached means
     nothing. These are logged through `EvaluationLogger`, the imperative API,
     because the numbers already exist and re-running them would measure a
     different thing.
  3. **Two prompts**, from `agent/prompts.py` -- the objects the code runs, not
     copies.
  4. **Three scorers**, from `agent/scorers.py`.

Models are deliberately skipped: largest change, smallest gain today.

Usage:
    python tools/publish_weave.py            # everything
    python tools/publish_weave.py --only datasets,prompts
"""

from __future__ import annotations

import sys
import json
import argparse
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import wb_env  # noqa: E402

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

import weave  # noqa: E402

CORPUS = ROOT / "tests" / "fixtures" / "recordings"
MANIFEST = ROOT / "breaker" / "manifest.json"


# --------------------------------------------------------------------------
# 1. Datasets
# --------------------------------------------------------------------------

def publish_recordings() -> str:
    """The 24 frozen recordings, one row per page-state.

    Screenshots are already refs rather than bytes, so a row stays small. The
    1GB Weave ingestion cap is one benchmark run away if image bytes ever reach
    an object.
    """
    rows = []
    for path in sorted(CORPUS.glob("*__*.json")):
        page, state = path.stem.split("__", 1)
        raw = json.loads(path.read_text(encoding="utf-8"))
        stops = raw.get("stops") or []
        rows.append({
            "id": path.stem,
            "page": page,
            "state": state,
            "url": raw.get("url", ""),
            "state_reached": raw.get("state_reached", True),
            "truncated": raw.get("truncated", False),
            "n_stops": len(stops),
            "n_candidates": len(raw.get("candidates") or []),
            "n_excluded": len(raw.get("excluded") or []),
            # The refs a citation has to resolve against, so the evidence
            # scorer can run straight off the dataset row.
            "known_refs": [f"stop {s['index']}" for s in stops]
                          + [f"candidate {c['selector']}"
                             for c in (raw.get("candidates") or [])],
            "recording": raw,
        })
    ds = weave.Dataset(rows=rows)
    ds.name = "frozen-recordings"
    ds.description = (
        "24 recordings frozen from baseline6: five broken pages and the clean "
        "page, four states each. The recall gate replays these through all five "
        "checks in about a second, because recording is the expensive part and "
        "the checks are pure functions of a Recording. Re-freeze after a "
        "deliberate recorder change and say so in the commit.")
    return str(weave.publish(ds, name="frozen-recordings").uri())


def publish_manifest() -> str:
    """The 15 planted defects: five criteria, three instances each."""
    rows = json.loads(MANIFEST.read_text(encoding="utf-8"))
    if isinstance(rows, dict):
        # `defects` in this file is a COUNT, not the list. Taking the first
        # truthy key published the integer 15 as the dataset.
        rows = next((v for k, v in rows.items() if isinstance(v, list) and v), [])
    if not isinstance(rows, list) or not rows:
        raise SystemExit(f"no defect rows found in {MANIFEST}")
    ds = weave.Dataset(rows=rows)
    ds.name = "planted-defects"
    ds.description = (
        "15 defects, three per criterion, planted on pages generated from the "
        "clean app. Three instances rather than one is what the lessons table "
        "is measured against: the first has nothing to retrieve, the third has "
        "two prior cases. It is also what caught the patcher stopping at the "
        "first occurrence of a find/replace pair.")
    return str(weave.publish(ds, name="planted-defects").uri())


# --------------------------------------------------------------------------
# 2. The two evaluations we already ran
# --------------------------------------------------------------------------

#: Every evaluation carries one line saying what changed since the previous one.
#: A delta with no cause attached means nothing, and two of these deltas were
#: caused by things other than the checks improving.
BASELINES = [
    {
        "name": "fixture-recall",
        "run": "baseline5",
        "changed": ("FIRST RECORDED. 8 of 15. The 2.4.11 fixture had just been "
                    "corrected to size each cover over a single control."),
        "artifact": "baseline5",
    },
    {
        "name": "fixture-recall",
        "run": "baseline6",
        "changed": ("THE SCORER CHANGED, NOT THE CHECKS. Matching moved from "
                    "selector strings to element identity collected from the "
                    "DOM, with an ancestor counting as a match. Six of the "
                    "seven new finds were already being detected and could not "
                    "be matched; the seventh came from replacing an "
                    "unobservable 2.4.3 fixture. No part of this delta is a "
                    "detection improvement."),
        "artifact": "baseline6",
    },
]


def log_fixture_baseline(spec: dict) -> str | None:
    """One backfilled evaluation over the 15 defects, from artifacts on disk."""
    from scorer.score import CRITERIA, PAGE_OF, anchor_index, load_manifest, matches

    planted = load_manifest()
    logger = weave.EvaluationLogger(
        name=spec["name"],
        model=f"ally-checks@{spec['run']}",
        dataset="planted-defects",
        eval_attributes={"run": spec["run"], "changed_since_previous": spec["changed"]},
    )
    found_total = planted_total = fp_total = 0
    for crit in CRITERIA:
        art = ROOT / "artifacts" / f"{spec['artifact']}-{PAGE_OF[crit]}.json"
        if not art.exists():
            print(f"    {crit}: no artifact, skipped")
            continue
        run = json.loads(art.read_text(encoding="utf-8"))
        anchors = anchor_index(run)
        reported: list[str] = []
        for f in run.get("findings", []):
            if f.get("criterion") == crit and f.get("status") == "failed":
                reported.extend(f.get("targets") or [])
        reported = list(dict.fromkeys(reported))

        for defect in planted.get(crit, []):
            hits = [t for t in reported if matches(t, defect, anchors)]
            pred = logger.log_prediction(
                inputs={"criterion": crit, "region": defect["region"],
                        "selector": defect["selector"], "page": PAGE_OF[crit]},
                output={"targets": reported, "matched": hits})
            pred.log_score("found-planted-defect", bool(hits))
            pred.finish()
            planted_total += 1
            found_total += bool(hits)
        fp_total += len([t for t in reported
                         if not any(matches(t, d, anchors) for d in planted.get(crit, []))])

    logger.log_summary({
        "recall": found_total / planted_total if planted_total else 0.0,
        "found": found_total,
        "planted": planted_total,
        "false_positives": fp_total,
        "changed_since_previous": spec["changed"],
    }, auto_summarize=False)
    logger.finish()
    return f"{spec['name']} / {spec['run']}: {found_total}/{planted_total}, {fp_total} FP"


UNKNOWN_SITE = [
    {
        "run": "ikea-before-fixes",
        "artifact": "wild-ikea-local",
        "changed": ("FIRST RECORDED. 41 findings on ikea.com, 0 correct, every "
                    "one inspected on the live page. Run before Stage 4 on "
                    "purpose: if precision collapsed on a page nobody built for "
                    "us, the checks would have to change."),
        "verified_true": 0,
        "verified_checked": 39,
    },
    {
        "run": "ikea-after-fixes",
        "artifact": "ikea-fixed2-local",
        "changed": ("SIX CHECKS AND THE RECORDER CHANGED: a visibility gate on "
                    "candidates, tabindex=-1 honoured anywhere, containers with "
                    "a focusable descendant excluded, candidates re-checked "
                    "after the sequence, coverage gating every pass, consent "
                    "dialogs dismissed, truncation no longer a keyboard trap, "
                    "and column-aware reading order. Findings fell 41 to 37 and "
                    "precision stayed 0: the fixes changed which things are "
                    "wrong, not whether they are wrong."),
        "verified_true": 0,
        "verified_checked": 33,
    },
]


def log_unknown_site(spec: dict) -> str | None:
    """One backfilled evaluation over a real site, where there is no manifest.

    There is nothing to score recall against here, so the only honest numbers
    are how many findings were reported and how much of the page was examined.
    Correctness came from inspecting each finding by hand and is recorded as an
    attribute rather than computed.
    """
    art = ROOT / "artifacts" / f"{spec['artifact']}.json"
    if not art.exists():
        print(f"    {spec['run']}: no artifact at {art.name}, skipped")
        return None
    data = json.loads(art.read_text(encoding="utf-8"))
    logger = weave.EvaluationLogger(
        name="unknown-site",
        model=f"ally-checks@{spec['run']}",
        dataset="frozen-recordings",
        eval_attributes={"run": spec["run"], "site": data.get("url", ""),
                         "changed_since_previous": spec["changed"]},
    )
    findings = data.get("findings", [])
    # The number that matters is unique targets, not Result objects. One Result
    # can name 23 elements, and 23 elements is what a person then has to check.
    targets: list[str] = []
    for f in findings:
        if f.get("status") == "failed":
            targets.extend(f.get("targets") or [])
    targets = list(dict.fromkeys(targets))
    reported = 0
    examined = excluded = 0
    for f in findings:
        cen = f.get("census") or {}
        examined += cen.get("examined", 0)
        excluded += cen.get("excluded", 0)
        pred = logger.log_prediction(
            inputs={"criterion": f.get("criterion"), "state": f.get("state_label")
                    or f.get("state")},
            output={"status": f.get("status"), "targets": f.get("targets") or [],
                    "census": cen})
        # No manifest, so this is not recall. It is the count a human then had
        # to check one by one.
        pred.log_score("findings-reported", 1 if f.get("status") == "failed" else 0)
        pred.finish()
        reported += f.get("status") == "failed"

    checked = spec.get("verified_checked", 0)
    true_pos = spec.get("verified_true", 0)
    logger.log_summary({
        # Unique elements named across every finding: what a person had to sit
        # down and check one by one.
        "targets_reported": len(targets),
        "criteria_firing": reported,
        "elements_examined": examined,
        "elements_excluded": excluded,
        # Correctness on a real site has no manifest behind it. These came from
        # opening each flagged element in the live page, and are recorded as a
        # measurement made by hand rather than computed.
        "hand_verified_checked": checked,
        "hand_verified_correct": true_pos,
        "precision_hand_verified": (true_pos / checked) if checked else None,
        "changed_since_previous": spec["changed"],
    }, auto_summarize=False)
    logger.finish()
    return (f"unknown-site / {spec['run']}: {len(targets)} targets across "
            f"{reported} criteria, {true_pos}/{checked} correct by hand")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="datasets,prompts,scorers,evaluations")
    args = ap.parse_args()
    want = {s.strip() for s in args.only.split(",") if s.strip()}

    cfg = wb_env.bootstrap()
    weave.init(cfg["ref"])
    print(f"publishing to {cfg['ref']}\n")

    if "datasets" in want:
        print("datasets")
        print("  frozen-recordings:", publish_recordings())
        print("  planted-defects:  ", publish_manifest())

    if "prompts" in want:
        print("\nprompts")
        from agent import prompts
        for name, uri in prompts.publish_all().items():
            print(f"  {name}: {uri}")

    if "scorers" in want:
        print("\nscorers")
        from agent import scorers
        for name, uri in scorers.publish_all().items():
            print(f"  {name}: {uri}")

    if want & {"evaluations", "fixture"}:
        print("\nevaluations: fixture recall (in order, each with what changed)")
        for spec in BASELINES:
            line = log_fixture_baseline(spec)
            if line:
                print("  " + line)

    if want & {"evaluations", "unknown"}:
        print("\nevaluations: unknown site (in order, each with what changed)")
        for spec in UNKNOWN_SITE:
            line = log_unknown_site(spec)
            if line:
                print("  " + line)

    print(f"\nhttps://wandb.ai/{cfg['ref']}/weave")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
