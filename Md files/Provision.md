# Provisioning

Two deployments. Local runs this weekend. Web comes after. Build local, and write the four seams listed at the end so the swap later is small.

Read `SCOPE.md` first. This file covers infrastructure only.

---

## Local, for the weekend

| Need | What we use | State |
|---|---|---|
| Containers | Daytona, Tier 2 | Already have it |
| Model, Focus Order and patches | W&B Inference, `meta-llama/Llama-3.3-70B-Instruct` | Already have it, $100 credits |
| Model, evidence gate and borderline Focus Visible | TypeSafe Jev, `jev-1.13.0` | Already have it |
| Traces and evaluations | Weave | Already have it, 1GB ingestion cap |
| Git push and pull request | GitHub personal access token, `repo` scope | Needs generating |
| Database | SQLite on disk | Nothing to provision |
| Screenshots | Local disk, `runs/{run_id}/{state}/stop-{n}.png` | Nothing to provision |
| Dashboard | Local HTTP server, server-sent events from the worker | Nothing to provision |
| Job queue | A table in SQLite | Nothing to provision |
| Clean app under test | Vercel, already deployed from the `clean-app` branch | Already have it |

There is exactly one thing to provision: the GitHub token.

### What we deliberately do not build for the weekend

No GitHub App, no OAuth, no login screen, no sessions. Those exist so strangers can grant the product access to their repositories, and nobody but the operator uses this on Sunday. The repository is in config.

No hosted database, no object storage, no queue service. One worker reading one SQLite file is enough, and each of those services costs setup time and buys nothing on stage.

**GitHub itself is not dropped.** Git, branches, commits and the pull request all stay. The worker pushes a branch with a personal access token and opens the PR through the API.

### What runs where

On the laptop: the worker process, a local web server for the dashboard, and the screenshots on disk.

Remote but not hosted by us: Daytona containers, W&B Inference, TypeSafe, Weave, and the Vercel-hosted clean app. We call all of those, we run none of them.

---

## Web, for anyone to use

Do not build this yet. It is recorded so the seams below make sense.

| Need | What we use | Why this one |
|---|---|---|
| Auth and repository access | GitHub App | Installed per repository, carries fine-grained permissions, opens pull requests as itself. An OAuth App acts as the user and asks for broad scopes. |
| Database | Neon | Free Postgres with no inactivity pause. Supabase pauses free projects after 7 days. Render's free Postgres expires 30 days after creation, so it is a trial rather than a free tier. |
| Worker | Render background worker | Of Render, Railway and Fly, only Render still has a real free tier. Railway removed its free tier in 2023 and Fly removed its free allowances in 2024. Render free services spin down after 15 minutes idle and take 30 to 60 seconds to wake. |
| Web app | Vercel | Already in use |
| Screenshots | Cloudflare R2 | Verify the current free limits before relying on a number |
| Queue | A Postgres table | A separate queue service earns nothing at this size |

---

## The four seams

Write these now. Each one is the difference between a one-file change later and a rewrite.

**1. Database access goes through one query layer.** Do not scatter SQLite calls through the codebase. Moving to Postgres should be a connection string and a driver.

**2. Screenshot saving goes behind one function.**

```
save_screenshot(run_id, state, index, image_bytes) -> url
```

Local writes to disk and returns a file path. The web version writes to R2 and returns a URL. Nothing else in the codebase knows which.

**3. Token acquisition goes behind one function.**

```
get_github_token(repo) -> token
```

Local reads an environment variable. The web version fetches an installation token. Every git operation after that is identical.

**4. The worker never assumes where it runs.** No absolute paths, no assumptions about the filesystem persisting between runs, and no database connection pool created inside a request handler. A pool inside a serverless function multiplies per instance and exhausts the database's connection cap.

---

## Today's actions

1. Generate the GitHub personal access token with `repo` scope and put it in the environment.
2. Write the four seams as thin functions before writing anything that calls them.

Nothing in the web column happens this week.