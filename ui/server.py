"""The dashboard: three screens, a local HTTP server, server-sent events.

    python ui/server.py [--port 8000]

Screens:
  /              Start. One URL field. The explorer finds the states.
  /runs/<id>     Run. Live view, two-column comparison, findings, patches.
  /benchmark     Benchmark. Populated by Stage 3; empty until then.

Events are notifications, not data. The worker appends a line to the run's
event log; the browser is told something happened and refetches the run's JSON.
Rendered state therefore always comes from one authoritative read rather than
from deltas accumulated in the page, which is a whole class of drift bug
removed rather than debugged.

Nothing here invents a number. A run that has not produced a figure shows what
it has, and the not_evaluated count sits beside every total rather than being
left out of it.
"""

from __future__ import annotations

import io
import json
import time
import argparse
import pathlib
import mimetypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATIC = pathlib.Path(__file__).resolve().parent / "static"
ARTIFACTS = ROOT / "artifacts"
RUNS = ROOT / "runs"


# --------------------------------------------------------------------------
# Reading what the worker wrote
# --------------------------------------------------------------------------

def list_runs() -> list[dict]:
    out = []
    if ARTIFACTS.exists():
        for p in sorted(ARTIFACTS.glob("run-*.json"), reverse=True):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            s = d.get("summary", {})
            out.append({"run_id": s.get("run_id", p.stem), "url": s.get("url", ""),
                        "counts": s.get("counts", {}), "mtime": p.stat().st_mtime})
    return out


def load_run(run_id: str) -> dict | None:
    p = ARTIFACTS / f"{run_id}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def counts_of(run: dict) -> dict:
    c = {"passed": 0, "failed": 0, "not_evaluated": 0}
    for f in run.get("findings", []):
        c[f["status"]] = c.get(f["status"], 0) + 1
    return c


# --------------------------------------------------------------------------
# HTML
# --------------------------------------------------------------------------

def page(title: str, body: str, target: str = "") -> bytes:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — Ally</title>
<link rel="stylesheet" href="/static/app.css">
</head>
<body>
<a class="skip-link" href="#main">Skip to content</a>
<header class="bar">
  <h1><a href="/" style="color:inherit;text-decoration:none">Ally</a></h1>
  <nav aria-label="Screens" style="display:flex;gap:14px;font-size:13px">
    <a href="/">Start</a><a href="/benchmark">Benchmark</a>
  </nav>
  <span class="target">{target}</span>
</header>
<main id="main">
{body}
</main>
</body>
</html>""".encode()


def esc(s) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def headline(c: dict) -> str:
    """Every total carries its not_evaluated. A run that judged nothing says so."""
    total = sum(c.values())
    judged = c.get("passed", 0) + c.get("failed", 0)
    warn = ""
    if total and judged == 0:
        warn = ('<p class="warn">Nothing was judged. Every check returned '
                'not_evaluated, so the absence of findings below means nothing '
                'could be measured, not that the page is clean.</p>')
    elif c.get("not_evaluated"):
        warn = (f'<p class="warn">{c["not_evaluated"]} of {total} checks reached no '
                f'verdict. Those criteria are not passes.</p>')
    return f"""<div class="headline">
  <span class="item"><span class="n">{c.get('failed', 0)}</span><span class="lbl">failed</span></span>
  <span class="item"><span class="n">{c.get('passed', 0)}</span><span class="lbl">passed</span></span>
  <span class="item"><span class="n">{c.get('not_evaluated', 0)}</span><span class="lbl">not evaluated</span></span>
  <span class="item"><span class="n">{total}</span><span class="lbl">checks</span></span>
  {warn}
</div>"""


def start_screen() -> bytes:
    rows = "".join(
        f'<tr><td><a href="/runs/{esc(r["run_id"])}">{esc(r["run_id"])}</a></td>'
        f'<td class="mono">{esc(r["url"])}</td>'
        f'<td>{r["counts"].get("failed", 0)} failed, '
        f'{r["counts"].get("not_evaluated", 0)} not evaluated</td></tr>'
        for r in list_runs()[:25])
    body = f"""
<h2>Audit a page</h2>
<p class="sub">One URL. The explorer finds the states itself; nobody writes a
state list for a site they have never seen.</p>
<form class="card" method="get" action="/start" style="display:flex;gap:10px;flex-wrap:wrap">
  <label for="url" class="sr-only">Page address</label>
  <input id="url" name="url" type="url" required style="flex:1;min-width:280px;
         padding:9px 11px;border:1px solid var(--line-strong);border-radius:8px;
         font:inherit" placeholder="https://example.com/page"
         value="https://broken-app.vercel.app/2-1-1.html">
  <button type="submit" style="padding:9px 18px;border:1px solid var(--accent);
          background:var(--accent);color:#fff;border-radius:8px;font:inherit;
          font-weight:600;cursor:pointer">Audit</button>
</form>
<p class="sub" style="margin-top:8px">The command this runs:
<code>python -m agent.run &lt;url&gt; --source &lt;path&gt;</code></p>

<h2>Runs</h2>
<p class="sub">Newest first. Read from what the worker wrote, not from memory.</p>
{'<table class="plain"><thead><tr><th>Run</th><th>Target</th><th>Result</th></tr></thead><tbody>'
 + rows + '</tbody></table>' if rows else
 '<div class="card">No runs yet. Nothing has been audited on this machine.</div>'}
"""
    return page("Start", body)


def live_view(run: dict) -> str:
    """Screen 2, part 1: the browser as the focus ring moves.

    One large frame, not a grid of cards: this drives one browser through one
    page, and twelve small tiles would be showing the same thing twelve times.
    """
    recs = run.get("recordings", {})
    states = list(recs.keys())
    if not states:
        return ('<div class="card">No recording yet. Frames appear here as the '
                'Tab run reaches each state.</div>')

    tabs = "".join(
        f'<button role="tab" id="tab-{esc(s)}" aria-selected="{"true" if i == 0 else "false"}" '
        f'aria-controls="panel-{esc(s)}" data-state="{esc(s)}" '
        f'style="padding:6px 12px;border:1px solid var(--line-strong);background:'
        f'{"var(--card)" if i == 0 else "transparent"};border-radius:999px;font:inherit;'
        f'font-size:13px;cursor:pointer">{esc(s)}</button>'
        for i, s in enumerate(states))

    panels = []
    for i, state in enumerate(states):
        rec = recs[state]
        stops = rec.get("stops", [])
        if not rec.get("state_reached"):
            panels.append(
                f'<div role="tabpanel" id="panel-{esc(state)}" aria-labelledby="tab-{esc(state)}"'
                f' {"" if i == 0 else "hidden"}><div class="card">'
                f'<strong>State not reached.</strong><br><span class="sub">'
                f'{esc(rec.get("reach_note", ""))}</span><br>'
                'Every criterion for this state is recorded as not evaluated with '
                'that reason, rather than judged against a page we never entered.'
                '</div></div>')
            continue

        items = []
        for s in stops:
            flag = ""
            if s.get("obscured_by"):
                flag = f'<span class="flag">covered by {esc(s["obscured_by"])}</span>'
            elif s.get("focus_delta") is not None and s["focus_delta"] < 0.005:
                flag = '<span class="flag">no visible focus</span>'
            name = s.get("name") or "(no accessible name)"
            items.append(
                f'<li><button type="button" data-shot="{esc(s.get("screenshot") or "")}"'
                f' data-state="{esc(state)}" aria-current="{"true" if s["index"] == 0 else "false"}">'
                f'<span class="idx">{s["index"]}</span>'
                f'<span class="nm">{esc(name)}<br><span class="role">'
                f'{esc(s.get("role") or s["tag"].lower())} · {esc(s["selector"])[:44]}</span></span>'
                f'{flag}</button></li>')

        first = next((s.get("screenshot") for s in stops if s.get("screenshot")), "")
        panels.append(f"""<div role="tabpanel" id="panel-{esc(state)}"
     aria-labelledby="tab-{esc(state)}" {"" if i == 0 else "hidden"}>
  <div class="live">
    <div class="frame">
      {'<img id="frame-' + esc(state) + '" src="/shot/' + esc(first) + '" alt="The page at the selected focus stop">'
       if first else '<div class="empty">No screenshot was captured for this state.</div>'}
    </div>
    <div class="stops"><ol>{''.join(items)}</ol></div>
  </div>
  <p class="legend">Stop 0 is where focus sat when the state was entered, before any
  Tab. It is half the evidence for a keyboard trap: focus was here, Tab was pressed,
  focus is still here.</p>
</div>""")

    return (f'<div role="tablist" aria-label="Page states" style="display:flex;gap:8px;'
            f'margin-bottom:12px;flex-wrap:wrap">{tabs}</div>' + "".join(panels))


AXE_TAGS = {"2.1.1": "wcag211", "2.1.2": "wcag212", "2.4.3": "wcag243",
            "2.4.7": "wcag247", "2.4.11": "wcag2411"}
NAMES = {"2.1.1": "Keyboard", "2.1.2": "No Keyboard Trap", "2.4.3": "Focus Order",
         "2.4.7": "Focus Visible", "2.4.11": "Focus Not Obscured"}


def comparison(run: dict) -> str:
    """Screen 2, part 2: our five against axe, on the same page state.

    The empty cells on axe's side are the argument. They are computed from
    axe's own WCAG tags on this page, not asserted from a table.
    """
    axe = run.get("axe", {})
    if not axe.get("ran"):
        return (f'<div class="card"><strong>axe did not run.</strong> '
                f'{esc(axe.get("reason", ""))}<br><span class="sub">An empty violation '
                'list and a scan that never happened are not the same fact, so no axe '
                'column is shown for this page.</span></div>')

    by_tag: dict[str, list[str]] = {}
    for v in axe.get("violations", []):
        for t in v.get("tags", []):
            by_tag.setdefault(t, []).append(v["id"])

    findings = run.get("findings", [])
    rows = []
    for crit, name in NAMES.items():
        mine = [f for f in findings if f["criterion"] == crit]
        failed = [f for f in mine if f["status"] == "failed"]
        ne = [f for f in mine if f["status"] == "not_evaluated"]
        if failed:
            ours = ('<span class="status failed">failed</span> '
                    + esc(failed[0]["summary"])[:110])
        elif ne:
            ours = ('<span class="status not_evaluated">not evaluated</span> '
                    + esc(ne[0]["reason"])[:110])
        elif mine:
            ours = '<span class="status passed">passed</span>'
        else:
            ours = '<span class="none">not run</span>'

        hits = sorted(set(by_tag.get(AXE_TAGS[crit], [])))
        theirs = (", ".join(f"<code>{esc(h)}</code>" for h in hits) if hits
                  else '<span class="none">no rule</span>')
        gap = '<span class="gap">only ours</span>' if failed and not hits else ""
        rows.append(f'<tr><td class="crit">{crit}<br><span class="role">{esc(name)}</span></td>'
                    f'<td>{ours}</td><td>{theirs}</td><td>{gap}</td></tr>')

    other = [v["id"] for v in axe.get("violations", [])
             if not any(t in AXE_TAGS.values() for t in v.get("tags", []))]
    note = (f'<p class="legend">axe also fired {len(other)} rule(s) on criteria we do '
            f'not claim: {", ".join(f"<code>{esc(o)}</code>" for o in sorted(set(other))[:8])}. '
            'Those are its findings and they go in the report unchanged.</p>'
            if other else "")

    return f"""<table class="compare">
<colgroup><col><col class="ours"><col><col></colgroup>
<thead><tr><th>Criterion</th><th>Ally</th><th>axe-core {esc(axe.get('version', ''))}</th><th></th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
<p class="legend">axe's column is read from the WCAG tags on the rules it fired on
this page, not from a published table. A rule appearing there would mean we are
competing with axe on its own ground.</p>
{note}"""


def findings_table(run: dict) -> str:
    rows = []
    for f in run.get("findings", []):
        detail = f.get("summary") or f.get("reason") or ""
        ev = ", ".join(f.get("evidence_refs", [])[:3])
        rows.append(f'<tr><td class="crit">{esc(f["criterion"])}</td>'
                    f'<td>{esc(f["state"])}</td>'
                    f'<td><span class="status {f["status"]}">{f["status"].replace("_", " ")}</span></td>'
                    f'<td>{esc(detail)}</td><td class="mono">{esc(ev)}</td></tr>')
    return (f'<table class="plain"><thead><tr><th>Criterion</th><th>State</th>'
            f'<th>Status</th><th>Detail</th><th>Evidence</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table>')


def fix_section(run: dict) -> str:
    fix = run.get("fix")
    if not fix:
        return ('<div class="card">No patches in this run. It audited and stopped.</div>')
    s = fix.get("summary", {})
    rows = "".join(
        f'<tr><td class="crit">{esc(o["criterion"])}</td><td>{esc(o["component"])}</td>'
        f'<td>{esc(o["status"].replace("_", " "))}</td>'
        f'<td>{o["locate_attempts"]}</td><td>{o["patch_attempts"]}</td>'
        f'<td>{len(o["closed"])}</td><td>{len(o["created"])}</td>'
        f'<td>{esc(o.get("reason", ""))[:70]}</td></tr>'
        for o in fix.get("outcomes", []))
    return f"""<div class="headline" style="margin-bottom:12px">
  <span class="item"><span class="n">{s.get('closed', 0)}</span><span class="lbl">closed</span></span>
  <span class="item"><span class="n">{s.get('created', 0)}</span><span class="lbl">created</span></span>
  <span class="item"><span class="n">{s.get('net', 0)}</span><span class="lbl">net</span></span>
  <span class="item"><span class="n">{s.get('could_not_locate', 0)}</span><span class="lbl">could not locate</span></span>
  <span class="item"><span class="n">{s.get('still_failing', 0)}</span><span class="lbl">still failing after 5</span></span>
</div>
<table class="plain"><thead><tr><th>Criterion</th><th>Component</th><th>Outcome</th>
<th>Locate</th><th>Patch</th><th>Closed</th><th>Created</th><th>Reason</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="legend"><strong>Could not locate</strong> means the text to edit never
matched and zero patches were applied. <strong>Still failing</strong> means patches
applied cleanly and the re-audit still reports the problem. They are opposite facts
and are never added together.</p>"""


def run_screen(run_id: str) -> bytes | None:
    run = load_run(run_id)
    if run is None:
        return None
    c = counts_of(run)
    summary = run.get("summary", {})
    body = f"""
<h2>Run {esc(run_id)}</h2>
<p class="sub">{esc(summary.get('url', ''))} · states {esc(', '.join(summary.get('states', [])))}</p>
{headline(c)}

<h2>Live view</h2>
<p class="sub">The page at each focus stop. Select a stop to see the frame captured
when focus landed on it.</p>
{live_view(run)}

<h2>Ally against axe, same page</h2>
<p class="sub">Both halves of the report. We run axe as-is and improve none of it;
these five are what it does not cover.</p>
{comparison(run)}

<h2>Findings</h2>
<p class="sub">Every check, including the ones that reached no verdict.</p>
{findings_table(run)}

<h2>Patches</h2>
{fix_section(run)}
"""
    return page(f"Run {run_id}", body, target=summary.get("url", ""))


def benchmark_screen() -> bytes:
    body = """
<h2>Benchmark</h2>
<p class="sub">Two runs side by side, precision and recall per criterion, with
not_evaluated in the same row as recall.</p>
<div class="card">
<strong>Not populated yet.</strong>
<p class="sub" style="margin-top:6px">This fills in at Stage 3, when the agent has
run against all five broken pages. It is deliberately empty rather than showing a
shape with invented numbers in it: a benchmark screen that displays a figure
nothing measured is worse than one that says it has nothing yet.</p>
</div>"""
    return page("Benchmark", body)


# --------------------------------------------------------------------------
# Server
# --------------------------------------------------------------------------

class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a) -> None:      # quiet
        pass

    def _send(self, body: bytes, ctype="text/html; charset=utf-8", code=200) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        u = urlparse(self.path)
        p = u.path

        if p == "/":
            return self._send(start_screen())
        if p == "/benchmark":
            return self._send(benchmark_screen())
        if p.startswith("/static/"):
            f = STATIC / p[len("/static/"):]
            if not f.exists():
                return self._send(b"not found", "text/plain", 404)
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            return self._send(f.read_bytes(), ctype)
        if p.startswith("/shot/"):
            # Screenshots are served from the storage seam's refs, never
            # inlined: a data: URI would put the bytes back into the page.
            f = ROOT / p[len("/shot/"):]
            if not f.exists() or f.suffix != ".png":
                return self._send(b"not found", "text/plain", 404)
            return self._send(f.read_bytes(), "image/png")
        if p.startswith("/runs/"):
            out = run_screen(p[len("/runs/"):])
            return self._send(out or page("Not found", "<h2>No such run</h2>"),
                              code=200 if out else 404)
        if p.startswith("/api/runs/"):
            run = load_run(p[len("/api/runs/"):])
            return self._send(json.dumps(run or {}).encode(),
                              "application/json", 200 if run else 404)
        if p == "/api/runs":
            return self._send(json.dumps(list_runs()).encode(), "application/json")
        if p == "/events":
            return self._events()
        if p == "/start":
            q = parse_qs(u.query)
            url = (q.get("url") or [""])[0]
            return self._send(page("Start", f"""<h2>Run this</h2>
<p class="sub">The dashboard reads what the worker writes; it does not start one,
so there is no half-started run to explain.</p>
<div class="card"><code>python -m agent.run {esc(url)} --source &lt;path-in-repo&gt;</code></div>
<p class="sub" style="margin-top:10px"><a href="/">Back</a></p>"""))
        return self._send(b"not found", "text/plain", 404)

    def _events(self) -> None:
        """Notify, never carry data. The page refetches on every nudge."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        last = None
        try:
            while True:
                latest = max((p.stat().st_mtime for p in ARTIFACTS.glob("run-*.json")),
                             default=0) if ARTIFACTS.exists() else 0
                if latest != last:
                    last = latest
                    self.wfile.write(b"event: changed\ndata: {}\n\n")
                    self.wfile.flush()
                time.sleep(2)
        except (BrokenPipeError, ConnectionResetError):
            return


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    ARTIFACTS.mkdir(exist_ok=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Ally dashboard on http://127.0.0.1:{args.port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
