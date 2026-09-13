# Running Ally

Two commands, once. After that, one.

```
cd frontend && npm install && npm run build
```

```
python ui/server.py
```

Then open <http://127.0.0.1:8000>.

Paste a live page and the GitHub repository behind it. That is the whole input.
Ally works out which file backs the page from the clone.

## Working on the frontend

`npm run dev` on port 5173 proxies `/api` and `/shot` to the Python server, so
run both and edit with hot reload. `npm run typecheck` before committing.

## Two things this machine does that others will not

The `&` in `W&B hack` breaks npm's generated shims: they resolve the working
directory and truncate at the ampersand, then look in `C:\Users\…\Downloads\`.
The scripts in `package.json` call `node ./node_modules/<pkg>/…` directly to
avoid the shims entirely. Keep them that way.

A stale Python process holding port 8000 serves the old build and looks exactly
like a routing bug. If a route 404s that plainly exists, check the port first.

## Environment

`.env` holds `WANDB_API_KEY`, `WANDB_ENTITY`, `WANDB_PROJECT` and
`DAYTONA_API_KEY`. `ALLY_SANDBOX` pins a warm sandbox so a run does not pay to
start one. `gh` must be authenticated for the pull-request step; without write
access to the repository the run still produces the complete diff and says why
it stopped short.
