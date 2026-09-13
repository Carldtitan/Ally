"""Does CDP DOMDebugger.getEventListeners actually find click handlers?

Source 3 of the 2.1.1 element list assumes it returns elements carrying click
handlers bound through addEventListener, which the DOM query in source 2 cannot
see. That is load-bearing for catching the failure in production code, and it
has not been tested.

Also measures how long a whole-page scan takes, because getEventListeners works
one element at a time and 2.1.1 needs every element on the page.

Usage:  python tools/listener_probe.py <sandbox-id>
"""

from __future__ import annotations

import os
import sys
import json
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

from daytona import Daytona, DaytonaConfig  # noqa: E402

SANDBOX_ID = sys.argv[1]

# Four ways to make something clickable. Only one is a real button.
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>listener probe</title><style>.ptr{cursor:pointer}</style></head><body>
<button id="real">Real button</button>

<!-- inline onclick attribute: source 2 (DOM query) sees this -->
<div id="inline_attr" onclick="void 0">Inline onclick</div>

<!-- addEventListener: source 2 CANNOT see this, source 3 should -->
<div id="added_listener">Added listener</div>

<!-- addEventListener AND no cursor:pointer, the hardest case -->
<span id="bare_span">Bare span with handler</span>

<!-- looks clickable, has NO handler at all: a false-positive trap for source 2 -->
<div id="ptr_only" class="ptr">Pointer cursor, no handler</div>

<script>
document.getElementById('added_listener').addEventListener('click', function(){});
document.getElementById('bare_span').addEventListener('click', function(){});
// a delegated handler on document, which is how many frameworks really do it
document.addEventListener('click', function(e){ /* delegation */ });
</script>
</body></html>
"""

RUNNER = r'''
import json, time, urllib.request
from websocket import create_connection
tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
page = next(t for t in tabs if t["type"] == "page")
ws = create_connection(page["webSocketDebuggerUrl"], timeout=30)
mid = 0
def send(method, params=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == mid:
            return m

send("Page.navigate", {"url": "http://localhost:3000/listeners.html"})
time.sleep(3)
send("DOM.enable"); send("DOMDebugger.enable")

out = {"per_element": [], "page_scan": {}}

for el in ["real", "inline_attr", "added_listener", "bare_span", "ptr_only"]:
    r = send("Runtime.evaluate", {"expression": "document.getElementById('%s')" % el})
    oid = r["result"]["result"].get("objectId")
    row = {"id": el, "listeners": [], "error": None}
    if oid:
        g = send("DOMDebugger.getEventListeners", {"objectId": oid})
        if "error" in g:
            row["error"] = g["error"].get("message")
        else:
            row["listeners"] = [l["type"] for l in g["result"].get("listeners", [])]
    out["per_element"].append(row)

# whole-page scan: how long, and what does it find?
t0 = time.time()
r = send("Runtime.evaluate", {"expression":
    "Array.from(document.querySelectorAll('*'))", "returnByValue": False})
arr = r["result"]["result"]["objectId"]
props = send("Runtime.getProperties", {"objectId": arr, "ownProperties": True})
found = []
n = 0
for p in props["result"]["result"]:
    if not p["name"].isdigit():
        continue
    oid = p.get("value", {}).get("objectId")
    if not oid:
        continue
    n += 1
    g = send("DOMDebugger.getEventListeners", {"objectId": oid})
    types = [l["type"] for l in g.get("result", {}).get("listeners", [])]
    if "click" in types:
        d = send("Runtime.callFunctionOn", {"objectId": oid, "returnByValue": True,
             "functionDeclaration": "function(){return this.id||this.tagName;}"})
        found.append(d["result"]["result"]["value"])
out["page_scan"] = {"elements_scanned": n, "with_click": found,
                    "seconds": round(time.time() - t0, 2)}
print("RESULT " + json.dumps(out))
ws.close()
'''

d = Daytona(DaytonaConfig(
    api_key=os.environ["DAYTONA_API_KEY"],
    api_url=os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api"),
))
sb = d.get(SANDBOX_ID)
if str(sb.state) != "SandboxState.STARTED":
    print("starting sandbox ...")
    d.start(sb)
    sb = d.get(SANDBOX_ID)

sb.fs.upload_file(PAGE.encode(), "/tmp/site/listeners.html")
sb.fs.upload_file(RUNNER.encode(), "/tmp/lprobe.py")
sb.process.exec("pkill -f http.server; cd /tmp/site && nohup python3 -m http.server 3000 "
                "> /tmp/srv.log 2>&1 & echo ok", timeout=60)
sb.process.exec("pkill -f chromium; sleep 1; DISPLAY=:0 nohup chromium --no-sandbox "
                "--disable-dev-shm-usage --disable-gpu --no-first-run "
                "--remote-debugging-port=9222 --remote-allow-origins=* "
                "--window-size=1024,740 about:blank > /tmp/c.log 2>&1 & echo ok", timeout=90)
sb.process.exec("pip install --quiet websocket-client 2>&1|tail -1; true", timeout=180)

r = sb.process.exec("cd /tmp && python3 lprobe.py 2>&1 | tail -3", timeout=300)
out = (r.result or "").strip()
line = next((l for l in out.splitlines() if l.startswith("RESULT")), None)
if not line:
    print("no result:\n", out[:800])
    raise SystemExit(1)
data = json.loads(line[7:])

print("=== per element: what getEventListeners returns ===")
print(f"{'element':18s} {'listeners':28s} note")
NOTES = {
    "real": "real button - focusable anyway",
    "inline_attr": "source 2 (DOM query) also sees this",
    "added_listener": "source 2 CANNOT see this - needs source 3",
    "bare_span": "no cursor:pointer either - hardest case",
    "ptr_only": "looks clickable, NO handler - source 2 false positive",
}
for row in data["per_element"]:
    lst = ",".join(row["listeners"]) or ("ERROR: " + str(row["error"]) if row["error"] else "(none)")
    print(f"  {row['id']:16s} {lst:28s} {NOTES[row['id']]}")

ps = data["page_scan"]
print(f"\n=== whole-page scan ===")
print(f"  elements scanned : {ps['elements_scanned']}")
print(f"  with click handler: {ps['with_click']}")
print(f"  time             : {ps['seconds']}s")
