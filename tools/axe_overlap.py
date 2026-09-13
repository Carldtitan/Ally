"""Does axe-core overlap our six criteria?

Two questions, both answered by calling axe rather than reasoning about it:

  A. Which axe rules are TAGGED with our six success criteria, and are they
     enabled by default? (axe 4.x ships target-size for 2.5.8, so this matters.)
  B. Running axe on a page carrying the revised six defects, what actually
     fires?

The scope claims "axe reports nothing on our six criteria". That claim is the
whole comparison, so it gets measured.

Usage:  python tools/axe_overlap.py <sandbox-id>
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

# Tag names axe uses for our six success criteria.
OUR_TAGS = {
    "wcag211": "2.1.1 Keyboard",
    "wcag212": "2.1.2 No Keyboard Trap",
    "wcag243": "2.4.3 Focus Order",
    "wcag247": "2.4.7 Focus Visible",
    "wcag2411": "2.4.11 Focus Not Obscured",
    "wcag258": "2.5.8 Target Size",
}

# The REVISED defect set: 2.4.3 broken with CSS order, not positive tabindex.
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Six planted defects</title><style>
body{font-family:sans-serif;padding:20px;margin:0}
.no-outline:focus{outline:none}
.tiny{width:16px;height:16px;padding:0;font-size:8px}
/* 2.4.3: visual order reversed against DOM order */
.row{display:flex}
.row .first{order:2}
.row .second{order:1}
footer{position:fixed;bottom:0;left:0;right:0;height:70px;background:#222;color:#fff}
</style></head><body>
<main>
<h1>Six planted defects</h1>

<!-- 2.1.1 Keyboard: a div acting as a button, never focusable -->
<div onclick="void 0" class="ctl">Save (div onclick)</div>

<!-- 2.1.2 No Keyboard Trap: keydown swallows Tab inside the dialog -->
<div id="dlg" role="dialog" aria-label="Trap"><button id="trapped">Inside dialog</button></div>
<script>
document.getElementById('dlg').addEventListener('keydown', function (e) {
  if (e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); }
});
</script>

<!-- 2.4.3 Focus Order: CSS order reverses these two visually -->
<div class="row">
  <button class="first">Comes first in the DOM</button>
  <button class="second">Comes second in the DOM</button>
</div>

<!-- 2.4.7 Focus Visible: outline removed -->
<button class="no-outline">Invisible focus</button>

<!-- 2.5.8 Target Size: under 24x24 -->
<button class="tiny">x</button>

<p>Some <a href="#a">inline link</a> in a sentence, which 2.5.8's Inline exception covers.</p>

<!-- 2.4.11 Focus Not Obscured: sticky footer covers this -->
<button id="covered">Covered by the footer</button>
<div style="height:40px"></div>
</main>
<footer>sticky footer</footer>
</body></html>
"""

RUNNER = r'''
import json, urllib.request, time
from websocket import create_connection
axe = open("/tmp/axe.min.js").read()
tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
page = next(t for t in tabs if t["type"] == "page")
ws = create_connection(page["webSocketDebuggerUrl"], timeout=30)
mid = 0
def send(method, params):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": method, "params": params}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == mid:
            return m
send("Page.navigate", {"url": "http://localhost:3000/defects.html"})
time.sleep(3)
send("Runtime.evaluate", {"expression": axe})

# A. the full rule inventory, with tags and default-enabled state
r = send("Runtime.evaluate", {"returnByValue": True, "expression":
    "JSON.stringify(axe.getRules().map(function(x){return {id:x.ruleId, tags:x.tags};}))"})
print("INVENTORY " + r["result"]["result"]["value"])

# B. what actually fires, with EVERY rule enabled (best-practice + experimental)
r = send("Runtime.evaluate", {"awaitPromise": True, "returnByValue": True, "expression":
    """axe.run(document, {resultTypes:['violations'],
        runOnly:{type:'tag', values:['wcag2a','wcag2aa','wcag21a','wcag21aa','wcag22aa',
                                     'best-practice','experimental']}})
       .then(function(x){return JSON.stringify(x.violations.map(function(v){
         return {id:v.id, impact:v.impact, tags:v.tags, nodes:v.nodes.length};}));})"""})
print("VIOLATIONS " + r["result"]["result"]["value"])
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

r = sb.process.exec(
    "cd /tmp && npm install --silent --no-fund --no-audit axe-core 2>&1 | tail -1; "
    "cp /tmp/node_modules/axe-core/axe.min.js /tmp/axe.min.js && "
    "node -e \"console.log(require('/tmp/node_modules/axe-core/package.json').version)\"",
    timeout=400)
print("axe-core", (r.result or "").strip()[-10:])

sb.fs.upload_file(PAGE.encode(), "/tmp/site/defects.html")
sb.fs.upload_file(RUNNER.encode(), "/tmp/axerun.py")
sb.process.exec("pkill -f http.server; cd /tmp/site && nohup python3 -m http.server 3000 "
                "> /tmp/srv.log 2>&1 & echo ok", timeout=60)
sb.process.exec("pkill -f chromium; sleep 1; DISPLAY=:0 nohup chromium --no-sandbox "
                "--disable-dev-shm-usage --disable-gpu --no-first-run "
                "--remote-debugging-port=9222 --remote-allow-origins=* "
                "--window-size=1024,740 about:blank > /tmp/c.log 2>&1 & echo ok", timeout=90)
sb.process.exec("pip install --quiet websocket-client 2>&1|tail -1; true", timeout=180)

r = sb.process.exec("cd /tmp && python3 axerun.py 2>&1 | tail -4", timeout=240)
out = (r.result or "").strip()
inv = json.loads(next(l for l in out.splitlines() if l.startswith("INVENTORY"))[10:])
vio = json.loads(next(l for l in out.splitlines() if l.startswith("VIOLATIONS"))[11:])

print(f"\n=== A. axe rules tagged with OUR six criteria ({len(inv)} rules total) ===")
hits = 0
for tag, name in OUR_TAGS.items():
    matching = [x for x in inv if tag in x["tags"]]
    if matching:
        hits += len(matching)
        for m in matching:
            kind = "best-practice" if "best-practice" in m["tags"] else "WCAG-tagged"
            print(f"  {name:28s} <- axe rule '{m['id']}' ({kind})")
    else:
        print(f"  {name:28s} <- no axe rule")
print(f"\n  overlap: {hits} axe rule(s) claim one of our six criteria")

print(f"\n=== B. what fired on the revised defect page ({len(vio)} rules) ===")
for v in vio:
    ours = [OUR_TAGS[t] for t in v["tags"] if t in OUR_TAGS]
    kind = "best-practice" if "best-practice" in v["tags"] else "WCAG"
    flag = "  <-- OVERLAPS OURS: " + ",".join(ours) if ours else ""
    print(f"  {v['id']:24s} {v['impact'] or '-':9s} {kind:13s} nodes={v['nodes']}{flag}")
if not any(t in OUR_TAGS for v in vio for t in v["tags"]):
    print("\n  No fired rule is tagged with any of our six. The claim holds.")
