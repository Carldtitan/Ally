# Scope

This supersedes anything earlier in the repository about what we are building. Read it before changing the checker, the benchmark, or the claims in the README.

---

## The two halves, which are not the same thing

There are two sources of findings in this product and they do different jobs. Do not mix them up.

**axe-core.** A third-party library we run as-is. It reads one loaded page and reports static problems: missing labels, missing alt text, low contrast, duplicate ids. We wrote none of it and we improve none of it. We run it, take its output, and put it in the report.

**Our agent.** What we built. It presses Tab through a page, records what happens, and decides whether a keyboard user can get around. axe covers none of what it does.

The final report is both sets of findings merged. The pull request fixes both.

---

## The five criteria our agent owns

All five are Level A or AA, and all five read the same recording. One Tab run through a page produces the evidence for every one of them.

We own a criterion only when axe does not. Measured against axe-core 4.13.0, enumerating all 105 rules by WCAG tag: four of these five have no axe rule at all. The exception is 2.1.1, covered below.

| Criterion | Name | Level | What the check does | Model |
|---|---|---|---|---|
| 2.1.1 | Keyboard | A | Builds a list of interactive elements from three sources, then compares it against the list of elements Tab reached. Anything missing is unreachable. | no |
| 2.1.2 | No Keyboard Trap | A | Focus never leaves the page, or the same element keeps repeating. | no |
| 2.4.3 | Focus Order | A | Compares tab order against reading order derived from element positions, then asks the model whether the difference matters. | yes |
| 2.4.7 | Focus Visible | AA | Compares the screenshot before and after focus lands, cropped to the focused element. No change means focus is invisible. | borderline cases only |
| 2.4.11 | Focus Not Obscured (Minimum) | AA | Something is drawn on top of the focused element. | no |

Three are arithmetic on the recording. Focus Order needs judgement, and Focus Visible needs it only when the pixel difference is small enough that a person might not notice.

**2.4.13 Focus Appearance is Level AAA and is not in our five.** It measures the focus indicator against fixed numbers: at least 2 CSS pixels thick, and a contrast ratio of at least 3 to 1 between the focused and unfocused states. Add it only if there is spare time, and label it AAA wherever it appears.

Watch out for stale numbering. During WCAG 2.2 drafting, Focus Appearance was 2.4.11 at Level AA. In the published standard, 2.4.11 is Focus Not Obscured (Minimum) at AA and Focus Appearance is 2.4.13 at AAA. Several blog posts still use the draft numbering.

**State 2.1.1 precisely, because axe does have rules tagged to it.** axe ships three: `frame-focusable-content`, `scrollable-region-focusable` and `server-side-image-map`. None of them fires on a `<div onclick>` acting as a button, which is the commonest real failure. So the claim is "axe has three rules tagged 2.1.1, and none detects an unfocusable div acting as a button". Never write "axe has no 2.1.1 coverage", because that is false and a judge can check it.

**Build the 2.1.1 element list from three sources, not just the accessibility tree.** A `<div onclick>` acting as a button has no interactive role, so it is absent from the tree. It is also absent from the focus stops. Both lists agree and nothing fires, which means our planted defect escapes. Merge these three:

1. The accessibility tree.
2. A DOM query for elements that look clickable but are not focusable: `cursor: pointer`, or an `onclick` attribute, with no `tabindex` and no interactive role.
3. Chrome DevTools Protocol `DOMDebugger.getEventListeners`, which returns elements carrying click handlers.

**On our clean app both source two and source three catch the planted defect**, because that page binds handlers with inline `onclick` attributes and direct `addEventListener` calls. Source three is the one that matters on real sites, where handlers are rarely written that way.

Source three was verified against a live page. It catches inline `onclick`, direct `addEventListener`, and a bare span carrying a handler. It correctly returns nothing for an element styled `cursor: pointer` with no handler, so it does not inherit source two's false positive. A whole-page scan of twelve elements took no measurable time.

**Exclude delegating containers, or every React page produces a false positive.** A React root container carries 131 listeners including `click`, and it is not focusable. A naive rule saying "has a click listener and is not focusable, so it is unreachable" flags it on every page. Skip elements that contain other candidates, or that have no text content of their own. Decide this before measuring precision, since our target on the clean app is zero.

**Source three sees React, but by proxy rather than directly.** React does not bind a JSX `onClick` to your element. It delegates to the root container, and the listener reported on a React element resolves into `react-dom.production.min.js` at the same script location as one of the root's. So it is React's dispatcher, not the application's handler.

It is still usable, because React attaches that dispatcher only to elements carrying an `onClick` prop. Verified on React 18 UMD production, six cases out of six: a `div` with `onClick` reports one listener and is not focusable, so it flags; a `div` and a `p` without `onClick` report none; a `button` and an `a` with `onClick` report one each and are focusable, so they pass.

**Treat that as a dependency, not a fact.** It rests on a `react-dom` implementation detail rather than any public contract, so a minor release can change it. It is untested on React 17 and 19, and on Vue, Svelte and Angular. Re-run `tools/react_listener_truth.py` before relying on it against a different framework.

**What still escapes source three is pure delegation.** A handler bound on `document` or on an ancestor, with no per-element marker, is attributed to no element at all. Hand-rolled delegation and jQuery's `.on(selector, ...)` both work that way. Comparing the screenshot against the accessibility tree with a vision model would catch those, which is what AccessiFix did. Leave that out for now and add it only if 2.1.1 recall turns out to be our weak number.

**2.5.8 Target Size is not ours.** axe-core 4.13.0 ships a `target-size` rule, tagged to WCAG 2.5.8, and it fired on our planted defect across three nodes. Building our own check means reimplementing a shipped rule and then competing with it, which the rule above forbids. 2.5.8 still appears in the report, from axe. This also retires the Inline exception work, since axe's rule handles it.

**On the axe count.** Deque measured 16 criteria with automated findings across their own audit corpus. That is their number, not a guarantee about our page. Count the criteria axe actually reports on our app and use that figure. Say "our five plus whatever axe reports" until we have counted.

---

## What we record

One run per page state.

**Capture stop 0 first, before the first Tab press.** Record whichever element holds focus when the state is entered. This is not cosmetic. Tab legitimately closes an ARIA menu, so capturing only after each press means the first recorded stop is already outside the menu. The evidence for a keyboard trap is "focus was on this element, Tab was pressed, focus is still on it", and stop 0 is half of that comparison. Without it a Tab-swallowing trap on a menu is invisible to us.

Then press Tab repeatedly. After each press capture:

- which element has focus, with its tag, accessible name and bounding box
- a screenshot
- what changed in the DOM

Separately, capture every interactive element on the page with its bounding box.

Nothing else. Do not record page HTML or base64 images into Weave op inputs. The ingestion cap is 1GB a month and we will hit it.

### How a state is reached

A page state is anything the Tab run can be performed against. The loaded page is one. A page with a dialog open is another. Some defects only exist in a state that is not the loaded one, so something has to reach that state before the Tab run starts.

There are two ways to reach a state, and we build both. They are not a sequence. Neither replaces the other.

| | Fixed list | Explorer |
|---|---|---|
| Used on | The clean app, in the benchmark | Real sites, in the product |
| Why | We wrote the page, so we already know every state it has | Nobody writes us a state list for somebody else's site |
| Job | Measuring | Shipping |
| Retired when | Never | Never |

**The fixed list, for the benchmark.** No model, no browser agent.

| State | How to reach it |
|---|---|
| `loaded` | Navigate, wait for load |
| `dialog-open` | Click the button named "Add Delivery Address" |
| `menu-open` | Click the menu button |
| `tabs-focused` | Move focus into the tab list |

Four states, not two. Two of the three keyboard traps live in states other than the loaded page, so with only `dialog-open` available 2.1.2 would cap at 1/3 with 2 never evaluated on every run, and its delta column could never move. The menu and the tabs are already on the clean app, so adding them costs two lines and unlocks the row.

Run the Tab loop once per state.

**After the reach step, assert in code that the DOM actually changed.** `aria-expanded` flipped, the dialog lost `hidden`, whichever applies. If it did not change, the state was not reached and every criterion for it returns `not_evaluated` with that reason.

This has to be code. A recording of a dialog that opened and one of a dialog that never opened have the same shape, because every stop sits in a small region either way. No model can separate them, since the signal is not in the tab stops at all.

**The fixed list is permanent, not a stepping stone.** It stays after the explorer works, because it is the only way to tell whether a change to a check made things better or worse. Every time we edit a check, we re-run against these states and compare the numbers.

An explorer cannot do that job. If it opens the dialog on Saturday and misses it on Sunday, recall drops and we cannot tell whether the check got worse or the explorer had a bad run. Two things would be moving at once and we could separate neither.

**The explorer is the product.** It reads the accessibility tree, picks an element, clicks it, and looks at what changed. On a site it has never seen, that is the only option, and we cannot ship something that asks a customer to describe their own dialogs.

**One thing the split gives us free.** Once both exist, run the explorer against the clean app and compare what it reached against the states we know are there. Did it find the dialog. Did it find the menu. That measures the explorer on its own, separately from the checks, using a page where every state is already known.

**Why this matters for 2.1.2.** The No Keyboard Trap defect is a keydown handler on the dialog that swallows Tab. The dialog carries `class="hidden"` until the button is clicked. If the Tab run only ever happens on the loaded page, the trap is never encountered and 2.1.2 returns recall zero, not because the check is weak but because the evidence was never captured.

The other four defects all live in the loaded state.

**"State not reached" is a recordable reason.** A criterion whose state was never reached returns `not_evaluated` with that reason. Without it, a state we failed to reach looks identical to a state with no trap in it, which is rule 1.4 appearing in a new place.

**Scope of the benchmark.** Four states: `loaded`, `dialog-open`, `menu-open` and `tabs-focused`. The clean app also carries a switch and a form that errors on submit. Each is a state where our five criteria could be measured and each is somewhere a real trap could hide. We are not attempting those two, and that is recorded rather than silent.

---

## Verification rules

Six rules, each from a bug found on 2026-09-12. Every one of them produced a
clean-looking wrong answer, which is the same category as the nine false passes
in the AccessiFix retrospective: not a crash, not an error, a confident result
that was not true.

The bug is recorded beside each rule so nobody weakens one later without
knowing what it cost.

**1. Every verifier runs against the clean page too, and must return zero.**
A check that only ever sees the broken page cannot tell you it works.
*Bug: the 2.4.7 switch defect never applied, and the verification passed anyway.
It asserted the damage was present without ever asking what an undamaged page
looked like.*

**2. Never verify by reading back the thing you changed.** Applying
`outline: none` and then asserting the outline is none is a mirror, not a test.
Verify against the rendered result.
*Bug: the tautological 2.4.7 verification. It could not have failed.*

**3. No constant without its measurement beside it.** A threshold with no
recorded numbers is a guess that looks like a decision.
*Bug: the focus-delta floor was guessed at 0.002. Measured: caret-only on a
focused text input is 0.002, a real outline is 0.18, the switch's
border-and-background indicator is 0.69. The floor is now 0.005, above
caret-only and far below any genuine indicator.*

**4. Reach every state the way a user does.** `element.focus()` is not keyboard
focus: the browser only paints the indicator for real Tab focus.
*Bug: verification by programmatic focus. On the clean page a JS-focused input
reports `outline-style: none` and the two frames come back byte-identical,
while the same element reached by Tab shows a 3px ring.*

**5. Compare frames at the same scroll position.** Focus scrolls the page, so
comparing against the previous stop mixes "an indicator appeared" with "the
page moved".
*Bug: focus-delta compared each frame against the previous stop's frame. The
recorder now captures a focused and an unfocused frame at one scroll position,
so the only difference is the indicator.*

**6. Crop in the same coordinate space as the screenshot.** A screenshot is
viewport-sized.
*Bug: document coordinates cropped against a viewport screenshot, so anything
below the fold was compared against unrelated pixels. Document coordinates stay
the basis for reading order; viewport coordinates are carried alongside for
cropping.*

**The test that enforces rule 1** is `tests/test_clean_page.py`. It runs every
check against the clean page and fails on any finding. That one test would have
caught the switch defect, the crop bug and the threshold.

---

## The benchmark

**We do not use Ma11y.** It covers three of our five criteria, it injects into the rendered DOM rather than source so there is nothing to patch, and it deliberately excludes anything involving JavaScript. Remove any reference to it.

**The clean app** is our teammate's page, built from W3C ARIA Authoring Practices examples. It has no accessibility problems in it.

It is static HTML, not React. The branch carries `vercel.json` with `framework: null`, no build step, and `outputDirectory: public`. The components are copied from `w3c/aria-practices` at commit `7e4034b`, and handlers are bound with inline `onclick` attributes and direct `addEventListener` calls. Do not infer React from Vercel, because Vercel serves static files.

She has pushed it to a branch on our shared repository and stopped there. Deployment is mine, because the repository sits under my GitHub account. Vercel builds every branch and gives each one its own preview URL, so the branch does not need merging into `main` to get a URL. If the page lives in a subfolder, set the root directory when importing or the build fails looking for a `package.json` that is not there.

**The broken app** is the clean app with one-line defects we apply ourselves.

**Three instances per criterion. Fifteen defects across five criteria.**

One instance per criterion does not produce a recall number, it produces a bit. Recall is either 0/1 or 1/1, so nothing can move between runs and the benchmark screen has nothing to display until a check flips entirely. Precision is worse, because one true positive plus one false positive gives 1/2 and the number jumps in halves.

Three instances give recall in thirds and precision that moves in useful increments.

They also test something one instance cannot: whether a check finds the second and third occurrence or stops at the first. That is a real failure mode, and grouped patching is exactly what creates it.

Each instance is still a single line, still planted by us, still needing no human labelling. Put them in different places on the page rather than side by side.

**Do not break Focus Order with a positive `tabindex`.** Measured with axe-core 4.13.0 against a page carrying all the defects: axe fires `tabindex` on the positive-tabindex element, and `region` on the headings. Both are best-practice rules with no WCAG tag, and the `tabindex` rule detects the presence of a positive value rather than judging the resulting order. It still means "axe reports nothing on our criteria" is false as written, and a judge can check it in thirty seconds.

Breaking it with CSS `order` fixes that. The DOM order stays sensible, the visual order changes, axe has no positive tabindex to find, and our check still catches it because it compares the tab sequence against reading order derived from on-screen positions. It is also the more realistic failure, since production sites break focus order with layout far more often than with `tabindex`.

| Criterion | How we break it |
|---|---|
| 2.1.1 Keyboard | Replace a `<button>` with a `<div onclick>`, in three different places |
| 2.1.2 No Keyboard Trap | Add a keydown handler that swallows Tab, on three separate containers. These defects live in states other than the loaded page. |
| 2.4.3 Focus Order | Reverse two controls visually with CSS `order` on a flex container, in three separate containers. Do not use a positive `tabindex`. |
| 2.4.7 Focus Visible | Add `outline: none` to three controls |
| 2.4.11 Focus Not Obscured | Add sticky elements that cover three focusable controls |

We planted the defect, so we know the correct answer. No human labels anything.

**Two numbers per criterion.** Recall, meaning how many planted defects we found out of three. Precision, meaning how much of what we reported was actually there. Never one aggregate number.

**Report `not_evaluated` in the same row as recall.** A criterion reading 0/3 recall with 3 not evaluated means we never reached the state, which is a different fact from a broken check. Separated across the screen, the two are indistinguishable.

**The clean app needs no answer key.** The correct output is zero findings from our five. Anything our five report on it is a false positive.

Scope that claim to our five. axe fires best-practice rules such as `region` on the ARIA APG examples, and those are not our false positives.

### Two counters, not one

The patcher can fail in two different ways and they mean opposite things. Count and label them separately.

**Locate attempts.** The model returns a find and replace pair and the text does not match. Our code sends the failure back with the real lines, and the model retries. Three attempts, then we record `not_evaluated` with the reason `could not locate the code`. This is rule 2.3.

**Patch attempts.** The patch applied cleanly, we rebuilt and re-audited, and the finding is still open. The fix was wrong. A finding can locate perfectly every time and still never close.

**Stop after five patch attempts.** Then record `not_evaluated` with the reason `still failing after 5 patches`. Without a ceiling, one stubborn finding loops through patch, rebuild and re-audit forever, against a hard $100 inference cap and a fixed deadline. Five is the limit, and it is the top of the chart's axis.

A locate failure has no position on a patch-attempt axis, because zero patches were applied. Plotting it at the ceiling would claim five fixes were tried and all failed, which is the opposite of what happened. It goes in its own counter with its own sentence.

The two failures also leave a finding in different states. A patch failure leaves it open and known-failing, because it was judged and it is still broken. A locate failure leaves it `not_evaluated`, because the criterion was never re-judged at all.

A finding that ran out of locate attempts and a finding that was patched three times and still fails are telling us different things about the system. Anywhere either is displayed, the two must be distinguishable.

**Attempts per closed finding is the patch counter**, not the locate counter.

**One honest caveat when that number is shown.** A falling line can mean the patcher learned, or it can mean the later findings were easier. Show the individual findings in the order they closed rather than only a mean, and link each one to its trace. The claim is what happened, not proof of learning.

---

## The comparison

Run axe on the same broken app. It reports nothing tagged to our five criteria. This is measured rather than asserted: with 2.5.8 moved to axe's column, no rule axe fires carries a WCAG tag matching anything we claim. Re-run `tools/axe_overlap.py` after any change to the defect set.

That is the comparison, and we are not cherry-picking. Deque's own data, across nearly 300,000 issues, shows zero automated findings for Focus Order and Focus Visible, and 234 for Keyboard against 9,178 manual ones.

**Do not claim we detect better than axe on axe's criteria.** We use axe for those, so the claim is meaningless.

**For the fixing side**, if there is time, run the patcher on A11YBench-Lite and report solve rate, side effect count and cost. Do not claim to beat published numbers without matching their harness settings.

---

## The firewall does not affect our coverage

Daytona Tier 2 blocks outbound requests to hosts outside the allowlist. Remote images and CDNs do not load.

This costs us nothing. All five criteria read a tab sequence and screenshots of our own page. None needs a remote image.

Two fixes to apply anyway, because they are faster and more deterministic:

1. Bundle axe-core into the container image. Never fetch it from a CDN.
2. Abort third-party requests explicitly in Playwright. Blocked requests currently hang until timeout, so `networkidle` never settles and we screenshot a half-loaded page.

Do not spend time on 1.1.1 or 1.4.5 image evidence. Those are axe's criteria, not ours.

---

## Which model does what

Two models, two jobs. This is measured, not assumed.

**W&B Inference generates.** It decides Focus Order and it writes the find and replace pairs for patches.

**TypeSafe Jev decides.** It answers typed questions against a state and returns a value with a probability distribution and a confidence score. It generates no text.

### The three answer types

Jev writes no sentences. You ask a question and choose which kind of answer you want back.

| Type | What you get | Example |
|---|---|---|
| `noul` | One number between 0 and 1 | "Is this tab order sensible?" returns 0.37 |
| `choice` | One option from a list you supply, plus a confidence score and a probability for each option | "Is the severity major, minor or none?" returns `major` at confidence 0.7 |
| `score` | A score against a rubric you supply, plus a confidence score | Rating a state on an ordered scale |

You can mix all three in one call. Every question is evaluated in parallel against the same state, so adding questions barely changes the response time.

**Jev is text only and has no vision.** Neither of its jobs needs it. The evidence gate reads the recording as data, meaning the list of tab stops with their tags, names and positions. Borderline Focus Visible receives the pixel difference as a number our code already computed, never the screenshots themselves.

### Why Focus Order goes to W&B Inference

Rule 5.2 requires the model to name which part of the recording proves its finding, so our code can look that reference up and discard the finding when it does not resolve. That mechanism is what raised Flow-A11y's fail precision from 23.5% to 41.4%.

Jev has three primitives. None of them can return a list of references. So with Jev, rule 5.2 is not implementable.

Measured head to head on four cases, clean through to chaotic ordering: W&B Inference was correct on all four, the union held on every call, and evidence references came back on each failure. Jev ranked the cases correctly but could say nothing about which tab stop was wrong.

**Pin `meta-llama/Llama-3.3-70B-Instruct`.** Measured across generally available models on four fixtures, one clean and three broken orderings:

| Model | Correct | Warm latency | Tokens per 4 calls |
|---|---|---|---|
| `meta-llama/Llama-3.3-70B-Instruct` | 4/4 | 0.40s | 1,299 |
| `openai/gpt-oss-120b` | 4/4 | 19.18s | 3,812 |
| `zai-org/GLM-5.3-Flash` | 4/4 | 22.89s | 3,763 |
| `Qwen/Qwen3.8-27B` | 3/4 | 29.87s | 7,944 |

Four fixtures cannot separate 4/4 from 3/4, so accuracy is not what decides this. Speed and cost are. The other three are reasoning models that spend 600 to 900 completion tokens thinking before the JSON starts. Across a 40-page benchmark re-run all weekend, that is 16 seconds against 13 to 20 minutes, at three times the tokens, against a hard $100 cap with no pay-as-you-go.

`Qwen/Qwen3-30B-A3B-Instruct-2507` is confirmed deprecated in W&B's documentation. Do not use it.

**Set `max_tokens` to at least 1000.** Reasoning models spend 600 to 900 tokens before emitting any JSON. A 400-token cap truncates them mid-object and reads as model failure. This produced one wrong conclusion already.

**The JSON schema does not enforce the union.** With `required: ["status"]`, this is schema-valid and useless:

```json
{ "status": "failed", "reason": "the order is wrong" }
```

Every model returned exactly that until the prompt demanded `evidence_refs` explicitly. So the union is prompt-enforced, and rule 5.2 is not a refinement. It is the only thing stopping unsupported findings reaching the report. Our code must check that `evidence_refs` exists and that every reference resolves against the recording.

### Where TypeSafe might still earn its place

**Borderline Focus Visible, and this is untested.** Code computes the pixel difference between the screenshot before and after focus lands, cropped to the focused element. When that number falls in the narrow band where a person might or might not notice, ask Jev whether they would. A calibrated number with a probability distribution is the right output for that question.

**The evidence gate is cut.** See below.

**Branch on the `choice` value, never on confidence.** Measured on the gate cases, confidence does not separate what matters. A fully rendered page sat at 0.51 to 0.56, and the unopened-dialog case sat at 0.42 to 0.60, overlapping it completely. Any threshold near 0.5 escalates healthy pages and still fails to catch the dialog. The `choice` value separated all five cases correctly on every run.

This was measured on the gate question only. Do not route on confidence for any other question either until it has been measured there too.

### The evidence gate is cut

The gate rejected all four real recordings of the clean app, at 0.94 to 0.99 confidence. As specced it would have returned `not_evaluated` on every state of every run.

Rewording the question bought real pages and sold the junk detection. Three of four real recordings were accepted, and "all stops inside a dialog that never opened" was then waved through at 0.98. A gate that accepts unjudgeable recordings is worse than no gate, because it gives false assurance.

**No third wording fixes it.** A recording of a dialog that did open and one of a dialog that never opened have the same shape, since every stop sits in a small region either way. The signal is not in the tab stops, so no model reading them can separate the two.

**The replacement is one line of code.** After the reach step, assert the DOM changed. It is deterministic, free, and it answers the question the model could not.

The earlier five-out-of-five result was a badly designed fixture set. All five recordings were written by one author in one style at one length, so the model learned to recognise that page rather than to recognise judgeability. Stop count alone moved the verdict: the same synthetic page cut from 36 stops to 9 flipped from accept to reject.

**Borderline Focus Visible is a separate question and is untested.** Code computes the pixel difference and hands over one number. There is no recording shape to be ambiguous about, so the failure above does not apply. Test it before assuming either way.

### Two rules for using Jev

**Use `choice` for verdicts. Use `noul` as a diagnostic only.** On the Focus Order fixtures a clean page returned 0.48 on one run and 0.53 on another, so any threshold near the middle flips a correct verdict between runs.

The gate cases show the same thing from another angle. The noul behaved well on three of them, 0.85 for a good page against 0.15 for a half-loaded one and 0.04 for an empty one. It then put the unopened-dialog case at 0.78, close to the good page, because the positions genuinely are stable and merely confined. The `choice` value got that case right every time. Where the two signals disagree, `choice` is the one that is correct.

**Ask small questions and combine them in code.** Decompose anything that weighs several factors into one question per factor. Questions evaluate in parallel against one state, so forty tab stops with three questions took 0.26 seconds. Adding questions barely moves it.

### Mechanics

Endpoint is `POST https://api.typesafe.ai/v1/systemone` with `Authorization: Bearer <key>`. It rejects OpenAI-shaped requests. There is a Python SDK, `typesafe-sdk-python`.

You do not supply a schema and it does not infer one. The primitive fixes the return shape. For `choice` you control the option keys, and the returned string is guaranteed to be one of them, so the discriminant is safe. `reason` and `evidence_refs` cannot come from the model at all, which for `not_evaluated` is an improvement, because we write the reason in code and it cannot be invented.

Rate limits are unknown. Twelve rapid calls all returned 200, and no 429 was triggered, so the error shape has not been seen.

### Pins

Five, and three have already caused problems.

- `jev-1.13.0`. The API resolves `jev-latest` and reports the resolved version in the response.
- `meta-llama/Llama-3.3-70B-Instruct`. Text only, and Focus Order is a text job.
- `max_tokens` at 1000 or above.
- `openai`. Version 1.51.0 breaks against httpx 0.28 with `Client.__init__() got an unexpected keyword argument 'proxies'`. 3.13.0 works.
- `httpx`. Installing `daytona` pulls 0.28, which is what breaks the openai SDK.

---

## What we do not build

- A rule engine. axe exists.
- A crawler as a feature. It is plumbing.
- A conformance score. No body certifies WCAG conformance, and the FTC fined a company $1 million for claiming it.
- An alt text generator.

---

## What we claim

We report on our five criteria plus whatever axe reports. All five of ours are Level A or AA. If we quote a total, we count what axe actually fires on the page rather than reusing Deque's figure.

We report the number of new violations our patches created, alongside the number closed.

We never say a site is compliant.