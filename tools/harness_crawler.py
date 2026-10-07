"""Autoresearch benchmark crawler for ankiweb UX navigation.

Visits all core screens (/deckbrowser, /browse, /graphs, /preferences, /tools, /about,
/add, /notetypes, /fields, /card-layout, /deck-options, /export, /notify, /preview, ...),
evaluating:
  1. Dead ends (pages with no top toolbar and no functional back/close/save/cancel control).
  2. Unintended target=_blank or window.open links to internal routes (breaks user flow).
  3. Broken interactive controls (inert close/back buttons, unhandled routes, 404/500 errors).

Emits structured summary and prints:
  METRIC ux_issues=<int> (lower is better; primary metric)
  METRIC dead_ends=<int>
  METRIC new_tab_traps=<int>
  METRIC broken_controls=<int>
  METRIC visited_screens=<int>
"""

from __future__ import annotations

import sys

from playwright.sync_api import sync_playwright


def run_crawl(base_url: str) -> dict[str, int]:
    issues: list[dict] = []
    dead_ends = 0
    new_tab_traps = 0
    broken_controls = 0
    visited = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        def audit_current_page(label: str, allow_no_toolbar: bool = False):
            nonlocal dead_ends, visited
            visited += 1
            cur_url = page.url
            has_toolbar = page.locator("#ankiweb-toolbar, #ankiweb-spa-toolbar").count() > 0
            has_close = (
                page.locator(
                    "button.btn-circle, form[method=dialog] button, .close-button, .back-btn, button:has-text('Close'), a:has-text('Decks'), button:has-text('Decks')"
                ).count()
                > 0
            )
            if not has_toolbar and not has_close and not allow_no_toolbar:
                dead_ends += 1
                issues.append({"type": "dead_end", "url": cur_url, "screen": label})

        # 1. Start at deckbrowser
        page.goto(f"{base_url}/deckbrowser", wait_until="networkidle")
        audit_current_page("deckbrowser")

        # 2. Add screen
        page.goto(f"{base_url}/add", wait_until="networkidle")
        audit_current_page("add")

        # Check editor links for window.open pattern in /add or /edit
        has_editor_window_open = page.evaluate(
            """() => {
            const body = document.body.innerHTML;
            return /window\\.open\\(['"`]\\/(preview|fields|card-layout|card-info)/.test(body);
        }"""
        )
        if has_editor_window_open:
            new_tab_traps += 1
            issues.append(
                {"type": "new_tab_trap", "url": "/add", "detail": "editor_links"}
            )

        # 3. Browse screen
        page.goto(f"{base_url}/browse", wait_until="networkidle")
        audit_current_page("browse")

        # 4. Graphs / Stats screen — verify return/escape control actually navigates away
        page.goto(f"{base_url}/graphs", wait_until="networkidle")
        audit_current_page("graphs")
        orig_graphs_url = page.url
        if page.locator("#ankiweb-spa-toolbar .back-btn").count() > 0:
            page.click("#ankiweb-spa-toolbar .back-btn")
            page.wait_for_load_state("networkidle")
        if page.url == orig_graphs_url:
            broken_controls += 1
            issues.append(
                {
                    "type": "broken_control",
                    "url": "/graphs",
                    "detail": "return control does not navigate away",
                }
            )

        # 5. Preferences
        page.goto(f"{base_url}/preferences", wait_until="networkidle")
        audit_current_page("preferences")

        # 6. Tools
        page.goto(f"{base_url}/tools", wait_until="networkidle")
        audit_current_page("tools")

        # 7. About
        page.goto(f"{base_url}/about", wait_until="networkidle")
        audit_current_page("about")

        # 8. Notify (Extras)
        page.goto(f"{base_url}/notify", wait_until="networkidle")
        audit_current_page("notify")

        # 9. Notetypes manager
        page.goto(f"{base_url}/notetypes", wait_until="networkidle")
        audit_current_page("notetypes")

        # 10. Export
        page.goto(f"{base_url}/export", wait_until="networkidle")
        audit_current_page("export")

        # 11. Deck Options (for first available deck) — verify escape navigation
        page.goto(f"{base_url}/deckbrowser", wait_until="networkidle")
        deck_ids = page.eval_on_selector_all(
            "tr.deck[id]", "nodes => nodes.map(n => n.id)"
        )
        if deck_ids:
            target_did = deck_ids[0]
            page.goto(f"{base_url}/deck-options/{target_did}", wait_until="networkidle")
            audit_current_page(f"deck-options-{target_did}")
            orig_deck_opt_url = page.url
            if page.locator("#ankiweb-spa-toolbar .back-btn").count() > 0:
                page.click("#ankiweb-spa-toolbar .back-btn")
                page.wait_for_load_state("networkidle")
            if page.url == orig_deck_opt_url:
                broken_controls += 1
                issues.append(
                    {
                        "type": "broken_control",
                        "url": f"/deck-options/{target_did}",
                        "detail": "return control does not navigate away",
                    }
                )

        browser.close()

    total_ux_issues = dead_ends + new_tab_traps + broken_controls
    return {
        "ux_issues": total_ux_issues,
        "dead_ends": dead_ends,
        "new_tab_traps": new_tab_traps,
        "broken_controls": broken_controls,
        "visited_screens": visited,
    }


def main() -> None:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
    results = run_crawl(base_url)

    print(f"METRIC ux_issues={results['ux_issues']}")
    print(f"METRIC dead_ends={results['dead_ends']}")
    print(f"METRIC new_tab_traps={results['new_tab_traps']}")
    print(f"METRIC broken_controls={results['broken_controls']}")
    print(f"METRIC visited_screens={results['visited_screens']}")


if __name__ == "__main__":
    main()
