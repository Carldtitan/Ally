"""The patcher: findings in, find-and-replace pairs out, applied by our code.

Never send a file to a model and take a whole file back. A 2,231 line file came
back with 4,033 changed lines for a task that needed three attributes added.
The model returns a short piece of existing text and its replacement; this
module does the search and the substitution.

**Two counters that mean opposite things.** Keep them apart everywhere.

  Locate attempts. The text the model asked us to find is not in the file, or
  matches more than once. We reply with what is really there and it tries
  again. Three attempts, then `not_evaluated: could not locate the code`. Zero
  patches were applied, so this has no position on a patch-attempt axis.

  Patch attempts. The patch applied cleanly, we rebuilt and re-audited, and the
  finding is still open. The fix was wrong. Five attempts, then
  `not_evaluated: still failing after 5 patches`.

A finding can locate perfectly every time and never close.

**One copy of a patch exists, and it lives in a file.** The planner writes it,
the approval screen reads that file, the applier reads the same file. A
fingerprint is taken at write time and checked before applying, so the bytes
somebody approved are the bytes that land. AccessiFix compared a patch against
a freshly regenerated one from the same pure function, which is a check that
could never fail.

**Findings are grouped before anything is sent.** Twenty violations of the same
component are one request, not twenty. Independent requests mean the model has
no memory of the fix it just wrote, and A11YRepair documented three icons
getting two different techniques, which broke voice control. Coarse grouping
solved 59% and created 377 new problems; fine grouping solved 78% and created
172.
"""

from __future__ import annotations

import os
import re
import json
import time
import hashlib
import pathlib
from dataclasses import dataclass, field, asdict

from .recording import Result

try:
    import weave
except ImportError:
    weave = None


def _op(fn):
    return weave.op()(fn) if weave else fn


MAX_LOCATE_ATTEMPTS = 3
MAX_PATCH_ATTEMPTS = 5

MODEL = "meta-llama/Llama-3.3-70B-Instruct"
MAX_TOKENS = 2000


# --------------------------------------------------------------------------
# Grouping
# --------------------------------------------------------------------------

@dataclass
class Group:
    """Findings that should be fixed together: one component, one criterion."""

    criterion: str
    component: str
    findings: list[Result] = field(default_factory=list)
    targets: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return f"{self.criterion}:{self.component}"


def component_of(selector: str) -> str:
    """The component a selector belongs to, for grouping.

    The nearest identified ancestor if there is one, otherwise the top of the
    path. Crude on purpose: the point is that instances of the same component
    travel together, not that the name is pretty.
    """
    if not selector:
        return "page"
    ids = re.findall(r"#([A-Za-z0-9_\-]+)", selector)
    if ids:
        return f"#{ids[0]}"
    return selector.split(">")[0].strip() or "page"


def group_findings(results: list[Result]) -> list[Group]:
    """Group open failures by component, then by criterion."""
    groups: dict[str, Group] = {}
    for r in results:
        if r.status != "failed":
            continue
        for target in (r.targets or ("page",)):
            comp = component_of(target)
            key = f"{r.criterion}:{comp}"
            g = groups.setdefault(key, Group(criterion=r.criterion, component=comp))
            if r not in g.findings:
                g.findings.append(r)
            if target not in g.targets:
                g.targets.append(target)
    return sorted(groups.values(), key=lambda g: (g.criterion, g.component))


# --------------------------------------------------------------------------
# The patch, as a file
# --------------------------------------------------------------------------

@dataclass
class Edit:
    """One find-and-replace. `find` must appear exactly once in the file."""

    path: str
    find: str
    replace: str


@dataclass
class PatchPlan:
    patch_id: str
    criterion: str
    component: str
    rationale: str
    edits: list[Edit]
    addresses: list[str] = field(default_factory=list)
    locate_attempts: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def plan_path(root: pathlib.Path, run_id: str, patch_id: str) -> pathlib.Path:
    return root / "runs" / run_id / "patches" / f"{patch_id}.json"


def write_plan(root: pathlib.Path, run_id: str, plan: PatchPlan) -> tuple[pathlib.Path, str]:
    """Write the one copy of this patch, and fingerprint it.

    Nothing regenerates the patch after this. The approval screen and the
    applier both read this file.
    """
    path = plan_path(root, run_id, plan.patch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(plan.to_dict(), indent=2, sort_keys=True)
    path.write_text(body, encoding="utf-8")
    return path, hashlib.sha256(body.encode()).hexdigest()


def read_plan(path: pathlib.Path, expect_fingerprint: str | None = None) -> PatchPlan:
    """Read a patch back, refusing it if the bytes changed since approval."""
    body = path.read_text(encoding="utf-8")
    if expect_fingerprint is not None:
        actual = hashlib.sha256(body.encode()).hexdigest()
        if actual != expect_fingerprint:
            raise ValueError(
                f"{path.name} changed after it was approved "
                f"({actual[:12]} != {expect_fingerprint[:12]}). Refusing to apply: "
                "the bytes somebody looked at are not the bytes on disk."
            )
    data = json.loads(body)
    data["edits"] = [Edit(**e) for e in data["edits"]]
    return PatchPlan(**data)


# --------------------------------------------------------------------------
# Applying
# --------------------------------------------------------------------------

@dataclass
class ApplyOutcome:
    applied: bool
    reason: str = ""
    #: Per-edit: how many times `find` matched. 1 is required.
    matches: list[int] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)


def apply_plan(plan: PatchPlan, workdir: pathlib.Path) -> ApplyOutcome:
    """Apply every edit, or none of them.

    All-or-nothing: a half-applied patch leaves the tree in a state nobody
    planned and the re-audit would be measuring something that was never
    proposed.
    """
    staged: dict[pathlib.Path, str] = {}
    matches: list[int] = []

    for edit in plan.edits:
        target = workdir / edit.path
        if not target.exists():
            return ApplyOutcome(False, f"{edit.path} does not exist in the checkout")
        text = staged.get(target, target.read_text(encoding="utf-8"))
        count = text.count(edit.find)
        matches.append(count)
        if count == 0:
            return ApplyOutcome(False, f"no match in {edit.path}", matches)
        if count > 1:
            return ApplyOutcome(False, f"{count} matches in {edit.path}", matches)
        staged[target] = text.replace(edit.find, edit.replace, 1)

    # A model that will not repeat a long stretch of code sometimes writes a
    # note in its place, and if that note lands in the file the code it
    # replaced is gone. Counting rather than searching: a genuine helper whose
    # name looks like such a note gave AccessiFix a false alarm.
    NOTES = ("rest of the file unchanged", "... unchanged ...", "rest of code",
             "unchanged code here", "// ... existing")
    for target, new_text in staged.items():
        old_text = target.read_text(encoding="utf-8")
        for note in NOTES:
            if new_text.lower().count(note) > old_text.lower().count(note):
                return ApplyOutcome(
                    False,
                    f"the patch adds an elision note ({note!r}) to {target.name}, "
                    "which would delete the code it stands in for", matches)

    for target, new_text in staged.items():
        target.write_text(new_text, encoding="utf-8")
    return ApplyOutcome(True, "applied", matches,
                        [str(p.relative_to(workdir)) for p in staged])


# --------------------------------------------------------------------------
# The model call, with the locate retry loop
# --------------------------------------------------------------------------

SCHEMA = {
    "type": "object",
    "properties": {
        "rationale": {"type": "string"},
        "edits": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "find": {"type": "string"},
                    "replace": {"type": "string"},
                },
                "required": ["path", "find", "replace"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["rationale", "edits"],
    "additionalProperties": False,
}

PROMPT = """You fix accessibility defects by returning find-and-replace pairs.

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
__RETRY__"""


@_op
def request_edits(client, criterion: str, component: str, findings_text: str,
                  path: str, source: str, lessons: str = "",
                  retry_note: str = "", model: str = MODEL) -> dict:
    """One model call. Traced, so the retry loop is visible in the trace tree."""
    prompt = (PROMPT
              .replace("__CRITERION__", criterion)
              .replace("__COMPONENT__", component)
              .replace("__FINDINGS__", findings_text)
              .replace("__PATH__", path)
              .replace("__SOURCE__", source)
              .replace("__LESSONS__", lessons)
              .replace("__RETRY__", retry_note))
    r = client.chat.completions.create(
        model=model, messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_schema",
                         "json_schema": {"name": "Patch", "schema": SCHEMA}},
        max_tokens=MAX_TOKENS)
    return json.loads((r.choices[0].message.content or "").strip())


def locate_context(text: str, wanted: str, width: int = 400) -> str:
    """What is really in the file near where the model thought its text was.

    Sent back on a failed locate so the next attempt sees the real lines rather
    than guessing again.
    """
    head = wanted.strip().splitlines()[0][:40] if wanted.strip() else ""
    idx = text.find(head) if head else -1
    if idx < 0:
        return text[:width]
    start = max(0, idx - width // 2)
    return text[start:start + width]
