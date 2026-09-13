# Ally

**Give Ally a live URL and the GitHub repository behind it. It audits the page
with a keyboard, fixes the code, proves the fix worked, and opens the pull
request.**

---

## The problem

**96 of every 100 websites fail accessibility standards.**

Not because the teams building them don't care. Because the tools stop one step
short of the thing that matters.

Run axe or Lighthouse on your site and you get a list of violations, a severity
badge, and a link to go read. Everything after that is yours: work out which
component drew the element, write the fix, check you didn't break the page,
open the PR. The tool told you *that* something was wrong. It couldn't tell you
*where in your code*, and it never closed the loop.

And the violations those tools can see are only half the picture. Contrast
ratios and missing labels are visible in the markup, so a scanner catches them.
The ones that actually strand a keyboard user are not:

- tab order that jumps backwards up the page
- a focus ring that exists in CSS but is invisible against the background
- a modal that traps focus and won't let go
- a `<div>` wired up with `onClick` that the keyboard can never reach
- focus landing on an element hidden behind a sticky header

None of those can be found by reading HTML. You have to **open the page and
press Tab**.

Large companies carry legal obligations here — the ADA, the European
Accessibility Act, Section 508. Small teams and solo builders ship fast and
plan to fix it later, and later never arrives, because "later" means auditing
every page by hand.

Ally is what happens when the audit and the fix are the same program.

---

## What Ally does

```
  live URL  +  GitHub repo
        │
        ├─ reads your router to find every real page
        ├─ opens each page in its own cloud sandbox, in a real Chrome
        ├─ presses Tab, records every stop, screenshots each one
        ├─ judges five WCAG criteria against that recording
        ├─ finds the component that drew the failing element
        ├─ rewrites it, rebuilds the project, audits the same page again
        └─ opens the pull request — only if the re-audit confirmed the fix
```

Ally does not scan your HTML. It drives your site.

**WCAG criteria covered today:** 2.1.1 Keyboard · 2.1.2 No Keyboard Trap ·
2.4.3 Focus Order · 2.4.7 Focus Visible · 2.4.11 Focus Not Obscured.

---

## The loop

The loop is the product. Finding a bug is the easy half.

1. **Patch** — rewrite the component that produced the failing element
2. **Rebuild** — run the project's real build, so the browser sees the change
3. **Re-audit** — drive the same page again with the same check
4. **Score** — count what closed, and count what the patch broke

**A finding is closed only when the check that was failing stops firing.** Not
when the patch applied. Not when the code compiled. If the bug is still there,
the loop goes round again with the build error or the still-failing check fed
back into the next attempt.

A patch that closes one finding and creates another has improved nothing, and
Ally will not open a pull request for it. **Every PR Ally opens is a change it
tested on the running page.**

---

## Weights & Biases: Weave

Weave is not where Ally's logs go. It is where Ally's **claims** are checked.

### Traces — one run is one tree

Eighteen operations are `@weave.op`. `ally_run` sits at the root and everything
nests beneath it:

```
ally_run                          ← the whole job, summary as its output
├─ clone_repo
├─ routes_from_repo               ← which pages exist
├─ source_for_route               ← which file draws each one
├─ check_keyboard  ×4 pages
├─ check_no_trap   ×4
├─ check_focus_order ×4           ← LLM judge
├─ check_focus_visible ×4
├─ check_not_obscured ×4
├─ prepare_build
├─ FixLoop.fix_group
│  ├─ request_edits               ← the model call
│  └─ FixLoop.reaudit             ← patch, rebuild, drive again
└─ open_pull_request
```

The root call returns the run's summary — pages, checks, findings, closed,
created, PR URL — so a run is one readable row, not two hundred orphans. Each
of the four page audits runs in its own thread and sandbox, and every call it
makes carries the job id and the page it was looking at.

### Datasets — the benchmark is versioned data

| Dataset | What it holds |
|---|---|
| `planted-defects` | 15 known accessibility bugs, 3 per criterion, with the selector and region of each |
| `frozen-recordings` | 24 full browser recordings — every Tab stop, screenshot and accessibility-tree node |

Recording a page costs a sandbox, a browser and four states. Frozen as a Weave
Dataset, the checks replay against them **in under a second**, so the full
15-defect benchmark runs on every change to a detection rule.

### Prompts — the published object is the one that runs

The patcher's prompt is a `weave.StringPrompt`, and `patcher.py` imports the
same object it publishes. The prompt versioned in Weave **is** the prompt that
executed. They cannot drift.

### Scorers — three questions per run

| Scorer | Asks |
|---|---|
| `FoundPlantedDefect` | Did it find the bug I planted, by element identity rather than string match? |
| `PatchCreatedNewFindings` | Did the fix break anything else on the page? |
| `EvidenceReferenceResolved` | Does every claim point at a screenshot that actually exists? |

### Evaluations — a comparison, not an assertion

`stage4-patch-effort` runs through `EvaluationLogger` with two models:
`ally-patcher@lessons-true` and `ally-patcher@lessons-false`. Same dataset,
same pages, same order — the only difference is whether the agent retrieves its
own prior fixes before writing a patch. When Ally recalls a past fix, **the IDs
of those specific lessons are attached to the trace**, so "the agent learns" is
something you can open and audit rather than a line on a chart.

### What Weave actually caught

Weave earned its place by finding bugs that would otherwise have shipped:

- **A page that rendered nothing was scoring as fixed.** The trace showed a
  re-audit passing every check against a blank page. The build had been
  OOM-killed and the failure was invisible.
- **Traces stopped saving entirely, silently.** A `.ref` property on our
  recording type collided with Weave's own `get_ref`. Nothing errored. There is
  now a test that asks the Weave server whether the call landed.
- **A patch was reported as closing two findings while creating two others.**
  Net zero. The scorer caught it; the PR gate now refuses it.

---

## ARIA

**ARIA generated the application the entire benchmark is built on.**

Grading an accessibility agent needs a site where you already know every right
answer. Real sites can't do that — you never know what you missed. A toy page
can't either: three buttons in a row exercise nothing.

So ARIA built a **realistic five-page application** — a delivery product with a
signup form, a preferences panel with switches, a modal dialog, a tab set and a
menu. Real components, real nesting, the ARIA Authoring Practices patterns a
production React app actually uses. That is the *clean* app, and it must pass
all five criteria cleanly, or the benchmark measures nothing.

From there, three programs that **share no code**:

```
breaker/       plants 15 defects into the clean pages, writes manifest.json
agent/         gets a URL. Never sees the manifest.
scorer/        reads the manifest and the findings, compares them
```

The manifest lives **outside** `public/`, so it is never served. An agent that
could fetch it would score perfectly and teach us nothing.

**15 defects, 3 per criterion** — three instances each, because a patcher that
fixes the first occurrence and stops looks identical to one that fixed them all
until you count.

ARIA gave the benchmark something it could not have had otherwise: a ground
truth that is realistic enough to be hard, and known well enough to be scored.

---

## The stack

| | |
|---|---|
| **Weave** | tracing, datasets, prompts, scorers, evaluations |
| **W&B Inference** | Llama 3.3 70B — the patcher and the focus-order judge |
| **ARIA** | generated the clean five-page benchmark application |
| **Daytona** | one sandbox per page, each with a real Chrome and a live noVNC desktop |
| **Chrome DevTools Protocol** | `Input.dispatchKeyEvent`, `Accessibility.getPartialAXTree`, `DOMDebugger.getEventListeners`, `Page.captureScreenshot` |
| **axe-core** | runs alongside every audit, for comparison |

---

## Evidence, not assertion

Three layers, and each check is aimed at the right one:

- **What the page claims** — DOM attributes and the accessibility tree
- **What the page does** — drive it, read `document.activeElement`
- **What a person sees** — two screenshots per stop, cropped and diffed

Every check returns one of three answers: **passed**, **failed**, or
**not evaluated with a reason**. A check that reached only a fraction of a
page's controls is not allowed to report a pass — "nothing wrong here" from a
check that examined 2% of the page is a different statement, and it is recorded
as a different statement.

---

## Running it

```bash
cd frontend && npm install && npm run build
python ui/server.py
```

Open <http://127.0.0.1:8000>, paste a live page and its GitHub repository. That
is the whole input.

See [DEMO.md](DEMO.md) for runs that have gone end to end, and
[RUN.md](RUN.md) for development notes.
