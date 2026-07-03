#!/usr/bin/env python3
"""Convert cookies exported from a real browser into the Playwright
storage_state.json format kudos_bot.py expects.

Log into strava.com normally in your everyday browser (Chrome, Firefox,
etc. - no automation involved), then export its cookies with the
"Cookie-Editor" extension (https://cookie-editor.com/): open it while on
strava.com, choose "Export" -> "Export as JSON", and save that to a file.

Usage:
    uv run python convert_cookies.py strava_cookies.json
"""
import json
import sys
from pathlib import Path

DEFAULT_INPUT = "strava_cookies.json"
DEFAULT_OUTPUT = "auth_state.json"

SAME_SITE_MAP = {
    "strict": "Strict",
    "lax": "Lax",
    "no_restriction": "None",
    "none": "None",
    "unspecified": "Lax",
}


def convert(raw_cookies: list) -> dict:
    cookies = []
    for c in raw_cookies:
        same_site_raw = str(c.get("sameSite", "unspecified")).lower()
        cookies.append(
            {
                "name": c["name"],
                "value": c["value"],
                "domain": c["domain"],
                "path": c.get("path", "/"),
                "expires": -1 if c.get("session") else c.get("expirationDate", -1),
                "httpOnly": bool(c.get("httpOnly", False)),
                "secure": bool(c.get("secure", False)),
                "sameSite": SAME_SITE_MAP.get(same_site_raw, "Lax"),
            }
        )
    return {"cookies": cookies, "origins": []}


def main() -> None:
    input_path = Path(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INPUT)
    output_path = Path(sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUTPUT)

    if not input_path.exists():
        print(f"Input file not found: {input_path}", file=sys.stderr)
        print(f"Usage: uv run python convert_cookies.py <exported-cookies.json> [{DEFAULT_OUTPUT}]", file=sys.stderr)
        sys.exit(1)

    raw_cookies = json.loads(input_path.read_text())
    storage_state = convert(raw_cookies)
    output_path.write_text(json.dumps(storage_state, indent=2))
    print(f"Wrote {len(storage_state['cookies'])} cookies to {output_path}")


if __name__ == "__main__":
    main()
