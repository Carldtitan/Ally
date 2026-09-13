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
    #: The sandbox's noVNC stream. Watching the browser being driven is the
    #: whole point of running it in a sandbox rather than headless on a laptop.
    watch_url: str = ""
    #: Every page this run visited, in the order it reached them.
    pages: list = field(default_factory=list)
    #: One entry per parallel sandbox, each with its own live desktop.
    lanes: list = field(default_factory=list)
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
             "pages": len(j.pages), "watch_url": j.watch_url,
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
        f"cd {checkout} && git ls-files | grep -Ei "
        f"'\\.(html|htm|jsx|tsx|vue|svelte|astro)$' | head -600", timeout=120)
    files = [f.strip() for f in (listing.result or "").splitlines() if f.strip()]
    if not files:
        return ""

    # Framework routes first. Next.js App Router puts the page for "/" in
    # app/page.tsx and for "/pricing" in app/pricing/page.tsx; the Pages Router
    # uses pages/index.tsx. A run against clearway picked app/layout.tsx, because
    # the old fallback was "shallowest file wins" and layout sorts first.
    from urllib.parse import urlparse

    route = (urlparse(url).path or "/").strip("/")
    candidates = []
    if route:
        candidates += [f"app/{route}/page.tsx", f"app/{route}/page.jsx",
                       f"app/{route}/page.js", f"pages/{route}.tsx",
                       f"pages/{route}.jsx", f"src/app/{route}/page.tsx",
                       f"src/pages/{route}.tsx"]
    else:
        candidates += ["app/page.tsx", "app/page.jsx", "app/page.js",
                       "pages/index.tsx", "pages/index.jsx",
                       "src/app/page.tsx", "src/pages/index.tsx"]
    lower = {f.lower(): f for f in files}
    for c in candidates:
        if c.lower() in lower:
            return lower[c.lower()]

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


MAX_PAGES = 6
MAX_LANES = 4


@_op
def find_pages(session, url: str, limit: int = MAX_PAGES) -> list:
    """Same-origin pages linked from the first one, the first `limit` of them.

    A multipage app audited at its front door tells you about the front door.
    Clearway is one, and the first run against it looked at a single URL.

    Deliberately shallow: the links on the entry page, in document order, not a
    full crawl. It is the difference between auditing a site and auditing a
    landing page, without turning the product into a spider.
    """
    js = """
    (function () {
      var here = location.origin, seen = {}, out = [];
      var links = document.querySelectorAll('a[href]');
      for (var i = 0; i < links.length; i++) {
        var u;
        try { u = new URL(links[i].getAttribute('href'), location.href); }
        catch (e) { continue; }
        if (u.origin !== here) continue;
        if (/\\.(pdf|zip|png|jpe?g|svg|gif|mp4|webm|css|js)$/i.test(u.pathname)) continue;
        u.hash = '';
        var s = u.toString().replace(/\\/$/, '');
        if (s === location.href.replace(/\\/$/, '').split('#')[0]) continue;
        if (seen[s]) continue;
        seen[s] = 1;
        out.push(s);
      }
      return out;
    })()
    """
    body = [
        "import json, urllib.request, time",
        "from websocket import create_connection",
        "tabs = json.load(urllib.request.urlopen('http://127.0.0.1:9222/json'))",
        "page = next(t for t in tabs if t['type'] == 'page')",
        "ws = create_connection(page['webSocketDebuggerUrl'], timeout=60)",
        "mid = 0",
        "def send(m, p=None):",
        "    global mid",
        "    mid += 1",
        "    ws.send(json.dumps({'id': mid, 'method': m, 'params': p or {}}))",
        "    while True:",
        "        r = json.loads(ws.recv())",
        "        if r.get('id') == mid: return r",
        "send('Page.enable')",
        f"send('Page.navigate', {{'url': {url!r}}})",
        "time.sleep(3.5)",
        "r = send('Runtime.evaluate', {'expression': " + repr(js) + ", 'returnByValue': True})",
        "print('LINKS ' + json.dumps(r.get('result', {}).get('result', {}).get('value') or []))",
        "ws.close()",
    ]
    script = "/tmp/ally_links.py"
    session.sb.fs.upload_file(chr(10).join(body).encode(), script)
    out = session.exec(f"cd /tmp && python3 ally_links.py 2>&1 | tail -3", timeout=240)
    line = next((l for l in (out.result or "").splitlines() if l.startswith("LINKS")), None)
    if not line:
        return []
    try:
        return json.loads(line[len("LINKS "):])[: limit - 1]
    except Exception:
        return []


# --------------------------------------------------------------------------
# The phases
# --------------------------------------------------------------------------

@_op
def prepare_build(session, checkout: str) -> tuple[str, str]:
    """Install and build the checkout once. Returns (what to serve, how to rebuild).

    The re-audit serves the patched tree over a static file server, which is
    right for a plain HTML page and wrong for every framework: a Vite repo's
    index.html asks for /src/main.tsx, a static server hands that back as
    TypeScript, and the page renders nothing.

    Returns ("", "") when the repository produces nothing servable, so the
    caller can say the fix step cannot run rather than re-auditing a blank page.
    """
    has = session.exec(f"cd {checkout} && test -f package.json && echo yes || echo no",
                       timeout=60)
    if "yes" not in (has.result or ""):
        return checkout, ""            # a static site: serve it as it stands

    session.exec(f"cd {checkout} && (npm ci --no-audit --no-fund || "
                 f"npm install --no-audit --no-fund) 2>&1 | tail -3", timeout=1500)
    build = f"cd {checkout} && npm run build"
    session.exec(f"{build} 2>&1 | tail -4", timeout=1500)
    found = session.exec(
        f"cd {checkout} && for d in dist out build public .; do "
        f'test -f "$d/index.html" && echo "$d" && break; done', timeout=60)
    out = [l.strip() for l in (found.result or "").splitlines() if l.strip()]
    if not out:
        return "", ""
    d = out[-1]
    return (checkout if d == "." else f"{checkout}/{d}"), build


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
    try:
        if audit.session.start_desktop():
            job.watch_url = audit.session.watch_url()
    except Exception:
        pass
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
    # Ask the repository what pages exist, before auditing anything. Crawling
    # a[href] only finds what the entry page links: BitEstate's router declares
    # ten routes and its landing page links to two, the rest being behind a
    # login. The source has no such blind spot.
    #
    # This runs BEFORE the first audit on purpose. It used to audit the entry
    # page alone, then discover, then start the rest -- so for the first minute
    # there was one sandbox on screen and nothing to suggest more were coming.
    from ui.fleet import Lane, MAX_SANDBOXES, run_lanes
    from ui.routes import routes_from_repo

    # Discover more routes than there are sandboxes. A route that turns out to
    # render a screen already seen frees its slot for the next one.
    all_urls = routes_from_repo(audit.session, CHECKOUT, job.url, limit=12)
    if not all_urls:
        all_urls = [job.url]
    urls = all_urls[:MAX_SANDBOXES]

    if len(urls) > 1:
        job.say("audit", f"{len(urls)} routes declared in the repository: "
                         + ", ".join(u.replace(job.url.rstrip('/'), '') or '/'
                                     for u in urls))
    else:
        # One declared route. Try the links on the page next -- a static site
        # with no framework has neither route files nor a router config -- and
        # only then treat the page as a flow whose steps are its pages.
        linked = find_pages(audit.session, job.url, limit=MAX_SANDBOXES)
        if linked:
            job.say("audit", f"one declared route, {len(linked)} linked page(s)")
            urls = [job.url] + linked[: MAX_SANDBOXES - 1]
        else:
            from ui.steps import discover_steps, register_step_state

            steps = discover_steps(audit.session, job.url, limit=MAX_SANDBOXES - 1)
            if steps:
                job.say("audit", f"one route and no links; {len(steps)} step(s) "
                                 "inside this page: "
                                 + ", ".join(x["label"] for x in steps))

    lanes = [Lane(index=0, url=urls[0])]
    if len(urls) > 1:
        lanes += [Lane(index=i + 1, url=u) for i, u in enumerate(urls[1:])]
    elif "steps" in dir() and steps:
        for i, st in enumerate(steps):
            name = register_step_state(f"step-{i + 1}", st["selector"])
            lanes.append(Lane(index=i + 1, url=job.url, state=name,
                              label=st["label"]))

    job.lanes = [l.to_dict() for l in lanes]
    job.say("audit", f"{len(lanes)} sandbox(es) starting together")

    def say(i: int, msg: str, level: str) -> None:
        job.say("audit", f"[{i}] {msg}", level)
        job.lanes = [l.to_dict() for l in lanes]

    run_lanes(lanes, states or ["loaded"], audit.judge, say)
    job.lanes = [l.to_dict() for l in lanes]

    # Different URL, same screen. BitEstate serves Home at both "/" and "/home",
    # so four sandboxes can spend their time auditing two pages twice. A lane
    # whose render matches one already seen is marked as a duplicate, its
    # findings are dropped rather than double counted, and its slot is spent on
    # a route nobody has looked at yet.
    queue = [u for u in all_urls[MAX_SANDBOXES:]]
    seen: dict = {}
    for wave in range(2):
        fresh = []
        for lane in lanes:
            if lane.status != "done" or not lane.signature:
                continue
            first = seen.get(lane.signature)
            if first is None:
                seen[lane.signature] = lane.url
            elif lane.url != first:
                lane.duplicate_of = first
                fresh.append(lane)
        if not fresh or not queue:
            break
        replacements = []
        for lane in fresh:
            if not queue:
                break
            nxt = queue.pop(0)
            job.say("audit", f"[{lane.index}] {lane.url} renders the same screen as "
                             f"{lane.duplicate_of}; trying {nxt} instead", "warn")
            replacements.append(Lane(index=lane.index, url=nxt))
        if not replacements:
            break
        run_lanes(replacements, states or ["loaded"], audit.judge, say)
        for r in replacements:
            for i, lane in enumerate(lanes):
                if lane.index == r.index:
                    lanes[i] = r
        job.lanes = [l.to_dict() for l in lanes]

    from agent.recording import Census, Result

    results = []
    #: What the entry page found, kept apart from the rest. The fix loop
    #: re-audits one URL, so only the entry page's findings can be confirmed
    #: closed; claiming closure for a page that was never re-tested is worse
    #: than not fixing it.
    entry_results = []
    #: Lane recordings arrive already serialised -- they cross a thread
    #: boundary as dicts -- so they are merged as dicts and never converted
    #: again. Putting them back into audit.recordings, which is typed for
    #: Recording objects, is what crashed the run at the end of the audit.
    merged: dict = {}
    for lane in lanes:
        if lane.duplicate_of:
            job.pages.append({"url": lane.url, "source": "", "findings": 0,
                              "note": f"same screen as {lane.duplicate_of}"})
            continue
        if lane.status != "done":
            job.pages.append({"url": lane.url, "source": "",
                              "findings": 0, "note": lane.note or lane.status})
            continue
        for f in lane.findings:
            fields = {k: (tuple(v) if isinstance(v, list) else v)
                      for k, v in f.items() if k != "census"}
            r = Result(census=Census(**(f.get("census") or {})), **fields)
            results.append(r)
            if lane.index == 0:
                entry_results.append(r)
        short = lane.label or (lane.url.rstrip("/").rsplit("/", 1)[-1] or "home")
        for st, r in lane.recordings.items():
            merged[f"{st} · {short}"] = r
        if not audit.axe and lane.axe.get("ran"):
            audit.axe = type("A", (), lane.axe)
        job.pages.append({
            "url": (f"{lane.url}  ({lane.label})" if lane.label else lane.url),
            "source": "",
            "findings": sum(1 for f in lane.findings if f.get("status") == "failed"),
            "note": ""})

    if all(l.status != "done" for l in lanes):
        raise RuntimeError(
            "no page could be audited. "
            + "; ".join(f"{l.url}: {l.note}" for l in lanes if l.note)[:300])

    failed = [r for r in results if r.status == "failed"]
    job.say("audit", f"{len(failed)} finding(s) across {len(results)} check(s) "
                     f"on {sum(1 for l in lanes if l.status == 'done')} page(s)")
    if job.pages:
        job.pages[0]["source"] = job.source

    job.findings = [r.to_dict() for r in results]
    job.recordings = merged
    # The loop reads its work from here, and it was never filled: every run
    # reached the fix phase with an empty list and nothing to group.
    audit.results = entry_results
    first_axe = next((l.axe for l in lanes if l.status == "done" and l.axe.get("ran")),
                     None)
    job.axe = first_axe or {"ran": False, "version": "", "violations": []}

    if not (want_fix and failed):
        job.say("pr", "Nothing to fix." if not failed else "Fix step skipped.")
        return

    # The loop, live. Every outcome is written to the table and the matching
    # rows for the criterion go into the next prompt.
    job.say("fix", "Installing and building the repository so the patch can "
                   "be re-audited")
    serve_root, build_cmd = prepare_build(audit.session, CHECKOUT)
    if not serve_root:
        job.say("pr", "This repository produced no page a static server can "
                      "serve, so a patch could not be re-audited. The findings "
                      "above stand; no fix was attempted.", "warn")
        return
    job.say("fix", f"Serving {serve_root.rsplit('/', 1)[-1]}/"
                   + (" and rebuilding between patches" if build_cmd else ""))

    lessons = Lessons(job.id)
    loop = FixLoop(audit, workdir=pathlib.Path(CHECKOUT),
                   serve_root=serve_root, client=_client(), lessons=lessons,
                   build=build_cmd)
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
    # A re-audit that could not be scored says so here rather than being read
    # as a clean sweep.
    if loop.blocked:
        job.say("reaudit", loop.blocked, "warn")

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
