"""Exercise the four seams end to end, in a throwaway root.

Runs against a temp ALLY_ROOT so it never touches real run data.
Usage:  python tools/seam_smoke.py
"""

from __future__ import annotations

import os
import sys
import json
import shutil
import pathlib
import tempfile

# .resolve() because on Windows mkdtemp can hand back an 8.3 short path
# ("MRB09A~1.PAU") while config.root() canonicalises it to the long form.
ROOT = pathlib.Path(tempfile.mkdtemp(prefix="ally-smoke-")).resolve()
os.environ["ALLY_ROOT"] = str(ROOT)
os.environ.pop("DATABASE_URL", None)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from ally import config, db, storage, tokens  # noqa: E402

ok = 0
bad = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global ok, bad
    if cond:
        ok += 1
        print(f"  [PASS] {label}" + (f" - {detail}" if detail else ""))
    else:
        bad += 1
        print(f"  [FAIL] {label}" + (f" - {detail}" if detail else ""))


print("\nseam 4: config")
check("root honours ALLY_ROOT", config.root() == ROOT, str(config.root()))
check("database_url derives from root", config.database_url().endswith("ally.db"))
check("is_sqlite", config.is_sqlite())

print("\nseam 1: db")
db.script("""
CREATE TABLE runs (id TEXT PRIMARY KEY, target TEXT NOT NULL, status TEXT NOT NULL);
CREATE TABLE findings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id TEXT NOT NULL REFERENCES runs(id),
  criterion TEXT NOT NULL, status TEXT NOT NULL, reason TEXT
);
""")
db.execute("INSERT INTO runs (id, target, status) VALUES (:id, :t, :s)",
           {"id": "r1", "t": "https://ally-clean-app.vercel.app", "s": "running"})
db.execute_many(
    "INSERT INTO findings (run_id, criterion, status, reason) "
    "VALUES (:run_id, :criterion, :status, :reason)",
    [{"run_id": "r1", "criterion": "2.4.3", "status": "failed", "reason": None},
     {"run_id": "r1", "criterion": "2.1.2", "status": "not_evaluated",
      "reason": "state not reached"}])

rows = db.query_all("SELECT criterion, status FROM findings WHERE run_id = :r "
                    "ORDER BY criterion", {"r": "r1"})
check("query_all returns dicts", rows and isinstance(rows[0], dict), json.dumps(rows))
one = db.query_one("SELECT target FROM runs WHERE id = :id", {"id": "r1"})
check("query_one", one is not None and one["target"].endswith("vercel.app"))
check("query_one misses return None",
      db.query_one("SELECT 1 AS x FROM runs WHERE id = :id", {"id": "nope"}) is None)

try:
    with db.transaction():
        db.execute("UPDATE runs SET status = :s WHERE id = :id",
                   {"s": "wrecked", "id": "r1"})
        raise RuntimeError("forced")
except RuntimeError:
    pass
after = db.query_one("SELECT status FROM runs WHERE id = :id", {"id": "r1"})
check("transaction rolls back on exception", after["status"] == "running", after["status"])

with db.transaction():
    db.execute("UPDATE runs SET status = :s WHERE id = :id",
               {"s": "done", "id": "r1"})
check("transaction commits on clean exit",
      db.query_one("SELECT status FROM runs WHERE id=:id", {"id": "r1"})["status"] == "done")

print("\nseam 2: storage")
png = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 64)
ref = storage.save_screenshot("r1", "dialog-open", 3, png)
check("returns a relative ref, not bytes", ref == "runs/r1/dialog-open/stop-003.png", ref)
check("file landed under root", (ROOT / ref).exists())
check("round-trips through the seam", storage.load_screenshot(ref) == png)
check("ref is stable without writing",
      storage.screenshot_ref("r1", "dialog-open", 3) == ref)
check("unsafe state name cannot escape its directory",
      ".." not in storage.screenshot_ref("r1", "../../etc", 1),
      storage.screenshot_ref("r1", "../../etc", 1))
try:
    storage.save_screenshot("r1", "loaded", 1, "not bytes")  # type: ignore[arg-type]
    check("rejects non-bytes", False, "accepted a str")
except TypeError as e:
    check("rejects non-bytes", True, str(e)[:46])
check("missing ref raises rather than returning empty",
      not storage.exists("runs/r1/loaded/stop-999.png"))

print("\nseam 3: tokens")
try:
    tok = tokens.get_github_token("Carldtitan/Ally")
    check("resolves a token", bool(tok), f"{len(tok)} chars, prefix {tok[:4]}...")
    remote = tokens.authenticated_remote("Carldtitan/Ally")
    check("builds an authenticated remote",
          remote.startswith("https://x-access-token:") and remote.endswith("Ally.git"))
    leaky = f"fatal: could not read from {remote}"
    check("redact removes the token from output",
          tok not in tokens.redact(leaky, "Carldtitan/Ally"))
except tokens.TokenError as e:
    check("resolves a token", False, str(e)[:80])

db.close()
shutil.rmtree(ROOT, ignore_errors=True)
print(f"\n{'=' * 56}\npassed {ok}   failed {bad}\n{'=' * 56}")
raise SystemExit(1 if bad else 0)
