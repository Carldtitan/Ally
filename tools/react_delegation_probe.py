"""Does source 2 or source 3 see a React <div onClick>?

The 2.1.1 plan has three sources. Sources 2 and 3 both assume the handler is
attached to the element itself:

  source 2: a DOM query for an `onclick` ATTRIBUTE
  source 3: CDP getEventListeners on the ELEMENT

React does neither. Since React 17 it attaches one listener at the root
container and dispatches synthetically, so a <div onClick={...}> carries no
onclick attribute and no element-level listener.

The clean app deploys on Vercel, so it is probably React. If both sources miss
a React div-as-button, the planted 2.1.1 defect escapes and recall is zero for
a reason that has nothing to do with the checker.

Usage:  python tools/react_delegation_probe.py <sandbox-id>
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

# React 18 UMD from unpkg, which IS on Daytona's allowlist (cdnjs/jsdelivr are not).
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>react delegation</title><style>.ptr{cursor:pointer}</style></head><body>
<div id="root"></div>
<script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>
<script>
var e = React.createElement;
function App() {
  return e('div', null,
    e('button', {id: 'react_button', onClick: function(){}}, 'Real React button'),
    // the planted 2.1.1 defect, written the way React writes it
    e('div', {id: 'react_div_styled', className: 'ptr', onClick: function(){}}, 'Save (styled)'),
    // same thing with no pointer styling at all
    e('div', {id: 'react_div_bare', onClick: function(){}}, 'Save (bare)')
  );
}
ReactDOM.createRoot(document.getElementById('root')).render(e(App));
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

send("Page.navigate", {"url": "http://localhost:3000/react.html"})
time.sleep(6)
send("DOM.enable"); send("DOMDebugger.enable")

out = {"react_loaded": False, "rows": [], "root_listeners": []}
r = send("Runtime.evaluate", {"returnByValue": True,
     "expression": "typeof React !== 'undefined' && !!document.getElementById('react_button')"})
out["react_loaded"] = bool(r["result"]["result"].get("value"))

for el in ["react_button", "react_div_styled", "react_div_bare"]:
    row = {"id": el}
    r = send("Runtime.evaluate", {"expression": "document.getElementById('%s')" % el})
    oid = r["result"]["result"].get("objectId")
    if not oid:
        row["missing"] = True
        out["rows"].append(row); continue
    g = send("DOMDebugger.getEventListeners", {"objectId": oid})
    row["source3_listeners"] = [l["type"] for l in g.get("result", {}).get("listeners", [])]
    d = send("Runtime.callFunctionOn", {"objectId": oid, "returnByValue": True,
        "functionDeclaration": """function(){return {
            onclick_attr: this.hasAttribute('onclick'),
            cursor: getComputedStyle(this).cursor,
            tabindex: this.getAttribute('tabindex'),
            role: this.getAttribute('role'),
            focusable: this.tabIndex >= 0};}"""})
    row["dom"] = d["result"]["result"]["value"]
    out["rows"].append(row)

# where did React actually put its listener?
r = send("Runtime.evaluate", {"expression": "document.getElementById('root')"})
oid = r["result"]["result"].get("objectId")
if oid:
    g = send("DOMDebugger.getEventListeners", {"objectId": oid})
    out["root_listeners"] = sorted({l["type"] for l in g.get("result", {}).get("listeners", [])})
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

sb.fs.upload_file(PAGE.encode(), "/tmp/site/react.html")
sb.fs.upload_file(RUNNER.encode(), "/tmp/rprobe.py")
sb.process.exec("pkill -f http.server; cd /tmp/site && nohup python3 -m http.server 3000 "
                "> /tmp/srv.log 2>&1 & echo ok", timeout=60)
sb.process.exec("pkill -f chromium; sleep 1; DISPLAY=:0 nohup chromium --no-sandbox "
                "--disable-dev-shm-usage --disable-gpu --no-first-run "
                "--remote-debugging-port=9222 --remote-allow-origins=* "
                "--window-size=1024,740 about:blank > /tmp/c.log 2>&1 & echo ok", timeout=90)

r = sb.process.exec("cd /tmp && python3 rprobe.py 2>&1 | tail -3", timeout=300)
out = (r.result or "").strip()
line = next((l for l in out.splitlines() if l.startswith("RESULT")), None)
if not line:
    print("no result:\n", out[:800]); raise SystemExit(1)
data = json.loads(line[7:])

print("React actually loaded and rendered:", data["react_loaded"])
if not data["react_loaded"]:
    print("  (unpkg may be blocked - the result below is meaningless)")

print(f"\n{'element':20s} {'src3 listeners':16s} {'src2: onclick':14s} {'cursor':10s} focusable")
for row in data["rows"]:
    if row.get("missing"):
        print(f"  {row['id']:18s} NOT RENDERED"); continue
    dm = row["dom"]
    l = ",".join(row["source3_listeners"]) or "(none)"
    print(f"  {row['id']:18s} {l:16s} {str(dm['onclick_attr']):14s} "
          f"{dm['cursor']:10s} {dm['focusable']}")

print(f"\nReact's own listeners live on #root: {data['root_listeners'][:8]}")

print("\n--- what this means for 2.1.1 ---")
for row in data["rows"]:
    if row.get("missing") or row["id"] == "react_button":
        continue
    dm = row["dom"]
    s3 = "click" in row["source3_listeners"]
    s2 = dm["onclick_attr"] or dm["cursor"] == "pointer"
    verdict = "CAUGHT" if (s2 or s3) else "ESCAPES BOTH SOURCES"
    print(f"  {row['id']:18s} source2={'yes' if s2 else 'no':3s} "
          f"source3={'yes' if s3 else 'no':3s}  -> {verdict}")
