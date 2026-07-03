#!/usr/bin/env python3
"""Strava auto-kudos bot.

Reuses a Strava session built by convert_cookies.py from cookies exported out
of a real browser, scrolls the activity feed until it finds the first
activity that hasn't been given kudos yet, then walks back up the feed giving
kudos to everything above it (skipping the user's own activities), with
randomized human-like timing.

Configuration is via environment variables (see .env.example):
  AUTH_STATE_PATH  - path to the session file from convert_cookies.py (default auth_state.json)
  HEADLESS         - "true" (default) or "false"
  MIN_KUDOS / MAX_KUDOS - random target range (default 50-75)
  OWN_NAME         - athlete name to skip (default "Drew Roen")
  SKIP_TOP_N       - ignore this many entries at the very top of the feed (default 0, for testing)
"""
import os
import random
import sys
import time
import traceback
from pathlib import Path

from dotenv import load_dotenv
from playwright.sync_api import Page, sync_playwright

load_dotenv(override=True)

AUTH_STATE_PATH = Path(os.environ.get("AUTH_STATE_PATH", "auth_state.json"))
HEADLESS = os.environ.get("HEADLESS", "true").strip().lower() != "false"
MIN_KUDOS = int(os.environ.get("MIN_KUDOS", "50"))
MAX_KUDOS = int(os.environ.get("MAX_KUDOS", "75"))
OWN_NAME = os.environ.get("OWN_NAME", "Drew Roen")
SKIP_TOP_N = int(os.environ.get("SKIP_TOP_N", "0"))

DASHBOARD_URL = "https://www.strava.com/dashboard"
SCREENSHOT_DIR = Path("screenshots")

# --- Selectors ---------------------------------------------------------
# Strava's dashboard is a React app; its DOM/class names shift over time.
# These are centralized here so they're easy to update in one place if
# Strava changes markup. They were not verified against the live site
# while offline-authoring this script, so double check them on first run
# (see README's "if selectors don't match" troubleshooting section).
FEED_ENTRY_SELECTOR = "div[data-testid='web-feed-entry']"
ATHLETE_NAME_SELECTOR = "a[data-testid='owners-name']"
KUDOS_BUTTON_SELECTOR = "button[data-testid='kudos_button']"

# The kudos button's `title` attribute is the ground truth for whether it
# still needs kudos - Strava sets it to one of these when a kudos is possible.
NEEDS_KUDOS_TITLES = {"give kudos", "be the first to give kudos!"}


def human_pause(min_s: float = 0.6, max_s: float = 1.8) -> None:
    time.sleep(random.uniform(min_s, max_s))


def open_dashboard(page: Page) -> None:
    """Navigate to the dashboard using the restored session; fail loudly if the
    saved session is missing or has expired (Strava redirects to /login)."""
    page.goto(DASHBOARD_URL)
    human_pause(1.0, 2.5)
    if "/login" in page.url:
        raise RuntimeError(
            f"The saved session in {AUTH_STATE_PATH} is missing or has expired. "
            "Re-export cookies from your browser and rerun convert_cookies.py."
        )


def kudos_already_given(button) -> bool:
    """Whether a kudos button reflects kudos already given (or ungivable,
    e.g. your own post) based on its title attribute."""
    title = (button.get_attribute("title") or "").strip().lower()
    return title not in NEEDS_KUDOS_TITLES


def classify_entry(entry, own_name: str) -> dict:
    """Inspect a feed entry and determine its athlete + kudos-eligibility."""
    kudos_button = entry.locator(KUDOS_BUTTON_SELECTOR)
    if kudos_button.count() == 0:
        # Not an activity card with kudos (e.g. a promo, challenge, or
        # "athletes to follow" suggestion) - not eligible.
        return {"eligible": False, "needs_kudos": False, "athlete": None}

    athlete_name = None
    name_locator = entry.locator(ATHLETE_NAME_SELECTOR)
    if name_locator.count() > 0:
        athlete_name = (name_locator.first.inner_text() or "").strip()

    if athlete_name == own_name:
        return {"eligible": False, "needs_kudos": False, "athlete": athlete_name}

    button = kudos_button.first
    already_given = kudos_already_given(button)
    return {"eligible": True, "needs_kudos": not already_given, "athlete": athlete_name}


def scroll_to_bottom_and_wait_for_more(
    page: Page, entries_locator, current_count: int, load_timeout_s: float = 10.0, poll_interval_s: float = 0.4
) -> int:
    """Trigger Strava's infinite-scroll to load more feed entries and poll
    until the count grows or load_timeout_s elapses. Returns the new count.

    Jumping straight to document.body.scrollHeight isn't reliable here -
    Strava's loader appears to react to the last rendered feed card actually
    entering the viewport (an IntersectionObserver on it or a sentinel just
    past it), not to raw scroll position. So scroll that specific card into
    view, then keep nudging with small wheel scrolls as a fallback for any
    scroll-event-based loading too.
    """
    if current_count > 0:
        try:
            entries_locator.nth(current_count - 1).scroll_into_view_if_needed(timeout=3000)
        except Exception:
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    else:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")

    deadline = time.monotonic() + load_timeout_s
    while time.monotonic() < deadline:
        page.wait_for_timeout(int(poll_interval_s * 1000))
        new_count = entries_locator.count()
        if new_count > current_count:
            return new_count
        # Nudge further with a wheel scroll in case the loader keys off
        # scroll events rather than (or in addition to) intersection.
        page.mouse.wheel(0, random.randint(400, 800))
    return entries_locator.count()


def collect_until_boundary(
    page: Page, own_name: str, skip_top_n: int = 0, max_scrolls: int = 400, stagnant_limit: int = 4
):
    """Scroll down the feed, classifying entries as they load, past the
    un-kudos'd newer activities, until the first activity that ALREADY has
    kudos is found - that marks where a previous run (or manual kudos-ing)
    left off.

    The first `skip_top_n` entries are treated as ineligible without even
    inspecting them - useful for testing against a feed whose topmost
    entries are already kudos'd.

    Returns (stop_index, entry_info_list, entries_locator). stop_index is the
    index of that already-kudos'd activity, or None if the entire reachable
    feed was scanned without finding one (i.e. nothing has been kudos'd yet).
    """
    entries_locator = page.locator(FEED_ENTRY_SELECTOR)
    entry_info = []
    stop_index = None
    stagnant = 0

    for _ in range(max_scrolls):
        count = entries_locator.count()
        for i in range(len(entry_info), count):
            if i < skip_top_n:
                info = {"eligible": False, "needs_kudos": False, "athlete": None}
            else:
                info = classify_entry(entries_locator.nth(i), own_name)
            entry_info.append(info)
            if info["eligible"] and not info["needs_kudos"]:
                stop_index = i
                break

        if stop_index is not None:
            break

        new_count = scroll_to_bottom_and_wait_for_more(page, entries_locator, count)
        human_pause(0.3, 0.9)

        if new_count <= count:
            stagnant += 1
            if stagnant >= stagnant_limit:
                print("Reached end of feed without finding a previously kudos'd activity.")
                break
        else:
            stagnant = 0

    return stop_index, entry_info, entries_locator


def main() -> None:
    if not AUTH_STATE_PATH.exists():
        print(
            f"{AUTH_STATE_PATH} not found. Export cookies from your browser and "
            "run `uv run python convert_cookies.py` to create it.",
            file=sys.stderr,
        )
        sys.exit(1)

    target = random.randint(MIN_KUDOS, MAX_KUDOS)
    print(f"Target kudos for this run: {target}")

    given = 0
    skipped_own = 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS)
        context = browser.new_context(storage_state=str(AUTH_STATE_PATH))
        page = context.new_page()

        try:
            open_dashboard(page)
            print("Loaded dashboard with saved session.")

            stop_index, entry_info, entries_locator = collect_until_boundary(page, OWN_NAME, SKIP_TOP_N)

            if stop_index is None:
                # Scanned the whole reachable feed without finding an
                # already-kudos'd activity - give kudos to everything found.
                upper_bound = len(entry_info) - 1
            else:
                upper_bound = stop_index - 1
                print(
                    f"Found already-kudos'd activity at feed position {stop_index}; "
                    "giving kudos to everything newer, working back up to the top."
                )

            if upper_bound < 0:
                print("No un-kudos'd activities found in feed. Nothing to do.")

            for i in range(upper_bound, -1, -1):
                info = entry_info[i]
                if info["athlete"] == OWN_NAME:
                    skipped_own += 1
                    continue
                if not info["eligible"] or not info["needs_kudos"]:
                    continue

                entry = entries_locator.nth(i)
                button = entry.locator(KUDOS_BUTTON_SELECTOR).first
                try:
                    button.click(timeout=5000)
                    given += 1
                    print(f"Gave kudos to activity #{i} ({info['athlete']}) [{given}/{target}]")
                except Exception as exc:
                    print(f"Failed to click kudos on activity #{i}: {exc}")
                    continue

                if given >= target:
                    break

                time.sleep(random.uniform(1.5, 5.0))

            print(f"Done. Gave {given} kudos (target {target}), skipped {skipped_own} own activities.")

        except Exception:
            SCREENSHOT_DIR.mkdir(exist_ok=True)
            failure_path = SCREENSHOT_DIR / "failure.png"
            try:
                page.screenshot(path=str(failure_path), full_page=True)
                print(f"Saved failure screenshot to {failure_path}")
            except Exception:
                pass
            traceback.print_exc()
            browser.close()
            sys.exit(1)

        browser.close()


if __name__ == "__main__":
    main()
