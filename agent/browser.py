"""The recorder: drives a browser in a Daytona sandbox and produces a Recording.

Six things it does that are easy to get wrong, every one of them measured:

  * **Accessible names come from the accessibility tree**, via
    `Accessibility.getPartialAXTree` with an `objectId`. Reading
    `innerText || value || aria-label` off the element disagreed with the tree
    on 7 of 10 stops on the clean app: labelled inputs came back empty and a
    switch returned its value, "none", as its name.
  * **Coordinates are document coordinates**, x + scrollX. The page scrolls as
    focus moves, so viewport y is non-monotonic and reading order derived from
    it is wrong.
  * **The reach step is asserted.** A state whose DOM did not change was not
    entered, and every criterion for it becomes not_evaluated with that reason
    rather than being judged against the wrong page.
  * **Stop 0 is captured before the first Tab.**
  * **Obscuring is decided by elementFromPoint** at the focused element's own
    centre, not by comparing rectangles: the renderer already knows about
    stacking contexts.
  * **Delegating containers are excluded** from the candidate list. A React
    root carries 131 listeners including click and is not focusable, so a naive
    rule flags it on every page.

Chromium needs `--remote-allow-origins=*` or the CDP websocket handshake is
refused with 403 even from 127.0.0.1. The screenshot field is `.screenshot`,
base64, not `.data`.
"""

from __future__ import annotations

import json

CHROME_FLAGS = (
    "--no-sandbox --disable-dev-shm-usage --disable-gpu --no-first-run "
    "--remote-debugging-port=9222 --remote-allow-origins=* "
    "--window-size=1024,740 --hide-scrollbars"
)

#: How to reach each state, and how to prove it was reached. The assertion is
#: read before and after the reach step; the state counts as entered only when
#: it changed.
STATES: dict[str, dict[str, object]] = {
    "loaded": {
        "reach": "",
        "assert": "document.readyState",
        "expect_change": False,
    },
    "dialog-open": {
        "reach": "(document.querySelector(\"[onclick*='openDialog']\")"
                 " || document.getElementById('ally-d1')).click()",
        "assert": "!document.getElementById('dialog1').classList.contains('hidden')",
        "expect_change": True,
    },
    "menu-open": {
        "reach": "document.getElementById('menubutton1').click()",
        "assert": "document.getElementById('menubutton1').getAttribute('aria-expanded')",
        "expect_change": True,
    },
    "tabs-focused": {
        "reach": "document.getElementById('tab-1').focus()",
        "assert": "document.activeElement.id",
        "expect_change": True,
    },
}


def build_runner(url: str, state: str, max_tabs: int = 40) -> str:
    """The Python script that runs inside the sandbox against CDP."""
    spec = STATES[state]
    return (RUNNER
            .replace("__URL__", json.dumps(url))
            .replace("__STATE__", json.dumps(state))
            .replace("__REACH__", json.dumps(spec["reach"]))
            .replace("__ASSERT__", json.dumps(spec["assert"]))
            .replace("__EXPECT_CHANGE__", "True" if spec["expect_change"] else "False")
            .replace("__MAX_TABS__", str(max_tabs)))


# The selector helper, shared by every snippet below. Prefers an id, falls back
# to a parent-scoped nth-of-type, so a selector still identifies one element on
# a page where nothing has an id.
SELECTOR_FN = """
function sel(el) {
  if (el.id) return '#' + el.id;
  var p = el.tagName.toLowerCase(), n = el.parentNode;
  if (!n || !n.children) return p;
  var same = Array.prototype.filter.call(n.children, function (c) { return c.tagName === el.tagName; });
  var i = Array.prototype.indexOf.call(same, el);
  var base = (n.id ? '#' + n.id + ' > ' : '') + p;
  return same.length > 1 ? base + ':nth-of-type(' + (i + 1) + ')' : base;
}
"""

RUNNER = r'''
import json, time, urllib.request
from websocket import create_connection

URL, STATE = __URL__, __STATE__
REACH, ASSERTION = __REACH__, __ASSERT__
EXPECT_CHANGE, MAX_TABS = __EXPECT_CHANGE__, __MAX_TABS__

tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9222/json"))
page = next(t for t in tabs if t["type"] == "page")
ws = create_connection(page["webSocketDebuggerUrl"], timeout=60, max_size=60000000)
mid = 0

def send(m, p=None):
    global mid
    mid += 1
    ws.send(json.dumps({"id": mid, "method": m, "params": p or {}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == mid:
            return r

def ev(expr, by_value=True):
    r = send("Runtime.evaluate", {"expression": expr, "returnByValue": by_value})
    return r.get("result", {}).get("result", {})

def val(expr):
    return ev("(function(){try{return (" + expr + ");}catch(e){return '__err:'+e.message;}})()").get("value")

send("DOM.enable"); send("Accessibility.enable"); send("Page.enable")
send("DOM.getDocument", {"depth": -1})
send("Page.navigate", {"url": URL}); time.sleep(4)

# ---- reach the state, then assert the DOM actually changed ---------------
before = val(ASSERTION)
if REACH:
    ev(REACH); time.sleep(1.2)
after = val(ASSERTION)
if EXPECT_CHANGE:
    reached = (before != after)
    if reached:
        note = "%s changed from %r to %r" % (ASSERTION[:50], before, after)
    else:
        note = "%s did not change (still %r) after the reach step" % (ASSERTION[:50], before)
else:
    reached = (after == "complete")
    note = "document.readyState is %r" % after

SELFN = """__SELECTOR_FN__"""

# ---- 2.1.1 candidates, sources one and two -------------------------------
CANDIDATES = """
(function () {
  var out = [];
  __SELFN__
  // Roles a composite widget manages with arrow keys and a roving tabindex.
  // Exactly one child is focusable at a time and the rest carry tabindex="-1"
  // on purpose, so flagging them as unreachable is a false positive. The ARIA
  // Authoring Practices patterns our control page is built from all do this.
  var COMPOSITE = ['menu','menubar','tablist','listbox','tree','treegrid',
                   'grid','radiogroup','toolbar','combobox'];
  var MANAGED = ['menuitem','menuitemradio','menuitemcheckbox','tab','option',
                 'treeitem','row','gridcell','radio'];
  function managedByWidget(el) {
    var role = (el.getAttribute('role') || '').toLowerCase();
    if (MANAGED.indexOf(role) >= 0) return true;
    // an explicit tabindex="-1" inside a composite is the roving pattern
    if (el.getAttribute('tabindex') === '-1') {
      for (var n = el.parentElement; n; n = n.parentElement) {
        var r = (n.getAttribute('role') || '').toLowerCase();
        if (COMPOSITE.indexOf(r) >= 0) return true;
      }
    }
    return false;
  }
  // Part of a bigger control rather than a control: a span inside a button
  // inherits cursor:pointer and is not separately reachable, nor should it be.
  function insideAControl(el) {
    for (var n = el.parentElement; n; n = n.parentElement) {
      if (n.tabIndex >= 0) return true;
      var r = (n.getAttribute('role') || '').toLowerCase();
      if (MANAGED.indexOf(r) >= 0 || n.tagName === 'BUTTON' || n.tagName === 'A') return true;
    }
    return false;
  }

  function add(el, source) {
    if (!el || el.nodeType !== 1) return;
    if (el === document.body || el === document.documentElement) return;
    if (managedByWidget(el) || insideAControl(el)) return;
    var s = sel(el);
    var hit = null;
    for (var k = 0; k < out.length; k++) if (out[k].selector === s) hit = out[k];
    if (hit) { if (hit.sources.indexOf(source) < 0) hit.sources.push(source); return; }
    var r = el.getBoundingClientRect();
    out.push({selector: s, tag: el.tagName, role: el.getAttribute('role'),
      name: (el.getAttribute('aria-label') || el.innerText || '').trim().slice(0, 60),
      x: Math.round(r.x + window.scrollX), y: Math.round(r.y + window.scrollY),
      w: Math.round(r.width), h: Math.round(r.height),
      focusable: el.tabIndex >= 0, sources: [source],
      childCount: el.querySelectorAll('a,button,input,select,textarea,[tabindex],[role]').length,
      ownText: Array.prototype.filter.call(el.childNodes, function (n) {
          return n.nodeType === 3 && n.textContent.trim(); }).length > 0});
  }
  document.querySelectorAll('a[href],button,input,select,textarea,[role=button],[role=link],[role=switch],[role=menuitem],[role=tab],[tabindex]')
    .forEach(function (el) { add(el, 'tree'); });
  Array.prototype.forEach.call(document.querySelectorAll('*'), function (el) {
    if (el.tabIndex >= 0) return;
    var cs = getComputedStyle(el);
    if (el.hasAttribute('onclick') || cs.cursor === 'pointer') add(el, 'dom-query');
  });
  return out;
})()
""".replace("__SELFN__", SELFN)

cands = val(CANDIDATES) or []
if isinstance(cands, str):
    cands = []

# ---- source three: CDP listeners -----------------------------------------
DESCRIBE = """function(){
  var r = this.getBoundingClientRect();
  __SELFN__
  var COMPOSITE = ['menu','menubar','tablist','listbox','tree','treegrid','grid',
                   'radiogroup','toolbar','combobox'];
  var MANAGED = ['menuitem','menuitemradio','menuitemcheckbox','tab','option',
                 'treeitem','row','gridcell','radio'];
  var role0 = (this.getAttribute('role') || '').toLowerCase();
  var managed = MANAGED.indexOf(role0) >= 0;
  if (!managed && this.getAttribute('tabindex') === '-1') {
    for (var n = this.parentElement; n && !managed; n = n.parentElement) {
      var r2 = (n.getAttribute('role') || '').toLowerCase();
      if (COMPOSITE.indexOf(r2) >= 0) managed = true;
    }
  }
  var inside = false;
  for (var m = this.parentElement; m && !inside; m = m.parentElement) {
    var r3 = (m.getAttribute('role') || '').toLowerCase();
    if (m.tabIndex >= 0 || MANAGED.indexOf(r3) >= 0
        || m.tagName === 'BUTTON' || m.tagName === 'A') inside = true;
  }
  return {selector: sel(this), tag: this.tagName, role: this.getAttribute('role'),
    managed: managed, insideControl: inside,
    name: (this.getAttribute('aria-label') || this.innerText || '').trim().slice(0, 60),
    x: Math.round(r.x + window.scrollX), y: Math.round(r.y + window.scrollY),
    w: Math.round(r.width), h: Math.round(r.height),
    focusable: this.tabIndex >= 0,
    childCount: this.querySelectorAll('a,button,input,select,textarea,[tabindex],[role]').length,
    ownText: Array.prototype.filter.call(this.childNodes, function (n) {
        return n.nodeType === 3 && n.textContent.trim(); }).length > 0};
}""".replace("__SELFN__", SELFN)

arr = ev("Array.from(document.querySelectorAll('*'))", by_value=False)
if arr.get("objectId"):
    props = send("Runtime.getProperties", {"objectId": arr["objectId"], "ownProperties": True})
    for p in props.get("result", {}).get("result", []):
        if not p["name"].isdigit():
            continue
        oid = (p.get("value") or {}).get("objectId")
        if not oid:
            continue
        g = send("DOMDebugger.getEventListeners", {"objectId": oid})
        types = [l["type"] for l in g.get("result", {}).get("listeners", [])]
        if "click" not in types:
            continue
        d = send("Runtime.callFunctionOn", {"objectId": oid, "returnByValue": True,
                                            "functionDeclaration": DESCRIBE})
        info = d.get("result", {}).get("result", {}).get("value")
        if not info or info.get("tag") in ("BODY", "HTML"):
            continue
        # same exclusions as source two: a composite widget's roving-tabindex
        # children, and anything that is part of a larger control
        if info.get("managed") or info.get("insideControl"):
            continue
        hit = None
        for c in cands:
            if c["selector"] == info["selector"]:
                hit = c
        if hit:
            if "listeners" not in hit["sources"]:
                hit["sources"].append("listeners")
        else:
            info["sources"] = ["listeners"]
            cands.append(info)

# A delegating container has candidates inside it and no text of its own.
cands = [c for c in cands if not (c.get("childCount", 0) > 0 and not c.get("ownText"))]

# ---- the Tab loop, stop 0 first ------------------------------------------
STOP_JS = """
(function () {
  var e = document.activeElement;
  if (!e) return null;
  __SELFN__
  var r = e.getBoundingClientRect();
  var cx = r.left + r.width / 2, cy = r.top + r.height / 2, over = null;
  if (r.width > 0 && r.height > 0 && cx >= 0 && cy >= 0 && cx <= innerWidth && cy <= innerHeight) {
    var top = document.elementFromPoint(cx, cy);
    if (top && top !== e && !e.contains(top) && !top.contains(e)) over = sel(top);
  }
  return {tag: e.tagName, selector: sel(e),
    x: Math.round(r.x + window.scrollX), y: Math.round(r.y + window.scrollY),
    vx: Math.round(r.x), vy: Math.round(r.y),
    w: Math.round(r.width), h: Math.round(r.height), obscured_by: over};
})()
""".replace("__SELFN__", SELFN)

def ax(oid):
    a = send("Accessibility.getPartialAXTree", {"objectId": oid, "fetchRelatives": False})
    for nd in a.get("result", {}).get("nodes", []):
        if nd.get("ignored"):
            continue
        return ((nd.get("name") or {}).get("value"), (nd.get("role") or {}).get("value"))
    return (None, None)

def capture(index):
    info = val(STOP_JS)
    if not info or isinstance(info, str):
        return None
    h = ev("document.activeElement", by_value=False)
    if h.get("objectId"):
        info["name"], info["role"] = ax(h["objectId"])
    else:
        info["name"], info["role"] = None, None
    # Two frames at the SAME scroll position: the element focused, and the
    # same view with focus dropped. Comparing against the previous stop's
    # frame cannot work, because focus scrolls the page and the two crops then
    # show different content -- or the element was off-screen entirely in the
    # earlier frame and there was nothing to compare.
    info["png_focused"] = send("Page.captureScreenshot", {"format": "png"})         .get("result", {}).get("data")
    if index > 0 and info["tag"] != "BODY":
        ev("(function(){var a=document.activeElement;"
           "if(a&&a.blur){window.__allyRefocus=a; a.blur();} return 1;})()")
        time.sleep(0.18)
        info["png_blurred"] = send("Page.captureScreenshot", {"format": "png"})             .get("result", {}).get("data")
        # Put focus back so the Tab loop carries on from the right element.
        ev("(function(){var e=window.__allyRefocus; if(e&&e.focus) e.focus();"
           "return 1;})()")
        time.sleep(0.12)
    else:
        info["png_blurred"] = None
    info["index"] = index
    return info

stops, truncated = [], False
if reached:
    first = capture(0)
    if first:
        stops.append(first)
    seen = None
    hit_cap = True
    for i in range(1, MAX_TABS + 1):
        for ty in ("rawKeyDown", "keyUp"):
            send("Input.dispatchKeyEvent", {"type": ty, "code": "Tab", "key": "Tab",
                                            "windowsVirtualKeyCode": 9})
        time.sleep(0.26)
        s = capture(i)
        if not s:
            hit_cap = False
            break
        stops.append(s)
        if s["tag"] == "BODY":
            hit_cap = False
            break
        key = (s["selector"], s["x"], s["y"])
        if seen is None:
            seen = key
        elif key == seen:
            hit_cap = False
            break
    truncated = hit_cap

print("RESULT " + json.dumps({
    "url": URL, "state": STATE, "state_reached": bool(reached), "reach_note": note,
    "stops": stops, "candidates": cands, "truncated": truncated,
    "page_height": val("document.documentElement.scrollHeight") or 0,
}))
ws.close()
'''.replace("__SELECTOR_FN__", SELECTOR_FN)
