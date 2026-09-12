'use strict';
// Keyboard, focus and axe checks for the clean-app control page.
// Usage: node verify.js <url>
// For a Vercel preview behind Deployment Protection, set VERCEL_AUTOMATION_BYPASS_SECRET.
const { chromium } = require('playwright');
const AxeBuilder = require('@axe-core/playwright').default;

const url = process.argv[2];
const results = [];
const reviews = [];

if (!url) {
  console.error('Usage: node verify.js <url>');
  process.exit(2);
}

// Protection Bypass for Automation. The cookie lets CSS and JS requests through too.
const bypass = process.env.VERCEL_AUTOMATION_BYPASS_SECRET;
const bypassHeaders = bypass
  ? { 'x-vercel-protection-bypass': bypass, 'x-vercel-set-bypass-cookie': 'true' }
  : {};

function check(name, ok, detail) {
  results.push({ name, ok: Boolean(ok), detail });
}

async function runAxe(page, label) {
  const r = await new AxeBuilder({ page }).analyze();
  check(
    `axe zero violations: ${label}`,
    r.violations.length === 0,
    r.violations.map((v) => `${v.id} [${v.impact}] ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`)
  );
  for (const v of r.incomplete) {
    reviews.push(`${label}: ${v.id} -> ${v.nodes.map((n) => n.target.join(' ')).join(' | ')}`);
  }
  return r;
}

function activeInfo(page) {
  return page.evaluate(() => {
    const el = document.activeElement;
    if (!el || el === document.body || el === document.documentElement) return null;
    const r = el.getBoundingClientRect();
    return {
      domIndex: Array.from(document.querySelectorAll('*')).indexOf(el),
      tag: el.tagName.toLowerCase(),
      id: el.id,
      role: el.getAttribute('role'),
      text: (el.textContent || el.value || '').trim().replace(/\s+/g, ' ').slice(0, 30),
      top: Math.round(r.top + window.scrollY),
      inDialog: Boolean(el.closest('#dialog1')),
    };
  });
}

// Screenshots the area around the focused element with and without focus.
// Viewport is taller than the page, so viewport and page coordinates match.
async function focusIsVisible(page) {
  const box = await page.evaluate(() => {
    const r = document.activeElement.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  });
  const pad = 8;
  const clip = {
    x: Math.max(0, box.x - pad),
    y: Math.max(0, box.y - pad),
    width: box.width + pad * 2,
    height: box.height + pad * 2,
  };
  const focused = await page.screenshot({ clip });
  await page.evaluate(() => {
    window.__verifyFocus = document.activeElement;
    document.activeElement.blur();
  });
  const unfocused = await page.screenshot({ clip });
  await page.evaluate(() => window.__verifyFocus.focus());
  return !focused.equals(unfocused);
}

async function axNode(page, selector) {
  const cdp = await page.context().newCDPSession(page);
  const { root } = await cdp.send('DOM.getDocument', { depth: 0 });
  const { nodeId } = await cdp.send('DOM.querySelector', { nodeId: root.nodeId, selector });
  const { nodes } = await cdp.send('Accessibility.getPartialAXTree', { nodeId, fetchRelatives: false });
  await cdp.detach();
  const n = nodes[0];
  const props = Object.fromEntries((n.properties || []).map((p) => [p.name, String(p.value.value)]));
  return {
    role: n.role && n.role.value,
    name: n.name && n.name.value,
    description: n.description ? n.description.value : '',
    ...props,
  };
}

(async () => {
  const browser = await chromium.launch({ channel: 'chrome' });
  const context = await browser.newContext({ extraHTTPHeaders: bypassHeaders, viewport: { width: 1280, height: 2400 } });
  const page = await context.newPage();
  const problems = [];
  page.on('pageerror', (e) => problems.push(`page error: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() === 'error' && !/favicon/.test(m.text())) problems.push(`console error: ${m.text()}`);
  });
  page.on('response', (r) => {
    if (r.status() >= 400 && !/favicon/.test(r.url())) problems.push(`HTTP ${r.status()} ${r.url()}`);
  });
  page.on('requestfailed', (r) => problems.push(`request failed ${r.url()}`));

  // 1. Initial state
  await page.goto(url, { waitUntil: 'load' });
  const title = await page.title();
  check('loaded the clean-app page, not a login or error page', title === 'Example Page', title);
  const height = await page.evaluate(() => document.documentElement.scrollHeight);
  check('page fits the test viewport, so screenshots need no scrolling', height <= 2400, `height ${height}`);
  await runAxe(page, 'initial');

  const names = {
    dialogButton: await axNode(page, 'section button'),
    menuButton: await axNode(page, '#menubutton1'),
    tablist: await axNode(page, '[role=tablist]'),
    tab1: await axNode(page, '#tab-1'),
    tabpanel1: await axNode(page, '#tabpanel-1'),
    switch: await axNode(page, '[role=switch]'),
    fullName: await axNode(page, '#full_name'),
    email: await axNode(page, '#email'),
  };
  console.log('Accessible names:', JSON.stringify(names, null, 1));
  check(
    'components expose the expected roles and names',
    names.menuButton.name.trim() === 'Actions' &&
      names.tablist.role === 'tablist' && names.tablist.name === 'Danish Composers' &&
      names.tab1.role === 'tab' && names.tab1.name === 'Maria Ahlefeldt' &&
      names.tabpanel1.name === 'Maria Ahlefeldt' &&
      names.switch.role === 'switch' && names.switch.name === 'Notifications' && names.switch.checked === 'false' &&
      names.fullName.name === 'Full name:' &&
      names.email.name === 'Email (required):' && names.email.required === 'true',
    names
  );

  // 2. Tab walk from the top of the page
  const stops = [];
  for (let i = 0; i < 40; i++) {
    await page.keyboard.press('Tab');
    const a = await activeInfo(page);
    if (!a || stops.some((s) => s.domIndex === a.domIndex)) break;
    a.focusVisible = await focusIsVisible(page);
    stops.push(a);
  }
  console.log('\nTab stops:');
  for (const s of stops) {
    console.log(`  ${s.focusVisible ? 'visible ' : 'INVISIBLE'} ${s.tag}${s.id ? '#' + s.id : ''}${s.role ? '[' + s.role + ']' : ''} "${s.text}" top=${s.top}`);
  }
  check('Tab reaches all 9 expected stops', stops.length === 9, stops.map((s) => s.id || s.text));
  check('focus is visible at every Tab stop', stops.every((s) => s.focusVisible), stops.filter((s) => !s.focusVisible).map((s) => s.id || s.text));
  check('Tab order follows DOM order', stops.every((s, i) => i === 0 || s.domIndex > stops[i - 1].domIndex));
  check('Tab order moves down the page', stops.every((s, i) => i === 0 || s.top >= stops[i - 1].top));

  const back = [];
  await page.focus('[role=switch]');
  for (let i = 0; i < stops.length - 1; i++) {
    await page.keyboard.press('Shift+Tab');
    const b = await activeInfo(page);
    back.push(b ? b.domIndex : null);
  }
  const expectedBack = stops.slice(0, -1).map((s) => s.domIndex).reverse();
  check('Shift+Tab walks the same stops in reverse', JSON.stringify(back) === JSON.stringify(expectedBack), { back, expectedBack });

  // 3. Modal dialog
  await page.goto(url, { waitUntil: 'load' });
  await page.getByRole('button', { name: 'Add Delivery Address' }).focus();
  await page.keyboard.press('Enter');
  let a = await activeInfo(page);
  check('Enter on the button opens the dialog and moves focus inside', (await page.isVisible('#dialog1')) && a && a.inDialog, a);
  const dialogAx = await axNode(page, '#dialog1');
  check('dialog exposes role, name and modal', dialogAx.role === 'dialog' && dialogAx.name === 'Add Delivery Address' && dialogAx.modal === 'true', dialogAx);
  await runAxe(page, 'dialog open');
  let trapped = true;
  const dialogStops = [];
  for (let i = 0; i < 16; i++) {
    await page.keyboard.press('Tab');
    a = await activeInfo(page);
    if (!a || !a.inDialog) trapped = false;
    else if (!dialogStops.some((s) => s.domIndex === a.domIndex)) {
      a.focusVisible = await focusIsVisible(page);
      dialogStops.push(a);
    }
  }
  for (let i = 0; i < 16; i++) {
    await page.keyboard.press('Shift+Tab');
    a = await activeInfo(page);
    if (!a || !a.inDialog) trapped = false;
  }
  check('Tab and Shift+Tab stay inside the open dialog', trapped);
  check('dialog Tab stops: 5 fields and 2 buttons', dialogStops.length === 7, dialogStops.map((s) => s.text || s.tag));
  check('focus is visible at every stop inside the dialog', dialogStops.every((s) => s.focusVisible), dialogStops.filter((s) => !s.focusVisible).map((s) => s.text || s.tag));
  await page.keyboard.press('Escape');
  a = await activeInfo(page);
  check('Escape closes the dialog and returns focus to its button', !(await page.isVisible('#dialog1')) && a && a.text === 'Add Delivery Address', a);
  check('focus is visible on the button after the dialog closes', await focusIsVisible(page));
  await page.keyboard.press('Enter');
  await page.getByRole('button', { name: 'Cancel' }).focus();
  await page.keyboard.press('Enter');
  a = await activeInfo(page);
  check('Cancel closes the dialog and returns focus to its button', !(await page.isVisible('#dialog1')) && a && a.text === 'Add Delivery Address', a);

  // 4. Menu button
  await page.goto(url, { waitUntil: 'load' });
  const menuState = () =>
    page.evaluate(() => ({
      expanded: document.getElementById('menubutton1').getAttribute('aria-expanded'),
      menuVisible: getComputedStyle(document.getElementById('menu1')).display !== 'none',
      output: document.getElementById('action_output').value,
    }));
  await page.focus('#menubutton1');
  await page.keyboard.press('Enter');
  let m = await menuState();
  a = await activeInfo(page);
  check('Enter opens the menu and focuses the first item', m.expanded === 'true' && m.menuVisible && a.text === 'Action 1', { m, a });
  check('focus is visible on a menu item', await focusIsVisible(page));
  await runAxe(page, 'menu open');
  const menuKeys = [['ArrowDown', 'Action 2'], ['End', 'Action 4'], ['ArrowDown', 'Action 1'], ['ArrowUp', 'Action 4'], ['Home', 'Action 1']];
  const menuSeq = [];
  for (const [key, want] of menuKeys) {
    await page.keyboard.press(key);
    a = await activeInfo(page);
    menuSeq.push({ key, want, got: a && a.text });
  }
  check('arrow keys, Home and End move through the menu items', menuSeq.every((s) => s.got === s.want), menuSeq);
  await page.keyboard.press('Escape');
  m = await menuState();
  a = await activeInfo(page);
  check('Escape closes the menu and returns focus to the button', m.expanded === 'false' && !m.menuVisible && a.id === 'menubutton1', { m, a });
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Tab');
  m = await menuState();
  a = await activeInfo(page);
  check('Tab from an open menu closes it and moves to the next field', !m.menuVisible && m.expanded === 'false' && a.id === 'action_output', { m, a });
  await page.focus('#menubutton1');
  await page.keyboard.press('Enter');
  await page.keyboard.press('ArrowDown');
  await page.keyboard.press('Enter');
  m = await menuState();
  a = await activeInfo(page);
  check('Enter on a menu item runs it, closes the menu and returns focus', m.output === 'Action 2' && !m.menuVisible && a.id === 'menubutton1', { m, a });

  // 5. Form
  await page.goto(url, { waitUntil: 'load' });
  const formState = () =>
    page.evaluate(() => {
      const msg = document.getElementById('email_error');
      return {
        invalid: document.getElementById('email').getAttribute('aria-invalid'),
        message: msg.textContent,
        messageVisible: msg.getBoundingClientRect().height > 0,
        status: document.getElementById('signup_status').textContent,
      };
    });
  await page.getByRole('button', { name: 'Submit' }).focus();
  await page.keyboard.press('Enter');
  let f = await formState();
  a = await activeInfo(page);
  check('submitting with the required field empty shows an error and focuses the field', f.invalid === 'true' && f.message && f.messageVisible && a.id === 'email', { f, a });
  let emailAx = await axNode(page, '#email');
  check(
    'field in error exposes "Error:" name, the message as description, invalid and required',
    emailAx.name.startsWith('Error:') && emailAx.description === f.message && emailAx.invalid === 'true' && emailAx.required === 'true',
    emailAx
  );
  await runAxe(page, 'form error');
  await page.fill('#email', 'not-an-email');
  await page.keyboard.press('Enter');
  f = await formState();
  check('a badly formatted email shows a format error', f.invalid === 'true' && /format/.test(f.message), f);
  await page.fill('#email', 'person@example.com');
  await page.keyboard.press('Enter');
  f = await formState();
  emailAx = await axNode(page, '#email');
  check('a valid email clears the error and shows a status message', f.invalid === null && f.message === '' && f.status !== '' && emailAx.name === 'Email (required):', { f, emailAx });
  await runAxe(page, 'form submitted');

  // 6. Tabs
  await page.goto(url, { waitUntil: 'load' });
  const tabState = () =>
    page.evaluate(() => ({
      active: document.activeElement.id,
      selected: Array.from(document.querySelectorAll('[role=tab]')).filter((t) => t.getAttribute('aria-selected') === 'true').map((t) => t.id),
      panels: Array.from(document.querySelectorAll('[role=tabpanel]')).filter((p) => getComputedStyle(p).display !== 'none').map((p) => p.id),
    }));
  await page.focus('#tab-1');
  const tabKeys = [['ArrowRight', 'tab-2'], ['ArrowRight', 'tab-3'], ['ArrowLeft', 'tab-2'], ['End', 'tab-4'], ['ArrowRight', 'tab-1'], ['ArrowLeft', 'tab-4'], ['Home', 'tab-1']];
  const tabSeq = [];
  for (const [key, want] of tabKeys) {
    await page.keyboard.press(key);
    tabSeq.push({ key, want, ...(await tabState()) });
  }
  check(
    'arrow keys, Home and End select tabs and show their panels',
    tabSeq.every((s) => s.active === s.want && s.selected.join() === s.want && s.panels.join() === s.want.replace('tab', 'tabpanel')),
    tabSeq
  );
  await page.keyboard.press('End');
  await page.keyboard.press('Tab');
  a = await activeInfo(page);
  check('Tab from the tab list moves to the visible panel', a.id === 'tabpanel-4', a);
  await runAxe(page, 'last tab selected');

  // 7. Switch
  await page.focus('[role=switch]');
  await page.keyboard.press('Space');
  const on = await page.getAttribute('[role=switch]', 'aria-checked');
  await page.keyboard.press('Enter');
  const off = await page.getAttribute('[role=switch]', 'aria-checked');
  check('Space and Enter toggle the switch', on === 'true' && off === 'false', { on, off });
  await page.keyboard.press('Space');
  await runAxe(page, 'switch on');

  // 8. Narrow screen: 320 CSS px wide, the WCAG reflow width
  const narrow = await browser.newContext({ extraHTTPHeaders: bypassHeaders, viewport: { width: 320, height: 900 } });
  const np = await narrow.newPage();
  await np.goto(url, { waitUntil: 'load' });
  const n = await np.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clippedTabs: Array.from(document.querySelectorAll('[role=tab]')).filter((t) => t.scrollWidth > t.clientWidth + 1).map((t) => t.id),
  }));
  check('no horizontal scrolling at 320px wide', n.scrollWidth <= 320, n);
  check('no clipped tab labels at 320px wide', n.clippedTabs.length === 0, n);
  await runAxe(np, 'narrow 320px');
  await np.getByRole('button', { name: 'Add Delivery Address' }).focus();
  await np.keyboard.press('Enter');
  const nd = await np.evaluate(() => ({ scrollWidth: document.querySelector('.dialog-backdrop').scrollWidth }));
  check('open dialog fits at 320px wide', nd.scrollWidth <= 320, nd);
  await runAxe(np, 'narrow 320px dialog open');

  check('no page errors or failed requests', problems.length === 0, problems);

  console.log('\nResults:');
  for (const r of results) {
    console.log(`${r.ok ? 'PASS' : 'FAIL'}  ${r.name}${r.ok ? '' : '\n      ' + JSON.stringify(r.detail)}`);
  }
  console.log(`\naxe "needs review" items (${reviews.length}):`);
  for (const x of reviews) console.log('  ' + x);
  const failed = results.filter((r) => !r.ok).length;
  console.log(`\n${results.length - failed} passed, ${failed} failed`);
  await browser.close();
  process.exit(failed ? 1 : 0);
})().catch((e) => {
  console.error(e);
  process.exit(2);
});
