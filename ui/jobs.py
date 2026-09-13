"""The job the product actually runs: a live URL and a repo in, a pull request out.

This is what the dashboard was missing. It used to render
`python -m agent.run <url> --source <path>` on screen and tell the reader the
dashboard does not start runs, which is not a product, it is a note about one.

One job, five phases, each of them a Weave op so the whole thing is one trace
tree a reader can open:

    clone -> audit -> fix -> re-audit -> pull request

**The loop is live inside it.** `FixLoop` is constructed with a `Lessons` table,
so every patch outcome is written down and the matching rows for that criterion
go into the next patch prompt, failures included and labelled as failures. The
retrieved row ids are attached to the patch call's trace attributes, so the
mechanism can be opened rather than taken on trust.

**Nobody types a file path.** The source file is derived by matching the live
URL against the files in the clone, because asking a person which file backs a
URL they just pasted is asking them to do the agent's job.
"""

from __future__ import annotations

import io
import os
import re
import sys
import json
import time
import uuid
import pathlib
import threading
import traceback
from dataclasses import dataclass, field, asdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import wb_env  # noqa: E402

try:
    import weave
except ImportError:  # the job still runs untraced
    weave = None


def _op(fn):
    return weave.op()(fn) if weave else fn


CHECKOUT = "/tmp/ally-job"
PHASES = ["clone", "audit", "fix", "reaudit", "pr"]


# --------------------------------------------------------------------------
# Job state, which the UI polls
# --------------------------------------------------------------------------

@dataclass
class Event:
    at: float
    phase: str
    message: str
    level: str = "info"


@dataclass
class Job:
    id: str
    url: str
    repo: str
    #: "queued" | "running" | "done" | "failed"
    status: str = "queued"
    phase: str = "clone"
    source: str = ""
    events: list = field(default_factory=list)
    findings: list = field(default_factory=list)
    recordings: dict = field(default_factory=dict)
    axe: dict = field(default_factory=dict)
    patches: list = field(default_factory=list)
    lesson_ids: list = field(default_factory=list)
    pr_url: str = ""
    pr_blocked: str = ""
    diff: str = ""
    trace_url: str = ""
    error: str = ""
    started: float = field(default_factory=time.time)
    finished: float = 0.0

    def say(self, phase: str, message: str, level: str = "info") -> None:
        self.phase = phase
        self.events.append(Event(time.time(), phase, message, level))

    def to_dict(self) -> dict:
        d = asdict(self)
        d["events"] = [asdict(e) for e in self.events]
        d["elapsed"] = round((self.finished or time.time()) - self.started, 1)
        return d


JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def get(job_id: str) -> Job | None:
    return JOBS.get(job_id)


def recent(limit: int = 20) -> list[dict]:
    with _LOCK:
        js = sorted(JOBS.values(), key=lambda j: j.started, reverse=True)[:limit]
    return [{"id": j.id, "url": j.url, "repo": j.repo, "status": j.status,
             "phase": j.phase, "findings": len(j.findings), "pr_url": j.pr_url,
             "started": j.started} for j in js]


# --------------------------------------------------------------------------
# Understanding what the user pasted
# --------------------------------------------------------------------------

GITHUB = re.compile(
    r"^(?:https?://)?(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)"
    r"(?:\.git)?/?$")


def parse_repo(text: str) -> tuple[str, str] | None:
    """"https://github.com/owner/name" -> ("owner", "name")."""
    m = GITHUB.match((text or "").strip())
    return (m.group(1), m.group(2)) if m else None


@_op
def guess_source(session, url: str, checkout: str) -> str:
    """Which file in the clone backs this URL?

    Asking the person who pasted the URL to also name the file is asking them to
    do the agent's job. The last path segment of the URL is the strongest signal,
    then an index file in a directory that looks like a web root.
    """
    listing = session.exec(
        f"cd {checkout} && git ls-files | grep -Ei '\\.(html|htm|jsx|tsx|vue|svelte)$' "
        f"| head -400", timeout=120)
    files = [f.strip() for f in (listing.result or "").splitlines() if f.strip()]
    if not files:
        return ""

    tail = url.rstrip("/").rsplit("/", 1)[-1] or "index.html"
    stem = tail.split("?")[0].split("#")[0]
    if stem and not stem.endswith((".html", ".htm")):
        stem = stem + ".html"

    exact = [f for f in files if f.rsplit("/", 1)[-1].lower() == stem.lower()]
    if exact:
        # Shallowest wins: public/2-1-1.html beats deep/nested/copy/2-1-1.html.
        return sorted(exact, key=lambda f: f.count("/"))[0]

    roots = ("public/", "static/", "dist/", "site/", "www/", "src/")
    indexes = [f for f in files if f.rsplit("/", 1)[-1].lower() in ("index.html", "index.htm")]
    preferred = [f for f in indexes if f.startswith(roots)] or indexes
    if preferred:
        return sorted(preferred, key=lambda f: f.count("/"))[0]
    return sorted(files, key=lambda f: f.count("/"))[0]


# --------------------------------------------------------------------------
# The phases
# --------------------------------------------------------------------------

@_op
def clone_repo(session, owner: str, name: str, job_id: str) -> str:
    """A shallow clone of the repo the user named, inside the sandbox."""
    url = f"https://github.com/{owner}/{name}.git"
    r = session.exec(
        f"rm -rf {CHECKOUT} && git clone --depth 1 -q {url} {CHECKOUT} && "
        f"cd {CHECKOUT} && git rev-parse --short HEAD", timeout=420)
    out = (r.result or "").strip()
    if not out or "fatal" in out.lower():
        raise RuntimeError(f"could not clone {owner}/{name}: {out[:200] or 'no output'}")
    return out.splitlines()[-1].strip()


def _can_push(owner: str, name: str) -> bool:
    """Do we have write access? Decides PR versus diff-only, before any work."""
    import subprocess
    try:
        r = subprocess.run(
            ["gh", "api", f"repos/{owner}/{name}", "--jq", ".permissions.push"],
            capture_output=True, text=True, timeout=60)
        return (r.stdout or "").strip() == "true"
    except Exception:
        return False


def _run(job: Job, states: list[str], want_fix: bool, want_pr: bool) -> None:
    from agent.audit import Audit
    from agent.fixloop import FixLoop
    from agent.judge import _client
    from agent.lessons import Lessons
    from agent.run import RemoteTree
    from agent import pr as pr_mod

    parsed = parse_repo(job.repo)
    if not parsed:
        raise RuntimeError(f"{job.repo!r} is not a GitHub repository URL")
    owner, name = parsed

    job.say("clone", f"Cloning {owner}/{name}")
    audit = Audit(job.url, sandbox_id=os.environ.get("ALLY_SANDBOX"),
                  states=states or ["loaded"], run_id=job.id)
    if weave is not None:
        client = getattr(audit, "weave_client", None)
        if client is not None:
            job.trace_url = f"https://wandb.ai/{wb_env.bootstrap()['ref']}/weave"
    sha = clone_repo(audit.session, owner, name, job.id)
    job.say("clone", f"At {sha}")

    job.source = guess_source(audit.session, job.url, CHECKOUT)
    if not job.source:
        raise RuntimeError("no HTML-like file found in the repository to patch")
    job.say("clone", f"The page is backed by {job.source}")

    # The loaded page always. Whether the menu and dialog passes are worth
    # running is a question about the page, not a question for whoever pasted the
    # URL: the recorder reports how many elements declare themselves a menu
    # trigger or a dialog, and that decides it.
    job.say("audit", "Tabbing through the loaded page")
    results = list(audit.run())

    extra = []
    first = audit.recordings.get("loaded")
    if first is not None and not states:
        if getattr(first, "menu_triggers", 0):
            extra.append("menu-generic")
        if getattr(first, "dialog_triggers", 0):
            extra.append("dialog-generic")
    if extra:
        job.say("audit", f"The page declares a {' and a '.join(x.split('-')[0] for x in extra)}"
                         f"; tabbing {'those' if len(extra) > 1 else 'that'} too")
        more = Audit(job.url, sandbox_id=os.environ.get("ALLY_SANDBOX"),
                     states=extra, run_id=f"{job.id}-more", use_weave=False,
                     judge=audit.judge)
        more.session = audit.session
        results += list(more.run())
        audit.recordings.update(more.recordings)
        audit.results = results

    job.findings = [r.to_dict() for r in results]
    job.recordings = {s: r.to_dict() for s, r in audit.recordings.items()}
    job.axe = {"ran": audit.axe.ran if audit.axe else False,
               "version": audit.axe.version if audit.axe else "",
               "violations": audit.axe.violations if audit.axe else []}
    failed = [r for r in results if r.status == "failed"]
    job.say("audit", f"{len(failed)} finding(s) across "
                     f"{len(results)} check(s)")

    if not (want_fix and failed):
        job.say("pr", "Nothing to fix." if not failed else "Fix step skipped.")
        return

    # The loop, live. Every outcome is written to the table and the matching
    # rows for the criterion go into the next prompt.
    lessons = Lessons(job.id)
    loop = FixLoop(audit, workdir=pathlib.Path(CHECKOUT),
                   serve_root=f"{CHECKOUT}", client=_client(), lessons=lessons)
    loop.workdir = RemoteTree(audit.session, CHECKOUT)

    job.say("fix", "Writing patches, then rebuilding and re-auditing each one")
    outcomes = loop.run(job.source)
    for o in outcomes:
        job.patches.append({
            "criterion": o.criterion, "component": o.component,
            "status": o.status, "patch_attempts": o.patch_attempts,
            "locate_attempts": o.locate_attempts,
            "closed": len(o.closed), "created": len(o.created),
            "reason": o.reason, "lesson_ids": list(o.lesson_ids)})
        job.lesson_ids.extend(o.lesson_ids)
    s = loop.summary()
    job.say("reaudit", f"{s['closed']} closed, {s['created']} created, "
                       f"{s['patch_attempts_per_closed']} attempts per fix")

    d = audit.session.exec(f"cd {CHECKOUT} && git diff --stat && echo '---' && "
                           f"git diff", timeout=180)
    job.diff = (d.result or "")[:60000]

    if not want_pr:
        job.say("pr", "Diff ready. Pull request not requested.")
        return
    if not _can_push(owner, name):
        job.pr_blocked = (f"No write access to {owner}/{name}, so no branch was "
                          f"pushed. The diff above is the complete change.")
        job.say("pr", job.pr_blocked, "warn")
        return

    job.say("pr", "Opening a pull request")
    try:
        body = pr_mod.build_body(audit, loop.summary(), outcomes, job.trace_url)
        out = pr_mod.open_pull_request(audit.session, f"{owner}/{name}", job.id,
                                      body, CHECKOUT)
        job.pr_url = (out or {}).get("url", "") if isinstance(out, dict) else str(out or "")
        job.say("pr", job.pr_url or "Pull request step returned no URL")
    except Exception as exc:
        job.pr_blocked = f"{type(exc).__name__}: {str(exc)[:180]}"
        job.say("pr", job.pr_blocked, "warn")


def start(url: str, repo: str, states: list[str] | None = None,
          want_fix: bool = True, want_pr: bool = True) -> Job:
    """Begin a job and return immediately. The UI polls it.

    `states` empty means "you decide", which is what the UI now sends.
    """
    job = Job(id=f"job-{uuid.uuid4().hex[:8]}", url=url.strip(), repo=repo.strip())
    with _LOCK:
        JOBS[job.id] = job

    def body() -> None:
        job.status = "running"
        try:
            if weave is not None:
                cfg = wb_env.bootstrap()
                weave.init(cfg["ref"])
                with weave.attributes({"job": job.id, "url": job.url,
                                       "repo": job.repo}):
                    _run(job, states or [], want_fix, want_pr)
            else:
                _run(job, states or [], want_fix, want_pr)
            job.status = "done"
        except Exception as exc:
            job.status = "failed"
            job.error = f"{type(exc).__name__}: {exc}"
            job.say(job.phase, job.error, "error")
            traceback.print_exc()
        finally:
            job.finished = time.time()
            out = ROOT / "artifacts" / f"{job.id}.json"
            try:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
            except Exception:
                pass

    threading.Thread(target=body, daemon=True).start()
    return job
