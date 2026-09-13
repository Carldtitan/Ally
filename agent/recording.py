"""The recording: what one Tab run through one page state produced.

Every one of the five checks reads this and nothing else. It is the single
piece of evidence in the system, which is why `evidence_refs` can be resolved
against it deterministically (SCOPE rule 5.2).

Three things the shape enforces:

  * **A result has three cases, not two.** `not_evaluated` carries a reason and
    the type will not let you construct it without one. A check that could not
    run must say so rather than being recorded as a pass.
  * **Screenshots are refs, never bytes.** `Stop.screenshot` holds what
    `ally.storage.save_screenshot` returned. The 1GB Weave cap is one benchmark
    run away if bytes ever reach an op input.
  * **Stop 0 exists.** The element focused when the state was entered, before
    any Tab. The evidence for a keyboard trap is "focus was here, Tab was
    pressed, focus is still here", and stop 0 is half of that comparison.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Literal


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------

Status = Literal["passed", "failed", "not_evaluated"]


@dataclass(frozen=True)
class Result:
    """One criterion's verdict on one state.

    Build with the constructors below, never directly: `not_evaluated` without
    a reason is the bug this whole type exists to prevent.
    """

    criterion: str
    state: str
    status: Status
    #: Required when status is not_evaluated. Never set otherwise.
    reason: str | None = None
    #: Refs into the recording that prove a failure. Required when failed.
    evidence_refs: tuple[str, ...] = ()
    #: One sentence for the report.
    summary: str = ""
    #: Which planted-defect-shaped thing was found, for the scorer to match on.
    targets: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.status == "not_evaluated" and not self.reason:
            raise ValueError(
                f"{self.criterion}: not_evaluated requires a reason. An unexplained "
                "not_evaluated is indistinguishable from a pass, which is the "
                "failure this type exists to prevent."
            )
        if self.status != "not_evaluated" and self.reason:
            raise ValueError(f"{self.criterion}: reason belongs only on not_evaluated")
        if self.status == "failed" and not self.evidence_refs:
            raise ValueError(
                f"{self.criterion}: a failure must cite evidence. Without a ref there "
                "is nothing for the resolution check to verify against."
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def passed(criterion: str, state: str, summary: str = "") -> Result:
    return Result(criterion=criterion, state=state, status="passed", summary=summary)


def failed(criterion: str, state: str, evidence_refs: tuple[str, ...] | list[str],
           summary: str, targets: tuple[str, ...] | list[str] = ()) -> Result:
    return Result(criterion=criterion, state=state, status="failed",
                  evidence_refs=tuple(evidence_refs), summary=summary,
                  targets=tuple(targets))


def not_evaluated(criterion: str, state: str, reason: str) -> Result:
    return Result(criterion=criterion, state=state, status="not_evaluated", reason=reason)


# --------------------------------------------------------------------------
# The recording
# --------------------------------------------------------------------------

@dataclass
class Stop:
    """One focus position. Index 0 is the state-entry stop, before any Tab."""

    index: int
    tag: str
    role: str | None
    #: Computed by the accessibility tree, never read off the element. On the
    #: clean app the naive `innerText || value || aria-label` disagreed with the
    #: tree on 7 of 10 stops: labelled inputs came back empty and a switch
    #: returned its value as its name.
    name: str | None
    #: Document coordinates, not viewport. The page scrolls as focus moves, so
    #: viewport y is non-monotonic and reading order derived from it is wrong.
    x: int
    y: int
    w: int
    h: int
    selector: str
    #: What storage.save_screenshot returned. A path or a URL. Never bytes.
    screenshot: str | None = None
    #: Is the focused element the one painted at its own centre? (2.4.11)
    obscured_by: str | None = None
    #: Pixel difference against the previous frame, cropped to this element.
    focus_delta: float | None = None

    @property
    def ref(self) -> str:
        """The citation form. `evidence_refs` entries look exactly like this."""
        return f"stop {self.index}"


@dataclass
class Candidate:
    """An element that looks interactive, from any of the three 2.1.1 sources."""

    selector: str
    tag: str
    role: str | None
    name: str | None
    x: int
    y: int
    w: int
    h: int
    focusable: bool
    #: "tree", "dom-query" or "listeners"
    sources: tuple[str, ...] = ()

    @property
    def ref(self) -> str:
        return f"candidate {self.selector}"


@dataclass
class Recording:
    """One Tab run through one state."""

    url: str
    state: str
    #: False when the reach step did not change the DOM. Every criterion for
    #: this state is then not_evaluated with that reason, rather than being
    #: judged against a state we never actually entered.
    state_reached: bool
    reach_note: str
    stops: list[Stop] = field(default_factory=list)
    candidates: list[Candidate] = field(default_factory=list)
    #: True when the Tab loop hit its cap instead of wrapping.
    truncated: bool = False
    viewport: tuple[int, int] = (1024, 740)
    page_height: int = 0

    # -- evidence resolution (SCOPE rule 5.2) ------------------------------

    def resolve(self, ref: str) -> Stop | Candidate | None:
        """Look up a cited ref. Returns None when the model invented it.

        Deterministic, no model involved. This is the check that does most of
        the work of keeping unsupported findings out of the report.
        """
        ref = (ref or "").strip()
        if ref.startswith("stop "):
            try:
                index = int(ref[len("stop "):])
            except ValueError:
                return None
            for stop in self.stops:
                if stop.index == index:
                    return stop
            return None
        if ref.startswith("candidate "):
            want = ref[len("candidate "):]
            for c in self.candidates:
                if c.selector == want:
                    return c
        return None

    def unresolved(self, refs) -> list[str]:
        """Which of these refs point at nothing. Empty means all resolved."""
        return [r for r in refs if self.resolve(r) is None]

    def to_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "state": self.state,
            "state_reached": self.state_reached,
            "reach_note": self.reach_note,
            "truncated": self.truncated,
            "viewport": list(self.viewport),
            "page_height": self.page_height,
            "stops": [asdict(s) for s in self.stops],
            "candidates": [asdict(c) for c in self.candidates],
        }
