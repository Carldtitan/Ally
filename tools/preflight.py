"""Preflight for Ally: proves the W&B surface works before a run depends on it.

Every check reports one of three states, never a boolean (Dos-and-donts 1.2):
  passed        - the check ran and succeeded
  failed        - the check ran and found a problem
  not_evaluated - the check could not run, and says why

Usage:  python tools/preflight.py
"""

from __future__ import annotations

import sys
import time
import uuid
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import wb_env  # noqa: E402

PASS, FAIL, SKIP = "passed", "failed", "not_evaluated"
results: list[tuple[str, str, str]] = []


def record(name: str, status: str, detail: str = "") -> None:
    results.append((name, status, detail))
    mark = {PASS: "PASS", FAIL: "FAIL", SKIP: "SKIP"}[status]
    print(f"  [{mark}] {name}" + (f" - {detail}" if detail else ""), flush=True)


# --------------------------------------------------------------- 1. config
print("\n1. Configuration")
try:
    cfg = wb_env.bootstrap()
    record("env loaded, entity is a bare slug", PASS, cfg["ref"])
except wb_env.ConfigError as exc:
    record("env loaded", FAIL, str(exc).splitlines()[0])
    raise SystemExit(1)

import certifi  # noqa: E402

record("TLS bundle pinned to certifi", PASS, certifi.where().split("site-packages")[-1])


# ------------------------------------------------------------- 2. identity
print("\n2. Identity")
try:
    import wandb

    viewer = wandb.Api(api_key=cfg["api_key"]).viewer
    teams = list(viewer.teams or [])
    record("API key authenticates", PASS, f"user={viewer.username}")
    if cfg["entity"] in teams:
        record("WANDB_ENTITY is a team you belong to", PASS, cfg["entity"])
    else:
        record("WANDB_ENTITY is a team you belong to", FAIL,
               f"{cfg['entity']!r} not in {teams}. Inference requires a team entity.")
except Exception as exc:
    record("API key authenticates", FAIL, f"{type(exc).__name__}: {exc}")


# ------------------------------------------- 3. weave init  (ORDER MATTERS)
# Rule 1.1: weave.init must run BEFORE any OpenAI client is constructed, or
# token and cost data is not captured for calls made through that client.
print("\n3. Weave init")
wc = None
try:
    import weave

    wc = weave.init(cfg["ref"])
    record("weave.init (precedes any model client)", PASS, cfg["ref"])
except ImportError:
    record("weave.init", SKIP, "weave not installed (pip install weave)")
except Exception as exc:
    record("weave.init", FAIL, f"{type(exc).__name__}: {str(exc)[:160]}")


# ------------------------------------------------------------ 4. inference
print("\n4. Inference")
try:
    client = wb_env.openai_client()
    models = sorted(m.id for m in client.models.list().data)
    record("model catalogue reachable", PASS, f"{len(models)} models")

    t0 = time.perf_counter()
    reply = client.chat.completions.create(
        model="meta-llama/Llama-3.1-8B-Instruct",
        messages=[{"role": "user", "content": "Reply with the single word: OK"}],
        max_tokens=5,
    )
    dt = time.perf_counter() - t0
    text = (reply.choices[0].message.content or "").strip()
    record("chat completion routed to team/project", PASS, f"{dt:.2f}s, said {text!r}")

    VISION = ("Qwen3.8-27B", "GLM-5.3-Flash", "gemma-4-31B", "Kimi-K2.7",
              "MiniMax-M3", "Qwen3.6-35B", "Qwen3.6-27B")
    seen = [m for m in models if any(v in m for v in VISION)]
    record("vision models present (Focus Visible needs one)", PASS, f"{len(seen)} available")
except Exception as exc:
    record("inference", FAIL, f"{type(exc).__name__}: {str(exc)[:160]}")


# --------------------------------------------------- 5. weave round-trip
print("\n5. Weave trace round-trip")
TIMEOUT = 90.0


def poll_until_readable(client_, call_id, timeout=TIMEOUT):
    """Seconds until get_call(call_id) succeeds, or None if it never does."""
    start = time.perf_counter()
    delay = 0.25
    while time.perf_counter() - start < timeout:
        try:
            if client_.get_call(call_id) is not None:
                return time.perf_counter() - start
        except Exception:
            pass
        time.sleep(delay)
        delay = min(delay * 1.4, 3.0)
    return None


if wc is None:
    record("weave round-trip", SKIP, "weave client not initialised in step 3")
else:
    try:
        marker = uuid.uuid4().hex[:12]

        @weave.op
        def ally_preflight_probe(marker: str) -> dict:
            """Stands in for a criterion judgement, so the trace shape is realistic."""
            return {"marker": marker, "criterion": "2.4.7", "status": "not_evaluated",
                    "reason": "preflight probe, no page was loaded"}

        _, call_a = ally_preflight_probe.call(marker)
        lag = poll_until_readable(wc, call_a.id)
        if lag is None:
            record("logged call readable by get_call", FAIL,
                   f"not queryable within {TIMEOUT:.0f}s")
        else:
            record("logged call readable by get_call", PASS,
                   f"{lag:.2f}s after the call returned")

        # op_name is the full "weave:///<entity>/<project>/op/<name>:<HASH>" URI.
        # A bare op name matches ZERO calls and does NOT raise, so never shorten
        # it: an empty result would otherwise mean both "no matches" and "wrong
        # filter", which is the ambiguity Dos-and-donts 1.4 warns about.
        found = list(wc.get_calls(filter={"op_names": [call_a.op_name]},
                                  columns=["inputs", "output", "summary"], limit=25))
        markers = [c.output.get("marker") for c in found
                   if isinstance(c.output, dict) and c.output.get("marker")]
        if marker in markers:
            record("filtered get_calls finds this run's call", PASS,
                   f"{len(found)} calls for this op, marker matched")
        else:
            record("filtered get_calls finds this run's call", FAIL,
                   f"{len(found)} calls returned, marker {marker} absent")

        # Cost is only populated when include_costs=True is passed explicitly.
        costed = list(wc.get_calls(filter={"op_names": [call_a.op_name]},
                                   limit=1, include_costs=True))
        has_costs = bool(costed and (costed[0].summary or {}).get("weave", {}).get("costs"))
        record("include_costs returns pricing", PASS if has_costs else SKIP,
               "USD figures present" if has_costs
               else "no costs on this op (only model calls carry pricing)")
    except Exception as exc:
        record("weave round-trip", FAIL, f"{type(exc).__name__}: {str(exc)[:200]}")


# ------------------------------------------------------------- 6. sandboxes
print("\n6. Sandboxes")
try:
    from wandb.sandbox import Sandbox  # noqa: F401

    record("wandb[sandbox] installed", PASS)
    record("sandbox usable", SKIP,
           "run tools/sandbox_probe.py - not enabled for this org as of last check")
except ImportError as exc:
    record("wandb[sandbox] installed", SKIP, str(exc)[:100])


# ----------------------------------------------------------------- summary
print("\n" + "=" * 64)
counts = {s: sum(1 for _, st, _ in results if st == s) for s in (PASS, FAIL, SKIP)}
print(f"passed {counts[PASS]}   failed {counts[FAIL]}   not_evaluated {counts[SKIP]}")
for label, state in (("Failing", FAIL), ("Not evaluated", SKIP)):
    rows = [(n, d) for n, st, d in results if st == state]
    if rows:
        print(f"\n{label}:")
        for n, d in rows:
            print(f"  - {n}: {d}")
print("=" * 64)
raise SystemExit(1 if counts[FAIL] else 0)
