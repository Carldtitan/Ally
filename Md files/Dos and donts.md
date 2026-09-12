# Dos and don'ts

## 1. Storing results

**1.1** Do not store a check result as a boolean. A boolean has two values. A check has three outcomes: it passed, it failed, or it did not execute. With a boolean, the third outcome gets written as one of the first two. In AccessiFix it got written as passed.

**1.2** Do store results as a type with three cases, where the third case requires a reason string:

```ts
type Result =
  | { status: 'passed' }
  | { status: 'failed' }
  | { status: 'not_evaluated'; reason: string }
```

The compiler will reject code that constructs `not_evaluated` without a reason. That is the point.

**1.3** Your system has two separate parts. The first part runs axe on a page. The second part takes what axe produced and writes your report.

The second part needs to know whether axe actually ran. Only the first part knows that, because only the first part was there. So the first part must say so, in writing, and the second part must read what it said.

The way to do that is to add one more field to the result. Alongside the list of violations, the first part writes a field that says whether axe finished. If axe finished, that field says yes. If axe crashed or the page never loaded, that field says no.

You still use the list of violations, and you should. The list is the answer to one question: what is wrong with this page. You read it for exactly that. The mistake was using it to answer a second question it cannot answer, which is whether axe looked at the page at all. An empty list is consistent with a clean page and with a page axe never opened, so the list cannot tell those apart.

So your report reads both fields, for different purposes. It first reads the field that says whether axe finished. If that field says no, the report writes "not evaluated" and stops there, because the list means nothing in that case. If that field says yes, the report reads the list of violations and uses every item in it.

**1.4** Do not calculate whether a check executed by looking at the check's output. In AccessiFix, an empty violations array meant either "clean page" or "axe never ran". Your code read the empty array and wrote "clean page".

**1.5** Do not read exit code 0 as success. Cypress exits 0 when it runs 40 passing tests. Cypress also exits 0 when it finds 0 test files. Read the test count, not the exit code.

**1.6** TypeScript runs before your program starts. It reads the descriptions of what your code contains and checks that those descriptions agree with each other. It never starts your program and watches it work.

In AccessiFix, TypeScript read a description saying a function called `runAudit` existed, and it approved the build. When your program actually started and asked for that function, the function was not there.

The lesson is that a successful build tells you the descriptions agree. It does not tell you the code works.

The cheap protection is a startup check. When your program first starts, before it does any work, it asks for each important function by name and checks that what came back really is a function. If any one of them is missing, the program stops immediately with a clear message. That takes about ten lines and it would have caught this whole family of bugs on the very first run.

---

## 2. Letting a model edit files

**2.1** Coding agents do not edit files the way you are imagining. There is no editor and no cursor moving around. They send small text instructions and a separate program carries them out.

Claude Code has a tool for editing a file. That tool takes three things: which file, what text to look for inside it, and what text to put in its place. The program running Claude Code then opens the file itself, searches for that text, and swaps it. If the text appears more than once, or not at all, the program refuses and tells the model.

Cursor, Codex and Aider all do this. None of them hand a whole file to the model and take a whole file back.

So the approach in 2.2 is not a workaround I invented for you. It is what every working coding tool already does.

There is one exception. When you are creating a brand new file, there is no existing text to search for, so you write the whole file out.

You are building your own edit loop rather than taking an existing one. That is the right call, and the reason is that the two things you are being judged on are both harness decisions. The grouping in 5.4 and the evidence trail in 5.2 are decided by whoever writes the loop. OpenHands and SWE-agent both fix one violation at a time, so taking either of them means fighting the harness on exactly the thing that matters. The whole loop is a few hundred lines, and you control what goes into the trace.

Do not send a file over about 400 lines to a model and ask for the whole file back. The model has to regenerate every line from what it read. Some lines come back changed. You measured 4,033 changed lines on a 2,231 line file when the task needed three attributes added.

**2.2** Do ask for find and replace pairs instead. The model returns a short piece of existing text and the text to put in its place. Your program does the search and the replacement. The file never passes through the model.

**2.3** You tell the model it failed and let it try again.

If the text it asked you to find is not in the file at all, the model invented that text. Your program replies saying there was no match, and includes the lines that are actually in that part of the file so the model can see what is really there.

If the text appears three times, the model gave you something too short to be unique. Your program replies saying there were three matches and asks for a longer piece of text. The model then includes the lines above and below, which makes it unique.

Allow three attempts. After the third failure, stop and record that finding as not evaluated, with the reason that you could not locate the code. That is your locator declining to guess, which is the behaviour you already got right in AccessiFix.

This retry loop is how coding agents already work. When Claude Code's edit tool cannot find the text, it returns an error, and that error goes back to the model as its next input. The model reads the error and sends a corrected edit. When the text matches more than once, the tool returns an error saying how many matches there were and asking for more surrounding context. Aider does the same and calls the failure a search block not found.

The one part that is not standard is giving up. Most coding tools retry until the model succeeds or the user stops it, because a person is sitting there watching. Yours runs unattended against somebody's repository, so it needs a limit and a recorded reason.

**2.4** When a model does not want to reproduce a long stretch of code, it sometimes writes a note in place of the code instead. The note says something like "rest of the file unchanged". If that note lands in your file, the code it replaced has been deleted.

The obvious defence is to search the patched file for notes like that. In AccessiFix this gave you a false alarm, because that component contained a genuine helper function whose name looked like one of those notes.

The better defence is to count rather than search. Count how many times the suspicious text appears in the original file, then count how many times it appears in the patched file. If the number went up, the patch added one and you reject the patch. If the number is the same, the text was already there and the patch is fine.

---

## 3. Approving a patch

The next three rules are about a part of your system you may not picture yet, so here is the situation first.

Before applying a patch to somebody's repository, you show it to a person and wait for them to approve it. For that to be safe, the patch the person looked at has to be the same patch that gets applied. If those two can differ, a person can approve one change and a different change lands in the repository.

**3.1** AccessiFix tried to check this and the check could never fail.

You had a function that turns a finding into a patch. Your safety check called that function twice, once to produce the patch it was about to show, and once more to produce the patch it was about to apply, then compared the two.

The same function with the same input gives the same answer every time. The two were always identical, so the check always passed.

What that check actually tested was whether the function is consistent with itself. It never tested whether the person approved the thing that was applied, because the patch the person saw had already been thrown away by the time the comparison happened.

**3.2** This is the repair for the problem in 3.1. The idea is that only one copy of the patch ever exists, and it lives in a file.

Your planner builds the patch and writes it to a file on disk. That is the last time the patch is built.

Your approval screen opens that file, reads what is in it, and shows that to the person. It does not build anything.

After the person says yes, the part that applies patches opens the same file, reads it, and applies exactly what is in it.

Because the file is the only copy, the person looked at the same bytes that were applied. There is nowhere for a difference to creep in.

If you want to be stricter, take a fingerprint of the file right after writing it, and check the fingerprint again just before applying. That catches anything that edits the file between approval and application.

**3.3** Say your scan reported that a button has no name a screen reader can announce. You patch the source to add one, and the project compiles.

At that point you know the code is valid. You do not know the button has a name now.

Three things can go wrong while still compiling. The component you patched might not be the one that page renders. The label might have landed on a wrapper element rather than on the button itself. Something else on the page might be hiding the button from assistive technology, which cancels the label out.

So you rebuild the site, load the page again, run the scan again, and check that this particular finding has gone. Only then do you mark it closed.

AccessiFix marked findings closed as soon as the patch compiled and never re-scanned the page. That is why it reported zero failures while eight findings were still open.

**3.4** Do count the violations that exist after the patch but did not exist before it. Report that number. A patch that closes nine problems and creates four has closed five.

---

## 4. What to check

**4.1** Do not write your own rule engine. axe-core is free and already covers the criteria a page scan can cover.

**4.2** Here is criterion 2.4.3, Focus Order, from start to finish. The other criteria in this group follow the same shape.

The criterion asks whether the order in which you reach things by pressing Tab makes sense.

First you drive the keyboard. Using Playwright, you press Tab, then ask the page which element now has focus, and record its tag, its visible text, and where it sits on screen. You do that forty times.

What you now have is an ordered list of every element the keyboard reached, in the order it reached them.

Then you run ordinary checks over that list, with no model involved. If the same element appears twice in a row, the keyboard is stuck on it. If after forty presses focus has never left the page, the user is trapped. If the position on screen jumps far down the page and then back up, the order is leaving a section and returning to it.

Finally you send the list to a model, along with a screenshot of the page with each stop numbered on it, and you ask it one question. Does this order match the order somebody would read the page in. That is the only part that needs judgement.

Focus Visible, criterion 2.4.7, reuses the same run. You take a screenshot before and after each Tab press and compare the area around the element that received focus. If nothing on screen changed, focus is invisible to the user.

Do target criteria that a page scan cannot cover. In Deque's data across 300,000 issues, 2.4.3 Focus Order and 2.4.7 Focus Visible had zero automated findings, and 2.1.1 Keyboard had 234 automated findings against 9,178 manual ones.

**4.3** A scanner like axe reads the page once, at the moment it finishes loading. Many accessibility problems are not present in the page at that moment.

A dialog that fails to hold keyboard focus only exists after somebody clicks the button that opens it. An error message that a screen reader fails to announce only exists after somebody submits the form with a field empty. The Tab order is produced by pressing Tab, and there is nothing in the page that holds it beforehand.

So your tool works differently. It performs an action, then inspects the page. Then it performs the next action, and inspects again. A scanner examines one state of the page, and your tool examines a whole sequence of states.

**4.4** Do record, after every action: which element has focus, what keys were pressed, what changed in the DOM, the accessibility tree, and a screenshot. Judging Focus Visible requires the screenshot taken at the moment focus landed.

**4.5** A browser agent is a model sitting in a loop with a browser. The model is given a screenshot, it decides what to do next, that action is carried out, and it is given a fresh screenshot. It repeats until it decides it is finished. The common open source one is called browser-use, and Claude in Chrome works the same way.

The Flow-A11y researchers tested one on this exact job. They gave it a website, a limit on how many steps it could take, and the list of WCAG criteria, and told it to explore and report accessibility problems. There were thirty-one known failures on those sites and it found none of them. On most of the checks it simply had no answer.

It failed because the evidence those criteria need is not in a screenshot. Deciding whether focus is visible needs a comparison between two screenshots, and the model only sees one at a time. Deciding whether a status message is announced needs to know whether a particular region of the page changed. Deciding whether the Tab order is sensible needs the complete ordered list of stops, which no single picture contains.

The same researchers then recorded focus changes, key presses and page changes as they happened, and asked the model about one criterion at a time against that recording. That version found twelve of the thirty-one.

So the browser agent has a job, and it is a narrow one. Use it to reach the states you want to inspect. Your recording observes what happened, and your per-criterion checks decide what it means.

---

## 5. Calling the model

These two rules assume you have the recording described in 4.4, so read that first.

**5.1** Each criterion needs particular evidence before anybody can judge it. Focus Order needs the list of elements the keyboard reached. Focus Visible needs that list and the screenshots. A criterion about announced status messages needs a record of the page region that changed.

So before you send anything to the model, your code checks whether the recording contains what that criterion needs. If the recording has no key presses in it, you never had a Tab order, so you stop and record the criterion as not evaluated, with the reason that no keyboard activity took place.

The reason this matters is that a model always answers. If you ask it about Tab order and send it only the page source, it will still produce something that reads like a verdict, and that verdict is grounded in nothing at all.

**5.2** You hand the model your recording as structured data. It has named parts, such as the list of focus stops and the list of screenshots.

You tell the model that whenever it reports a failure, it must also name which part of that recording proves the failure. It might answer that the page fails Focus Order, and point at the third entry in the list of focus stops.

Your code then goes and looks up that third entry. If it is there, the model was looking at something real and you keep the finding. If the model pointed at a part of the recording that does not exist, it invented its evidence, and you throw the finding away.

This costs you nothing. It is a lookup, with no model involved and no judgement required. When the Flow-A11y team added it, every invented reference disappeared, and the share of their reported failures that turned out to be real failures rose from just under a quarter to just over two fifths.

**5.3** The evidence points both ways, so I should not have given you that as a rule.

The A11YRepair researchers ran the same repair job twice, once with the relevant WCAG guideline text attached to every violation and once without. On one system, attaching the text helped a lot. It solved about eight per cent more violations and cut the number of new problems it created from twenty-eight down to seven, for roughly fifteen dollars more.

On a second system the same change made things worse. It solved slightly fewer violations and cost thirty dollars more.

Their explanation is that it depends on the violation. A missing image description has one obvious fix that the model already knows, so the guideline text is thousands of tokens of noise. A rule about how big a tap target must be contains a specific number that the model will not guess, so the guideline text is essential.

Make this a setting you can switch on and off. Once your benchmark exists, run it both ways and keep whichever wins. That turns an argument into a measurement and it takes twenty minutes.

**5.4** Say a scan reports forty violations on one page. You have a choice about how to hand them to the model.

The obvious way is one violation per request, forty requests in total. That causes two problems.

The first is wasted work. Twenty of those violations are the same icon component appearing twenty times in different places. The model finds the same file twenty times and writes the same fix twenty times, and you pay for all of it.

The second is worse. Each request is independent, so the model has no memory of the fixes it already wrote. A11YRepair documented this happening with three icons that were missing labels. For the first two, the model added a title element inside the icon itself. For the third, it added a label at the place where the icon is used. Those are two different techniques, and mixing them meant the text a user sees no longer matched the text that gets announced. Anyone controlling their computer by voice says the text they can see, so those controls stopped working. The fix created two new problems.

The alternative is to sort the violations into groups before you send anything. Put everything from the same component together, then split those by which criterion they break. You end up with perhaps eight requests instead of forty, and the model sees all three icons at once, so it picks one technique for all three.

A11YRepair measured the difference. Grouping as coarsely as possible solved fifty-nine per cent of violations and created 377 new problems. Grouping at the finest level solved seventy-eight per cent and created 172.

---

## 6. Measuring yourself

**6.1** Do break pages on purpose using Ma11y, then run your agent on the broken pages. Ma11y has 25 operators that inject accessibility defects. You planted the defect so you know the correct answer without labelling anything.

**6.2** Do score precision and recall for each criterion separately. A single overall number will not tell you which part of the system is broken.

**6.3** Do record how often your agent returns "not_evaluated" and report that number. If you change something and violations drop, that could mean the agent got more accurate or it could mean the agent stopped answering.

**6.4** You are doing both, and they answer different questions. I did not separate them clearly enough.

A11YBench already exists. It contains sixty real repositories from GitHub with 8,886 known violations in them. You clone a few of those repositories and run your agent against them. The value is that other people have published scores on it, so your number can be compared to theirs. The limit is that it covers violations a page scan can find, so it will not exercise the interaction criteria you care about.

Ma11y is the other half, and you generate it yourself. You take any page, and Ma11y damages it in a known way using one of its twenty-five operators. Because you caused the damage, you know the right answer without anybody labelling anything. Run it two hundred times and you have two hundred test cases in a few minutes. This is where you test Focus Order and Focus Visible, because A11YBench does not cover them.

When I said show the number move, I did not mean training a model. I meant this. Run your agent over the Ma11y set and write down the precision and recall for each criterion. Read the traces for the cases it got wrong. Change something, such as a check, a prompt, or a rule. Run the same set again, and put the two sets of numbers side by side.

---

## 7. What you claim

**7.1** Do not say your tool makes a site WCAG compliant. No organisation certifies WCAG conformance. The FTC fined accessiBe $1 million for making that claim.

**7.2** Do list the criteria you did not attempt, with a reason. 1.2.4 Captions (Live) needs a live stream. 3.3.4 Error Prevention needs a completed financial transaction.

**7.3** Do write PR bodies that state only what executed and what it found. Anyone reading the PR can run the tests themselves.

---

## 8. Infrastructure

**8.1** Do not use WSL. It shuts down the Linux environment when the command that started it returns, killing background processes you started.

**8.2** Do not use ngrok. Two separate failures in AccessiFix produced the same error code, so you could not tell them apart.

**8.3** Weave and checkpointing solve different problems, so you want both.

Weave keeps a record of everything that happened during a run, which you read afterwards to understand what your agent did. It is what you show the judges. You cannot restart a crashed run from it, because it holds a description of the work rather than the work itself.

Checkpointing means writing the actual output of each stage somewhere you can load it back. After the crawl finishes, you save the crawl result to a file. When your program starts, it looks for that file, and if it finds it, it skips the crawl and carries on from the next stage. That is about twenty lines of code and it means a crash at two in the morning does not cost you the crawl.

**8.4** A git repository has one set of files sitting on disk, and one branch selected at a time. Everything working in that folder shares both of those.

If you run three agents in the same folder, they are all editing the same files. When the second agent switches to its own branch, the files underneath the first agent change without warning, and the first agent then writes its patch into the second agent's branch. Afterwards you cannot tell which agent produced which change.

Git has a feature for this called a worktree. It gives you a second folder attached to the same repository, with its own branch selected. You create one folder per agent, and each agent works in its own folder without ever seeing the others. All the commits still land in the same repository.

The alternative is to clone the whole repository once per agent, which works and wastes disk space. A worktree shares the history and only duplicates the files you are editing.

**8.5** Do not create a database connection pool inside a serverless function. Each instance creates its own pool. Ten instances with five connections each is fifty connections, and Supabase's session pooler caps at fifteen.