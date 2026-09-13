"""Run the recorder and the five checks against a site the sandbox cannot reach.

The Daytona Tier 2 egress allowlist passes Vercel hosts and nothing else: DNS
resolves for any domain, but `curl https://example.com` returns no response at
all. So the sandbox can audit our own fixtures and nothing in the wild, and
"how much of what it reports is wrong on a page nobody built for us" cannot be
answered from inside it.

The runner is plain Python talking CDP to 127.0.0.1:9222. Nothing in it is
specific to the sandbox, so the same script, byte for byte from
`build_runner`, drives a local Chrome instead. **The check code is untouched and
is the same code the recall gate scores.** The only difference is which machine
the browser is on.

No patching. This reports and stops.

Usage:
    python tools/record_local.py https://example.com/ --states loaded,menu-generic
"""

from __future__ import annotations

import os
import sys
import json
import time
import shutil
import argparse
import pathlib
import subprocess
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import wb_env  # noqa: E402

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

from agent import checks  # noqa: E402
from agent.browser import CHROME_FLAGS, STATES, build_runner  # noqa: E402
from agent.session import Session  # noqa: E402

CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
]


def chrome_path() -> str:
    for p in CHROME:
        if pathlib.Path(p).exists():
            return p
    raise SystemExit("no Chrome found; this run needs a local browser")


#: Headless Chrome announces itself as HeadlessChrome, and major publishers
#: serve it an error page. allrecipes.com returned HTTP 402 and a 316-character
#: "contact support" notice, and all five checks reported a confident pass on it.
#: A normal UA string is what an accessibility auditor sends; it is set so the
#: page under test is the page, not a block notice.
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def start_chrome(profile: pathlib.Path) -> subprocess.Popen:
    """Headless Chrome with the sandbox's flags, so recordings are comparable."""
    if profile.exists():
        shutil.rmtree(profile, ignore_errors=True)
    profile.mkdir(parents=True, exist_ok=True)
    args = ([chrome_path(), "--headless=new", f"--user-data-dir={profile}",
             f"--user-agent={UA}"] + CHROME_FLAGS.split())
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            urllib.request.urlopen("http://127.0.0.1:9222/json/version", timeout=2)
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise SystemExit("Chrome did not open its debugging port")


def record(url: str, state: str, run_id: str, script: pathlib.Path) -> dict:
    """Exactly what the sandbox does, with the subprocess local."""
    script.write_text(build_runner(url, state, max_tabs=40, pair_capture=True,
                                   shots=True), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, timeout=600, cwd=str(script.parent))
    out = (proc.stdout or "") + (proc.stderr or "")
    line = next((l for l in out.splitlines() if l.startswith("RESULT")), None)
    if not line:
        # Same rule as the sandbox path: a crashed recorder raises rather than
        # being returned as an unreached state.
        raise RuntimeError(f"no RESULT for {state} at {url}: {out[-400:]}")
    return json.loads(line[len("RESULT "):])


PREFLIGHT_JS = {
    "status": ("performance.getEntriesByType('navigation')[0] ? "
               "performance.getEntriesByType('navigation')[0].responseStatus : 0"),
    "title": "document.title",
    "focusable": ("document.querySelectorAll('a[href],button,input,select,"
                  "textarea,[tabindex]').length"),
    "iframes": "document.querySelectorAll('iframe').length",
    "dialogs": "document.querySelectorAll('[role=\"dialog\"],dialog').length",
    "expandable": "document.querySelectorAll('[aria-expanded]').length",
    "text": "document.body?document.body.innerText.length:0",
}


def preflight(url: str, script: pathlib.Path) -> dict:
    """Is the page under test the page, or a block notice?"""
    body = ["import json, time, urllib.request",
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
            "def val(e):",
            "    r = send('Runtime.evaluate', {'expression': "
            "'(function(){try{return (' + e + ');}catch(x){return null;}})()',"
            " 'returnByValue': True})",
            "    return r.get('result', {}).get('result', {}).get('value')",
            "send('Page.enable')",
            f"send('Page.navigate', {{'url': {url!r}}})",
            "for _ in range(80):",
            "    if val('document.readyState') == 'complete': break",
            "    time.sleep(0.5)",
            "time.sleep(4.0)",
            f"out = {{k: val(v) for k, v in {PREFLIGHT_JS!r}.items()}}",
            "print('RESULT ' + json.dumps(out))",
            "ws.close()"]
    script.write_text(chr(10).join(body), encoding="utf-8")
    proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                          text=True, timeout=300)
    line = next((l for l in (proc.stdout or "").splitlines()
                 if l.startswith("RESULT")), None)
    return json.loads(line[len("RESULT "):]) if line else {}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--states", default="loaded")
    ap.add_argument("--tag", default="wild")
    ap.add_argument("--no-judge", action="store_true")
    args = ap.parse_args()

    states = [s.strip() for s in args.states.split(",") if s.strip()]
    for s in states:
        if s not in STATES:
            raise SystemExit(f"unknown state {s!r}; known: {sorted(STATES)}")

    judge = None
    if args.no_judge:
        print("!! JUDGE SKIPPED. 2.4.3 is NOT verified by this run.\n")
    else:
        from agent.judge import make_judge
        judge = make_judge()

    try:
        import weave

        weave.init(wb_env.bootstrap()["ref"])
    except Exception as exc:
        print(f"!! weave.init failed, this run is NOT on the record: "
              f"{type(exc).__name__}: {str(exc)[:80]}")

    scratch = pathlib.Path(os.environ.get("TEMP", ".")) / f"ally-local-{args.tag}"
    scratch.mkdir(parents=True, exist_ok=True)
    proc = start_chrome(scratch / "profile")
    # _assemble needs no sandbox: it only decodes screenshots and computes the
    # focus deltas, both of which are local already.
    asm = Session.__new__(Session)

    # Preflight. Nothing downstream asserts the page is the page: our `loaded`
    # state is satisfied by readyState alone, which a 402, a 404 and a paywall
    # all satisfy too. allrecipes.com returned 402 and a 316-character block
    # notice, and all five checks reported a confident pass on it. The status and
    # the shape of the DOM are printed before any check runs so that cannot be
    # mistaken for a clean audit again.
    pre = preflight(args.url, scratch / "ally_preflight.py")
    print(f"site: {args.url}")
    print(f"  HTTP {pre.get('status')}   title {str(pre.get('title'))[:50]!r}")
    print(f"  {pre.get('focusable')} focusable, {pre.get('iframes')} iframe(s), "
          f"{pre.get('dialogs')} dialog(s), {pre.get('expandable')} expandable, "
          f"{pre.get('text')} chars of text")
    if pre.get("status") not in (200, 0, None) or (pre.get("text") or 0) < 1000:
        print("  !! this does not look like the real page. Every number below is "
              "then measuring an error page, not a site.")
    print("no patching; checks only\n")
    findings, artifact = [], {"url": args.url, "states": {}, "findings": []}
    try:
        for state in states:
            try:
                raw = record(args.url, state, f"{args.tag}-{state}",
                             scratch / "ally_record.py")
            except Exception as exc:
                print(f"=== {state}: RECORDER FAILED: {type(exc).__name__}: "
                      f"{str(exc)[:160]}\n")
                continue
            rec = asm._assemble(raw, f"{args.tag}-{state}")
            print(f"=== {state} ===")
            print(f"  reached={rec.state_reached}  truncated={rec.truncated}  "
                  f"stops={len(rec.stops)}  candidates={len(rec.candidates)}  "
                  f"excluded={len(rec.excluded)}")
            print(f"  reach: {rec.reach_note[:100]}")
            if not rec.state_reached:
                print("  every criterion is not_evaluated for this state\n")

            for criterion, fn in checks.CHECKS.items():
                with checks.criterion_tag(criterion, state, args.url):
                    r = fn(rec) if criterion != "2.4.3" else fn(rec, judge=judge)
                findings.append((state, r))
                artifact["findings"].append(dict(r.to_dict(), state_label=state))
                print(f"  {criterion:8s} {r.status:14s} {r.census.line}")
                detail = (r.summary or r.reason or "")[:150]
                print(f"           {detail}")
                if r.targets:
                    for t in r.targets[:6]:
                        print(f"             target: {t}")
            artifact["states"][state] = rec.to_dict()
            print()
    finally:
        proc.terminate()

    print("=" * 94)
    print(f"CENSUS TOTALS  {args.url}")
    print("=" * 94)
    print(f"{'criterion':10s} {'examined':>9s} {'failed':>7s} {'passed':>7s} "
          f"{'undecided':>10s} {'nothing':>8s} {'excluded':>9s}")
    print("-" * 94)
    for criterion in checks.CHECKS:
        rs = [r for _, r in findings if r.criterion == criterion]
        c = [r.census for r in rs]
        print(f"{criterion:10s} {sum(x.examined for x in c):>9d} "
              f"{sum(x.failed for x in c):>7d} {sum(x.passed for x in c):>7d} "
              f"{sum(x.undecided for x in c):>10d} "
              f"{sum(x.inapplicable for x in c):>8d} "
              f"{sum(x.excluded for x in c):>9d}")
    print("-" * 94)
    notes = sorted({x.exclusion_note for _, r in findings
                    if (x := r.census).exclusion_note})
    if notes:
        print("exclusion reasons: " + "; ".join(notes))

    fired = [(s, r) for s, r in findings if r.status == "failed"]
    print(f"\n{len(fired)} finding(s) reported. Every one needs a verdict by hand: "
          "this page has no manifest.")

    out = ROOT / "artifacts" / f"{args.tag}-local.json"
    out.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"saved {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
