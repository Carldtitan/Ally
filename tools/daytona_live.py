"""Live Daytona computer-use demo for Ally.

Creates a sandbox, starts Daytona's computer-use stack (virtual display + VNC),
publishes a preview URL you can watch in a browser, then drives a real website
through the keyboard exactly the way Ally will: press Tab, ask the page what
has focus, record it.

The sandbox is left RUNNING so the stream stays watchable. Stop it with:
    python tools/daytona_live.py --stop <sandbox-id>
"""

from __future__ import annotations

import os
import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env

wb_env.load_dotenv()
wb_env.use_certifi_bundle()

from daytona import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams  # noqa: E402

TARGET_URL = os.environ.get("ALLY_TARGET_URL", "https://example.com")
VNC_PORT = 6080


def client() -> Daytona:
    return Daytona(DaytonaConfig(
        api_key=os.environ["DAYTONA_API_KEY"],
        api_url=os.environ.get("DAYTONA_API_URL", "https://app.daytona.io/api"),
    ))


if len(sys.argv) > 2 and sys.argv[1] == "--stop":
    d = client()
    sb = d.get(sys.argv[2])
    d.delete(sb)
    print("deleted", sys.argv[2])
    raise SystemExit(0)

d = client()

print("creating sandbox ...", flush=True)
t0 = time.perf_counter()
sandbox = d.create(CreateSandboxFromSnapshotParams(
    public=True,                 # so the preview URL opens without a token
    auto_stop_interval=30,       # minutes idle before Daytona stops it
    auto_archive_interval=60,
    labels={"project": "ally", "purpose": "computer-use-demo"},
))
print(f"  created in {time.perf_counter() - t0:.1f}s")
print(f"  id    : {sandbox.id}")
print(f"  state : {sandbox.state}")
for attr in ("cpu", "memory", "disk", "target"):
    print(f"  {attr:6s}: {getattr(sandbox, attr, '?')}")

# ---- what vCPU did we actually get, from inside the box? ------------------
print("\nreported from inside the sandbox:", flush=True)
for label, cmd in (
    ("nproc (HOST cores - do not size from this)", "nproc"),
    ("cgroup cpu.max", "cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo n/a"),
    ("cgroup memory.max", "cat /sys/fs/cgroup/memory.max 2>/dev/null || echo n/a"),
    ("kernel", "uname -sr"),
):
    try:
        r = sandbox.process.exec(cmd, timeout=60)
        print(f"  {label:44s}: {(r.result or '').strip()[:60]}")
    except Exception as exc:
        print(f"  {label:44s}: {type(exc).__name__}")

# ---- start the computer-use stack ----------------------------------------
print("\nstarting computer-use (virtual display + VNC) ...", flush=True)
t0 = time.perf_counter()
try:
    sandbox.computer_use.start()
    print(f"  started in {time.perf_counter() - t0:.1f}s")
except Exception as exc:
    print(f"  FAILED: {type(exc).__name__}: {str(exc)[:200]}")
    raise SystemExit(1)

for _ in range(30):
    try:
        st = sandbox.computer_use.get_status()
        print("  status:", st)
        break
    except Exception:
        time.sleep(2)

try:
    info = sandbox.computer_use.display.get_info()
    print("  display:", info)
except Exception as exc:
    print("  display info unavailable:", type(exc).__name__)

# ---- publish the watchable URL -------------------------------------------
print("\npreview links:", flush=True)
links = {}
for port in (VNC_PORT, 5900, 8080):
    try:
        link = sandbox.get_preview_link(port)
        url = getattr(link, "url", link)
        links[port] = url
        print(f"  port {port}: {url}")
    except Exception as exc:
        print(f"  port {port}: unavailable ({type(exc).__name__})")

print("\n" + "=" * 68)
if VNC_PORT in links:
    # noVNC serves a bare directory index at the port root; the viewer page
    # itself is /vnc.html. Hand over the URL that actually shows the desktop.
    print("WATCH HERE:", links[VNC_PORT].rstrip("/")
          + "/vnc.html?autoconnect=true&resize=scale")
print("sandbox id:", sandbox.id)
print("=" * 68, flush=True)
