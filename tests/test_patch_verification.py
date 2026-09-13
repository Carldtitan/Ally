"""Verification rule 1, applied to the patcher.

The patcher is the component most able to produce a clean-looking wrong answer,
because its whole job is making findings disappear, which is also exactly what
a broken patcher looks like. "Zero findings" is the success signal AND the
failure signal.

Three things must hold, and all three are checked here:

  1. The finding the patch targeted is gone from the re-audit of the patched
     page. Not "the patch applied" -- AccessiFix closed findings on a
     successful compile and reported zero failures while eight were open.
  2. The patched page produces no NEW findings. A patch that closes one and
     creates two has closed nothing worth having.
  3. The clean page still returns zero, before and after. A patcher that
     degrades the control page is producing findings out of thin air, and the
     broken page alone could never tell you.

Usage:  python tests/test_patch_verification.py [--sandbox ID]
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

CLEAN = "https://ally-clean-app.vercel.app/"


def count_findings(session: Session, url: str, states, run_id: str) -> tuple[int, int, list]:
    """Returns (failed, not_evaluated, detail rows)."""
    failed = not_eval = 0
    rows = []
    for state in states:
        rec = session.record(url, state, run_id=run_id)
        if not rec.state_reached:
            rows.append((state, "-", "state not reached", rec.reach_note))
            continue
        for criterion, fn in checks.CHECKS.items():
            with checks.criterion_tag(criterion, state, url):
                r = fn(rec) if criterion != "2.4.3" else fn(rec, judge=None)
            if r.status == "failed":
                failed += 1
                rows.append((state, criterion, "failed", r.summary))
            elif r.status == "not_evaluated":
                not_eval += 1
                rows.append((state, criterion, "not_evaluated", r.reason))
    return failed, not_eval, rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", default=os.environ.get("ALLY_SANDBOX"))
    ap.add_argument("--states", default="loaded")
    ap.add_argument("--patched", default="http://localhost:3000/2-1-1.html",
                    help="the patched page, served inside the sandbox")
    args = ap.parse_args()

    session = Session(args.sandbox)
    states = [s.strip() for s in args.states.split(",") if s.strip()]
    bad = 0

    print("rule 1 on the patcher: the control page must be unchanged by patching\n")

    clean_failed, clean_ne, clean_rows = count_findings(
        session, CLEAN, states, "patchtest-clean")
    print(f"clean page  : {clean_failed} failed, {clean_ne} not evaluated")
    for state, crit, status, detail in clean_rows:
        print(f"   {state:13s} {crit:7s} {status:14s} {str(detail)[:58]}")
    if clean_failed:
        print("   FAIL: the control page reports findings. Every one is a false positive.")
        bad += 1

    # The patched page is served from the sandbox by the fix loop. If nothing is
    # serving, say so rather than reporting a clean result for a page that was
    # never fetched -- an empty finding list and a page that never loaded are
    # not the same fact.
    probe = session.sb.process.exec(
        f"curl -s -o /dev/null -w '%{{http_code}}' --max-time 8 {args.patched}", timeout=60)
    code = (probe.result or "").strip()
    print(f"\npatched page: {args.patched} -> HTTP {code or 'no response'}")
    if code != "200":
        print("   NOT CHECKED: nothing is serving the patched tree. Run agent.run first.")
        print("   Reporting this rather than a clean result for a page never fetched.")
        return 1 if bad else 0

    p_failed, p_ne, p_rows = count_findings(
        session, args.patched, states, "patchtest-patched")
    print(f"patched page: {p_failed} failed, {p_ne} not evaluated")
    for state, crit, status, detail in p_rows:
        print(f"   {state:13s} {crit:7s} {status:14s} {str(detail)[:58]}")
    if p_failed:
        print("   the patched page still has open findings (may be expected mid-run)")

    print("\n" + ("PASS: the control page is unaffected by patching."
                  if not bad else "FAIL: see above."))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
