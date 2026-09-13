# Filming Ally

Everything below has been run end to end. Times are wall-clock from a warm start.

## Start it

```bash
python ui/server.py          # http://127.0.0.1:8000
```

The page is served from `frontend/dist`. If you change the frontend:

```bash
cd frontend
node ./node_modules/typescript/bin/tsc -b
node ./node_modules/vite/bin/vite.js build
```

(The scripts are called directly because the `&` in the folder name truncates
npm's shims.)

## What to show, in order

**1. Home.** Paste a live page and its repository. Two fields, one button.

**2. The browsers.** Within about a minute the Runs tab shows up to four
desktops side by side, each a real Chromium in its own sandbox being driven by
the keyboard. This is the part people want to watch: focus moving through the
page, one Tab at a time.

**3. Pages audited.** The table names every page and the file that draws it —
`/verify` → `src/components/VerifyPage.jsx`. Ally reads the router, so it knows
which pages exist without crawling for links, and it skips redirects.

**4. Findings.** Each criterion shows passed / failed / could-not-decide, with
axe-core beside it for the same page. The interesting column is the one where
Ally found something axe has no rule for.

**5. The Loop.** Patch, rebuild, re-audit, count. A finding is closed only when
the same check on the rebuilt page stops reporting it.

**6. The pull request.** Opened only when the re-audit confirmed a net
improvement.

## Runs that work

| Site | Repository | What it exercises |
|---|---|---|
| `bit-estate.vercel.app` | `Carldtitan/BitEstate-Capstone-` (branch `ally/buildable-clone`) | react-router, 4 pages, Parcel build, patch → rebuild → re-audit → PR |
| `touchgrass-gray.vercel.app` | `Carldtitan/touchgrass` | one page with steps inside it, Vite; finds nothing and says so |
| `clearway-kappa.vercel.app` | `Carldtitan/Clearway` | a page whose screens are reached by pressing a control — four language flows |

BitEstate needs `branch: "ally/buildable-clone"` until
[PR #1](https://github.com/Carldtitan/BitEstate-Capstone-/pull/1) is merged;
that branch adds the `package.json` and two modules the repository was missing,
without which no clean clone of it can be built.

To start a run against a branch:

```bash
curl -s -X POST http://127.0.0.1:8000/api/audit \
  -H "Content-Type: application/json" \
  -d '{"url":"https://bit-estate.vercel.app",
       "repo":"https://github.com/Carldtitan/BitEstate-Capstone-",
       "branch":"ally/buildable-clone","fix":true,"pr":true}'
```

## Weave

Every run is one trace: `ally_run` at the root, with the clone, the route
discovery, the build, each patch attempt, each re-audit and the pull request
beneath it. Lanes run in their own threads and their calls carry the job id and
the page they were looking at, so a run's work collects in one view.

https://wandb.ai/carldtytan-minerva-university/ally/weave

## If a run takes longer than you want on camera

The fix step tries up to five patches, and each one rebuilds the project and
re-audits the page. Auditing alone is about four minutes; a full run with the
loop is eight to fifteen. Film the audit live and cut to a finished run for the
loop and the pull request.
