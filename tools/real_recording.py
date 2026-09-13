"""Record the four fixed states on the live clean app, then answer two open questions.

1. Does the TypeSafe gate say `yes` to a REAL recording? It has only ever been
   tested on three synthetic bad ones plus a synthetic good one. A gate tuned to
   reject junk that also rejects real pages would block every audit, and we would
   not find out until a run returned five not_evaluated.

2. What does a state actually cost? Screenshot bytes, recording bytes, tab stops.
   Every state the explorer reaches is another one of these, against 1GB of Weave
   ingestion a month and a hard $100 inference cap.

Usage:  python tools/real_recording.py <sandbox-id> [url]
"""

from __future__ import annotations

import os
import sys
import json
import time
import pathlib
import urllib.request

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

from daytona import Daytona, DaytonaConfig  # noqa: E402

SANDBOX_ID = sys.argv[1]
URL = sys.argv[2] if len(sys.argv) > 2 else "https://ally-clean-app.vercel.app"
MAX_TABS = 40

# The fixed list from SCOPE.md. Each entry says how to reach the state, as a
# JS expression run after load. No model, no explorer.
STATES = {
    "loaded": "null",
    "dialog-open": "document.querySelector(\"button[onclick*='openDialog']\").click()",
    "menu-open": "document.getElementById('menubutton1').click()",
    "tabs-focused": "document.getElementById('tab-1').focus()",
}

RUNNER = r'''
import json, time, base64, urllib.request
from websocket import create_connection

STATES = __STATES__
URL = "__URL__"
MAX_TABS = __MAXTABS__

tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
page = next(t for t in tabs if t["type"] == "page")
ws = create_connection(page["webSocketDebuggerUrl"], timeout=40, max_size=40_000_000)
mid = 0
def send(m, p=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            return r

send("DOM.enable"); send("Accessibility.enable"); send("Page.enable")

def tab():
    send("Input.dispatchKeyEvent", {"type": "rawKeyDown", "windowsVirtualKeyCode": 9,
                                    "key": "Tab", "code": "Tab"})
    send("Input.dispatchKeyEvent", {"type": "keyUp", "windowsVirtualKeyCode": 9,
                                    "key": "Tab", "code": "Tab"})

def focused():
    r = send("Runtime.evaluate", {"expression": "document.activeElement"})
    oid = r["result"]["result"].get("objectId")
    if not oid:
        return None
    d = send("Runtime.callFunctionOn", {"objectId": oid, "returnByValue": True,
        "functionDeclaration": """function(){var r=this.getBoundingClientRect();return{
            tag:this.tagName, id:this.id||null,
            x:Math.round(r.x+window.scrollX), y:Math.round(r.y+window.scrollY),
            vx:Math.round(r.x), vy:Math.round(r.y),
            w:Math.round(r.width), h:Math.round(r.height)};}"""})
    info = d["result"]["result"]["value"]
    a = send("Accessibility.getPartialAXTree", {"objectId": oid, "fetchRelatives": False})
    for nd in a.get("result", {}).get("nodes", []):
        if nd.get("ignored"):
            continue
        info["name"] = (nd.get("name") or {}).get("value")
        info["role"] = (nd.get("role") or {}).get("value")
        break
    info.setdefault("name", None); info.setdefault("role", None)
    return info

def shot():
    r = send("Page.captureScreenshot", {"format": "png"})
    return len(base64.b64decode(r["result"]["result"]["data"] if "result" in r["result"] else r["result"]["data"]))

out = {}
for state, reach in STATES.items():
    send("Page.navigate", {"url": URL})
    time.sleep(4)
    if reach != "null":
        send("Runtime.evaluate", {"expression": reach})
        time.sleep(1.2)
    else:
        send("Runtime.evaluate", {"expression": "document.body.focus()"})

    stops, png_bytes, first = [], 0, None
    for i in range(MAX_TABS):
        tab(); time.sleep(0.28)
        f = focused()
        if f is None:
            break
        png_bytes += shot()
        key = (f["tag"], f.get("id"), f["x"], f["y"])
        # a wrap: focus returned to where it started, or fell out to BODY
        if f["tag"] == "BODY" and i > 0:
            stops.append(f); break
        if first is not None and key == first and i > 0:
            stops.append(f); break
        if first is None:
            first = key
        stops.append(f)

    out[state] = {"stops": stops, "png_bytes": png_bytes,
                  "recording_bytes": len(json.dumps(stops))}

print("RESULT " + json.dumps(out))
ws.close()
'''


def main() -> None:
    d = Daytona(DaytonaConfig(
        api_key=os.environ["DAYTONA_API_KEY"],
        api_url=os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api"),
    ))
    sb = d.get(SANDBOX_ID)
    if str(sb.state) != "SandboxState.STARTED":
        print("starting sandbox ...")
        d.start(sb)
        sb = d.get(SANDBOX_ID)

    runner = (RUNNER
              .replace("__STATES__", json.dumps(STATES))
              .replace("__URL__", URL)
              .replace("__MAXTABS__", str(MAX_TABS)))
    sb.fs.upload_file(runner.encode(), "/tmp/record.py")
    sb.process.exec("pkill -f chromium; sleep 2; DISPLAY=:0 nohup chromium --no-sandbox "
                    "--disable-dev-shm-usage --disable-gpu --no-first-run "
                    "--remote-debugging-port=9222 --remote-allow-origins=* "
                    "--window-size=1024,740 about:blank > /tmp/c.log 2>&1 & echo ok", timeout=120)
    r = sb.process.exec("cd /tmp && python3 record.py 2>&1 | tail -3", timeout=600)
    out = (r.result or "").strip()
    line = next((l for l in out.splitlines() if l.startswith("RESULT")), None)
    if not line:
        print("no result:\n", out[:900])
        raise SystemExit(1)
    rec = json.loads(line[7:])

    print(f"target: {URL}\n")
    print(f"{'state':16s} {'stops':>5s} {'png KB':>8s} {'rec bytes':>10s}  first three stops")
    print("-" * 100)
    tot_stops = tot_png = tot_rec = 0
    for state, data in rec.items():
        stops = data["stops"]
        tot_stops += len(stops)
        tot_png += data["png_bytes"]
        tot_rec += data["recording_bytes"]
        preview = ", ".join(
            f"{s['role'] or s['tag']}:{(s['name'] or '')[:16]}" for s in stops[:3])
        print(f"{state:16s} {len(stops):5d} {data['png_bytes']/1024:8.0f} "
              f"{data['recording_bytes']:10d}  {preview}")
    print("-" * 100)
    print(f"{'TOTAL':16s} {tot_stops:5d} {tot_png/1024:8.0f} {tot_rec:10d}")

    pathlib.Path("artifacts").mkdir(exist_ok=True)
    pathlib.Path("artifacts/real-recording.json").write_text(
        json.dumps(rec, indent=2), encoding="utf-8")

    # ---- question 2: what does a run cost? ------------------------------
    print("\n=== cost of one benchmark run (4 states, clean + broken = 8 recordings) ===")
    per_run_png = tot_png * 2
    per_run_rec = tot_rec * 2
    print(f"  screenshots on disk      : {per_run_png/1024/1024:.1f} MB  (never sent to Weave)")
    print(f"  recordings into Weave    : {per_run_rec/1024:.0f} KB  (refs and stops only)")
    budget = 1024 * 1024 * 1024
    print(f"  runs before the 1GB cap  : {budget // max(per_run_rec, 1):,}  logging refs")
    print(f"                             {budget // max(per_run_png, 1):,}  if we logged the PNGs")

    # ---- question 3: does the gate accept a REAL recording? -------------
    print("\n=== TypeSafe gate against the real recordings ===")
    import typesafe_gate as G
    for state, data in rec.items():
        stops = [{"tag": s["tag"], "name": s["name"] or "", "x": s["x"], "y": s["y"],
                  "w": s["w"], "h": s["h"]} for s in data["stops"]]
        if not stops:
            print(f"  {state:16s} no stops recorded"); continue
        a = G.ask(G.render(stops))
        g = a["answers"]["judgeable"]
        verdict = "OK" if g["choice"] == "yes" else "REJECTED A REAL PAGE"
        print(f"  {state:16s} gate={g['choice']:4s} conf={g['confidence']:.2f} "
              f"noul={a['answers']['trustworthy']['noul']:.2f}  {verdict}")


if __name__ == "__main__":
    main()
