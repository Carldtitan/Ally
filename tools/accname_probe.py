"""How should the recorder read an accessible name?

The recording spec says each focus stop carries "tag, accessible name and
bounding box". My first driver computed the name as
`innerText || value || aria-label`, and on the deployed clean app that produced
'none' for the switch and '' for two labelled inputs.

If those names are wrong, 2.1.1 breaks: it matches the accessibility tree
against the focus stops, and the match is on identity. A stop whose name is ''
cannot be matched to a tree node named 'Name', so a reachable control looks
unreachable and the clean app reports false positives.

This compares the naive read against the accessibility tree's computed name,
which is the one the standard defines, on the real deployed page.

Usage:  python tools/accname_probe.py <sandbox-id> [url]
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
URL = sys.argv[2] if len(sys.argv) > 2 else "https://ally-clean-app.vercel.app"

RUNNER = r'''
import json, time, urllib.request
from websocket import create_connection
tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
page = next(t for t in tabs if t["type"] == "page")
ws = create_connection(page["webSocketDebuggerUrl"], timeout=30)
mid = 0
def send(m, p=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            return r

send("DOM.enable"); send("Accessibility.enable"); send("DOM.getDocument", {"depth": -1})
send("Page.navigate", {"url": "URL_HERE"}); time.sleep(5)
send("Runtime.evaluate", {"expression": "document.body.focus()"})

rows = []
for i in range(10):
    send("Input.dispatchKeyEvent", {"type": "rawKeyDown", "windowsVirtualKeyCode": 9,
                                    "key": "Tab", "code": "Tab"})
    send("Input.dispatchKeyEvent", {"type": "keyUp", "windowsVirtualKeyCode": 9,
                                    "key": "Tab", "code": "Tab"})
    time.sleep(0.35)

    r = send("Runtime.evaluate", {"expression": "document.activeElement"})
    oid = r["result"]["result"].get("objectId")
    if not oid:
        continue

    # the naive read my first driver used
    n = send("Runtime.callFunctionOn", {"objectId": oid, "returnByValue": True,
        "functionDeclaration": """function(){return {
            tag:this.tagName,
            naive:(this.innerText||this.value||this.getAttribute('aria-label')||'').trim().slice(0,40),
            id:this.id||null};}"""})
    info = n["result"]["result"]["value"]

    # The accessibility tree's computed name, which is the one the standard
    # defines. Pass objectId directly: going via DOM.requestNode needs a prior
    # DOM.getDocument to populate the node map, and without it every lookup
    # silently returns nothing.
    ax_name, ax_role = None, None
    a = send("Accessibility.getPartialAXTree",
             {"objectId": oid, "fetchRelatives": False})
    nodes = a.get("result", {}).get("nodes", [])
    for nd in nodes:
        if nd.get("ignored"):
            continue
        ax_name = (nd.get("name") or {}).get("value")
        ax_role = (nd.get("role") or {}).get("value")
        break
    info["ax_name"] = ax_name
    info["ax_role"] = ax_role
    rows.append(info)

print("RESULT " + json.dumps(rows))
ws.close()
'''.replace("URL_HERE", URL)

d = Daytona(DaytonaConfig(
    api_key=os.environ["DAYTONA_API_KEY"],
    api_url=os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api"),
))
sb = d.get(SANDBOX_ID)
if str(sb.state) != "SandboxState.STARTED":
    print("starting sandbox ...")
    d.start(sb)
    sb = d.get(SANDBOX_ID)

sb.fs.upload_file(RUNNER.encode(), "/tmp/accname.py")
sb.process.exec("pkill -f chromium; sleep 2; DISPLAY=:0 nohup chromium --no-sandbox "
                "--disable-dev-shm-usage --disable-gpu --no-first-run "
                "--remote-debugging-port=9222 --remote-allow-origins=* "
                "--window-size=1024,740 about:blank > /tmp/c.log 2>&1 & echo ok", timeout=120)
r = sb.process.exec("cd /tmp && python3 accname.py 2>&1 | tail -3", timeout=300)
out = (r.result or "").strip()
line = next((l for l in out.splitlines() if l.startswith("RESULT")), None)
if not line:
    print("no result:\n", out[:800])
    raise SystemExit(1)
rows = json.loads(line[7:])

print(f"target: {URL}\n")
print(f"{'#':>2} {'tag':8s} {'naive read':26s} {'AX tree name':26s} {'AX role':14s} agree")
print("-" * 92)
disagree = 0
for i, r_ in enumerate(rows, 1):
    naive = r_["naive"] or "(empty)"
    ax = r_["ax_name"] if r_["ax_name"] is not None else "(none)"
    same = (r_["naive"] or "") == (r_["ax_name"] or "")
    if not same:
        disagree += 1
    print(f"{i:2d} {r_['tag']:8s} {naive[:26]:26s} {str(ax)[:26]:26s} "
          f"{str(r_['ax_role'])[:14]:14s} {'yes' if same else 'NO'}")
print("-" * 92)
print(f"{disagree} of {len(rows)} stops disagree between the naive read and the AX tree")
