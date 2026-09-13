"""Stage 4: does the lessons table lower patch attempts per closed finding?

Runs the fix loop across all five broken pages, in order, and records attempts
per closed finding for each. With the table on, page five retrieves what pages
one to four learned. With it off, nothing is retrieved and the same five pages
run cold.

**The control matters more than the treatment.** A falling line with the table
on proves nothing on its own: the later pages might simply be easier. The same
five pages in the same order with the table off is the only thing that
separates those two explanations.

**What this number is and is not.** The table records patch outcomes, so it can
only improve patching. A finding that was never detected produces no row, so
the table cannot reach detection at all. This measures effort per fix across
the findings already detected, and nothing about how many are detected.

Usage:
    python scorer/stage4.py --lessons off --tag s4-control
    python scorer/stage4.py --lessons on  --tag s4-treatment
"""

from __future__ import annotations

import os
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

from agent.fixloop import FixLoop  # noqa: E402
from agent.judge import _client, make_judge  # noqa: E402
from agent.lessons import Lessons  # noqa: E402
from agent.recording import Census, Result  # noqa: E402
from agent.run import CHECKOUT, REPO, RemoteTree  # noqa: E402
from agent.session import Session  # noqa: E402

CRITERIA = ["2.1.1", "2.1.2", "2.4.3", "2.4.7", "2.4.11"]
PAGE_OF = {"2.1.1": "2-1-1", "2.1.2": "2-1-2", "2.4.3": "2-4-3",
           "2.4.7": "2-4-7", "2.4.11": "2-4-11"}


def _result_from(f: dict) -> Result:
    """A Result back from its own dict, census included.

    The census is a nested dataclass, so a flat `Result(**f)` would leave it as a
    plain dict and `.census.examined` would raise on an attribute that looks like
    it exists. Rebuilt explicitly instead.
    """
    fields = {k: (tuple(v) if isinstance(v, list) else v)
              for k, v in f.items() if k != "census"}
    return Result(census=Census(**(f.get("census") or {})), **fields)


class SavedAudit:
    """An audit reconstructed from disk, so Stage 4 does not re-audit.

    The fix loop needs findings, states, a session and a judge. Re-running the
    audits would cost more than the patching and would measure a different set
    of findings, which is the one thing a before/after comparison cannot have.
    """

    def __init__(self, artifact: dict, session: Session, judge, run_id: str) -> None:
        s = artifact["summary"]
        self.url = s["url"]
        self.states = s["states"]
        self.run_id = run_id
        self.session = session
        self.judge = judge
        self.results = [_result_from(f) for f in artifact["findings"]]


def clone_fresh(session: Session) -> None:
    r = session.exec(
        f"rm -rf {CHECKOUT} && git clone --depth 1 --branch main -q {REPO} {CHECKOUT} "
        f"&& echo CLONED", timeout=300)
    if "CLONED" not in (r.result or ""):
        raise SystemExit(f"clone failed: {(r.result or '')[:200]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sandbox", default=os.environ.get("ALLY_SANDBOX"))
    ap.add_argument("--lessons", choices=["on", "off"], default="on")
    ap.add_argument("--tag", default="s4")
    ap.add_argument("--baseline", default="baseline6")
    args = ap.parse_args()

    use_lessons = args.lessons == "on"
    cfg = wb_env.bootstrap()
    weave.init(cfg["ref"])

    # Logged as an evaluation from the start, not written up afterwards. The arm
    # and the one-line reason for it are attributes, because a delta with no
    # cause attached means nothing.
    arm = "treatment (lessons table live)" if use_lessons else "control (no retrieval)"
    changed = ("Lessons table ON: every patch outcome is written down, and the "
               "matching rows for this criterion go into the next prompt, "
               "failures included and labelled as failures."
               if use_lessons else
               "Lessons table OFF: the same five pages in the same order with "
               "nothing retrieved. This is the arm that matters -- a falling "
               "line with the table on proves nothing by itself, because the "
               "later pages might simply be easier.")
    ev = weave.EvaluationLogger(
        name="stage4-patch-effort",
        model=f"ally-patcher@lessons-{args.lessons}",
        dataset="planted-defects",
        eval_attributes={"arm": arm, "lessons": args.lessons,
                         "baseline": args.baseline,
                         "changed_since_previous": changed},
    )
    closed_in_order: list[dict] = []

    session = Session(args.sandbox)
    judge = make_judge()
    client = _client()

    if use_lessons:
        # A fresh table per treatment run, so the comparison is against a known
        # starting point rather than whatever happened to be left over.
        from ally import db
        db.script("DROP TABLE IF EXISTS lessons;")

    rows = []
    print(f"Stage 4  lessons={args.lessons}  tag={args.tag}")
    print("five pages, in order, one fix loop each\n")

    for i, crit in enumerate(CRITERIA, 1):
        page = PAGE_OF[crit]
        art = ROOT / "artifacts" / f"{args.baseline}-{page}.json"
        if not art.exists():
            print(f"  [{i}] {crit}: no baseline artifact, skipped")
            continue
        artifact = json.loads(art.read_text(encoding="utf-8"))
        run_id = f"{args.tag}-{page}"
        audit = SavedAudit(artifact, session, judge, run_id)

        open_failures = [r for r in audit.results if r.status == "failed"]
        if not open_failures:
            print(f"  [{i}] {crit}: nothing detected to fix")
            rows.append({"order": i, "criterion": crit, "groups": 0, "closed": 0,
                         "created": 0, "attempts": None, "retrieved": 0})
            continue

        clone_fresh(session)
        source = f"broken-app/public/{page}.html"
        lessons = Lessons(run_id) if use_lessons else None
        loop = FixLoop(audit, workdir=pathlib.Path(CHECKOUT),
                       serve_root=f"{CHECKOUT}/broken-app/public",
                       client=client, lessons=lessons)
        loop.workdir = RemoteTree(session, CHECKOUT)

        print(f"  [{i}] {crit}  {len(open_failures)} finding(s) detected")
        try:
            outcomes = loop.run(source)
        except Exception as exc:
            print(f"      FAILED: {type(exc).__name__}: {str(exc)[:110]}")
            continue

        s = loop.summary()
        retrieved = sum(len(o.lesson_ids) for o in outcomes)

        # One prediction per group, so a reader can open any patch and see the
        # lesson ids that went into the prompt that produced it.
        for o in outcomes:
            pred = ev.log_prediction(
                inputs={"criterion": o.criterion, "component": o.component,
                        "page": page, "order": i, "lesson_ids": o.lesson_ids,
                        "lessons_retrieved": len(o.lesson_ids)},
                output={"status": o.status, "patch_attempts": o.patch_attempts,
                        "locate_attempts": o.locate_attempts,
                        "closed": len(o.closed), "created": len(o.created),
                        "reason": o.reason})
            pred.log_score("patch-attempts", o.patch_attempts)
            pred.log_score("closed", 1 if o.status == "closed" else 0)
            pred.log_score("patch-created-new-findings", len(o.created))
            pred.finish()
            if o.status == "closed":
                closed_in_order.append({
                    "order": len(closed_in_order) + 1, "criterion": o.criterion,
                    "component": o.component, "page": page,
                    "patch_attempts": o.patch_attempts,
                    "lessons_retrieved": len(o.lesson_ids),
                    "lesson_ids": o.lesson_ids})
        rows.append({"order": i, "criterion": crit, "groups": s["groups"],
                     "closed": s["closed"], "created": s["created"],
                     "attempts": s["patch_attempts_per_closed"],
                     "retrieved": retrieved,
                     "could_not_locate": s["could_not_locate"],
                     "still_failing": s["still_failing"]})
        print(f"      closed {s['closed']}  created {s['created']}  "
              f"attempts/closed {s['patch_attempts_per_closed']}  "
              f"lessons retrieved {retrieved}")

    print("\n" + "=" * 88)
    print(f"STAGE 4  lessons={args.lessons}")
    print("=" * 88)
    print(f"{'#':>2} {'criterion':10s} {'closed':>7s} {'created':>8s} "
          f"{'attempts/closed':>16s} {'lessons used':>13s}")
    print("-" * 88)
    for r in rows:
        a = "—" if r["attempts"] is None else f"{r['attempts']:.2f}"
        print(f"{r['order']:>2} {r['criterion']:10s} {r['closed']:>7d} "
              f"{r['created']:>8d} {a:>16s} {r['retrieved']:>13d}")
    print("-" * 88)
    closed = sum(r["closed"] for r in rows)
    print(f"   total closed {closed}, created {sum(r['created'] for r in rows)}")
    print("\nThis is effort per fix across findings ALREADY detected. The table "
          "records\npatch outcomes, so a finding that was never detected produces "
          "no row and the\ntable cannot reach detection at all.")

    # The metric, and the honest version of it. A flat line is still the metric:
    # the findings are listed individually in the order they closed, so a reader
    # can see whether later ones took fewer attempts than earlier ones rather
    # than being asked to trust one average over five pages.
    print("\nfindings in the order they closed")
    print(f"{'#':>2} {'criterion':9s} {'component':22s} {'attempts':>8s} "
          f"{'lessons used':>12s}  lesson ids")
    for row in closed_in_order:
        print(f"{row['order']:>2} {row['criterion']:9s} {row['component'][:22]:22s} "
              f"{row['patch_attempts']:>8d} {row['lessons_retrieved']:>12d}  "
              f"{row['lesson_ids']}")
    if not closed_in_order:
        print("  nothing closed, so there is no effort-per-fix number this run")

    attempts = [r["patch_attempts"] for r in closed_in_order]
    half = len(attempts) // 2
    first, second = attempts[:half], attempts[half:]
    trend = None
    if first and second:
        a, b = sum(first) / len(first), sum(second) / len(second)
        trend = round(b - a, 2)
        print(f"\nmean attempts, first half {a:.2f} -> second half {b:.2f} "
              f"(change {trend:+.2f})")
        if trend >= 0:
            print("This did not fall. Reported as it is. The table records patch "
                  "outcomes, so it\ncan only reach patching, and on this evidence "
                  "it did not help enough to show.")

    ev.log_summary({
        "arm": arm,
        "lessons": args.lessons,
        "closed": sum(r["closed"] for r in rows),
        "created": sum(r["created"] for r in rows),
        "patch_attempts_per_closed": (round(sum(attempts) / len(attempts), 2)
                                      if attempts else None),
        "mean_attempts_change_first_to_second_half": trend,
        "lessons_retrieved_total": sum(r["retrieved"] for r in rows),
        "closed_in_order": closed_in_order,
        "changed_since_previous": changed,
    }, auto_summarize=False)
    ev.finish()

    out = ROOT / "artifacts" / f"{args.tag}-stage4.json"
    out.write_text(json.dumps({"lessons": args.lessons, "rows": rows,
                               "closed_in_order": closed_in_order}, indent=2),
                   encoding="utf-8")
    print(f"\nsaved {out}")


if __name__ == "__main__":
    main()
