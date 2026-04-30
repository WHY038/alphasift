# -*- coding: utf-8 -*-
"""
Wrapper script to run alphasift with customized settings.
This script applies a monkey patch to adjust network request parameters
without modifying the original source code.
"""

import logging
import sys
import time
from functools import wraps

# --- Monkey Patching Section ---
# We will attempt to patch the requests library's get method to add robustness.
# This is a more reliable approach than patching the application's internal functions.

try:
    import pandas as pd
    import requests
    from alphasift.cli import main as alphasift_main
    from alphasift.snapshot import _normalize
except ImportError as e:
    print(f"Error: A required library is missing. {e}", file=sys.stderr)
    print("Please ensure all project dependencies are installed by running 'pip install -r requirements.txt'", file=sys.stderr)
    sys.exit(1)


def robust_fetch_decorator(func):
    """
    A decorator that wraps a function to make it more robust.
    It replaces the original _fetch_em_datacenter function.
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        # These are the parameters for the eastmoney datacenter API
        url = "https://data.eastmoney.com/dataapi/xuangu/list"
        all_items = []
        page = 1
        page_size = 500
        retries = 3        # Retry up to 3 times
        timeout = 60       # Increase timeout to 60 seconds

        while True:
            params = {
                "st": "SECURITY_CODE", "sr": "1", "ps": str(page_size), "p": str(page),
                "sty": "SECUCODE,SECURITY_CODE,SECURITY_NAME_ABBR,NEW_PRICE,CHANGE_RATE,VOLUME_RATIO,DEAL_AMOUNT,TURNOVERRATE,PE9,PBNEWMRQ,TOTAL_MARKET_CAP,CIRCULATION_MARKET_CAP",
                "filter": '(MARKET+in+("上交所主板","深交所主板","深交所创业板","上交所科创板","北交所"))',
                "source": "SELECT_SECURITIES", "client": "WEB",
            }
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Referer": "https://data.eastmoney.com/xuangu/",
            }

            data = None
            for attempt in range(retries):
                try:
                    resp = requests.get(url, params=params, headers=headers, timeout=timeout)
                    resp.raise_for_status()
                    data = resp.json()
                    break  # Success, exit retry loop
                except (requests.exceptions.RequestException, ValueError) as e:
                    logging.warning(f"[Robust Fetch] Attempt {attempt + 1}/{retries} failed for page {page}: {e}")
                    if attempt + 1 == retries:
                        logging.error("[Robust Fetch] All retry attempts failed. Raising exception.")
                        raise  # Re-raise the exception after all retries failed
                    time.sleep(5 * (attempt + 1))  # Exponential backoff wait

            if data is None:
                raise RuntimeError("[Robust Fetch] Failed to fetch data after multiple retries")

            if not data.get("success"):
                raise RuntimeError(f"[Robust Fetch] em_datacenter API error: {data.get('message', 'unknown')}")

            items = data.get("result", {}).get("data", [])
            if not items:
                # If no items on the first page, or any subsequent page, we are done.
                break
            all_items.extend(items)

            total_count = data.get("result", {}).get("count", 0)
            if not total_count or page * page_size >= total_count:
                break
            page += 1

        if not all_items:
            raise RuntimeError("[Robust Fetch] em_datacenter returned no data")

        df = pd.DataFrame(all_items)
        # Use the original project's normalize function to keep logic consistent
        return _normalize(df, source="em_datacenter")

    return wrapper


def apply_patch():
    """Applies the monkey patch to the alphasift.snapshot module."""
    try:
        import alphasift.snapshot
        # Directly replace the function with our decorated, robust version
        alphasift.snapshot._fetch_em_datacenter = robust_fetch_decorator(alphasift.snapshot._fetch_em_datacenter)
        logging.info("Monkey patch for _fetch_em_datacenter applied successfully.")
    except (ImportError, AttributeError) as e:
        print(f"Error: Could not apply patch. {e}", file=sys.stderr)
        print("Please ensure the alphasift project structure has not significantly changed.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    # 1. Apply the patch before doing anything else
    apply_patch()

    # 2. Now, run the original main function from the alphasift CLI
    print("Starting alphasift with custom robust fetch patch...")
    alphasift_main()
    print("Alphasift execution finished.")
