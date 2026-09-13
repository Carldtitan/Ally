"""Drive a live website inside a Daytona sandbox using Daytona computer use.

This is the Ally interaction loop in miniature (Dos-and-donts 4.2): press Tab,
ask the page which element now has focus, record it with a screenshot. Watch it
happen live on the sandbox's noVNC preview URL while it runs.

Usage:
    python tools/daytona_drive.py <sandbox-id> [url]
"""

from __future__ import annotations

import os
import sys
import json
import time
import base64
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

from daytona import Daytona, DaytonaConfig  # noqa: E402

SANDBOX_ID = sys.argv[1]
URL = sys.argv[2] if len(sys.argv) > 2 else "https://www.wikipedia.org"
SHOTS = pathlib.Path("artifacts/focus-run")
SHOTS.mkdir(parents=True, exist_ok=True)

d = Daytona(DaytonaConfig(
    api_key=os.environ["DAYTONA_API_KEY"],
    api_url=os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api"),
))
sb = d.get(SANDBOX_ID)
# get_preview_link returns the port root, which noVNC serves as a bare
# directory index. The viewer itself lives at /vnc.html.
watch = sb.get_preview_link(6080).url.rstrip("/") + "/vnc.html?autoconnect=true&resize=scale"
print("WATCH:", watch, flush=True)

# A CDP client that lives inside the sandbox. Chromium exposes DevTools on
# 9222; Runtime.evaluate is how we ask the page what has focus, which is the
# one question a screenshot cannot answer (rule 4.5).
READER = r'''
import json, sys, urllib.request
from websocket import create_connection
tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
page = next(t for t in tabs if t["type"] == "page")
ws = create_connection(page["webSocketDebuggerUrl"], timeout=15)
ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
    "returnByValue": True,
    "expression": """(() => { const e = document.activeElement; if (!e) return null;
      const r = e.getBoundingClientRect();
      return { tag: e.tagName, type: e.type || null,
               text: (e.innerText || e.value || e.getAttribute('aria-label') || '').trim().slice(0, 45),
               href: (e.getAttribute('href') || '').slice(0, 45),
               x: Math.round(r.x), y: Math.round(r.y),
               w: Math.round(r.width), h: Math.round(r.height) }; })()"""}}))
while True:
    m = json.loads(ws.recv())
    if m.get("id") == 1:
        print(json.dumps(m["result"]["result"].get("value")))
        break
ws.close()
'''

print(f"\nlaunching chromium at {URL} (with CDP on 9222) ...", flush=True)
sb.process.exec("pkill -f chromium; sleep 1; true", timeout=60)
sb.process.exec(
    "DISPLAY=:0 nohup chromium --no-sandbox --disable-dev-shm-usage --disable-gpu "
    # --remote-allow-origins is required or Chromium rejects the CDP websocket
    # handshake with 403 Forbidden, even from 127.0.0.1.
    "--no-first-run --disable-infobars --remote-debugging-port=9222 "
    "--remote-allow-origins=* "
    f"--window-size=1024,740 --window-position=0,0 '{URL}' "
    "> /tmp/chromium.log 2>&1 & echo ok",
    timeout=90,
)
sb.process.exec("pip install --quiet websocket-client 2>&1 | tail -1; true", timeout=180)
time.sleep(10)

sb.fs.upload_file(READER.encode(), "/tmp/focus.py")

wins = getattr(sb.computer_use.display.get_windows(), "windows", [])
print("windows:", [w.title for w in wins])


def shot(name: str) -> int:
    r = sb.computer_use.screenshot.take_full_screen()
    raw = base64.b64decode(r.screenshot)
    (SHOTS / f"{name}.png").write_bytes(raw)
    return len(raw)


def focus() -> dict | None:
    r = sb.process.exec("cd /tmp && python3 focus.py", timeout=60)
    try:
        return json.loads((r.result or "").strip().splitlines()[-1])
    except Exception:
        return None


print("loaded:", shot("00-loaded"), "bytes", flush=True)

print("\npressing Tab and recording focus (the 2.4.3 loop):\n", flush=True)
stops = []
for i in range(1, 9):
    sb.computer_use.keyboard.press("Tab")
    time.sleep(0.9)
    f = focus()
    n = shot(f"{i:02d}-tab")
    stops.append({"n": i, "focus": f, "png_bytes": n})
    if f:
        print(f"  Tab {i}: <{f['tag']}> {f['text']!r:48s} at ({f['x']},{f['y']}) {n}b", flush=True)
    else:
        print(f"  Tab {i}: focus unreadable, {n}b", flush=True)

(SHOTS / "focus-stops.json").write_text(json.dumps(stops, indent=2))
print(f"\n{len(stops)} stops -> {SHOTS}/focus-stops.json")
print("screenshots:", len(list(SHOTS.glob('*.png'))))
print("\nSTILL WATCHABLE:", watch)
