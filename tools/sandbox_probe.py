"""Sandbox probe for Ally (W&B setup rules 3.6 / 5.2 / 5.3).

There are TWO ways to reach the same CoreWeave sandbox service, and they are
gated separately:

  AuthStrategy.WANDB              - via wandb.sandbox, authenticated with
                                    WANDB_API_KEY. Requires the *W&B org* to
                                    have sandboxes enabled. Ours does not:
                                    "sandboxes not enabled for this organization"

  AuthStrategy.COREWEAVE_API_KEY  - via cwsandbox directly against
                                    https://api.cwsandbox.com, authenticated
                                    with CWSANDBOX_API_KEY. A CoreWeave
                                    credential, independent of the W&B org flag.

This script tries the CoreWeave path first and falls back to the W&B path, so
it reports which doors are actually open. The whole Ally design assumes a
sandbox can load a live website, so this must pass before building on it.

Usage:
    CWSANDBOX_API_KEY=...  python tools/sandbox_probe.py
"""

from __future__ import annotations

import os
import sys
import json
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env  # noqa: E402

wb_env.bootstrap()

# Runs *inside* the sandbox. Answers rules 5.2 (egress) and 5.3 (cpu/memory).
PROBE = r'''
import json, socket, urllib.request, os
out = {}
try:
    socket.gethostbyname("example.com"); out["dns"] = "ok"
except Exception as e:
    out["dns"] = f"FAIL {type(e).__name__}"
try:
    r = urllib.request.urlopen("https://example.com", timeout=20)
    out["https"] = f"ok {r.status}"
except Exception as e:
    out["https"] = f"FAIL {type(e).__name__}: {str(e)[:80]}"
out["cpu_count"] = os.cpu_count()
for p in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
    try:
        v = open(p).read().strip()
        out["mem_limit"] = v if v == "max" else f"{int(v)/2**30:.2f} GiB"
        break
    except Exception:
        pass
try:
    q = open("/sys/fs/cgroup/cpu.max").read().split()
    out["cpu_quota"] = "unlimited" if q[0] == "max" else f"{int(q[0])/int(q[1]):.2f} cores"
except Exception:
    pass
print("PROBE_JSON " + json.dumps(out))
'''


def run_probe(sandbox_cls, auth, label):
    """Start one sandbox through `auth` and report egress + resources."""
    print(f"\n--- {label} ---", flush=True)
    t0 = time.perf_counter()
    try:
        kwargs = {"container_image": "python:3.11", "max_lifetime_seconds": 600}
        if auth is not None:
            kwargs["auth"] = auth
        with sandbox_cls.run(**kwargs) as sb:
            print(f"  started in {time.perf_counter() - t0:.1f}s  id={sb.sandbox_id}")
            for name, attr in (("egress policy", "effective_egress"),
                               ("ingress policy", "effective_ingress"),
                               ("resource limits", "resource_limits"),
                               ("resource requests", "resource_requests")):
                try:
                    print(f"  {name:18s}: {getattr(sb, attr)}")
                except Exception as exc:
                    print(f"  {name:18s}: unavailable ({type(exc).__name__})")

            res = sb.exec(["python", "-c", PROBE]).result()
            out = getattr(res, "stdout", "") or ""
            line = next((l for l in out.splitlines() if l.startswith("PROBE_JSON")), None)
            if not line:
                print("  no probe output. stdout:", out[:200])
                return False
            data = json.loads(line[len("PROBE_JSON "):])
            print("\n  RESULT")
            for k, v in data.items():
                print(f"    {k:12s}: {v}")
            ok = str(data.get("https", "")).startswith("ok")
            print(f"\n  EGRESS TO PUBLIC INTERNET: {'WORKS' if ok else 'BLOCKED'}")
            return ok
    except Exception as exc:
        print(f"  {type(exc).__name__}: {str(exc)[:220]}")
        return False


print("=" * 66)
print("Sandbox probe - trying both auth paths")
print("=" * 66)

attempted = []

# ---- Path 1: CoreWeave API key (independent of the W&B org flag) ----------
if os.environ.get("CWSANDBOX_API_KEY"):
    try:
        import cwsandbox
        from cwsandbox import AuthStrategy

        cls = getattr(cwsandbox, "Sandbox", None)
        if cls is None:
            from cwsandbox._sandbox import Sandbox as cls  # type: ignore
        attempted.append(run_probe(cls, AuthStrategy.COREWEAVE_API_KEY,
                                   "CoreWeave API key -> api.cwsandbox.com"))
    except Exception as exc:
        print(f"\n--- CoreWeave path ---\n  setup failed: {type(exc).__name__}: {exc}")
        attempted.append(False)
else:
    print("\n--- CoreWeave API key -> api.cwsandbox.com ---")
    print("  SKIPPED: CWSANDBOX_API_KEY is not set.")
    print("  This is the path the W&B staff pointed at. Get a CoreWeave")
    print("  sandbox key, export it, and re-run this script.")

# ---- Path 2: W&B org entitlement -----------------------------------------
try:
    from wandb.sandbox import Sandbox as WandbSandbox

    attempted.append(run_probe(WandbSandbox, None, "W&B API key -> org entitlement"))
except Exception as exc:
    print(f"\n--- W&B path ---\n  setup failed: {type(exc).__name__}: {exc}")
    attempted.append(False)

print("\n" + "=" * 66)
if any(attempted):
    print("At least one path works. Build on the one that succeeded.")
    raise SystemExit(0)
print("No sandbox path is open yet. Do not build on sandboxes (rule 3.6).")
print("Fallback for per-agent isolation: git worktrees (Dos-and-donts 8.4).")
raise SystemExit(1)
