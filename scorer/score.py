"""The scorer: compares what the breaker planted against what the agent found.

The third of three programs that share nothing. The breaker wrote the manifest
and never saw a finding; the agent got a URL and never saw the manifest; this
reads both and is the only place they meet.

Precision and recall per criterion, never one aggregate number, and
`not_evaluated` in the same row as recall. A criterion reading 0/3 recall with
3 not evaluated means the state was never reached, which is a different fact
from a check that ran and missed. Separated across the screen they are
indistinguishable, which is how a measurement stops meaning anything.

The clean page needs no answer key: the correct output of our five there is
nothing, so anything they report is a false positive by definition.

Usage:
    python scorer/score.py                      # audit all five, then score
    python scorer/score.py --from artifacts/    # score runs already on disk
"""

from __future__ import annotations

import os
import sys
import json
import argparse
import pathlib
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import wb_env  # noqa: E402

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

MANIFEST = ROOT / "breaker" / "manifest.json"
BROKEN_BASE = "https://broken-app.vercel.app"
CLEAN_URL = "https://ally-clean-app.vercel.app/"

CRITERIA = ["2.1.1", "2.1.2", "2.4.3", "2.4.7", "2.4.11"]
PAGE_OF = {"2.1.1": "2-1-1", "2.1.2": "2-1-2", "2.4.3": "2-4-3",
           "2.4.7": "2-4-7", "2.4.11": "2-4-11"}


def load_manifest() -> dict:
    data = json.loads(MANIFEST.read_text(encoding="utf-8"))
    planted: dict[str, list[dict]] = defaultdict(list)
    for row in data["rows"]:
        planted[row["criterion"]].append(row)
    return planted


def manifest_token(selector: str) -> str:
    """The manifest's selector as one identity token, in anch()'s vocabulary.

    `#ally-d1` and `.city_input` already are tokens. `[role="switch"]` becomes
    `[role=switch]`: quoting and case are ours to choose, so they are normalised
    on both sides rather than compared as written.
    """
    t = (selector or "").strip()
    if t.startswith("[") and "=" in t:
        key, _, value = t.strip("[]").partition("=")
        return f"[{key.strip().lower()}={value.strip().strip(chr(34) + chr(39)).lower()}]"
    return t


def anchor_index(run: dict) -> dict[str, dict]:
    """selector -> what that element is and what it sits inside.

    Read from the recordings the audit saved, so matching uses DOM facts
    collected at the time rather than inferences about a string afterwards.
    """
    out: dict[str, dict] = {}
    for rec in (run.get("recordings") or {}).values():
        for item in list(rec.get("stops") or ()) + list(rec.get("candidates") or ()):
            a = item.get("anchors")
            if a and item.get("selector"):
                out.setdefault(item["selector"], a)
    return out


def legacy_matches(target: str, defect: dict) -> bool:
    """String matching, kept only for artifacts recorded before anchors.

    This is the bug. `sel()` prefers an id and otherwise emits an ancestor path,
    so it never emits a class or an attribute selector, and no amount of slicing
    makes `[role="switch"]` match `body>main>section:nth-of-type(5)>div`. Six of
    the fifteen defects were detected correctly and scored as missed for two
    days. Its use is counted and reported, never silent.
    """
    sel = defect["selector"]
    t = (target or "").strip()
    if not t or not sel:
        return False
    if t == sel:
        return True
    if sel.startswith("#") and sel in t:
        return True
    if sel.startswith("[") and sel.strip("[]").split("=")[0] in t:
        return True
    key = sel.lstrip(".#[").split("=")[0].strip('"]')
    return bool(key) and key in t


#: Incremented whenever an artifact has no anchors for a reported target, so a
#: score computed the old way cannot be mistaken for one computed the new way.
LEGACY_USES: list[str] = []


def matches(target: str, defect: dict, anchors: dict[str, dict] | None = None) -> bool:
    """Does a reported target name the element this defect was planted on?

    Element identity, not string similarity. The manifest names an element by
    id, class or role; the recorder addresses it by id or by path. Those are
    different questions about the same element, so the comparison is made
    against what the element actually is.

    An ancestor counts. 2.4.3 is planted on a container -- reversing a flex row
    -- and manifests on the controls inside it, which is what the check reports
    and what a keyboard user meets. `#email` inside `#email_item` is the defect
    being observed where it is observable, not a near miss.
    """
    a = (anchors or {}).get(target)
    if a is None:
        LEGACY_USES.append(target)
        return legacy_matches(target, defect)
    tok = manifest_token(defect["selector"])
    return tok in (a.get("self") or ()) or tok in (a.get("within") or ())


def score_run(run: dict, planted: dict) -> dict:
    """Per-criterion recall, precision and not_evaluated for one page."""
    out = {}
    findings = run.get("findings", [])
    anchors = anchor_index(run)
    for crit in CRITERIA:
        mine = [f for f in findings if f["criterion"] == crit]
        failed = [f for f in mine if f["status"] == "failed"]
        ne = [f for f in mine if f["status"] == "not_evaluated"]

        reported: list[str] = []
        for f in failed:
            reported.extend(f.get("targets") or [])
        reported = list(dict.fromkeys(reported))

        defects = planted.get(crit, [])
        found = [d for d in defects if any(matches(t, d, anchors) for t in reported)]
        true_pos = [t for t in reported if any(matches(t, d, anchors) for d in defects)]
        false_pos = [t for t in reported if t not in true_pos]

        out[crit] = {
            "planted": len(defects),
            "found": len(found),
            "reported": len(reported),
            "true_positives": len(true_pos),
            "false_positives": len(false_pos),
            "not_evaluated": len(ne),
            "ne_reasons": [f["reason"] for f in ne],
            "missed": [f"{d['region']} ({d['selector']})"
                       for d in defects if d not in found],
            "fp_targets": false_pos,
        }
    return out


def fmt(n: int, d: int) -> str:
    return f"{n}/{d}" if d else "—"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", default=os.environ.get("ALLY_SANDBOX"))
    ap.add_argument("--states", default="loaded,dialog-open,menu-open,tabs-focused")
    ap.add_argument("--no-audit", action="store_true",
                    help="score artifacts already on disk instead of auditing")
    ap.add_argument("--tag", default="baseline")
    args = ap.parse_args()

    planted = load_manifest()
    states = [s.strip() for s in args.states.split(",") if s.strip()]
    results: dict[str, dict] = {}
    clean_run = None

    if not args.no_audit:
        from agent.audit import Audit

        # One session for every page: starting a sandbox per page would cost
        # more than the audits.
        shared = None
        for crit in CRITERIA:
            page = PAGE_OF[crit]
            url = f"{BROKEN_BASE}/{page}.html"
            print(f"\n=== {crit}  {url}")
            saved = ROOT / "artifacts" / f"{args.tag}-{page}.json"
            if saved.exists():
                # Resume: a page already audited under this tag is not redone.
                # A crash twenty minutes in should not cost the pages that
                # already finished.
                print("  already audited under this tag, reusing")
                results[crit] = json.loads(saved.read_text(encoding="utf-8"))
                continue
            audit = Audit(url, sandbox_id=args.sandbox, states=states,
                          run_id=f"{args.tag}-{page}")
            if shared is not None:
                audit.session = shared
            shared = audit.session
            try:
                audit.run()
                audit.save()
                results[crit] = json.loads(saved.read_text(encoding="utf-8"))
            except Exception as exc:
                # Record the page as unaudited rather than losing the run. An
                # absent page is reported as absent, never as zero findings.
                print(f"  FAILED: {type(exc).__name__}: {str(exc)[:110]}")
                print("  continuing; this page will read as not audited")

        print(f"\n=== clean  {CLEAN_URL}")
        clean_path = ROOT / "artifacts" / f"{args.tag}-clean.json"
        if clean_path.exists():
            print("  already audited under this tag, reusing")
            clean_run = json.loads(clean_path.read_text(encoding="utf-8"))
        else:
            try:
                clean = Audit(CLEAN_URL, sandbox_id=args.sandbox, states=states,
                              run_id=f"{args.tag}-clean")
                clean.session = shared
                clean.run()
                clean.save()
                clean_run = json.loads(clean_path.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"  FAILED: {type(exc).__name__}: {str(exc)[:110]}")
    else:
        for crit in CRITERIA:
            p = ROOT / "artifacts" / f"{args.tag}-{PAGE_OF[crit]}.json"
            if p.exists():
                results[crit] = json.loads(p.read_text(encoding="utf-8"))
        p = ROOT / "artifacts" / f"{args.tag}-clean.json"
        if p.exists():
            clean_run = json.loads(p.read_text(encoding="utf-8"))

    # ---- the matrix --------------------------------------------------
    print("\n" + "=" * 96)
    print(f"BASELINE  ({args.tag})   three instances planted per criterion")
    print("=" * 96)
    print(f"{'criterion':10s} {'planted':>7s} {'found':>6s} {'recall':>7s} "
          f"{'precision':>10s} {'not_eval':>9s} {'clean FP':>9s}  notes")
    print("-" * 96)

    scored = {}
    for crit in CRITERIA:
        run = results.get(crit)
        if run is None:
            print(f"{crit:10s} {'—':>7s} {'—':>6s} {'—':>7s} {'—':>10s} "
                  f"{'—':>9s} {'—':>9s}  not audited")
            continue
        s = score_run(run, planted)[crit]
        scored[crit] = s

        clean_fp = 0
        if clean_run is not None:
            cs = score_run(clean_run, planted)[crit]
            # On the clean page every reported target is a false positive.
            clean_fp = cs["reported"]

        note = ""
        if s["not_evaluated"]:
            note = s["ne_reasons"][0][:44]
        elif s["missed"]:
            note = "missed: " + ", ".join(s["missed"])[:44]

        print(f"{crit:10s} {s['planted']:>7d} {s['found']:>6d} "
              f"{fmt(s['found'], s['planted']):>7s} "
              f"{fmt(s['true_positives'], s['reported']):>10s} "
              f"{s['not_evaluated']:>9d} {clean_fp:>9d}  {note}")

    print("-" * 96)
    tot_p = sum(v["planted"] for v in scored.values())
    tot_f = sum(v["found"] for v in scored.values())
    tot_ne = sum(v["not_evaluated"] for v in scored.values())
    print(f"{'':10s} {tot_p:>7d} {tot_f:>6d} {fmt(tot_f, tot_p):>7s} "
          f"{'':>10s} {tot_ne:>9d}")
    print("\nnot_evaluated sits in the row with recall on purpose: 0/3 recall with 3 "
          "not\nevaluated means the state was never reached, which is not a broken "
          "check.")
    if clean_run is None:
        print("\nThe clean page was not audited, so the false-positive column is "
              "unmeasured\nrather than zero.")

    # ---- every false positive, named ---------------------------------
    # A wrong element cited inside an otherwise correct finding is a precision
    # defect. Reporting only the ratio lets it disappear into a passing row,
    # which is how the judge citing an unrelated stop stayed unexamined while
    # 2.4.3 read 0/3 for an entirely different reason.
    fps = [(c, t) for c, v in scored.items() for t in v["fp_targets"]]
    print(f"\nfalse positives on the broken pages: {len(fps)}")
    for crit, target in fps:
        print(f"  {crit:8s} {target}")
    if not fps:
        print("  none")

    if LEGACY_USES:
        # Rule 7: a skip is reported, never silent. A score where some targets
        # were matched as strings and others by element identity is two
        # measurements added together and must not be read as one.
        uniq = sorted(set(LEGACY_USES))
        print(f"\n!! {len(uniq)} target(s) had no anchors, so string matching "
              f"was used for them.")
        print("!! Those rows were computed the old way. Re-audit to score them "
              "on identity:")
        for t in uniq[:8]:
            print(f"!!   {t}")

    out = ROOT / "artifacts" / f"{args.tag}-score.json"
    out.write_text(json.dumps({"tag": args.tag, "states": states,
                               "per_criterion": scored}, indent=2), encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
