"""The five criteria our agent owns. All five read one recording.

Each check is a root-level Weave op, never nested inside a run trace, because
Signals only score root traces -- fifty judgements under one parent means one
gets scored. Each call is tagged with its criterion through `weave.attributes`,
and queries filter on that attribute rather than on op name. Op names carry a
content hash that changes whenever the function is edited, so a filter written
against a bare op name silently matches nothing.

Four of the five are arithmetic. Only Focus Order asks a model, and Focus
Visible asks one only when the pixel difference is too small to call.
"""

from __future__ import annotations

import contextlib

from .recording import (Census, Recording, Result, exclusion_summary, failed,
                        not_evaluated, passed)

try:
    import weave
except ImportError:  # the checks still run without Weave installed
    weave = None


def _op(fn):
    return weave.op()(fn) if weave else fn


@contextlib.contextmanager
def criterion_tag(criterion: str, state: str, url: str):
    """Tag the call so `get_calls` can filter on criterion, not op name."""
    if weave is None:
        yield
        return
    with weave.attributes({"criterion": criterion, "state": state, "url": url}):
        yield


def _gate(rec: Recording, criterion: str) -> Result | None:
    """Preconditions shared by every check (SCOPE rule 5.1).

    A check that runs against evidence it does not have produces a verdict
    grounded in nothing, which is worse than no verdict.
    """
    if not rec.state_reached:
        return not_evaluated(criterion, rec.state,
                             f"state not reached: {rec.reach_note}")
    if len(rec.stops) < 2:
        return not_evaluated(criterion, rec.state,
                             "no keyboard activity recorded: fewer than two focus stops")
    return None


# --------------------------------------------------------------------------
# 2.1.1 Keyboard
# --------------------------------------------------------------------------

@_op
def check_keyboard(rec: Recording) -> Result:
    """Every interactive element, against the elements Tab actually reached.

    The candidate list is merged from three sources upstream, because a div
    acting as a button is in none of them alone: it has no interactive role so
    the accessibility tree omits it, and it is not focusable so the focus stops
    omit it too. Both lists agreeing is exactly how the defect escapes.
    """
    if (skip := _gate(rec, "2.1.1")):
        return skip
    n_ex, ex_note = exclusion_summary(rec)
    if not rec.candidates:
        return not_evaluated("2.1.1", rec.state,
                             "no interactive elements were captured, so there is "
                             "nothing to compare the focus stops against",
                             census=Census(excluded=n_ex, exclusion_note=ex_note))

    reached = {s.selector for s in rec.stops}
    missed = [c for c in rec.candidates if not c.focusable and c.selector not in reached]
    # Every candidate is examined: either it is focusable or Tab reached it
    # (passed), or neither is true (failed). Nothing here is undecided, and the
    # elements the scan skipped are reported beside the count rather than
    # vanishing out of it.
    census = Census(examined=len(rec.candidates), failed=len(missed),
                    passed=len(rec.candidates) - len(missed),
                    excluded=n_ex, exclusion_note=ex_note)
    if not missed:
        return passed("2.1.1", rec.state,
                      f"all {len(rec.candidates)} interactive elements were reached by Tab",
                      census=census)

    return failed(
        "2.1.1", rec.state, census=census,
        evidence_refs=[c.cite for c in missed],
        targets=[c.selector for c in missed],
        summary=(f"{len(missed)} interactive element"
                 f"{'' if len(missed) == 1 else 's'} carry a click handler but are "
                 "not focusable, so the keyboard never reaches them: "
                 + ", ".join(f"{c.tag.lower()}{'' if not c.name else ' “' + c.name[:30] + '”'}"
                             for c in missed[:3])),
    )


# --------------------------------------------------------------------------
# 2.1.2 No Keyboard Trap
# --------------------------------------------------------------------------

@_op
def check_no_trap(rec: Recording) -> Result:
    """Focus never leaves, or the same element keeps repeating.

    Stop 0 matters here. Tab legitimately closes an ARIA menu, so a recording
    that starts after the first Tab is already outside the menu and the trap is
    invisible. The comparison is "focus was on this, Tab was pressed, focus is
    still on this", and stop 0 is the left-hand side.
    """
    if (skip := _gate(rec, "2.1.2")):
        return skip

    repeats: list[tuple] = []
    run_start = 0
    for i in range(1, len(rec.stops)):
        if rec.stops[i].selector == rec.stops[i - 1].selector:
            if not repeats or repeats[-1][1] != i - 1:
                run_start = i - 1
            repeats.append((run_start, i))

    # One Tab press is one examined element: focus either moved (passed) or did
    # not (failed). A truncated sequence means focus never left the page at all,
    # which fails on the last press rather than on a repeat.
    presses = len(rec.stops) - 1
    census = Census(examined=presses, failed=len(repeats),
                    passed=presses - len(repeats))
    if not repeats:
        if rec.truncated:
            return failed(
                "2.1.2", rec.state,
                census=Census(examined=presses, failed=1, passed=presses - 1),
                evidence_refs=[rec.stops[-1].cite],
                targets=[rec.stops[-1].selector],
                summary=(f"focus never left the page: {len(rec.stops)} Tab presses without "
                         "returning to the document, so the sequence was cut off"),
            )
        return passed("2.1.2", rec.state, census=census,
                      summary=f"focus moved on every one of {presses} Tab presses "
                              "and left the page at the end")

    stuck = {rec.stops[j].selector for _, j in repeats}
    refs = sorted({rec.stops[i].cite for pair in repeats for i in pair},
                  key=lambda r: int(r.split()[1]))
    return failed(
        "2.1.2", rec.state, evidence_refs=refs, targets=sorted(stuck), census=census,
        summary=(f"focus stayed on the same element across a Tab press "
                 f"{len(repeats)} time{'' if len(repeats) == 1 else 's'}: "
                 + ", ".join(sorted(stuck)[:3])),
    )


# --------------------------------------------------------------------------
# 2.4.11 Focus Not Obscured (Minimum)
# --------------------------------------------------------------------------

@_op
def check_not_obscured(rec: Recording) -> Result:
    """Something is painted on top of the element that has focus.

    Decided in the browser with elementFromPoint at the focused element's own
    centre, recorded per stop as `obscured_by`. Comparing rectangles here would
    re-derive what the renderer already knows and get stacking contexts wrong.
    """
    if (skip := _gate(rec, "2.4.11")):
        return skip

    hidden = [s for s in rec.stops if s.obscured_by]
    # elementFromPoint needs a point, so a stop with no box on screen has
    # nothing to check rather than being quietly counted as visible.
    testable = [s for s in rec.stops if s.w > 0 and s.h > 0]
    census = Census(examined=len(testable), failed=len(hidden),
                    passed=len(testable) - len(hidden),
                    inapplicable=len(rec.stops) - len(testable))
    if not hidden:
        return passed("2.4.11", rec.state, census=census,
                      summary=f"every one of {len(testable)} focused elements was "
                              "visible at its own centre")

    return failed(
        "2.4.11", rec.state, census=census,
        evidence_refs=[s.cite for s in hidden],
        targets=[s.selector for s in hidden],
        summary=(f"{len(hidden)} focused element{'' if len(hidden) == 1 else 's'} "
                 "had something drawn over " + ("it" if len(hidden) == 1 else "them") + ": "
                 + ", ".join(f"{s.selector} behind {s.obscured_by}" for s in hidden[:3])),
    )


# --------------------------------------------------------------------------
# 2.4.7 Focus Visible
# --------------------------------------------------------------------------

#: Below this fraction of changed pixels, nothing visible happened.
#:
#: Calibrated against measurement, not guessed. A focused text input always
#: paints a blinking caret whether or not it has a focus indicator, and that
#: alone measured 0.0017 to 0.0020 on the two input fields of the control page.
#: A real outline on the same fields measured 0.1765 to 0.1795, and the switch's
#: border-and-background indicator 0.6861. The floor therefore sits above
#: caret-only and two orders of magnitude below any genuine indicator.
INVISIBLE_BELOW = 0.005
#: Above this, the indicator is unambiguous. Between the two is the band where
#: a person might or might not notice, and the only part that is a judgement.
VISIBLE_ABOVE = 0.02


@_op
def check_focus_visible(rec: Recording, borderline_judge=None) -> Result:
    """The screenshot before and after focus lands, cropped to the element.

    `focus_delta` is the fraction of pixels that changed, computed in code.
    Two thresholds and a band between them: under the floor nothing changed,
    over the ceiling something clearly did, and in between a human might or
    might not notice, which is the only part that is a judgement.
    """
    if (skip := _gate(rec, "2.4.7")):
        return skip

    after_tab = [s for s in rec.stops if s.index > 0]
    measured = [s for s in after_tab if s.focus_delta is not None]
    # A stop with no frame pair has nothing to check. Counting it as a pass is
    # the exact mistake this census exists to make impossible.
    no_pair = len(after_tab) - len(measured)
    if not measured:
        return not_evaluated("2.4.7", rec.state,
                             "no focus-indicator comparison was captured: the check "
                             "needs a screenshot before and after each Tab press",
                             census=Census(inapplicable=no_pair))

    invisible = [s for s in measured if s.focus_delta < INVISIBLE_BELOW]
    borderline = [s for s in measured
                  if INVISIBLE_BELOW <= s.focus_delta < VISIBLE_ABOVE]

    # The band between the thresholds is the only judgement in this check. With
    # no judge those stops are undecided, not passed: nobody looked at them.
    undecided = list(borderline)
    if borderline and borderline_judge is not None:
        undecided = []
        for stop in borderline:
            verdict = borderline_judge(stop)
            if verdict is False:
                invisible.append(stop)
            elif verdict is None:
                undecided.append(stop)

    census = Census(examined=len(measured), failed=len(invisible),
                    undecided=len(undecided),
                    passed=len(measured) - len(invisible) - len(undecided),
                    inapplicable=no_pair)
    if not invisible:
        note = (f"; {len(undecided)} borderline and undecided" if undecided else "")
        return passed("2.4.7", rec.state, census=census,
                      summary=f"the focus indicator changed the screen at all "
                              f"{len(measured)} stops{note}")

    invisible.sort(key=lambda s: s.index)
    return failed(
        "2.4.7", rec.state, census=census,
        evidence_refs=[s.cite for s in invisible],
        targets=[s.selector for s in invisible],
        summary=(f"{len(invisible)} control{'' if len(invisible) == 1 else 's'} showed "
                 "no visible change when focus landed: "
                 + ", ".join(f"{s.selector} ({s.focus_delta:.4f} of pixels changed)"
                             for s in invisible[:3])),
    )


# --------------------------------------------------------------------------
# 2.4.3 Focus Order
# --------------------------------------------------------------------------

def _ordered_stops(rec: Recording) -> list:
    """The stops 2.4.3 compares: one lap, real controls only.

    Two exclusions, both because an element that is not a new position must not
    be treated as one.

    **The lap closes at the first repeat.** Focus cycles: a modal dialog does it
    by design, and an ordinary page wraps back to its first control. The
    recorder captures a full lap plus the start of a second, so the same element
    appears at both ends of the sequence. Reading order sorts the revisit by its
    position and puts it near the front while tab order has it last, and the
    comparison diverges at position 0 on a page with no defects in it. That was
    the whole of 2.4.3's three false positives on the control page.

    Stop 0 counts for identity even though it is not itself a Tab destination:
    it is where focus sat on entry, so a later stop matching it is the lap
    closing. Ignoring it made the first revisit look like a first visit and the
    dialog kept diverging.

    **BODY is the wrap marker**, not a control. It sits at (0,0) and would sort
    to the front of reading order.
    """
    seen: set = set()
    kept: list = []
    for s in rec.stops:
        key = (s.selector, s.x, s.y)
        if s.index > 0 and key in seen:
            break                      # the lap closed; the rest is a second lap
        seen.add(key)
        if s.index > 0 and s.h > 0 and s.tag not in ("BODY", "HTML"):
            kept.append(s)
    return kept


def reading_order(rec: Recording) -> list[int]:
    """The order a sighted person would read these stops: top down, then left.

    Banded by row so that two controls side by side are not called out of order
    because one sits three pixels lower.
    """
    indexed = _ordered_stops(rec)
    band = 24
    return [s.index for s in sorted(indexed, key=lambda s: (round(s.y / band), s.x))]


@_op
def check_focus_order(rec: Recording, judge=None) -> Result:
    """Tab order against reading order, then a model on whether it matters.

    The arithmetic finds every difference. Most differences are harmless, so a
    model decides which ones a keyboard user would actually be hurt by, and it
    must cite the stops that prove it (rule 5.2). A citation that does not
    resolve against this recording is dropped by the caller.
    """
    if (skip := _gate(rec, "2.4.3")):
        return skip

    ordered = _ordered_stops(rec)
    tab_order = [s.index for s in ordered]
    # Stops dropped by _ordered_stops -- a closed lap, zero height, BODY -- have
    # no position to order, so they are inapplicable rather than absent.
    skipped = len(rec.stops) - len(ordered)
    if len(tab_order) < 2:
        return not_evaluated("2.4.3", rec.state,
                             "fewer than two positioned stops, so there is no order "
                             "to compare",
                             census=Census(inapplicable=skipped))

    expected = reading_order(rec)
    if tab_order == expected:
        return passed("2.4.3", rec.state,
                      summary=f"tab order matches reading order across "
                              f"{len(tab_order)} stops",
                      census=Census(examined=len(tab_order), passed=len(tab_order),
                                    inapplicable=skipped))

    out_of_place = [i for i, (a, b) in enumerate(zip(tab_order, expected)) if a != b]
    # Arithmetic found a difference; whether it hurts anyone is the judgement.
    # Without a verdict those stops are undecided, and the ones in the right
    # place are still genuinely passed.
    undecided_census = Census(examined=len(tab_order), undecided=len(out_of_place),
                              passed=len(tab_order) - len(out_of_place),
                              inapplicable=skipped)
    if judge is None:
        return not_evaluated("2.4.3", rec.state,
                             "tab order differs from reading order but no judge was "
                             "available to decide whether the difference matters",
                             census=undecided_census)

    verdict = judge(rec, tab_order, expected)
    if verdict is None:
        return not_evaluated("2.4.3", rec.state,
                             "the judge returned no usable verdict",
                             census=undecided_census)
    if verdict.get("status") == "passed":
        return passed("2.4.3", rec.state,
                      summary=f"tab order differs from reading order at "
                              f"{len(out_of_place)} positions, judged not to "
                              "disadvantage a keyboard user",
                      census=Census(examined=len(tab_order), passed=len(tab_order),
                                    inapplicable=skipped))
    if verdict.get("status") == "not_evaluated":
        return not_evaluated("2.4.3", rec.state,
                             verdict.get("reason") or "the judge could not decide",
                             census=undecided_census)

    refs = tuple(verdict.get("evidence_refs") or ())
    if not refs:
        return not_evaluated("2.4.3", rec.state,
                             "the judge reported a failure without citing any stop, so "
                             "there is nothing to verify it against",
                             census=undecided_census)
    # Rule 5.2, and this is the whole point of it: a citation that does not
    # resolve against this recording was invented, so the finding it supports
    # is discarded rather than reported with the bad ref quietly dropped.
    # Deterministic code, no model involved.
    phantom = rec.unresolved(refs)
    good = tuple(r for r in refs if r not in phantom)
    if not good:
        return not_evaluated(
            "2.4.3", rec.state,
            f"the judge cited {len(phantom)} stop(s) that are not in this recording "
            f"({', '.join(phantom[:3])}), so the finding is unsupported",
            census=undecided_census)

    cited = [rec.resolve(r) for r in good]
    note = (f" ({len(phantom)} invented citation(s) discarded)" if phantom else "")
    return failed(
        "2.4.3", rec.state, evidence_refs=good,
        census=Census(examined=len(tab_order), failed=len(good),
                      passed=max(0, len(tab_order) - len(good)),
                      inapplicable=skipped),
        targets=[c.selector for c in cited if c is not None],
        summary=(verdict.get("summary")
                 or f"tab order does not follow reading order at {len(good)} stops") + note,
    )


CHECKS = {
    "2.1.1": check_keyboard,
    "2.1.2": check_no_trap,
    "2.4.3": check_focus_order,
    "2.4.7": check_focus_visible,
    "2.4.11": check_not_obscured,
}
