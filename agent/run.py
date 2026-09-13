"""One complete pass: audit, fix, re-audit, pull request.

    python -m agent.run <url> --source broken-app/public/2-1-1.html

The checkout lives inside the sandbox, cloned from GitHub, which Daytona's
Tier 2 allowlist permits. The patched page is served on localhost:3000 and
re-audited there, which needs no egress at all.

Every number printed carries its not_evaluated count. A run that judged nothing
must say so at the top rather than reporting five passes.
"""

from __future__ import annotations

import os
import sys
import json
import time
import argparse
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

import wb_env  # noqa: E402

from agent.audit import Audit, DEFAULT_STATES  # noqa: E402
from agent.fixloop import FixLoop  # noqa: E402
from agent.judge import _client  # noqa: E402

REPO = "https://github.com/Carldtitan/Ally.git"
CHECKOUT = "/tmp/ally-work"


def counts(results) -> dict:
    out = {"passed": 0, "failed": 0, "not_evaluated": 0}
    for r in results:
        out[r.status] += 1
    return out


def headline(label: str, c: dict) -> str:
    """Every number carries its not_evaluated. A run that judged nothing says so."""
    total = sum(c.values())
    judged = c["passed"] + c["failed"]
    line = (f"{label}: {c['failed']} failed, {c['passed']} passed, "
            f"{c['not_evaluated']} not evaluated, of {total} checks")
    if judged == 0 and total:
        line += "\n  NOTHING WAS JUDGED. Every check returned not_evaluated."
    elif c["not_evaluated"]:
        line += f"\n  {c['not_evaluated']} of {total} checks reached no verdict."
    return line


def clone(session, branch: str = "main") -> None:
    session.start_browser()
    r = session.sb.process.exec(
        f"rm -rf {CHECKOUT} && git clone --depth 1 --branch {branch} -q {REPO} {CHECKOUT} "
        f"&& echo CLONED $(cd {CHECKOUT} && git rev-parse --short HEAD)", timeout=300)
    if "CLONED" not in (r.result or ""):
        raise SystemExit(f"clone failed: {(r.result or '')[:300]}")
    print(f"  checkout: {(r.result or '').strip().splitlines()[-1]}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--source", required=True,
                    help="path inside the repo the patcher may edit")
    ap.add_argument("--sandbox", default=os.environ.get("ALLY_SANDBOX"))
    ap.add_argument("--states", default=",".join(DEFAULT_STATES))
    ap.add_argument("--no-fix", action="store_true")
    ap.add_argument("--no-weave", action="store_true")
    args = ap.parse_args()

    wb_env.load_dotenv()
    wb_env.use_certifi_bundle()
    states = [s.strip() for s in args.states.split(",") if s.strip()]

    audit = Audit(args.url, sandbox_id=args.sandbox, states=states,
                  use_weave=not args.no_weave)
    audit.run()
    audit.print_findings()

    before = counts(audit.results)
    print("\n" + headline("BASELINE", before))
    if args.no_fix:
        print(f"\nsaved {audit.save()}")
        return

    print("\ncloning the repository into the sandbox ...")
    clone(audit.session)

    serve_root = f"{CHECKOUT}/{pathlib.PurePosixPath(args.source).parent}"
    loop = FixLoop(audit, workdir=pathlib.Path(CHECKOUT), serve_root=serve_root,
                   client=_client())
    # The workdir is remote, so edits are applied through the sandbox rather
    # than on this machine. fixloop reads and writes via a small shim.
    loop.workdir = RemoteTree(audit.session, CHECKOUT)
    outcomes = loop.run(args.source)

    s = loop.summary()
    print("\n" + "=" * 74)
    print(f"closed {s['closed']}  created {s['created']}  net {s['net']}")
    print(f"could not locate {s['could_not_locate']}   "
          f"still failing after 5 patches {s['still_failing']}")
    if s["patch_attempts_per_closed"] is not None:
        print(f"patch attempts per closed finding: {s['patch_attempts_per_closed']}")
    print("=" * 74)

    out = audit.save()
    extra = json.loads(out.read_text(encoding="utf-8"))
    extra["fix"] = {"summary": s,
                    "outcomes": [o.__dict__ for o in outcomes]}
    out.write_text(json.dumps(extra, indent=2), encoding="utf-8")
    print(f"saved {out}")


class RemoteTree:
    """pathlib-ish shim so the fix loop can edit files inside the sandbox."""

    def __init__(self, session, root: str) -> None:
        self.session, self.root = session, root.rstrip("/")

    def __truediv__(self, rel: str) -> "RemoteFile":
        return RemoteFile(self.session, f"{self.root}/{rel}", rel)


class RemoteFile:
    def __init__(self, session, path: str, rel: str) -> None:
        self.session, self.path, self.rel = session, path, rel

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    def exists(self) -> bool:
        r = self.session.sb.process.exec(f"test -f {self.path} && echo Y || echo N",
                                         timeout=60)
        return "Y" in (r.result or "")

    def read_text(self, encoding: str = "utf-8") -> str:
        import base64
        r = self.session.sb.process.exec(f"base64 -w0 {self.path}", timeout=120)
        return base64.b64decode((r.result or "").strip()).decode(encoding)

    def write_text(self, text: str, encoding: str = "utf-8") -> None:
        self.session.sb.fs.upload_file(text.encode(encoding), self.path)

    def relative_to(self, _root) -> str:
        return self.rel


if __name__ == "__main__":
    main()
