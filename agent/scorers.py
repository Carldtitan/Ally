"""The three scores, as Weave objects rather than arithmetic buried in a script.

Each one already existed somewhere in the codebase. As a `weave.Scorer` it
becomes a published object with a version, so a change to how we score is a diff
a reader can open rather than a line that moved in a report. That matters here
more than usual: the scoreboard read 8 of 15 for two days while the checks were
finding 14, and the bug was in the scoring, not the checking.

  * **FoundPlantedDefect** -- did the run report the element the defect was
    planted on? Matches on element identity collected from the DOM, with an
    ancestor counting, never on selector strings. That is the fix for the bug
    above.
  * **PatchCreatedNewFindings** -- did the fix break something that worked? A
    patcher that closes one finding and opens two is worse than no patcher, and
    this is the only number that says so.
  * **EvidenceReferenceResolved** -- does every citation resolve against the
    recording it claims to come from? SCOPE rule 5.2. Deterministic, no model
    involved: a ref that does not resolve was invented, and the finding it
    supports is discarded rather than reported with the bad ref quietly dropped.

`Scorer.score` is keyword-only on `output` in weave 0.52, and any other argument
is filled from the dataset row by name.
"""

from __future__ import annotations

from typing import Any

import weave


class FoundPlantedDefect(weave.Scorer):
    """Did the run name the element this defect was planted on?

    `output` is the run's reported targets for one criterion; the dataset row
    supplies the defect. Matching is on element identity -- what the element is,
    and what it sits inside -- because the manifest names elements by class or
    role and the recorder addresses them by id or by DOM path. Those are
    different questions about the same element.
    """

    def score(self, *, output: Any, selector: str = "", region: str = "",
              anchors: dict | None = None, **kwargs: Any) -> dict:
        from scorer.score import matches

        targets = list(output or ())
        index = anchors or {}
        defect = {"selector": selector, "region": region}
        hits = [t for t in targets if matches(t, defect, index)]
        return {
            "found": bool(hits),
            "matched_targets": hits,
            # A run that reported nothing at all is a different failure from one
            # that reported the wrong element, and the summary should not merge
            # them.
            "reported_anything": bool(targets),
        }


class PatchCreatedNewFindings(weave.Scorer):
    """Did the fix open findings that were not there before?

    Closing three and opening four is a regression that a "findings closed"
    count reports as progress. Both numbers travel together or neither means
    anything.
    """

    def score(self, *, output: Any, **kwargs: Any) -> dict:
        before = {self._key(f) for f in (kwargs.get("before") or ())}
        after = {self._key(f) for f in (output or ())}
        created = sorted(after - before)
        closed = sorted(before - after)
        return {
            "created": len(created),
            "closed": len(closed),
            "net_closed": len(closed) - len(created),
            "clean": not created,
            "created_findings": created[:10],
        }

    @staticmethod
    def _key(f: Any) -> str:
        if isinstance(f, dict):
            return f"{f.get('criterion')}|{f.get('state')}|{','.join(f.get('targets') or [])}"
        return str(f)


class EvidenceReferenceResolved(weave.Scorer):
    """Does every citation resolve against the recording it came from?

    SCOPE rule 5.2. The judge cites stops by ref; a ref that names a stop this
    recording does not contain was invented. Deterministic on purpose -- asking
    a model whether a model hallucinated is not a check.
    """

    def score(self, *, output: Any, known_refs: list | None = None,
              **kwargs: Any) -> dict:
        cited = list(output or ())
        known = set(known_refs or ())
        phantom = [r for r in cited if r not in known]
        return {
            "all_resolved": not phantom,
            "cited": len(cited),
            "phantom": len(phantom),
            "phantom_refs": phantom[:6],
        }


#: Every scorer this system uses, for the publish step.
ALL = {
    "found-planted-defect": FoundPlantedDefect,
    "patch-created-new-findings": PatchCreatedNewFindings,
    "evidence-reference-resolved": EvidenceReferenceResolved,
}


def publish_all() -> dict:
    """Publish one instance of each scorer and return name -> ref URI."""
    out = {}
    for name, cls in ALL.items():
        inst = cls()
        inst.name = name
        inst.description = (cls.__doc__ or "").strip().split("\n")[0]
        out[name] = str(weave.publish(inst, name=name).uri())
    return out
