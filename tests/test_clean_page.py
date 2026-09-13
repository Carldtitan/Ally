"""Verification rule 1: every check runs against the clean page and returns zero.

A check that only ever sees the broken page cannot tell you it works. On the
control page the correct output of our five is nothing at all, so any finding
here is a false positive by definition and fails the build.

This one test would have caught three of the four bugs found on 2026-09-12:

  * the 2.4.7 switch defect that never applied, because the clean page would
    have reported the same thing as the broken one
  * the crop that used document coordinates against a viewport screenshot,
    because the elements below the fold would have produced nonsense here
  * the guessed focus-delta threshold, because caret-only change on a clean
    input would have been reported as an invisible indicator

Run it against a page whose correct answer is already known, not against a page
you are trying to learn about.

Usage:
    python tests/test_clean_page.py [--sandbox ID] [--url URL]
"""

from __future__ import annotations

import os
import sys
import argparse
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import wb_env  # noqa: E402

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

from agent import checks  # noqa: E402
from agent.session import Session  # noqa: E402

CLEAN_URL = "https://ally-clean-app.vercel.app/"
STATES = ("loaded", "dialog-open", "menu-open", "tabs-focused")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", default=os.environ.get("ALLY_SANDBOX"))
    ap.add_argument("--url", default=CLEAN_URL)
    ap.add_argument("--states", default=",".join(STATES))
    ap.add_argument("--no-judge", action="store_true",
                    help="skip the model call; the 2.4.3 row then reads "
                         "not_evaluated rather than being judged")
    args = ap.parse_args()

    session = Session(args.sandbox)
    states = [s.strip() for s in args.states.split(",") if s.strip()]

    judge = None
    if args.no_judge:
        # Verification rule 7: a skip is reported, never silent. A run with the
        # judge off has NOT verified 2.4.3 and must not read as if it had.
        print("!! JUDGE SKIPPED (--no-judge). 2.4.3 is NOT verified by this run.")
        print("!! Do not read a pass below as covering it.
")
    else:
        from agent.judge import make_judge
        judge = make_judge()

    print(f"clean page: {args.url}")
    print("the correct output of our five here is nothing at all\n")

    findings: list = []
    not_evaluated: list = []
    ran = 0

    for state in states:
        rec = session.record(args.url, state, run_id="clean-test")
        if not rec.state_reached:
            # An unreached state is a fixture or reach problem, not a finding,
            # but it must be loud: it silently removes a state from coverage.
            print(f"  [{state:13s}] NOT REACHED - {rec.reach_note}")
            continue
        print(f"  [{state:13s}] {len(rec.stops):2d} stops, "
              f"{len(rec.candidates):2d} candidates")

        for criterion, fn in checks.CHECKS.items():
            with checks.criterion_tag(criterion, state, args.url):
                # The judge runs here too. Passing judge=None skipped the one
                # check that uses a model, so the test could not see a model
                # false positive on the control page -- and there is one: on
                # the clean dialog, 2.4.3 reports two of its inputs as out of
                # order. Rule 1 says every check runs against the clean page;
                # excluding the expensive one defeats it.
                result = fn(rec) if criterion != "2.4.3" else fn(rec, judge=judge)
            ran += 1
            if result.status == "failed":
                findings.append(result)
            elif result.status == "not_evaluated":
                not_evaluated.append(result)

    print(f"\n{ran} checks run across {len(states)} states")

    if not_evaluated:
        print(f"\n{len(not_evaluated)} not_evaluated (not a failure, but say why):")
        for r in not_evaluated:
            print(f"  {r.criterion:8s} {r.state:14s} {r.reason}")

    if findings:
        print(f"\nFAIL: {len(findings)} finding(s) on a page with no defects in it.")
        print("Every one of these is a false positive by definition.\n")
        for r in findings:
            print(f"  {r.criterion:8s} {r.state:14s} {r.summary}")
            print(f"           evidence: {', '.join(r.evidence_refs[:4])}")
        return 1

    print("\nPASS: no findings on the clean page.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
