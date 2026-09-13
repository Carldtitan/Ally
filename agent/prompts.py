"""The two prompts, as published Weave objects rather than string literals.

A prompt is the part of this system most likely to change and least likely to be
recorded when it does. As a `weave.StringPrompt` each edit becomes a version with
a URI, so "the judge got better" is a diff between two objects a reader can open
rather than a claim.

**These are the objects the code runs, not copies of them.** `judge.py` and
`patcher.py` import from here, so publishing cannot drift from what executed.

Substitution is `.replace()` on `__PLACEHOLDER__`, never `str.format`. Both
prompts show JSON objects to the model and `format` reads their braces as field
references, which is why the placeholders look like this.
"""

from __future__ import annotations

try:
    import weave
except ImportError:  # the prompts are still usable without Weave installed
    weave = None


def _prompt(name: str, description: str, content: str):
    """A StringPrompt when Weave is available, otherwise something with .content.

    `StringPrompt.__init__` takes only `content` in weave 0.52 -- `name` and
    `description` are model fields set afterwards, not constructor arguments.
    """
    if weave is not None:
        p = weave.StringPrompt(content=content)
        p.name = name
        p.description = description
        return p

    class _Local:
        def __init__(self, c: str) -> None:
            self.content = c

    return _Local(content)


FOCUS_ORDER_JUDGE = _prompt(
    "focus-order-judge",
    "Decides whether a tab-order/reading-order difference disadvantages a "
    "keyboard user, and must cite the stops that prove it (SCOPE rule 5.2).",
    """You judge WCAG 2.4.3 Focus Order on one page state.

Below are the elements the keyboard reached, in the order Tab reached them, and
the order a sighted person would read them, derived from their positions on the
page. Positions are document coordinates in CSS pixels.

A difference between the two orders is not automatically a failure. Decide
whether this particular difference would disadvantage someone using a keyboard.

Reply as JSON only.
  matches, or the difference is harmless -> {"status": "passed", "summary": "..."}
  the difference disadvantages a keyboard user ->
      {"status": "failed", "evidence_refs": ["stop 3", "stop 5"], "summary": "..."}
  you cannot tell from this evidence ->
      {"status": "not_evaluated", "reason": "..."}

evidence_refs is REQUIRED on a failed verdict. Each entry names a stop from the
list below, written exactly as "stop N", and must be one of the stops where the
order actually goes wrong. Do not use reason on a failed verdict.

State: __STATE__

Tab order reached these stops, in this order:
__TAB_ROWS__

Reading order derived from position would be:
__READING_ROWS__
""")


PATCHER_FIND_REPLACE = _prompt(
    "patcher-find-replace",
    "Turns findings into literal find/replace pairs. Carries the lessons-table "
    "rows for this criterion, failures included and labelled as failures.",
    """You fix accessibility defects by returning find-and-replace pairs.

Criterion: __CRITERION__
Component: __COMPONENT__

What the audit found:
__FINDINGS__

The source file is __PATH__. Here it is:
--- BEGIN __PATH__ ---
__SOURCE__
--- END __PATH__ ---

__LESSONS__
Return JSON only:
{"rationale": "one sentence", "edits": [{"path": "...", "find": "...", "replace": "..."}]}

Rules for `find`:
  It must appear EXACTLY ONCE in the file. Include enough surrounding text to
  be unique; a short fragment that appears twice will be rejected.
  Copy it character for character from the source above, including whitespace.
  Never write an elision note such as "rest of the file unchanged": anything
  you omit from `replace` is deleted.

Fix every listed instance in one response, using the same technique for each.
Mixing techniques across instances of one component is how a fix breaks voice
control: the visible text and the announced name stop matching.
__RETRY__""")


#: Every prompt this system runs, for the publish step.
ALL = {
    "focus-order-judge": FOCUS_ORDER_JUDGE,
    "patcher-find-replace": PATCHER_FIND_REPLACE,
}


def publish_all() -> dict:
    """Publish each prompt and return name -> ref URI.

    Re-publishing unchanged content is a no-op version-wise; a changed prompt
    becomes a new version under the same name, which is the point.
    """
    if weave is None:
        raise RuntimeError("weave is not installed, so prompts cannot be published")
    out = {}
    for name, p in ALL.items():
        out[name] = str(weave.publish(p, name=name).uri())
    return out
