"""Is a React onClick a REAL element listener, or was the earlier probe reading delegation?

React has delegated to the root container since v17, so onClick should never
attach to the element. The earlier probe reported `click` on a React div, which
contradicts that. This settles it.

Method: one <div onClick> alone on a page. No refs. No addEventListener
anywhere in the file. Then print the FULL listener objects, resolve each
handler's scriptId to a URL, and dump the handler's own source. If the location
points into react-dom's bundle, the probe was reading React's dispatcher and
not a direct listener.

Usage:  python tools/react_listener_truth.py <sandbox-id>
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

# Deliberately minimal. One div, one onClick, nothing else that could bind a
# listener. If a `click` listener shows up on #target, React put it there.
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>react listener truth</title></head><body>
<div id="root"></div>
<script src="https://unpkg.com/react@18.3.1/umd/react.production.min.js"></script>
<script src="https://unpkg.com/react-dom@18.3.1/umd/react-dom.production.min.js"></script>
<script>
ReactDOM.createRoot(document.getElementById('root')).render(
  React.createElement('div', {id: 'target', onClick: function handlerFromJSX(){}}, 'Save')
);
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
scripts = {}          # scriptId -> url, filled from Debugger.scriptParsed events

def send(method, params=None):
    """Send a command and drain events, recording scriptParsed as we go."""
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
    while True:
        m = json.loads(ws.recv())
        if m.get("method") == "Debugger.scriptParsed":
            p = m["params"]
            scripts[p["scriptId"]] = p.get("url") or "(inline/eval)"
        if m.get("id") == mid:
            return m

send("Debugger.enable")
send("DOM.enable")
send("DOMDebugger.enable")
send("Page.navigate", {"url": "http://localhost:3000/truth.html"})
time.sleep(7)
send("Runtime.evaluate", {"expression": "1"})   # drain any late scriptParsed

out = {"scripts_seen": len(scripts), "targets": {}}

for el in ("target", "root"):
    r = send("Runtime.evaluate", {"expression": "document.getElementById(%r)" % el})
    oid = r["result"]["result"].get("objectId")
    if not oid:
        out["targets"][el] = {"missing": True}
        continue
    g = send("DOMDebugger.getEventListeners", {"objectId": oid})
    raw = g.get("result", {}).get("listeners", [])
    rows = []
    for l in raw:
        if l["type"] != "click":
            continue
        sid = l.get("scriptId")
        row = {
            "type": l["type"],
            "useCapture": l.get("useCapture"),
            "passive": l.get("passive"),
            "scriptId": sid,
            "scriptUrl": scripts.get(sid, "UNRESOLVED"),
            "line": l.get("lineNumber"),
            "col": l.get("columnNumber"),
            "source": None,
        }
        h = l.get("handler") or {}
        if h.get("objectId"):
            d = send("Runtime.callFunctionOn", {
                "objectId": h["objectId"], "returnByValue": True,
                "functionDeclaration": "function(){return this.toString().slice(0,160);}"})
            row["source"] = d.get("result", {}).get("result", {}).get("value")
        rows.append(row)
    out["targets"][el] = {"click_listeners": rows, "all_types": len(raw)}

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

sb.fs.upload_file(PAGE.encode(), "/tmp/site/truth.html")
sb.fs.upload_file(RUNNER.encode(), "/tmp/truth.py")
sb.process.exec("pkill -f http.server; cd /tmp/site && nohup python3 -m http.server 3000 "
                "> /tmp/srv.log 2>&1 & echo ok", timeout=60)
sb.process.exec("pkill -f chromium; sleep 1; DISPLAY=:0 nohup chromium --no-sandbox "
                "--disable-dev-shm-usage --disable-gpu --no-first-run "
                "--remote-debugging-port=9222 --remote-allow-origins=* "
                "--window-size=1024,740 about:blank > /tmp/c.log 2>&1 & echo ok", timeout=90)

r = sb.process.exec("cd /tmp && python3 truth.py 2>&1 | tail -3", timeout=300)
out = (r.result or "").strip()
line = next((l for l in out.splitlines() if l.startswith("RESULT")), None)
if not line:
    print("no result:\n", out[:900])
    raise SystemExit(1)
data = json.loads(line[7:])

print(f"scripts parsed: {data['scripts_seen']}\n")
for el, info in data["targets"].items():
    if info.get("missing"):
        print(f"#{el}: NOT RENDERED")
        continue
    rows = info["click_listeners"]
    print(f"#{el}: {info['all_types']} listeners total, {len(rows)} of type click")
    for r_ in rows:
        print(f"    scriptUrl : {r_['scriptUrl']}")
        print(f"    location  : line {r_['line']} col {r_['col']}  "
              f"useCapture={r_['useCapture']} passive={r_['passive']}")
        print(f"    source    : {r_['source']}")
    print()

t = data["targets"].get("target", {})
rows = t.get("click_listeners", [])
print("--- verdict ---")
if not rows:
    print("  No click listener on the element. React onClick is NOT visible to")
    print("  getEventListeners. Source 3 cannot see React handlers.")
else:
    urls = {r_["scriptUrl"] for r_ in rows}
    if any("react" in u.lower() for u in urls):
        print("  A click listener IS reported, but its handler lives in React's bundle:")
        print("   ", urls)
        print("  That is React's dispatcher, not a handler bound to this element.")
    else:
        print("  Click listener resolves OUTSIDE React's bundle:", urls)
        print("  That would be a genuine element-level listener.")
