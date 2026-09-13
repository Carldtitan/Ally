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


def build_runner(url: str, state: str, max_tabs: int = 40,
                 pair_capture: bool = True, shots: bool = True,
                 no_exclusions: bool = False) -> str:
    """The Python script that runs inside the sandbox against CDP.

    `no_exclusions` keeps every element the scan would have skipped, still
    recording why it would have been skipped. It exists so the cost of an
    exclusion can be measured against the fifteen defects rather than argued
    about: run both ways and compare recall.
    """
    spec = STATES[state]
    return (RUNNER
            .replace("__URL__", json.dumps(url))
            .replace("__STATE__", json.dumps(state))
            .replace("__REACH__", json.dumps(spec["reach"]))
            .replace("__ASSERT__", json.dumps(spec["assert"]))
            .replace("__EXPECT_CHANGE__", "True" if spec["expect_change"] else "False")
            .replace("__MAX_TABS__", str(max_tabs))
            .replace("__PAIR_CAPTURE__", "True" if pair_capture else "False")
            .replace("__SHOTS__", "True" if shots else "False")
            .replace("__NO_EXCLUSIONS__", "True" if no_exclusions else "False"))


# The selector helper, shared by every snippet below. Prefers an id, falls back
# to a parent-scoped nth-of-type, so a selector still identifies one element on
# a page where nothing has an id.
SELECTOR_FN = """
// What this element IS, in the vocabulary a manifest uses, plus the same for
// every ancestor. `sel` above answers "how do I address this element"; this
// answers "is this the element the manifest meant", which is a different
// question and the one the scorer was getting wrong.
//
// The scorer compared the manifest's selector string against `sel`'s output as
// text. `sel` prefers an id and otherwise emits an ancestor path, so it never
// emits a class or an attribute selector, and `[role="switch"]` could not
// match `body>main>section:nth-of-type(5)>div` however the strings were sliced.
// Six of the fifteen defects were detected correctly and scored as misses for
// two days. Element identity is a DOM fact, so it is collected here rather
// than guessed at from a string later.
function anch(el) {
  function toks(n) {
    var out = [n.tagName.toLowerCase()];
    if (n.id) out.push('#' + n.id);
    var r = n.getAttribute && n.getAttribute('role');
    if (r) out.push('[role=' + r.trim().toLowerCase() + ']');
    if (n.classList) {
      for (var i = 0; i < n.classList.length; i++) out.push('.' + n.classList[i]);
    }
    return out;
  }
  var self = toks(el), within = [];
  for (var a = el.parentElement; a && a.nodeType === 1; a = a.parentElement) {
    if (a === document.body || a === document.documentElement) break;
    within = within.concat(toks(a));
  }
  // Deduplicated: an ancestor chain repeats tag names constantly.
  var seen = {}, w = [];
  for (var k = 0; k < within.length; k++) {
    if (!seen[within[k]]) { seen[within[k]] = 1; w.push(within[k]); }
  }
  return {self: self, within: w};
}

function sel(el) {
  // A full ancestor path, not just the element and its parent.
  //
  // A bare tag name collided: the delivery dialog holds several unlabelled
  // <input> elements, each the only input inside its own wrapper, so every one
  // of them produced the selector "input". Consecutive different inputs then
  // looked like the same element repeating, and 2.1.2 reported a keyboard trap
  // on a page with no defects in it.
  if (el.id) return '#' + el.id;
  var parts = [];
  for (var n = el; n && n.nodeType === 1 && n !== document.documentElement;
       n = n.parentElement) {
    if (n.id) { parts.unshift('#' + n.id); break; }
    var part = n.tagName.toLowerCase();
    var p = n.parentElement;
    if (p) {
      var same = Array.prototype.filter.call(p.children, function (c) {
        return c.tagName === n.tagName; });
      if (same.length > 1) {
        part += ':nth-of-type(' + (Array.prototype.indexOf.call(same, n) + 1) + ')';
      }
    }
    parts.unshift(part);
    if (parts.length >= 7) break;
  }
  return parts.join('>');
}
"""

RUNNER = r'''
import json, time, urllib.request
from websocket import create_connection

URL, STATE = __URL__, __STATE__
PAIR_CAPTURE = __PAIR_CAPTURE__
NO_EXCL = __NO_EXCLUSIONS__
SHOTS = __SHOTS__
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
# Tell the renderer the page is focused regardless of what the window manager
# thinks. Under Xvfb the Chromium window loses focus unpredictably, and a Tab
# dispatched at an unfocused page either does nothing or resumes from a stale
# position: three runs of the same page gave 11, 2 and 3 stops, one of them
# starting in the middle of the document. This is what
# Emulation.setFocusEmulationEnabled exists for.
send("Emulation.setFocusEmulationEnabled", {"enabled": True})
send("Page.bringToFront")
send("DOM.getDocument", {"depth": -1})
# A fresh document first. Chromium keeps the sequential focus navigation
# starting point across a same-tab navigation, so the Tab loop would otherwise
# begin wherever the previous page left focus. Three runs of the same page gave
# 5, 15 and 10 stops, starting at three different controls.
# document.body.focus() does not help: body is not focusable without a
# tabindex, so the call is a no-op and the starting point is untouched.
send("Page.navigate", {"url": "about:blank"}); time.sleep(1.0)
send("Page.navigate", {"url": URL})
# Wait for the document to actually be complete rather than sleeping a fixed
# guess: the page's scripts set tabindex values, so tabbing before they run
# reaches a different set of elements.
for _ in range(40):
    if val("document.readyState") == "complete":
        break
    time.sleep(0.25)
time.sleep(1.2)
send("Page.bringToFront")

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
  return {tag: e.tagName, selector: sel(e), anchors: anch(e),
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
    # The focused frame only. Nothing here touches focus.
    #
    # The unfocused reference used to be taken by blurring and refocusing right
    # here, and that perturbed the Tab sequence: three runs of the same page
    # gave 2, 6 and 11 stops, because a programmatic refocus does not always
    # restore the sequential focus navigation starting point. It is taken in a
    # second pass instead, after the sequence is complete, when perturbing
    # focus can no longer change what was recorded.
    info["png_focused"] = (send("Page.captureScreenshot", {"format": "png"})
                           .get("result", {}).get("data")) if SHOTS else None
    info["png_blurred"] = None
    info["index"] = index
    return info

stops, truncated = [], False
if reached:
    first = capture(0)
    if first:
        stops.append(first)
    # Seeded with stop 0: it is where focus sat on entry, so a later stop
    # matching it is the lap closing.
    seen = {(first["selector"], first["x"], first["y"])} if first else set()
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
        # Any repeat closes the lap, not only a return to the first stop.
        # Comparing against the first alone let a sequence that re-entered
        # the cycle at a different point run on to the cap.
        key = (s["selector"], s["x"], s["y"])
        if key in seen:
            hit_cap = False
            break
        seen.add(key)
    truncated = hit_cap

# The 2.1.1 element scan runs AFTER the Tab loop, not before it.
# It is hundreds of CDP round trips -- a getProperties over every element,
# then getEventListeners and callFunctionOn per element -- and running it
# first left the Tab sequence non-deterministic: the same page recorded
# 11, 10 and 3 stops across three runs. The DOM it inspects is the same
# either way, so nothing is lost by doing it once the sequence is safely
# recorded.


# ---- 2.1.1 candidates, sources one and two -------------------------------
CANDIDATES = """
(function () {
  var out = [], ex = [];
  var NO_EXCLUSIONS = __NO_EXCLUSIONS__;
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
    // Every exclusion is recorded with its reason. Turning one off is a
    // one-line experiment; not knowing it fired is how the switch and the
    // tablist went missing for a whole baseline.
    var mw = managedByWidget(el), ic = insideAControl(el);
    if (mw || ic) {
      ex.push({selector: sel(el), tag: el.tagName, role: el.getAttribute('role'),
        rule: mw ? 'managed' : 'inside-control',
        reason: mw ? 'roving tabindex or a role a composite widget manages'
                   : 'inside a larger control, not separately reachable',
        source: source});
      if (!NO_EXCLUSIONS) return;
    }
    var s = sel(el);
    var hit = null;
    for (var k = 0; k < out.length; k++) if (out[k].selector === s) hit = out[k];
    if (hit) { if (hit.sources.indexOf(source) < 0) hit.sources.push(source); return; }
    var r = el.getBoundingClientRect();
    out.push({selector: s, tag: el.tagName, role: el.getAttribute('role'),
      anchors: anch(el),
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
  return {items: out, excluded: ex};
})()
""".replace("__SELFN__", SELFN)

scan = val(CANDIDATES) or {}
if not isinstance(scan, dict):
    scan = {}
cands = scan.get("items") or []
excluded = scan.get("excluded") or []

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
        anchors: anch(this),
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
            excluded.append({"selector": info.get("selector", ""), "tag": info.get("tag", ""),
                             "role": info.get("role"),
                             "rule": "managed" if info.get("managed") else "inside-control",
                             "reason": "roving tabindex or a role a composite widget manages"
                                       if info.get("managed") else
                                       "inside a larger control, not separately reachable",
                             "source": "listeners"})
            if not NO_EXCL:
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
# The third exclusion, and it was the least visible of the three: it silently
# removed whole elements after the scan had already accepted them.
kept = []
for c in cands:
    if c.get("childCount", 0) > 0 and not c.get("ownText") and not NO_EXCL:
        excluded.append({"selector": c["selector"], "tag": c["tag"], "role": c.get("role"),
                         "rule": "delegating-container",
                         "reason": "%d focusable descendant(s) and no text of its own"
                                   % c.get("childCount", 0),
                         "source": ",".join(c.get("sources") or [])})
    else:
        kept.append(c)
cands = kept


# ---- second pass: the unfocused reference frames -----------------------
# The Tab sequence is finished, so focus can be moved freely now. Each stop
# is revisited at ITS OWN scroll offset, recoverable as (document - viewport),
# so the two frames being compared show the same region of the page and the
# only difference is the focus indicator.
if PAIR_CAPTURE and SHOTS:
    ev("(function(){var a=document.activeElement; if(a&&a.blur) a.blur(); "
       "return 1;})()")
    time.sleep(0.3)
    for st in stops:
        if st["index"] == 0 or st["tag"] == "BODY":
            continue
        sx = st["x"] - st["vx"]
        sy = st["y"] - st["vy"]
        ev("window.scrollTo(%d, %d)" % (sx, sy))
        time.sleep(0.16)
        st["png_blurred"] = send("Page.captureScreenshot", {"format": "png"})                 .get("result", {}).get("data")

print("RESULT " + json.dumps({
    "url": URL, "state": STATE, "state_reached": bool(reached), "reach_note": note,
    "stops": stops, "candidates": cands, "excluded": excluded,
    "truncated": truncated,
    "page_height": val("document.documentElement.scrollHeight") or 0,
}))
ws.close()
'''.replace("__SELECTOR_FN__", SELECTOR_FN)
