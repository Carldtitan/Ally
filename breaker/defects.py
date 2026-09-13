"""The fifteen planted defects: five criteria, three instances each.

Each instance sits on its own element, so no element carries two defects, and
one criterion per page, so defects cannot interfere with each other.

Two fixture-design rules learned the hard way, both from the TypeSafe gate
failure. The lesson there was that a fixture is worthless when the defect is
indistinguishable from correct behaviour in the evidence we collect.

  * **Never plant a keyboard trap on a modal dialog.** An ARIA modal dialog is
    *supposed* to cycle Tab within itself. A Tab-swallowing handler there is
    indistinguishable from the correct pattern, so it would test nothing. The
    three 2.1.2 instances go on a menu, a tablist and a text input, none of
    which may legitimately hold focus.
  * **Never break a control that a state reach depends on** in a way that stops
    the reach working. The 2.1.1 instances turn buttons into divs but keep the
    click handler, so `.click()` still opens the dialog and the state is still
    reachable. The defect is the lost focusability, not lost function.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Defect:
    """One planted instance. The manifest row the scorer reads."""

    criterion: str
    instance: int
    #: Where on the page, for the write-up and for the scorer's "did it find
    #: the second and third occurrence" question.
    region: str
    #: The state the Tab run must be in for this defect to be observable.
    state: str
    #: A CSS selector identifying the damaged element on the broken page.
    selector: str
    #: One sentence, in the terms the checker would use.
    expect: str
    #: Literal find/replace pairs applied to index.html.
    replacements: tuple[tuple[str, str], ...] = ()
    #: CSS appended inside a <style> block.
    css: str = ""
    #: JavaScript appended inside a <script> block at end of body.
    js: str = ""
    #: HTML appended just before </body>.
    html: str = ""


# --------------------------------------------------------------------------
# 2.1.1 Keyboard - three divs acting as buttons.
# Clickable, not focusable. Click behaviour is preserved deliberately so the
# dialog state stays reachable; what is lost is the keyboard.
# --------------------------------------------------------------------------
KEYBOARD = [
    Defect(
        criterion="2.1.1", instance=1, region="header, delivery section",
        state="loaded", selector="#ally-d1",
        expect="a div with a click handler, no tabindex and no interactive role, "
               "so Tab never reaches it",
        replacements=((
            '<button type="button" onclick="openDialog(\'dialog1\', this)">Add Delivery Address</button>',
            '<div id="ally-d1" class="fake-btn" onclick="openDialog(\'dialog1\', this)">Add Delivery Address</div>',
        ),),
    ),
    Defect(
        criterion="2.1.1", instance=2, region="signup form",
        state="loaded", selector="#ally-d2",
        expect="the form's submit control is a div, unreachable by keyboard",
        replacements=((
            '<button type="submit">Submit</button>',
            '<div id="ally-d2" class="fake-btn" onclick="document.getElementById(\'signup\')'
            '.dispatchEvent(new Event(\'submit\', {cancelable: true, bubbles: true}))">Submit</div>',
        ),),
    ),
    Defect(
        criterion="2.1.1", instance=3, region="preferences, page foot",
        state="loaded", selector='[role="switch"]',
        expect="the switch keeps its role and its click handler but loses tabindex, "
               "so it is announced but never reached",
        replacements=((
            '<div role="switch" aria-checked="false" tabindex="0">',
            '<div role="switch" aria-checked="false">',
        ),),
    ),
]

# --------------------------------------------------------------------------
# 2.1.2 No Keyboard Trap - three Tab-swallowing handlers.
# Deliberately NOT on the modal dialog: a modal is supposed to cycle Tab.
# --------------------------------------------------------------------------
TRAP = [
    Defect(
        criterion="2.1.2", instance=1, region="actions menu",
        state="menu-open", selector="#menu1",
        expect="Tab is swallowed inside the open menu, so focus repeats on the "
               "same menu item instead of leaving",
        js="document.getElementById('menu1').addEventListener('keydown', function (e) {\n"
           "  if (e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); }\n"
           "}, true);",
    ),
    Defect(
        criterion="2.1.2", instance=2, region="composers tablist",
        state="tabs-focused", selector='[role="tablist"]',
        expect="Tab is swallowed in the tablist, so focus never moves on to the "
               "tab panel",
        js="document.querySelector('[role=\"tablist\"]').addEventListener('keydown', function (e) {\n"
           "  if (e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); }\n"
           "}, true);",
    ),
    Defect(
        criterion="2.1.2", instance=3, region="signup form, email field",
        state="loaded", selector="#email",
        expect="Tab is swallowed on the email input, so focus stays on it",
        js="document.getElementById('email').addEventListener('keydown', function (e) {\n"
           "  if (e.key === 'Tab') { e.preventDefault(); e.stopPropagation(); }\n"
           "}, true);",
    ),
]

# --------------------------------------------------------------------------
# 2.4.3 Focus Order - three flex containers with reversed CSS order.
# Never a positive tabindex: axe's `tabindex` rule fires on that and the
# comparison claim stops being true.
# --------------------------------------------------------------------------
ORDER = [
    Defect(
        criterion="2.4.3", instance=1, region="signup form",
        state="loaded", selector="#email_item",
        expect="the email field is painted above the name field while DOM order "
               "still reaches name first, so tab order contradicts reading order",
        css="#signup { display: flex; flex-direction: column; }\n"
            "#email_item { order: -1; }",
    ),
    Defect(
        criterion="2.4.3", instance=2, region="delivery dialog footer",
        state="dialog-open", selector=".dialog_form_actions",
        expect="Add and Cancel are painted in the opposite order to the one Tab "
               "reaches them in",
        css=".dialog_form_actions { display: flex; flex-direction: row-reverse; "
            "justify-content: flex-end; }",
    ),
    Defect(
        criterion="2.4.3", instance=3, region="composers tablist",
        state="loaded", selector='[role="tablist"]',
        expect="the four tabs are painted right to left while Tab reaches them "
               "left to right",
        css='[role="tablist"] { display: flex; flex-direction: row-reverse; '
            "justify-content: flex-end; }",
    ),
]

# --------------------------------------------------------------------------
# 2.4.7 Focus Visible - outline removed on three controls.
# site.css sets `:focus { outline: 3px solid #0b5cad }` globally, so a more
# specific rule removing it leaves no visible indicator at all.
# --------------------------------------------------------------------------
VISIBLE = [
    Defect(
        criterion="2.4.7", instance=1, region="signup form, name field",
        state="loaded", selector="#full_name",
        expect="nothing on screen changes when focus lands on the name field",
        css="#full_name:focus { outline: none !important; }",
    ),
    Defect(
        criterion="2.4.7", instance=2, region="delivery dialog, city field",
        state="dialog-open", selector=".city_input",
        expect="nothing on screen changes when focus lands on the city field",
        css=".city_input:focus { outline: none !important; }",
    ),
    Defect(
        criterion="2.4.7", instance=3, region="preferences, page foot",
        state="loaded", selector='[role="switch"]',
        expect="nothing on screen changes when focus lands on the switch",
        # The switch's indicator is NOT an outline. switch.css already sets
        # outline:none on :focus and signals focus with padding, border-width
        # and two background colours instead. `outline: none` here was a no-op,
        # which is why the first fixture check passed while the defect was
        # absent. Every focused property is pinned back to its unfocused value.
        css=(
            '[role="switch"]:focus {\n'
            "  padding: 4px 4px 8px 8px !important;   /* base is 4px 4px 8px 8px */\n"
            "  border-width: 0 !important;            /* base is 0 */\n"
            "  background-color: transparent !important;\n"
            "  outline: none !important;\n"
            "}\n"
            '[role="switch"]:focus span.switch { background-color: transparent !important; }'
        ),
    ),
]

# --------------------------------------------------------------------------
# 2.4.11 Focus Not Obscured - three sticky elements drawn over controls.
# --------------------------------------------------------------------------
OBSCURED = [
    Defect(
        criterion="2.4.11", instance=1, region="page foot",
        state="loaded", selector="#ally-cover-1",
        expect="a fixed bar at the foot of the viewport covers the switch when "
               "focus lands on it",
        css="#ally-cover-1 { position: fixed; left: 0; right: 0; bottom: 0; "
            "height: 120px; background: #23150f; color: #fff; z-index: 9000; "
            "padding: 10px 16px; }",
        html='<div id="ally-cover-1">Cookie preferences</div>',
    ),
    Defect(
        criterion="2.4.11", instance=2, region="page head",
        state="loaded", selector="#ally-cover-2",
        expect="a fixed banner at the top of the viewport covers the delivery "
               "button when focus lands on it",
        css="#ally-cover-2 { position: fixed; left: 0; right: 0; top: 0; "
            "height: 210px; background: #b85632; color: #fff; z-index: 9000; "
            "padding: 10px 16px; }",
        html='<div id="ally-cover-2">Announcement</div>',
    ),
    Defect(
        criterion="2.4.11", instance=3, region="signup form",
        state="loaded", selector="#ally-cover-3",
        expect="a fixed panel covers the submit control when focus lands on it",
        css="#ally-cover-3 { position: fixed; left: 0; width: 640px; top: 520px; "
            "height: 110px; background: #3f765c; color: #fff; z-index: 9000; "
            "padding: 10px 16px; }",
        html='<div id="ally-cover-3">Live chat</div>',
    ),
]

PAGES: dict[str, list[Defect]] = {
    "2-1-1": KEYBOARD,
    "2-1-2": TRAP,
    "2-4-3": ORDER,
    "2-4-7": VISIBLE,
    "2-4-11": OBSCURED,
}

#: Shared styling for the div-as-button instances, so they look like the
#: buttons they replaced. A defect the eye can spot is not the defect we mean.
FAKE_BUTTON_CSS = """
.fake-btn {
  display: inline-block;
  font: inherit;
  padding: 1px 7px;
  border: 1px solid #767676;
  border-radius: 3px;
  background: #efefef;
  cursor: pointer;
}
"""
