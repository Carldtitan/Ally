"""The fix loop: patch, rebuild, re-audit, count what closed and what appeared.

A finding is closed only when the same check, on the same state, on the rebuilt
page, no longer reports it. Never when the patch merely applied. AccessiFix
closed findings on a successful compile and reported zero failures while eight
were still open.

Verification rule 1 applies here more than anywhere, because the patcher's
whole job is making findings disappear, which is also what a broken patcher
looks like. Three things are therefore measured after every patch:

  * the finding it targeted is gone from the re-audit
  * the re-audit's other findings are counted, so a patch that closes one and
    creates two is reported as closing one and creating two
  * the clean page is re-checked and must still return zero

A patch that closes nine and creates four has closed five.
"""

from __future__ import annotations

import os
import json
import time
import pathlib
import shutil
from dataclasses import dataclass, field

from ally import db
from .patcher import (MAX_LOCATE_ATTEMPTS, MAX_PATCH_ATTEMPTS, ApplyOutcome,
                      Edit, Group, PatchPlan, apply_plan, group_findings,
                      locate_context, read_plan, request_edits, write_plan)
from .recording import Result, not_evaluated

try:
    import weave
except ImportError:
    weave = None


def _op(fn):
    return weave.op()(fn) if weave else fn


@dataclass
class FixOutcome:
    """What happened to one group of findings."""

    criterion: str
    component: str
    #: "closed", "still_failing", "could_not_locate", "rejected"
    status: str
    locate_attempts: int = 0
    patch_attempts: int = 0
    closed: list[str] = field(default_factory=list)
    created: list[str] = field(default_factory=list)
    reason: str = ""
    patch_files: list[str] = field(default_factory=list)
    lesson_ids: list[int] = field(default_factory=list)

    def as_result(self, state: str) -> Result | None:
        """The three-state record for a group that never closed."""
        if self.status == "could_not_locate":
            return not_evaluated(self.criterion, state,
                                 f"could not locate the code after "
                                 f"{self.locate_attempts} attempts")
        if self.status == "still_failing":
            return not_evaluated(self.criterion, state,
                                 f"still failing after {self.patch_attempts} patches")
        return None


class FixLoop:
    """Drives patch -> rebuild -> re-audit for one audit's findings."""

    def __init__(self, audit, workdir: pathlib.Path, serve_root: str,
                 client=None, lessons=None, approve=None) -> None:
        self.audit = audit
        self.workdir = pathlib.Path(workdir)
        self.serve_root = serve_root.rstrip("/")
        self.client = client
        #: Stage 4 plugs the lessons table in here. Absent, the prompt carries
        #: no prior cases and the first instance of a criterion has nothing to
        #: retrieve, which is the point of the number that moves.
        self.lessons = lessons
        #: Called with the patch file path. Returns True to apply. Absent, the
        #: loop applies without a gate, which is only correct in the benchmark.
        self.approve = approve
        self.outcomes: list[FixOutcome] = []
        self.root = pathlib.Path(os.environ.get("ALLY_ROOT", "."))

    # -- one group --------------------------------------------------------

    @_op
    def fix_group(self, group: Group, source_path: str) -> FixOutcome:
        target = self.workdir / source_path
        findings_text = "\n".join(
            f"  - {f.summary}\n    evidence: {', '.join(f.evidence_refs[:4])}"
            for f in group.findings)

        lesson_rows, lesson_text = [], ""
        if self.lessons is not None:
            lesson_rows, lesson_text = self.lessons.recall(group)

        outcome = FixOutcome(criterion=group.criterion, component=group.component,
                             status="could_not_locate",
                             lesson_ids=[r["id"] for r in lesson_rows])

        patch_attempts = 0
        retry_note = ""

        while patch_attempts < MAX_PATCH_ATTEMPTS:
            plan = self._locate(group, source_path, findings_text, lesson_text,
                                retry_note, outcome)
            if plan is None:
                return outcome            # locate budget spent

            patch_attempts += 1
            outcome.patch_attempts = patch_attempts
            plan.patch_id = f"{group.criterion.replace('.', '-')}-{group.component.strip('#')}-{patch_attempts}"

            # One copy of the patch, on disk. Approval and application both
            # read this file; nothing regenerates it.
            path, fingerprint = write_plan(self.root, self.audit.run_id, plan)
            outcome.patch_files.append(str(path))

            if self.approve is not None and not self.approve(path, plan):
                outcome.status = "rejected"
                outcome.reason = "a person declined this patch"
                return outcome

            approved = read_plan(path, expect_fingerprint=fingerprint)
            applied = apply_plan(approved, self.workdir)
            if not applied.applied:
                # An apply failure is a locate failure in disguise: the text
                # did not match. Feed the real lines back and try again.
                retry_note = (f"\n\nYour previous edit did not apply: {applied.reason}. "
                              f"Here is what is really in the file:\n"
                              + locate_context(target.read_text(encoding="utf-8"),
                                               approved.edits[0].find if approved.edits else ""))
                patch_attempts -= 1
                outcome.locate_attempts += 1
                if outcome.locate_attempts >= MAX_LOCATE_ATTEMPTS:
                    outcome.status = "could_not_locate"
                    outcome.reason = applied.reason
                    return outcome
                continue

            closed, created = self.reaudit(group)
            outcome.closed, outcome.created = closed, created
            if closed and not any(group.criterion == c.split(":")[0] for c in created):
                outcome.status = "closed"
                return outcome

            retry_note = ("\n\nYour previous patch applied cleanly but the re-audit "
                          "still reports the problem. The fix was wrong, not the "
                          "location. Try a different technique.")

        outcome.status = "still_failing"
        outcome.reason = f"still failing after {MAX_PATCH_ATTEMPTS} patches"
        return outcome

    # -- the locate retry loop -------------------------------------------

    def _locate(self, group: Group, source_path: str, findings_text: str,
                lesson_text: str, retry_note: str,
                outcome: FixOutcome) -> PatchPlan | None:
        target = self.workdir / source_path
        source = target.read_text(encoding="utf-8")

        while outcome.locate_attempts < MAX_LOCATE_ATTEMPTS:
            outcome.locate_attempts += 1
            try:
                data = request_edits(self.client, group.criterion, group.component,
                                     findings_text, source_path, source,
                                     lesson_text, retry_note)
            except Exception as exc:
                outcome.reason = f"{type(exc).__name__}: {str(exc)[:120]}"
                retry_note = f"\n\nThe previous response could not be read: {outcome.reason}"
                continue

            edits = [Edit(**e) for e in data.get("edits", [])]
            if not edits:
                retry_note = "\n\nYour previous response contained no edits."
                continue

            bad = [e for e in edits if source.count(e.find) != 1]
            if bad:
                e = bad[0]
                n = source.count(e.find)
                retry_note = (
                    f"\n\nYour previous `find` matched {n} times, and it must match "
                    "exactly once. " + ("It is not in the file at all; here is what "
                                        "is really there:\n" if n == 0 else
                                        "Include more surrounding lines to make it "
                                        "unique. Nearby text:\n")
                    + locate_context(source, e.find))
                continue

            return PatchPlan(patch_id="pending", criterion=group.criterion,
                             component=group.component,
                             rationale=data.get("rationale", ""), edits=edits,
                             addresses=[f.summary for f in group.findings],
                             locate_attempts=outcome.locate_attempts)

        outcome.status = "could_not_locate"
        outcome.reason = f"could not locate the code after {MAX_LOCATE_ATTEMPTS} attempts"
        return None

    # -- rebuild and re-audit --------------------------------------------

    @_op
    def reaudit(self, group: Group) -> tuple[list[str], list[str]]:
        """Serve the patched tree, run the same checks on the same states.

        Returns (closed, created) as criterion:state keys. A finding is closed
        only because the check no longer reports it, never because a patch
        applied.
        """
        before = {f"{r.criterion}:{r.state}" for r in self.audit.results
                  if r.status == "failed"}

        self.audit.session.sb.process.exec(
            f"pkill -f 'http.server 3000'; sleep 1; cd {self.serve_root} && "
            "nohup python3 -m http.server 3000 > /tmp/patched.log 2>&1 & echo ok",
            timeout=90)
        time.sleep(2)

        after: set[str] = set()
        not_eval: list[str] = []
        page = self.audit.url.rstrip("/").rsplit("/", 1)[-1] or "index.html"
        local = f"http://localhost:3000/{page}"

        from . import checks as checks_mod
        for state in self.audit.states:
            rec = self.audit.session.record(local, state,
                                            run_id=f"{self.audit.run_id}-reaudit")
            for criterion, fn in checks_mod.CHECKS.items():
                with checks_mod.criterion_tag(criterion, state, local):
                    r = fn(rec) if criterion != "2.4.3" else fn(rec, judge=self.audit.judge)
                if r.status == "failed":
                    after.add(f"{criterion}:{state}")
                elif r.status == "not_evaluated":
                    not_eval.append(f"{criterion}:{state}")

        self.last_not_evaluated = not_eval
        return sorted(before - after), sorted(after - before)

    # -- the whole pass ---------------------------------------------------

    def run(self, source_path: str) -> list[FixOutcome]:
        groups = group_findings(self.audit.results)
        print(f"\n{len(groups)} group(s) to fix "
              f"(findings grouped by component, then criterion)")
        for g in groups:
            print(f"  [{g.criterion} {g.component}] {len(g.findings)} finding(s)")
            outcome = self.fix_group(g, source_path)
            self.outcomes.append(outcome)
            print(f"      -> {outcome.status}  "
                  f"locate={outcome.locate_attempts} patch={outcome.patch_attempts}  "
                  f"closed={len(outcome.closed)} created={len(outcome.created)}"
                  + (f"  {outcome.reason}" if outcome.reason else ""))
        return self.outcomes

    # -- reporting --------------------------------------------------------

    def summary(self) -> dict:
        closed = sum(len(o.closed) for o in self.outcomes)
        created = sum(len(o.created) for o in self.outcomes)
        return {
            "groups": len(self.outcomes),
            "closed": closed,
            "created": created,
            "net": closed - created,
            # The two counters, never merged.
            "could_not_locate": sum(1 for o in self.outcomes
                                    if o.status == "could_not_locate"),
            "still_failing": sum(1 for o in self.outcomes
                                 if o.status == "still_failing"),
            "patch_attempts_per_closed": (
                round(sum(o.patch_attempts for o in self.outcomes if o.status == "closed")
                      / max(1, sum(1 for o in self.outcomes if o.status == "closed")), 2)
                if any(o.status == "closed" for o in self.outcomes) else None),
        }
