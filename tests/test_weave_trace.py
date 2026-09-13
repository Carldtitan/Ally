"""Verification rule 8: a check call must actually arrive in Weave.

Weave is a judging criterion, and for the whole build up to 2026-09-12 not one
trace was saved. `weave.init` succeeded, the ops ran, the results were correct,
and every call was dropped on the way out.

The cause was a name collision. Weave decides whether an object is already
saved with `get_ref(obj)`, which is literally `getattr(obj, "ref", None)`. Our
`Stop.ref` and `Candidate.ref` returned citation strings like "stop 3" for
SCOPE rule 5.2, so Weave took a str for an ObjectRef and called `ref.project`
on it. `_save_nested_objects` raised AttributeError, the call was discarded,
and the only visible sign was one suppressed warning line.

Nothing in the codebase could have caught this: the checks return the right
answers whether or not the trace saves. So this test does the one thing that
distinguishes them -- it runs a real check under a real client, then asks the
server whether the call is there.

Usage:
    python tests/test_weave_trace.py
"""

from __future__ import annotations

import sys
import time
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import wb_env  # noqa: E402

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

from agent import checks  # noqa: E402
from agent.recording import Candidate, Recording, Stop  # noqa: E402


def a_recording() -> Recording:
    """A Recording holding both objects that carried the bad property.

    No sandbox. The bug is in serialisation, not in the browser, so a synthetic
    recording exercises it exactly as a real one does.
    """
    rec = Recording(url="https://example.test/", state="loaded",
                    state_reached=True, reach_note="synthetic")
    rec.stops = [
        Stop(index=0, tag="BODY", role=None, name=None, x=0, y=0, w=0, h=0,
             selector="body", vx=0, vy=0),
        Stop(index=1, tag="BUTTON", role="button", name="Go", x=10, y=20,
             w=80, h=30, selector="#go", vx=10, vy=20, focus_delta=0.18),
        Stop(index=2, tag="INPUT", role="textbox", name="Email", x=10, y=60,
             w=200, h=30, selector="#email", vx=10, vy=60, focus_delta=0.002),
    ]
    rec.candidates = [
        Candidate(selector="#fake", tag="DIV", role=None, name="Submit",
                  x=10, y=100, w=80, h=30, focusable=False, sources=("tree",)),
    ]
    return rec


def main() -> int:
    try:
        import weave
    except ImportError:
        print("FAIL: weave is not installed, so tracing cannot be verified")
        return 1

    cfg = wb_env.bootstrap()
    client = weave.init(cfg["ref"])
    print(f"weave.init -> {cfg['ref']}")

    # A marker only this run uses, so the query cannot pick up an older call.
    marker = f"trace-test-{int(time.time())}"
    rec = a_recording()

    ran = []
    for criterion in ("2.1.1", "2.1.2", "2.4.7", "2.4.11"):
        with checks.criterion_tag(criterion, marker, rec.url):
            result = checks.CHECKS[criterion](rec)
        ran.append((criterion, result.status))
    print(f"ran {len(ran)} checks: " + ", ".join(f"{c}={s}" for c, s in ran))

    # Without the flush the query races the background exporter, and a pass
    # here would mean "not yet sent" rather than "sent and stored".
    client.finish()

    found, attempts = [], 0
    for attempt in range(1, 13):
        attempts = attempt
        found = [c for c in client.get_calls()
                 if (c.attributes or {}).get("state") == marker]
        if len(found) >= len(ran):
            break
        time.sleep(2.0)

    print(f"queried the server {attempts} time(s): {len(found)} call(s) "
          f"carry state={marker!r}")

    if len(found) < len(ran):
        print(f"\nFAIL: ran {len(ran)} traced checks, {len(found)} arrived.")
        print("The calls were dropped between the op and the server. A `ref`")
        print("property on an object inside the payload is the known cause;")
        print("see the module docstring.")
        return 1

    # The payload must survive too. A call that arrives with its inputs
    # stripped is not a trace record of anything.
    bad = [c for c in found if not (c.inputs or {})]
    if bad:
        print(f"\nFAIL: {len(bad)} call(s) arrived with no inputs recorded.")
        return 1

    crits = sorted({(c.attributes or {}).get("criterion") for c in found})
    print(f"criteria tagged on the arrived calls: {crits}")
    print("\nPASS: every traced check arrived with its inputs intact.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
