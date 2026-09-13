"""Open the pull request.

The body states only what executed and what it found. Anyone reading it can run
the same checks themselves. It never says a site is compliant, because no body
certifies WCAG conformance and the FTC fined accessiBe $1 million for saying
otherwise.

Three things it always reports, because leaving any of them out turns a real
result into a flattering one:

  * findings closed AND findings created. A patch that closes nine and creates
    four has closed five.
  * every criterion that returned not_evaluated, with its reason. A run that
    judged nothing must say so rather than showing five passes.
  * the two patcher counters separately: could-not-locate means zero patches
    were applied, still-failing means five were and none worked.

The credential comes from `ally.tokens`, and every command's output goes
through `redact` before it is printed: git and gh both echo the remote URL,
which carries the token in its userinfo.
"""

from __future__ import annotations

import json
import time
import urllib.request

from ally import tokens

try:
    import weave
except ImportError:
    weave = None


def _op(fn):
    return weave.op()(fn) if weave else fn


def _rows(results, status: str):
    return [r for r in results if r.status == status]


def build_body(audit, fix_summary: dict, outcomes, weave_url: str = "") -> str:
    """The PR description. Facts that executed, nothing else."""
    res = audit.results
    failed, passed = _rows(res, "failed"), _rows(res, "passed")
    ne = _rows(res, "not_evaluated")

    lines = [
        "## What ran",
        "",
        f"- Target: {audit.url}",
        f"- States driven: {', '.join(audit.states)}",
        f"- Run id: `{audit.run_id}`",
        "",
        "## What it found",
        "",
        f"{len(failed)} failed, {len(passed)} passed, **{len(ne)} not evaluated**, "
        f"of {len(res)} checks.",
        "",
    ]
    if not failed and not passed:
        lines += ["**Nothing was judged.** Every check returned not_evaluated. "
                  "The findings below are absent because nothing could be "
                  "measured, not because the page is clean.", ""]

    if failed:
        lines += ["| Criterion | State | Finding | Evidence |", "|---|---|---|---|"]
        for r in failed:
            lines.append(f"| {r.criterion} | {r.state} | {r.summary} | "
                         f"`{', '.join(r.evidence_refs[:3])}` |")
        lines.append("")

    if ne:
        lines += ["### Not evaluated", "",
                  "Recorded rather than passed. A criterion we could not judge is "
                  "not a criterion that passed.", "",
                  "| Criterion | State | Reason |", "|---|---|---|"]
        for r in ne:
            lines.append(f"| {r.criterion} | {r.state} | {r.reason} |")
        lines.append("")

    lines += [
        "## What changed",
        "",
        f"- Findings closed: **{fix_summary.get('closed', 0)}**",
        f"- Findings created by these patches: **{fix_summary.get('created', 0)}**",
        f"- Net: **{fix_summary.get('net', 0)}**",
        "",
        "A finding is closed only when the same check, on the same state, on the "
        "rebuilt page, no longer reports it. Never because a patch applied.",
        "",
    ]

    locate = fix_summary.get("could_not_locate", 0)
    still = fix_summary.get("still_failing", 0)
    if locate or still:
        lines += ["### Groups that did not close", "",
                  "These are different facts and are counted separately.", ""]
        if locate:
            lines.append(f"- **Could not locate the code** ({locate}): the text to edit "
                         "could not be matched. Zero patches were applied.")
        if still:
            lines.append(f"- **Still failing after 5 patches** ({still}): patches applied "
                         "cleanly and the re-audit still reports the problem. The fix "
                         "was wrong, not the location.")
        lines.append("")

    if audit.axe is not None:
        if audit.axe.ran:
            overlap = audit.axe.overlapping()
            lines += ["## axe-core, run alongside", "",
                      f"axe-core {audit.axe.version}: {len(audit.axe.violations)} rules "
                      f"fired. Criteria it reported: "
                      f"{', '.join(sorted(audit.axe.criteria)) or 'none tagged'}.", ""]
            if overlap:
                lines.append(f"Rules tagged to criteria this agent also claims: "
                             f"{', '.join(overlap)}.")
            else:
                lines.append("No rule axe fired carries a WCAG tag matching any "
                             "criterion this agent claims.")
            lines.append("")
        else:
            lines += ["## axe-core, run alongside", "",
                      f"**axe did not run**: {audit.axe.reason}. An empty violation "
                      "list and a scan that never happened are not the same fact, so "
                      "no axe result is reported for this page.", ""]

    if weave_url:
        lines += [f"## Trace", "", f"Every check, patch and re-audit: {weave_url}", ""]

    lines += ["---", "",
              "This does not make the site WCAG compliant, and nothing here is a "
              "conformance claim. No organisation certifies WCAG conformance. These "
              "are the checks that ran and what they reported; run them yourself."]
    return "\n".join(lines)


@_op
def open_pull_request(session, repo: str, run_id: str, body: str,
                      checkout: str, base: str = "main",
                      title: str | None = None) -> dict:
    """Push a branch from the sandbox checkout and open the PR.

    Returns {"url": ...} or {"error": ...}. Never raises on a git failure: a
    run that audited and patched correctly should still report its findings if
    the push is refused.
    """
    branch = f"ally/fix-{run_id}"
    title = title or f"Accessibility fixes from Ally run {run_id}"
    remote = tokens.authenticated_remote(repo)

    script = "; ".join([
        f"cd {checkout}",
        "git config user.email ally@localhost",
        "git config user.name 'Ally'",
        f"git checkout -q -b {branch}",
        "git add -A",
        f"git -c commit.gpgsign=false commit -q -m {json.dumps(title)} || echo NOCHANGES",
        f"git push -q {remote} {branch} && echo PUSHED || echo PUSHFAILED",
    ])
    res = session.sb.process.exec(script, timeout=420)
    out = tokens.redact(res.result or "", repo)

    if "NOCHANGES" in out:
        return {"error": "nothing to commit: no patch changed a file", "log": out[-400:]}
    if "PUSHED" not in out:
        return {"error": "the branch could not be pushed", "log": out[-400:]}

    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls",
        data=json.dumps({"title": title, "head": branch, "base": base,
                         "body": body}).encode(),
        headers={"Authorization": f"Bearer {tokens.get_github_token(repo)}",
                 "Accept": "application/vnd.github+json",
                 "User-Agent": "ally/0.1",
                 "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read().decode())
        return {"url": data.get("html_url"), "number": data.get("number"),
                "branch": branch}
    except urllib.error.HTTPError as exc:
        return {"error": f"GitHub answered {exc.code}",
                "detail": tokens.redact(exc.read().decode()[:300], repo),
                "branch": branch}
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {tokens.redact(str(exc)[:200], repo)}",
                "branch": branch}
