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

    print("Discovered sample entities:")
    print(f"  - Anomaly ID:    {anom_id}")
    print(f"  - Service Name:  {svc_name}")
    print(f"  - Principal:     {p_name}")
    print(f"  - User profile:  {user_name}")
    print(f"  - Trace ID:      {tr_id}")
    print("-" * 75)

    pages_to_test = [
        ("/", "Overview Dashboard"),
        ("/topology", "Topology Route (Redirects to Users)"),
        ("/anomalies", "Anomalies Finding List"),
        (f"/anomalies/{anom_id}", f"Anomaly Detail #{anom_id}"),
        ("/services", "Services Inventory"),
        (f"/services/{svc_name}", f"Service Drilldown ({svc_name})"),
        ("/principals", "Principals Inventory"),
        ("/users", "User Intelligence Directory"),
        (f"/users/{user_name}/overview", f"User Overview Tab ({user_name})"),
        (f"/users/{user_name}/activity", f"User Activity & Performance Tab ({user_name})"),
        (f"/users/{user_name}/topology", f"User Access & Topology Tab ({user_name})"),
        (f"/users/{user_name}/changes", f"User Behavior Changes Tab ({user_name})"),
        (f"/users/{user_name}/patterns", f"User Usage Patterns Tab ({user_name})"),
        (f"/users/{user_name}/investigations", f"User Anomalies & Investigations Tab ({user_name})"),
        ("/traces", "Distributed Traces List"),
        ("/agent-stats", "Agent Fleet Infrastructure"),
    ]
    if tr_id:
        pages_to_test.append((f"/traces/{tr_id}", f"Trace Waterfall ({tr_id[:12]}...)"))

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
                if r.status >= 400 and not any(ign in r.url for ign in ["favicon", "404"])
                else None
            )

            start_t = time.time()
            target_url = f"{BASE_URL}{route}"
            status_str = "PASS"
            fail_reason = ""

            try:
                resp = page.goto(target_url, wait_until="networkidle", timeout=15000)
                # Allow React query resolution and hydration
                page.wait_for_timeout(1500)
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
