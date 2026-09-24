#!/usr/bin/env python3
"""
Playwright End-to-End Real Browser Test Suite for TraceScope.
Launches headless Chromium, navigates to all SPA routes, waits for React rendering,
and captures any unhandled JavaScript exceptions (pageerror) or React render crashes.
"""
import sys
import time
import urllib.request
import os
import json
import shutil
import re
from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("BASE_URL", "http://127.0.0.1:30102")

def get_json(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PlaywrightTest/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        print(f"Warning: failed to query {url}: {e}", file=sys.stderr)
        return {}

def main():
    print("=" * 75)
    print(" TraceScope Real Browser (Playwright Chromium) UI & JS Safety Suite")
    print(f" Target: {BASE_URL}")
    print("=" * 75)

    # 1. Fetch dynamic sample identifiers from APIs
    anom_data = get_json(f"{BASE_URL}/api/v1/anomalies?limit=1")
    anom_id = anom_data.get("items", [{}])[0].get("id", 1) if anom_data.get("items") else 1

    svc_data = get_json(f"{BASE_URL}/api/v1/services?limit=1")
    svc_name = svc_data.get("items", [{}])[0].get("name", "apex-edge-gateway") if svc_data.get("items") else "apex-edge-gateway"

    p_data = get_json(f"{BASE_URL}/api/v1/principals?limit=1")
    p_name = p_data.get("items", [{}])[0].get("principal_name", "customer_loyalty_service") if p_data.get("items") else "customer_loyalty_service"

    user_data = get_json(f"{BASE_URL}/api/v1/users?limit=1")
    user_name = user_data.get("items", [{}])[0].get("principal_name", p_name) if user_data.get("items") else p_name

    tr_data = get_json(f"{BASE_URL}/api/v1/traces?limit=1")
    tr_id = tr_data.get("items", [{}])[0].get("trace_id", "") if tr_data.get("items") else ""

    changes_data = get_json(f"{BASE_URL}/api/v1/changes?limit=100")
    change_id = changes_data.get("items", [{}])[0].get("id", "") if changes_data.get("items") else ""
    user_change_id = ""
    user_change_principal = ""
    user_changes_data = get_json(f"{BASE_URL}/api/v1/changes?subject=user&limit=1")
    for change in user_changes_data.get("items", []) or changes_data.get("items", []):
        subject = change.get("subject") or {}
        if subject.get("type") == "user":
            user_change_id = change.get("id", "")
            user_change_principal = subject.get("name", "")
            break

    print("Discovered sample entities:")
    print(f"  - Anomaly ID:    {anom_id}")
    print(f"  - Service Name:  {svc_name}")
    print(f"  - Principal:     {p_name}")
    print(f"  - User profile:  {user_name}")
    print(f"  - Trace ID:      {tr_id}")
    print(f"  - Change Episode: {change_id}")
    print(f"  - User Change Episode: {user_change_id}")
    print("-" * 75)

    pages_to_test = [
        ("/", "Overview Dashboard"),
        ("/topology", "Interactive Service Topology"),
        ("/anomalies", "Anomalies Finding List"),
        ("/changes", "Changes Episode List"),
        (f"/anomalies/{anom_id}", f"Anomaly Detail #{anom_id}"),
        ("/services", "Services Inventory"),
        (f"/services/{svc_name}", f"Service Drilldown ({svc_name})"),
        ("/principals", "Principals Inventory"),
        ("/users", "User Intelligence Directory"),
        (f"/users/{user_name}/overview", f"Legacy User Overview Redirect ({user_name})"),
        (f"/users/{user_name}/activity", f"User Activity & Behavior Tab ({user_name})"),
        (f"/users/{user_name}/topology", f"User Access & Topology Tab ({user_name})"),
        (f"/users/{user_name}/changes", f"User Behavior Changes Tab ({user_name})"),
        (f"/users/{user_name}/patterns", f"User Usage Patterns Tab ({user_name})"),
        (f"/users/{user_name}/investigations", f"Legacy User Investigations Redirect ({user_name})"),
        ("/unknown-users", "Unknown & Unauthenticated Traffic Monitor"),
        ("/traces", "Distributed Traces List"),
        ("/agent-stats", "Agent Fleet Infrastructure"),
    ]
    if tr_id:
        pages_to_test.append((f"/traces/{tr_id}", f"Trace Waterfall ({tr_id[:12]}...)"))
    if change_id:
        pages_to_test.append((f"/changes/{change_id}", f"Change Episode Detail ({change_id})"))
    if user_change_id and user_change_principal:
        pages_to_test.append((f"/users/{user_change_principal}/changes/{user_change_id}", f"User Change Detail ({user_change_id})"))
        legacy_change_id = user_change_id.removeprefix("chg-")
        pages_to_test.append((f"/anomalies/{legacy_change_id}", f"Legacy Anomaly-to-Change Redirect ({legacy_change_id})"))

    only_route = os.environ.get("ONLY_ROUTE")
    if only_route:
        pages_to_test = [page for page in pages_to_test if page[0] == only_route]

    total_tests = len(pages_to_test)
    failed_tests = []
    
    with sync_playwright() as p:
        launch_options = {
            "headless": True,
            "args": ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        }
        system_chromium = shutil.which("chromium") or shutil.which("chromium-browser") or shutil.which("google-chrome")
        if system_chromium:
            launch_options["executable_path"] = system_chromium
        browser = p.chromium.launch(
            **launch_options
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})

        for route, title in pages_to_test:
            page = context.new_page()
            # Fast mock: block slow external CDN webfonts from blocking DOM load
            page.route("**/fonts.googleapis.com/**", lambda route: route.abort())
            page.route("**/fonts.gstatic.com/**", lambda route: route.abort())
            page.route("**/*.woff*", lambda route: route.abort())
            page_errors = []
            console_errors = []
            api_errors = []

            # Attach listeners
            page.on("pageerror", lambda err, errs=page_errors: errs.append(str(err)))
            page.on(
                "console",
                lambda msg, errs=console_errors: errs.append(msg.text)
                if msg.type == "error" and not any(ign in msg.text.lower() for ign in ["favicon", "404"])
                else None
            )
            page.on(
                "response",
                lambda r, errs=api_errors: errs.append(f"{r.url} -> {r.status}")
                if r.status >= 400 and not any(ign in r.url for ign in ["favicon", "404", "investigations"])
                else None
            )

            start_t = time.time()
            target_url = f"{BASE_URL}{route}"
            status_str = "PASS"
            fail_reason = ""

            try:
                resp = page.goto(target_url, wait_until="domcontentloaded", timeout=30000)
                # Allow React query resolution and hydration
                page.wait_for_selector("#root", timeout=15000)
                page.wait_for_timeout(2000)
                elapsed = time.time() - start_t

                # Check if root has content
                root_html = page.inner_html("#root")
                if not root_html.strip():
                    status_str = "FAIL"
                    fail_reason = "Empty #root HTML (React failed to mount)"

                # Check for unhandled JS errors
                if page_errors:
                    status_str = "FAIL"
                    fail_reason = "; ".join(page_errors)

                # Check for failed API calls
                if api_errors:
                    status_str = "FAIL"
                    fail_reason = "Failed API requests: " + "; ".join(api_errors)

                # Check for ErrorState rendered inside page
                if "Unable to load estate metrics" in root_html or "Field required" in root_html:
                    status_str = "FAIL"
                    fail_reason = "Rendered ErrorState with failed data query"

                # Check HTTP response
                if resp and resp.status != 200:
                    status_str = "FAIL"
                    fail_reason = f"HTTP {resp.status}"

                # Full-canvas topology interactions: inspector stays absent until
                # an object click, and zoom/reset controls mutate the viewport.
                if route == "/topology" and status_str == "PASS":
                    inspector = page.locator("[data-testid='topology-inspector']")
                    if page.locator("[data-testid='topology-search']").count() != 1:
                        status_str = "FAIL"
                        fail_reason = "Topology fast-travel search is missing"
                    elif inspector.count() != 0:
                        status_str = "FAIL"
                        fail_reason = "Topology inspector rendered before object selection"
                    elif page.locator("[data-api-connection='true']").count() != 0:
                        status_str = "FAIL"
                        fail_reason = "API-to-service connections rendered before API selection"
                    else:
                        search = page.locator("[data-testid='topology-search']")
                        search.fill(svc_name)
                        try:
                            search_result = page.locator("[data-topology-search-result='true']").first
                            search_result.wait_for(state="visible", timeout=10000)
                            search_result.click()
                            inspector.wait_for(state="visible", timeout=10000)
                            selected_card = page.locator("[data-topology-node='true'][style*='z-index: 30']")
                            if selected_card.count() != 1:
                                status_str = "FAIL"
                                fail_reason = "Fast-travel result was not selected on the top node layer"
                            page.get_by_label("Close topology detail panel").click()
                            inspector.wait_for(state="detached", timeout=3000)
                            search.fill("")
                        except Exception as exc:
                            status_str = "FAIL"
                            fail_reason = f"Topology fast-travel search failed: {exc}"
                        layer = page.locator("[data-testid='topology-transform-layer']")
                        page.locator("[data-testid='topology-zoom-in']").click()
                        if "scale(1.1)" not in (layer.get_attribute("style") or ""):
                            status_str = "FAIL"
                            fail_reason = "Topology zoom-in control did not transform the canvas"
                        page.locator("[data-testid='topology-reset-view']").click()
                        if "scale(1)" not in (layer.get_attribute("style") or ""):
                            status_str = "FAIL"
                            fail_reason = "Topology reset control did not restore the canvas"
                        time_slider = page.locator("[data-testid='topology-time-slider']")
                        if time_slider.get_attribute("max") != "2015" or time_slider.get_attribute("step") != "1":
                            status_str = "FAIL"
                            fail_reason = "Topology timeline is not configured for 2,016 five-minute windows"
                        else:
                            initial_window = page.locator("[data-testid='topology-selected-window']").inner_text()
                            time_slider.fill("2014")
                            time_slider.dispatch_event("pointerup")
                            if page.locator("[data-testid='topology-selected-window']").inner_text() == initial_window:
                                status_str = "FAIL"
                                fail_reason = "Topology timeline slider did not change the selected five-minute window"
                        first_node_card = page.locator("[data-topology-node='true']").first
                        first_node = first_node_card.locator(":scope > button:not([data-node-drag-ignore='true'])")
                        if first_node.count() > 0:
                            first_node.click()
                            try:
                                inspector.wait_for(state="visible", timeout=3000)
                            except Exception:
                                status_str = "FAIL"
                                fail_reason = "Topology inspector did not open after node selection"
                            if status_str == "PASS":
                                try:
                                    page.wait_for_selector("[data-testid='topology-tps-chart'], [data-testid='topology-tps-empty']", timeout=10000)
                                except Exception:
                                    status_str = "FAIL"
                                    inspector_text = inspector.inner_text(timeout=1000)[:240] if inspector.count() else "inspector closed"
                                    fail_reason = f"Topology TPS chart did not render: {inspector_text}; page_errors={page_errors}; console_errors={console_errors}"
                            if status_str == "PASS":
                                initial_position = first_node_card.get_attribute("style")
                                box = first_node_card.bounding_box()
                                if box:
                                    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
                                    page.mouse.down()
                                    page.mouse.move(box["x"] + box["width"] / 2 + 36, box["y"] + box["height"] / 2 + 24, steps=4)
                                    page.mouse.up()
                                    if first_node_card.get_attribute("style") == initial_position:
                                        status_str = "FAIL"
                                        fail_reason = "Topology node card did not move after pointer drag"
                        if status_str == "PASS":
                            page.locator("aside a[href='/services']").click()
                            page.wait_for_url("**/services", timeout=5000)
                            if not page.url.endswith("/services"):
                                status_str = "FAIL"
                                fail_reason = "Sidebar navigation did not leave the topology canvas"
                            else:
                                try:
                                    page.locator("[aria-label='Interactive service topology']").wait_for(state="detached", timeout=3000)
                                except Exception:
                                    status_str = "FAIL"
                                    full_root_text = page.locator("#root").inner_text()
                                    root_text = (full_root_text[:180] + " ... " + full_root_text[-420:]).replace("\n", " | ")
                                    active_link = page.locator("aside a[aria-current='page']")
                                    active_href = active_link.get_attribute("href") if active_link.count() else "none"
                                    fail_reason = f"Topology canvas remained mounted after sidebar route change; url={page.url}; active={active_href}; page_errors={page_errors}; console_errors={console_errors}; root={root_text}"

                if route.startswith("/changes/") and status_str == "PASS":
                    if page.locator("[data-testid='investigation-panel']").count() != 1:
                        status_str = "FAIL"
                        fail_reason = "LLM investigation panel is missing from Change detail"

                if route.endswith("/overview") and status_str == "PASS":
                    if not page.url.rstrip("/").endswith(f"/users/{user_name}/activity"):
                        status_str = "FAIL"
                        fail_reason = f"Legacy User Overview route did not redirect to Activity; url={page.url}"
                    elif page.locator("[data-testid='user-activity-segments']").count() != 1:
                        status_str = "FAIL"
                        fail_reason = "Redirected User Activity segmented control is missing"

                if route.endswith("/activity") and status_str == "PASS":
                    segments = page.locator("[data-testid='user-activity-segments'] button")
                    segment_labels = [segments.nth(index).inner_text().strip() for index in range(segments.count())]
                    if len(segment_labels) != 2 or not re.search(r"Behavior|Hành vi", segment_labels[0], re.IGNORECASE) or segment_labels[1] != "Access":
                        status_str = "FAIL"
                        fail_reason = f"Activity modes must be Behavior and Access; found {segment_labels}"
                    elif not re.search(r"Behavior|Hành vi", page.locator("[data-testid='user-activity-segments'] button[aria-selected='true']").inner_text().strip(), re.IGNORECASE):
                        status_str = "FAIL"
                        fail_reason = "User Activity did not open on Behavior"
                    elif page.get_by_text(re.compile(r"TPS vs Baseline|TPS so với Baseline", re.IGNORECASE)).count() == 0:
                        status_str = "FAIL"
                        fail_reason = "Behavior view is missing the TPS vs Baseline panel"
                    elif page.locator("[data-testid='activity-heatmap-panel']").count() != 1:
                        status_str = "FAIL"
                        fail_reason = "Behavior view is missing the active-hour heatmap"
                    elif page.locator("[data-testid='activity-heatmap-data'], [data-testid='activity-heatmap-empty']").count() != 1:
                        status_str = "FAIL"
                        fail_reason = "Heatmap must render measured cells or an explicit empty state"
                    elif page.get_by_text(re.compile(r"Error rate|Tỷ lệ lỗi", re.IGNORECASE)).count() == 0 or page.get_by_text(re.compile(r"HTTP status|Trạng thái HTTP", re.IGNORECASE)).count() == 0:
                        status_str = "FAIL"
                        fail_reason = "Behavior view is missing Error rate or HTTP status panels"
                    elif page.get_by_text(re.compile(r"Latency|Độ trễ", re.IGNORECASE)).count() == 0 or page.get_by_text("Bandwidth", exact=True).count() == 0:
                        status_str = "FAIL"
                        fail_reason = "Behavior view is missing Latency or Bandwidth panels"
                    else:
                        segments.nth(1).click()
                        page.wait_for_timeout(150)
                        if page.locator("text=Access for").count() == 0 and page.get_by_text("Selected IP", exact=True).count() == 0:
                            status_str = "FAIL"
                            fail_reason = "Access view did not render the IP → Service → API board"

                if route.endswith("/investigations") and status_str == "PASS":
                    if not page.url.rstrip("/").endswith(f"/users/{user_name}/changes"):
                        status_str = "FAIL"
                        fail_reason = f"Legacy User Investigations route did not redirect to User Changes; url={page.url}"

                if route.startswith("/users/") and "/changes/" in route and status_str == "PASS":
                    if page.locator("[data-testid='investigation-panel']").count() != 1:
                        status_str = "FAIL"
                        fail_reason = "LLM investigation panel is missing from User Change detail"

                if route.startswith("/changes/") and status_str == "PASS":
                    if page.locator("[data-testid='investigation-panel']").count() != 1:
                        status_str = "FAIL"
                        fail_reason = "LLM investigation panel is missing from Change detail"

            except Exception as ex:
                elapsed = time.time() - start_t
                status_str = "FAIL"
                fail_reason = str(ex)

            page.close()

            if status_str == "PASS":
                print(f"[PASS] {title:<36} | {route:<40} | {elapsed:.2f}s | 0 JS errors")
            else:
                print(f"[FAIL] {title:<36} | {route:<40} | {elapsed:.2f}s | ERROR: {fail_reason}")
                failed_tests.append((route, title, fail_reason))

        browser.close()

    print("=" * 75)
    if not failed_tests:
        print(f" ALL {total_tests} REAL BROWSER PAGES PASSED (0 unhandled JS exceptions)")
        print("=" * 75)
        sys.exit(0)
    else:
        print(f" {len(failed_tests)} of {total_tests} REAL BROWSER PAGES FAILED:")
        for r, t, err in failed_tests:
            print(f"   - {t} ({r}): {err}")
        print("=" * 75)
        sys.exit(1)

if __name__ == "__main__":
    main()
