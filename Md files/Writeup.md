# Ally: what actually happened

Notes for the submission. Two sections, deliberately separate: what the system
worked out by itself, and what a person corrected by hand. Conflating them is
the easiest way to overstate an agent, and the interesting parts of this build
are in both columns.

---

## The measurement bug, which is the best thing in here

**For two days the scoreboard said 8 of 15. The checks were finding 14.**

The benchmark plants fifteen defects, three per criterion, and scores recall by
matching each reported target against the manifest row that planted it. The
manifest names elements the way a person writes CSS — `[role="switch"]`,
`.city_input`, `#email_item`. The recorder addresses elements the way a
serialiser has to — an id if there is one, otherwise a DOM path like
`body>main>section:nth-of-type(5)>div`. The scorer compared those two as
strings.

No amount of string slicing makes `[role="switch"]` match
`body>main>section:nth-of-type(5)>div`. They are the same element.

The failure was invisible because it was consistent. Every criterion's row was
wrong by exactly the number of manifest entries that named an element by class
or role instead of by id:

| Criterion | manifest rows with a bare id | scoreboard said |
|---|---|---|
| 2.1.1 | 2 of 3 | 2 of 3 |
| 2.1.2 | 2 of 3 | 2 of 3 |
| 2.4.7 | 1 of 3 | 1 of 3 |
| 2.4.3 | 0 of 3 | 0 of 3 |
| 2.4.11 | 3 of 3 | 3 of 3 |
| | **8** | **8 of 15** |

Counting the id-based manifest rows predicts all five rows exactly. That is what
settled it — not an argument about whether the checks were good, an arithmetic
prediction that reproduced the whole table.

**It also inverted the diagnosis.** The standing hypothesis was that two
exclusions added to cut 2.1.1 false positives — roving-tabindex children, and
spans inside buttons — had quietly cost recall, because the missed 2.1.1 defect
was a `div role="switch"` built from spans and the missed 2.1.2 defect was on a
tablist. Plausible, and wrong. Running the scan with the exclusions disabled:

| | exclusions on | exclusions off |
|---|---|---|
| 2.1.1 targets | 3, including the switch | 10 — the same 3 plus 4 menu items and 3 tabs |
| 2.1.2 targets | `#tab-1`, focus repeated | `#tab-1`, identical |

Nothing came back, because nothing had gone. The switch and the tablist were in
the findings the whole time, under selectors the manifest could not match.
Turning the exclusions off only added seven false positives that are correct
roving-tabindex behaviour.

**Two things that made it survive so long.** The clean-page test runs constantly,
so every false positive is seen immediately. The fifteen defects ran rarely, so a
miss was almost never seen. And a wrong recall number looks exactly like a weak
checker, which is a much more believable story than a broken scoreboard.

The scorer now matches on element identity collected from the DOM at record
time — what the element is, and what it sits inside — rather than on string
similarity. An ancestor counts as a match, because 2.4.3 is planted on a
container (a reversed flex row) and manifests on the controls inside it, which is
both what the check reports and what a keyboard user meets.

### The re-baseline, run rather than re-matched

`baseline6`, a fresh audit of all five broken pages and the clean page, four
states each, judge live, every call traced:

| Criterion | recall | precision | not_evaluated | clean-page FP |
|---|---|---|---|---|
| 2.1.1 | 3/3 | 3/3 | 0 | 0 |
| 2.1.2 | 3/3 | 3/3 | 0 | 0 |
| 2.4.3 | 3/3 | 4/5 | 1 | 0 |
| 2.4.7 | 3/3 | 3/3 | 0 | 0 |
| 2.4.11 | 3/3 | 3/3 | 0 | 0 |
| **total** | **15/15** | **16/17** | 1 | 0 |

No target fell back to string matching, so every row was scored on identity.

**Where the seven came from, kept separate on purpose.** Six from the scorer fix:
the 2.1.1 switch, the 2.1.2 tablist, the 2.4.7 city field, the 2.4.7 switch, and
both observable 2.4.3 instances were already being detected and are now matched.
One from the fixture replacement: 2.4.3 instance 3, which no checker could have
found. `8 + 6 + 1 = 15`. **Nothing in this movement is a detection improvement.**
The checks are the same checks; six of the seven were a measuring bug and the
seventh was a fixture bug.

### The judge's first clean comparison

Every previous 2.4.3 number was taken against a fixture that could not be matched
or against check code that changed between runs, so this is the first time the
judge has been measured at all. It is 4 of 5, and the detail matters more than the
ratio.

- On `loaded` it produced one finding naming both planted defects — the switch
  reached first while painted last, and the email/name pair swapped. Correct on
  both.
- On `dialog-open` it named both footer buttons. Correct.
- On `menu-open` it found the email/name swap again in a second state. Correct.
- On `tabs-focused` it returned `not_evaluated`: fewer than two positioned stops,
  so there is no order to compare. Honest rather than empty.
- The one scored false positive is `#full_name`. It is one of the two controls
  whose relative order is wrong, so the citation is defensible; it scores as a
  false positive because the manifest names the container that was reordered
  (`#email_item`) and `#full_name` sits in a sibling container. **That is a
  scoring-convention artifact, not a hallucination, and it is recorded as such.**
- The earlier `#action_output` citation — a genuinely unrelated element cited
  inside a correct finding — did not recur once the fixture and the revisit bug
  were fixed. It stays on the record because it happened, not because it is still
  happening.

**Rule 1 now passes with the judge live.** 2.4.3 returns `passed` in all four
states on the clean page, with a stated stop count each time. Before the revisit
fix it reported two of the clean dialog's address inputs as out of order.

---

## The traces that never saved

Weave is a judging criterion. Until 2026-09-12, not one trace from this build
was stored.

`weave.init` succeeded. The ops ran. The results were correct. Every call was
discarded on the way out, because of a name collision:

- SCOPE rule 5.2 requires every finding to cite evidence that resolves
  deterministically, so `Stop` and `Candidate` each had a `ref` property
  returning a citation string like `"stop 3"`.
- Weave decides whether an object is already saved with
  `get_ref(obj) = getattr(obj, "ref", None)`, then calls `ref.project`.
- A `str` has no `.project`. `_save_nested_objects` raised, the call was dropped,
  and the only visible sign was a single suppressed warning line — which a log
  filter in the diagnostic tooling was removing.

Nothing in the codebase could have caught this, because the checks return the
same answers whether or not the trace saves. `tests/test_weave_trace.py` now runs
real checks under a real client, flushes, and asks the server whether the calls
arrived with their inputs intact. The property is `cite`.

---

## What the agent worked out on its own

- **Recording non-determinism, traced to six separate causes.** The same page
  gave 11, 5 and 15 Tab stops across runs. In the order they mattered: Chromium
  keeps the sequential focus navigation starting point across a same-tab
  navigation, so each run began wherever the last one left focus (`about:blank`
  first); under Xvfb the window loses focus unpredictably
  (`Emulation.setFocusEmulationEnabled`); the unfocused reference frame was being
  taken by blurring and refocusing mid-sequence, which does not reliably restore
  the starting point (moved to a second pass after the sequence completes); the
  2.1.1 candidate scan ran before the Tab loop and its hundreds of CDP round
  trips disturbed focus (moved after); a fixed sleep raced the page's own scripts
  setting tabindex values (readyState polling); and the browser was reused across
  recordings. Now ten consecutive runs across three pages and two states produce
  identical stop sequences with screenshots on.
- **`document.body.focus()` does not help** — body is not focusable without a
  tabindex, so the call is a no-op and the starting point is untouched.
- **Bare tag selectors collide.** The delivery dialog holds several unlabelled
  inputs, each the only input in its own wrapper, so every one produced the
  selector `input`. Consecutive different inputs then looked like the same
  element repeating, and 2.1.2 reported a keyboard trap on a page with no
  defects. Selectors are full ancestor paths now.
- **A React root container carries 131 listeners including `click`** and is not
  focusable, so the naive 2.1.1 rule flags it on every React page. Hence the
  delegating-container exclusion.
- **React's `onClick` is visible by proxy.** React binds its dispatcher, not your
  handler, but it attaches that dispatcher only to elements carrying an `onClick`
  prop — six of six cases on React 18 UMD. Recorded as a dependency on an
  implementation detail, not a fact.
- **axe overlap, measured rather than assumed.** Enumerating all 105 rules in
  axe-core 4.13.0 by WCAG tag: four of our five have no axe rule at all. 2.1.1
  has three, none of which fires on a `div onclick` acting as a button. 2.5.8 was
  dropped from our scope because axe's `target-size` rule already fired on the
  planted defect across three nodes.
- **Focus-delta thresholds, measured not guessed.** Caret-only change on a
  focused text input is 0.002; a real outline is 0.18; the switch's
  border-and-background indicator is 0.69. The floor sits at 0.005.

## What a person corrected by hand

These are not the agent's wins and are not presented as such.

- **The 2.4.7 switch defect never applied.** `outline: none` was a no-op because
  `switch.css` already sets it and signals focus with padding, border-width and
  two background colours. The verification asserted the damage was present
  without asking what an undamaged page looked like — it read back the thing it
  had changed. Caught by a person. It cascaded into three real checker bugs: a
  document-coordinate crop against a viewport screenshot, comparison against the
  previous frame rather than an unfocused frame at the same scroll position, and
  the guessed threshold above.
- **The 2.4.11 fixture measured the manifest, not the checker.** The covers were
  sized over containers rather than over single controls. Correcting it moved
  2.4.11 from 0 of 3 to 3 of 3 — a fixture correction, not a detection
  improvement, and it must be reported that way.
- **Patch retries were eating the locate budget.** Two opposite failures — three
  locate attempts with no patch applied, five patch attempts that were applied
  and failed — had been collapsed into one counter by hand, in the loop the
  design exists to prevent that in. They are counted and labelled separately now.
- **Three edits to one file collapsed to one**, because `RemoteFile` hashed by
  identity. The patch reported applied and the file was unchanged.
- **The rule-1 test passed `judge=None`**, skipping the only check that uses a
  model, to save a model call. Written one day; defeated by an optimisation the
  next. That became verification rule 7.
- **A Stage 4 control run was aborted deliberately.** The check code had changed
  underneath the baseline it was being compared against. A before-and-after
  computed by two different programs measures nothing.
- **The exclusion hypothesis was a person's, and it was wrong.** It was also the
  right question, and testing it is what produced the table above.

---

## Two things to state plainly, because both are easy to overclaim

**The lessons table can only improve patching.** It records patch outcomes, so a
finding that was never detected produces no row. It cannot reach detection at
all. Any number from it is effort per fix across the findings already detected,
and says nothing about how many are detected.

**The judge has never been given a clean comparison, so nobody has measured it.**
Every number involving 2.4.3 so far was taken either against a fixture that could
not be matched, or against check code that changed between runs. One real
precision defect is on the record and is being kept visible rather than averaged
away: on the 2.4.3 signup finding the judge cited `#action_output` alongside
`#email`. `#email` is correct; `#action_output` is unrelated to the reordering. A
wrong element inside a correct finding is a precision defect and it does not get
to disappear into a passing row.

**One fixture was unobservable by construction.** 2.4.3 instance 3 reversed the
tablist's flex row, but the tabs use a roving tabindex, so exactly one of the
four is in the Tab sequence and reversing the row leaves that stop's rank
unchanged. Measured: tab order `[1..9]`, reading order `[1,2,3,5,4,6,7,8,9]`,
position 7 is `#tab-1` in both. No checker could ever have found it. Replaced
with a positive tabindex on the page-foot switch — WCAG failure technique F44 —
which cannot be unobservable, because positive tabindex values are visited before
every `tabindex=0` element on the page: the control painted last is reached
first.

**The three-instance design earned itself.** Three instances per criterion, not
one, is what caught the patcher stopping at the first occurrence of a
find/replace pair.
