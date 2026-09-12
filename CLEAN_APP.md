# clean-app

Control page for the Ally benchmark. It is meant to contain no accessibility problems, so anything the agent reports on it is a false positive.

## What is on the page

Everything is served from `public/`. There is no build step and no dependencies.

| Component | Source |
|---|---|
| Modal dialog: opens from a button, closes on Escape | APG `dialog-modal/examples/dialog.html` |
| Menu button: arrow keys | APG `menu-button/examples/menu-button-actions.html` |
| Tabs | APG `tabs/examples/tabs-automatic.html` |
| Switch: custom toggle | APG `switch/examples/switch.html` |
| Form: text field, required field, error on submit | W3C WAI Forms Tutorial, User Notifications, "After submit" |

APG is github.com/w3c/aria-practices, `content/patterns`, commit `7e4034b`. The APG JavaScript and CSS files in `public/js` and `public/css` are unchanged copies.

Changes from the APG examples:

- Dialog: only the first dialog is kept. The nested demo dialogs and their placeholder links are removed. Its heading is `h2` instead of `h1`. The address fields have `autocomplete`.
- `public/css/site.css`: page layout, a focus outline for elements APG does not style, a z-index so the open menu sits above the tabs, and a rule that lets tab labels wrap on narrow screens instead of being cut off.
- `public/js/form.js` is the only script not copied from APG.

## Vercel setup

`vercel.json` sets these for this branch, so the dashboard values for them do not matter:

- Framework: Other (`"framework": null`)
- Install: skipped (`"installCommand": ""`)
- Build: a no-op `echo`
- Output directory: `public`

Two dashboard settings do matter.

1. **Root Directory** must be empty, meaning the repository root. It applies to every branch and cannot be set in `vercel.json`. If it points to a folder that only exists on main, this branch will not deploy.
2. **Deployment Protection.** Vercel turns on Vercel Authentication by default for every deployment except the latest production one. The clean-app branch URL is a preview, so the agent would load a Vercel login page instead of this page. Do one of these:
   - Switch off Vercel Authentication in the project's Settings → Deployment Protection.
   - Create a Protection Bypass for Automation secret in the same place. Send it on every request as the `x-vercel-protection-bypass` header, plus `x-vercel-set-bypass-cookie: true` so the CSS and JavaScript load too.

Give the agent the branch URL. It always points to the newest deployment of the branch:

```
<project-name>-git-clean-app-<scope-slug>.vercel.app
```

## Checking the deployment

Requires Node and Google Chrome.

```
cd verify
npm install
node verify.js https://<branch-url>/
```

If Deployment Protection is still on, set `VERCEL_AUTOMATION_BYPASS_SECRET` before running it.

The script runs axe-core on 9 page states and drives the page with the keyboard. It checks Tab order, visible focus at every stop, the dialog focus trap and Escape, menu arrow keys and Escape, tab arrow keys, the switch, form errors, and layout at 320px wide.

Last run, on 2026-09-12 against a local server: 42 of 42 checks passed. axe-core 4.13 found 0 violations in all 9 states.

axe also lists "needs review" items. These are expected:

- `aria-valid-attr-value` on the menu button. `aria-controls` points to the menu, which is hidden while closed, so axe cannot check it.
- `color-contrast` on text underneath the open menu or dialog. axe cannot see the background there. The dialog text measures 17.4:1.

The axe DevTools browser extension has not been run. It uses the same axe-core engine, but run it once on the live URL.
