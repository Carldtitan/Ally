"""One audit: a URL in, findings out. This is the agent.

It gets a URL and nothing else. It never reads the breaker's manifest, which is
why it is a separate program and why the manifest lives outside public/.

Weave runs here, in the orchestrator, never inside the sandbox: api.wandb.ai is
not on Daytona's Tier 2 egress allowlist, so a trace written from in there fails
silently.

Every criterion judgement is its own root-level call, tagged with
`weave.attributes({"criterion": ..., "state": ...})`. Filter on the attribute,
never on op name: an op name carries a content hash that changes whenever the
function is edited, so a filter written against a bare name silently matches
nothing.

Usage:
    python -m agent.audit <url> [--sandbox ID] [--states loaded,dialog-open]
"""

from __future__ import annotations

import os
import sys
import json
import uuid
import time
import argparse
import pathlib
from dataclasses import asdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))

import wb_env  # noqa: E402

from agent import axe as axe_mod  # noqa: E402
from agent import checks  # noqa: E402
from agent.browser import STATES  # noqa: E402
from agent.judge import make_judge  # noqa: E402
from agent.recording import Recording, Result  # noqa: E402
from agent.session import Session  # noqa: E402

DEFAULT_STATES = ("loaded", "dialog-open", "menu-open", "tabs-focused")


class Audit:
    """One pass over one URL across one or more states."""

    def __init__(self, url: str, sandbox_id: str | None = None,
                 states=DEFAULT_STATES, run_id: str | None = None,
                 use_weave: bool = True, judge=None) -> None:
        self.url = url
        self.states = tuple(states)
        self.run_id = run_id or f"run-{uuid.uuid4().hex[:8]}"
        self.session = Session(sandbox_id)
        self.recordings: dict[str, Recording] = {}
        self.results: list[Result] = []
        self.axe: axe_mod.AxeResult | None = None
        self.weave_client = None

        if use_weave:
            try:
                import weave

                cfg = wb_env.bootstrap()
                self.weave_client = weave.init(cfg["ref"])
            except Exception as exc:
                print(f"  weave.init failed, continuing untraced: "
                      f"{type(exc).__name__}: {str(exc)[:90]}")

        # Built after weave.init so the model client is patched and token and
        # cost data is captured.
        self.judge = judge if judge is not None else make_judge()

    # -- the pass ---------------------------------------------------------

    def run(self) -> list[Result]:
        print(f"run {self.run_id}\n  target {self.url}")
        print(f"  watch  {self.session.watch_url()}\n")

        for state in self.states:
            t0 = time.perf_counter()
            rec = self.session.record(self.url, state, self.run_id)
            self.recordings[state] = rec
            flag = "reached" if rec.state_reached else "NOT REACHED"
            print(f"  [{state:13s}] {flag:11s} {len(rec.stops):2d} stops, "
                  f"{len(rec.candidates):2d} candidates  ({time.perf_counter()-t0:.1f}s)")
            if not rec.state_reached:
                print(f"                  {rec.reach_note}")

            for criterion, fn in checks.CHECKS.items():
                with checks.criterion_tag(criterion, state, self.url):
                    if criterion == "2.4.3":
                        result = fn(rec, judge=self.judge)
                    else:
                        result = fn(rec)
                self.results.append(result)

        print("\n  running axe-core alongside ...")
        self.axe = axe_mod.run_axe(self.session, self.url)
        if self.axe.ran:
            overlap = self.axe.overlapping()
            print(f"  axe {self.axe.version}: {len(self.axe.violations)} rules fired, "
                  f"criteria {sorted(self.axe.criteria) or 'none tagged'}")
            if overlap:
                print(f"  !! axe fired on criteria we claim: {overlap}")
                print("     The comparison claim is false while that is true.")
        else:
            # An empty violation list and a scan that never ran are not the
            # same fact, and reporting the second as a clean page is the worst
            # result this tool can produce.
            print(f"  axe DID NOT RUN: {self.axe.reason}")

        return self.results

    # -- reporting --------------------------------------------------------

    def summary(self) -> dict:
        by_status: dict[str, int] = {}
        for r in self.results:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        return {
            "run_id": self.run_id, "url": self.url,
            "states": list(self.states),
            "counts": by_status,
            "axe_ran": bool(self.axe and self.axe.ran),
            "axe_overlap": self.axe.overlapping() if self.axe and self.axe.ran else [],
        }

    def save(self, path: str | None = None) -> pathlib.Path:
        out = pathlib.Path(path or f"artifacts/{self.run_id}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "summary": self.summary(),
            "findings": [r.to_dict() for r in self.results],
            "recordings": {s: r.to_dict() for s, r in self.recordings.items()},
            "axe": {"ran": self.axe.ran if self.axe else False,
                    "reason": self.axe.reason if self.axe else "not attempted",
                    "version": self.axe.version if self.axe else "",
                    "violations": self.axe.violations if self.axe else []},
        }, indent=2), encoding="utf-8")
        return out

    def print_findings(self) -> None:
        print(f"\n{'criterion':10s} {'state':14s} {'status':14s} detail")
        print("-" * 108)
        for r in self.results:
            detail = (r.summary or r.reason or "")[:66]
            print(f"{r.criterion:10s} {r.state:14s} {r.status:14s} {detail}")
        print("-" * 108)
        c = self.summary()["counts"]
        print(f"passed {c.get('passed', 0)}   failed {c.get('failed', 0)}   "
              f"not_evaluated {c.get('not_evaluated', 0)}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--sandbox", default=os.environ.get("ALLY_SANDBOX"))
    ap.add_argument("--states", default=",".join(DEFAULT_STATES))
    ap.add_argument("--no-weave", action="store_true")
    ap.add_argument("--run-id")
    args = ap.parse_args()

    wb_env.load_dotenv()
    wb_env.use_certifi_bundle()

    states = [s.strip() for s in args.states.split(",") if s.strip()]
    unknown = [s for s in states if s not in STATES]
    if unknown:
        raise SystemExit(f"unknown states {unknown}; known: {sorted(STATES)}")

    audit = Audit(args.url, sandbox_id=args.sandbox, states=states,
                  run_id=args.run_id, use_weave=not args.no_weave)
    audit.run()
    audit.print_findings()
    print(f"\nsaved {audit.save()}")


if __name__ == "__main__":
    main()
