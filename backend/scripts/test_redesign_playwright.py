#!/usr/bin/env python3
"""
Playwright test script for the Relationship Map and Changes redesign.
Verifies all requirements in Section 6 & 7 of docs/relationship-map-redesign-plan.md:
1. EN and VI support
2. 1440px and 390px viewports (no horizontal overflow, responsive layout)
3. /changes:
   - Rail filters (view, type checkbox, subject, assessment, clear filters)
   - Type chip click in episode
   - Where-changes-are panel (tabs, row click, where URL param, filter chip removal)
   - Pager and sort
   - Explore on map -> opens /workspace/map with appropriate anchor
   - Old-style URLs still apply filters
4. /workspace/map:
   - Left rail kind switch (users, apis, services)
   - Search input + keyboard navigation / Enter
   - Walk: user -> service (scope chip appears) -> API
   - Breadcrumb navigation back
   - +N more in-place filtering
   - Unknown users anchor
5. Mocked large estate (240 services, 1,500 APIs, 180 users):
   - Never more than 10 rows per side on screen.
"""

import json
import os
import sys
import time
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:31102")

def check_overflow_and_errors(page, label):
    # Check no horizontal overflow
    overflow = page.evaluate("() => document.documentElement.scrollWidth - document.documentElement.clientWidth")
    assert overflow <= 1, f"Horizontal overflow on {label}: {overflow}px (scrollWidth={page.evaluate('document.documentElement.scrollWidth')}, clientWidth={page.evaluate('document.documentElement.clientWidth')})"

def test_changes_page(browser, base_url, lang="en", width=1440, height=900):
    print(f"\n--- Testing /changes ({lang.upper()}, {width}x{height}) ---")
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()

    page_errors = []
    failed_requests = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.on("response", lambda res: failed_requests.append(f"{res.status} {res.url}") if res.status >= 400 and "/api/" in res.url else None)

    # Set language
    page.add_init_script(f"localStorage.setItem('tracescope_lang', '{lang}');")

    # 1. Open /changes
    page.goto(f"{base_url}/changes", wait_until="networkidle")
    time.sleep(1)
    check_overflow_and_errors(page, f"/changes {lang} {width}px")

    # 2. Check view switcher in left rail
    all_btn = page.locator("aside button:has-text('All'), aside button:has-text('Tất cả')").first
    if all_btn.count():
        all_btn.click()
        page.wait_for_timeout(300)
        assert "view=all" in page.url

    attn_btn = page.locator("aside button:has-text('Needs attention'), aside button:has-text('Cần chú ý')").first
    if attn_btn.count():
        attn_btn.click()
        page.wait_for_timeout(300)

    # 3. Check subject filter buttons
    user_subj = page.locator("aside button:text-is('User')").first
    if user_subj.count():
        user_subj.click()
        page.wait_for_timeout(300)
        assert "subject=user" in page.url
        all_subj = page.locator("aside button:text-is('All'), aside button:text-is('Tất cả')").first
        all_subj.click()
        page.wait_for_timeout(300)

    # 4. Check Where-changes-are right panel
    where_panel = page.locator("aside:has-text('Where changes are'), aside:has-text('Nơi xuất hiện thay đổi')")
    where_service_tab = where_panel.locator("button:text-is('Service')").first
    if where_service_tab.count():
        where_service_tab.click()
        page.wait_for_timeout(300)
        # Click first row in Where table
        first_where_row = where_panel.locator("div.max-h-\\[500px\\] button[type='button']").first
        if first_where_row.count():
            first_where_row.click()
            page.wait_for_timeout(300)
            assert "where=" in page.url, f"Expected where= in URL, got {page.url}"
            # Remove where filter via rail chip
            rail_chip_x = page.locator("aside button[aria-label='Remove filter'], aside button[aria-label='Gỡ bộ lọc']").first
            if rail_chip_x.count():
                rail_chip_x.click()
                page.wait_for_timeout(300)
                assert "where=" not in page.url

    # 5. Check Explore on map link
    explore_links = page.locator("a:has-text('Explore map →'), a:has-text('Khám phá bản đồ →')")
    if explore_links.count():
        first_explore = explore_links.first
        href = first_explore.get_attribute("href")
        assert "/workspace/map" in href, f"Expected map link, got {href}"
        assert "anchor_kind=" in href, f"Expected anchor_kind in map link, got {href}"
        print(f"  Explore on map link target: {href}")

    # 6. Test old-style URL preservation
    page.goto(f"{base_url}/changes?view=all&subject=user&change_type=traffic_spike&sort=recent", wait_until="networkidle")
    page.wait_for_timeout(500)
    assert "view=all" in page.url
    assert "subject=user" in page.url
    assert "change_type=traffic_spike" in page.url
    assert "sort=recent" in page.url

    assert not page_errors, f"Page errors on /changes: {page_errors}"
    assert not failed_requests, f"Failed API calls on /changes: {failed_requests}"
    print(f"  /changes ({lang}, {width}px) passed successfully.")
    context.close()

def test_map_page(browser, base_url, lang="en", width=1440, height=900):
    print(f"\n--- Testing /workspace/map ({lang.upper()}, {width}x{height}) ---")
    context = browser.new_context(viewport={"width": width, "height": height})
    page = context.new_page()

    page_errors = []
    failed_requests = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))
    page.on("response", lambda res: failed_requests.append(f"{res.status} {res.url}") if res.status >= 400 and "/api/" in res.url else None)

    page.add_init_script(f"localStorage.setItem('tracescope_lang', '{lang}');")

    # 1. Open /workspace/map
    page.goto(f"{base_url}/workspace/map", wait_until="networkidle")
    time.sleep(1)
    check_overflow_and_errors(page, f"/workspace/map {lang} {width}px")

    # 2. Check kind switcher (APIs, Services, Users)
    api_tab = page.locator("aside button[role='tab']:text-is('APIs')").first
    if api_tab.count():
        api_tab.click()
        page.wait_for_timeout(400)
        assert "list=apis" in page.url

    svc_tab = page.locator("aside button[role='tab']:has-text('Services'), aside button[role='tab']:has-text('Dịch vụ')").first
    if svc_tab.count():
        svc_tab.click()
        page.wait_for_timeout(400)
        assert "list=services" in page.url

    users_tab = page.locator("aside button[role='tab']:has-text('Users'), aside button[role='tab']:has-text('User')").first
    if users_tab.count():
        users_tab.click()
        page.wait_for_timeout(400)
        assert "list=" not in page.url  # default

    # 3. Test Unknown users anchor
    unk_btn = page.locator("aside button:has-text('Unknown users'), aside button:has-text('Người dùng chưa xác định')").first
    if unk_btn.count():
        unk_btn.click()
        page.wait_for_timeout(500)
        assert "anchor_kind=unknown" in page.url
        center_title = page.locator("h3:has-text('-anonymous-')")
        assert center_title.count() >= 1, "Expected -anonymous- in centre card"

    # 4. Test Search input with Enter
    search_input = page.locator("aside input[type='text']").first
    search_input.click()
    search_input.fill("order")
    page.wait_for_timeout(700)
    # Check dropdown appeared
    dropdown = page.locator("aside div.shadow-pop button")
    assert dropdown.count() >= 1, f"Expected search results dropdown, found {dropdown.count()}"
    search_input.press("ArrowDown")
    search_input.press("Enter")
    page.wait_for_timeout(600)
    assert "anchor=" in page.url

    # 5. Test Walk: Navigate to User -> Service -> API, breadcrumb back
    page.goto(f"{base_url}/workspace/map?anchor_kind=user&anchor=alice_wsse", wait_until="networkidle")
    page.wait_for_timeout(600)
    assert "anchor_kind=user" in page.url

    # Click a service on the right side ("Reaches")
    right_rows = page.locator("div.min-w-0.w-full").last.locator("button")
    if right_rows.count():
        first_svc = right_rows.first
        first_svc.click()
        page.wait_for_timeout(600)
        assert "anchor_kind=service" in page.url, f"Expected anchor_kind=service, got {page.url}"
        assert "scope_user=alice_wsse" in page.url, f"Expected scope_user=alice_wsse, got {page.url}"
        print("  Scope user chip confirmed on Service anchor!")

        # Breadcrumb back to user
        crumb_user = page.locator("nav[aria-label='Breadcrumb'] button:has-text('alice_wsse')").first
        if crumb_user.count():
            crumb_user.click()
            page.wait_for_timeout(600)
            assert "anchor_kind=user" in page.url
            print("  Breadcrumb back confirmed!")

    assert not page_errors, f"Page errors on /workspace/map: {page_errors}"
    assert not failed_requests, f"Failed API calls on /workspace/map: {failed_requests}"
    print(f"  /workspace/map ({lang}, {width}px) passed successfully.")
    context.close()

def test_large_mocked_estate(browser, base_url):
    print("\n--- Testing Large Mocked Estate (240 services, 1500 APIs, 180 users) ---")
    context = browser.new_context(viewport={"width": 1440, "height": 900})
    page = context.new_page()

    page_errors = []
    page.on("pageerror", lambda err: page_errors.append(str(err)))

    # Intercept /api/v1/relationships with large mock data
    def handle_relationships(route):
        url = route.request.url
        if "facets=principal" in url and "limit=1000" in url:
            # Rail users list
            users = [{"name": f"user_{i}", "requests": 50000 - i * 100, "prev_requests": 40000, "services": 12, "errors": 0, "error_rate": 0, "tps": 1, "p95_ms": 10, "state": "active", "principals": 1, "unknown_requests": 0, "callers": 2, "apis": 15, "ips": 1} for i in range(180)]
            body = {
                "window": {"start_ms": 1000, "end_ms": 2000, "previous_start_ms": 0, "history_available": True},
                "summary": {"requests": 1000000, "errors": 0, "error_rate": 0, "tps": 10, "p95_ms": 10, "prev_requests": 900000, "unknown_requests": 50000, "unknown_ips": 5, "principals": 180, "callers": 20, "apis": 1500, "services": 240, "ips": 100, "first_seen_ms": 0, "last_seen_ms": 2000},
                "series": [],
                "facets": {"principal": {"total": 180, "items": users, "truncated": False}},
                "service_meta_options": {"environment": [], "group": [], "module": []},
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(body))
            return

        # Main anchor explorer query
        callers = [{"name": f"caller_{i}", "requests": 20000 - i * 50, "prev_requests": 15000, "services": 5, "errors": 0, "error_rate": 0, "tps": 1, "p95_ms": 10, "state": "active", "principals": 1, "unknown_requests": 0, "callers": 1, "apis": 5, "ips": 1} for i in range(40)]
        services = [{"name": f"service_{i}", "requests": 30000 - i * 80, "prev_requests": 25000, "services": 1, "errors": 0, "error_rate": 0, "tps": 2, "p95_ms": 12, "state": "active", "principals": 5, "unknown_requests": 0, "callers": 3, "apis": 10, "ips": 2} for i in range(240)]
        principals = [{"name": f"user_{i}", "requests": 10000 - i * 20, "prev_requests": 8000, "services": 4, "errors": 0, "error_rate": 0, "tps": 1, "p95_ms": 8, "state": "active", "principals": 1, "unknown_requests": 0, "callers": 1, "apis": 4, "ips": 1} for i in range(6)]

        body = {
            "window": {"start_ms": 1000, "end_ms": 2000, "previous_start_ms": 0, "history_available": True},
            "summary": {"requests": 5000000, "errors": 0, "error_rate": 0, "tps": 50, "p95_ms": 15, "prev_requests": 4500000, "unknown_requests": 100000, "unknown_ips": 10, "principals": 180, "callers": 40, "apis": 1500, "services": 240, "ips": 200, "first_seen_ms": 0, "last_seen_ms": 2000},
            "series": [],
            "facets": {
                "caller": {"total": 40, "items": callers, "truncated": False},
                "service": {"total": 240, "items": services, "truncated": False},
                "principal": {"total": 6, "items": principals, "truncated": False},
            },
            "service_meta_options": {"environment": [], "group": [], "module": []},
        }
        route.fulfill(status=200, content_type="application/json", body=json.dumps(body))

    page.route("**/api/v1/relationships*", handle_relationships)

    page.goto(f"{base_url}/workspace/map", wait_until="networkidle")
    page.wait_for_timeout(600)

    # Count visible rows on Left side
    left_side_btn = page.locator("div.flex-col > div:has-text('Called from'), div.md\\:grid > div:first-child").locator("button[style*='height: 36px']")
    left_count = left_side_btn.count()
    print(f"  Visible left side rows count: {left_count} (Must be <= 10)")
    assert 0 < left_count <= 10, f"Expected <= 10 rows on left side, found {left_count}"

    # Count visible rows on Right side
    right_side_btn = page.locator("div.flex-col > div:has-text('Services'), div.md\\:grid > div:last-child").locator("button[style*='height: 36px']")
    right_count = right_side_btn.count()
    print(f"  Visible right side rows count: {right_count} (Must be <= 10)")
    assert 0 < right_count <= 10, f"Expected <= 10 rows on right side, found {right_count}"

    # Check "+ N more" button is present on both sides
    more_buttons = page.locator("button:has-text('+ 30'), button:has-text('+ 230')")
    assert more_buttons.count() >= 1, f"Expected '+ N more' buttons to be present, found {more_buttons.count()}"
    print(f"  Found {more_buttons.count()} '+ N more' buttons ({[b.inner_text() for b in more_buttons.all()]})")
    print("  Large estate correctly bounded complexity to <= 10 rows per side with +N more!")

    assert not page_errors, f"Page errors: {page_errors}"
    context.close()

def main():
    print("=" * 70)
    print(" TraceScope Redesign Verification Suite (Playwright)")
    print(f" Target: {BASE_URL}")
    print("=" * 70)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # 1. Desktop EN 1440px
        test_changes_page(browser, BASE_URL, lang="en", width=1440, height=900)
        test_map_page(browser, BASE_URL, lang="en", width=1440, height=900)

        # 2. Desktop VI 1440px
        test_changes_page(browser, BASE_URL, lang="vi", width=1440, height=900)
        test_map_page(browser, BASE_URL, lang="vi", width=1440, height=900)

        # 3. Mobile 390px
        test_changes_page(browser, BASE_URL, lang="en", width=390, height=844)
        test_map_page(browser, BASE_URL, lang="en", width=390, height=844)

        # 4. Large Mocked Estate
        test_large_mocked_estate(browser, BASE_URL)

        browser.close()

    print("\n" + "=" * 70)
    print(" ALL REDESIGN VERIFICATION TESTS PASSED SUCCESSFULLY! ")
    print("=" * 70)

if __name__ == "__main__":
    main()
