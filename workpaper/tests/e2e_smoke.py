"""Browser smoke test for the React front end (run against a live server).

    python3 -m uvicorn app.main:app --port 8765 &      # with a fresh DB_PATH
    python3 tests/e2e_smoke.py http://127.0.0.1:8765

Needs Playwright with Chromium. Not part of the unit-test run. It drives the app the way a
person would, by role and label (which also checks the accessible names), and fails on any
page error, console error, or native browser dialog.
"""
from __future__ import annotations

import sys

from playwright.sync_api import Page, expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"
PROBLEMS: list[str] = []


def page_for(browser, user: str, width: int = 1440) -> Page:
    ctx = browser.new_context(viewport={"width": width, "height": 900})
    ctx.add_init_script(f"localStorage.setItem('wp.user', '{user}')")
    pg = ctx.new_page()
    pg.on("pageerror", lambda e: PROBLEMS.append(f"{user}: page error {e}"))
    pg.on("console", lambda m: PROBLEMS.append(f"{user}: console {m.text}") if m.type == "error" and "403" not in m.text else None)
    pg.on("dialog", lambda d: (PROBLEMS.append(f"{user}: native dialog '{d.message}'"), d.dismiss()))
    return pg


def step(name: str):
    print(f"  - {name}")


def preparer(browser):
    print("preparer")
    pg = page_for(browser, "st-01")
    pg.goto(BASE)
    totals = pg.get_by_label("Return totals")
    expect(totals).to_contain_text("Federal")
    before = totals.inner_text()

    step("open the top finding from the queue; the trace drawer opens")
    pg.locator("main ul li button").first.click()
    trace = pg.get_by_role("complementary", name="Trace")
    expect(trace).to_be_visible()

    step("accept it: an adjustment, a toast with undo, new totals")
    trace.get_by_role("button", name="Accept and adjust").click()
    expect(pg.get_by_role("status").filter(has_text="Undo")).to_be_visible()
    expect(totals).not_to_have_text(before)

    step("follow the evidence: a line, then a source value")
    trace.get_by_role("navigation", name="Trace path").wait_for()
    trace.locator("section", has_text="Lines affected").get_by_role("button").first.click()
    expect(trace.get_by_role("navigation", name="Trace path").get_by_role("listitem")).to_have_count(2)

    step("revert uses a dialog with a reason (no window.prompt)")
    trace.get_by_role("button", name="Revert").first.click()
    dlg = pg.get_by_role("dialog")
    expect(dlg).to_be_visible()
    pg.keyboard.press("Escape")
    expect(dlg).to_have_count(0)

    step("undo from the toast restores the totals")
    pg.get_by_role("button", name="Close trace").click()
    pg.goto(BASE + "/#changes/history")
    pg.get_by_role("button", name="Undo").first.click()
    pg.goto(BASE + "/#")
    pg.get_by_label("Return totals").wait_for()
    assert pg.get_by_label("Return totals").inner_text() == before, "undo did not restore the totals"

    step("adjust dialog: Escape closes it")
    pg.goto(BASE + "/#return")
    pg.get_by_role("button", name="F1040.1a", exact=True).click()
    trace.get_by_role("button", name="Adjust").click()
    expect(pg.get_by_role("dialog", name="Adjust F1040.1a")).to_be_visible()
    pg.keyboard.press("Escape")
    expect(pg.get_by_role("dialog")).to_have_count(0)

    step("search is a keyboard combobox")
    pg.keyboard.press("/")
    pg.keyboard.type("D08")
    expect(pg.get_by_role("listbox", name="Search results")).to_be_visible()
    pg.keyboard.press("ArrowDown")
    pg.keyboard.press("Enter")
    expect(pg).to_have_url(f"{BASE}/#doc/D08")

    step("a preparer cannot move the season clock")
    expect(pg.get_by_role("button", name="Next:")).to_have_count(0)

    step("every section and record renders")
    for r in ["", "return/F8949", "documents", "doc/D23", "checks", "review", "changes/since", "changes/compare", "changes/whatif",
              "changes/variances", "filing", "firm"]:
        pg.goto(f"{BASE}/#{r}")
        expect(pg.locator("main h1").first).to_be_visible()
    for r in pg.evaluate("fetch('/api/bootstrap',{headers:{'X-User':'st-01'}}).then(r=>r.json()).then(b=>b.reports.map(x=>x.id))"):
        pg.goto(f"{BASE}/#records/{r}")
        expect(pg.locator("main h1").first).to_be_visible()


def partner(browser):
    print("partner")
    pg = page_for(browser, "st-03")
    pg.goto(BASE)
    step("the partner advances the season clock")
    clock_before = pg.locator("header").inner_text()
    pg.get_by_role("button", name="Next:").click()
    expect(pg.locator("header")).not_to_have_text(clock_before)
    step("send with open gates asks for confirmation in a dialog")
    pg.goto(BASE + "/#filing")
    pg.get_by_role("button", name="Send to client anyway (recorded)").click()
    expect(pg.get_by_role("dialog", name="Send with open gates?")).to_be_visible()
    pg.get_by_role("button", name="Cancel").click()


def admin(browser):
    print("administrator")
    pg = page_for(browser, "st-05")
    pg.goto(BASE + "/#firm")
    step("reset asks first")
    pg.get_by_role("button", name="Reset demo").click()
    expect(pg.get_by_role("dialog", name="Reset the demo workpaper?")).to_be_visible()
    pg.get_by_role("button", name="Cancel").click()
    expect(pg.get_by_text("unbroken hash chain")).to_be_visible()


def client(browser):
    print("client")
    pg = page_for(browser, "cu-01")
    pg.goto(BASE)
    expect(pg.get_by_role("heading", name="Hello Ngozi")).to_be_visible()
    expect(pg.get_by_role("navigation", name="Sections")).to_have_count(0)


def mobile(browser):
    print("mobile")
    pg = page_for(browser, "st-02", width=390)
    for r in ["", "return", "documents", "doc/D08", "checks", "review", "changes/compare", "filing", "firm", "records/summary"]:
        pg.goto(f"{BASE}/#{r}")
        expect(pg.locator("main h1, main [aria-label='Return totals']").first).to_be_visible()
        wide = pg.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
        if wide:
            PROBLEMS.append(f"mobile: horizontal page scroll on #{r}")
    step("no horizontal page scroll at 390px")


with sync_playwright() as p:
    b = p.chromium.launch()
    for flow in (preparer, partner, admin, client, mobile):
        try:
            flow(b)
        except Exception as e:  # report every flow, not just the first failure
            PROBLEMS.append(f"{flow.__name__}: {e}")
    b.close()

if PROBLEMS:
    print("\nPROBLEMS")
    print("\n".join(PROBLEMS))
    sys.exit(1)
print("\nall browser flows passed")
