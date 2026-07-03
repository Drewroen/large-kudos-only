#!/usr/bin/env python3
"""Convert cookies exported from a real browser into the Playwright
storage_state.json format kudos_bot.py expects.

Log into strava.com normally in your everyday browser (Chrome, Firefox,
etc. - no automation involved), then export its cookies with the
"Cookie-Editor" extension (https://cookie-editor.com/): open it while on
strava.com, choose "Export" -> "Export as JSON", and save that to a file.

Usage:
    uv run python convert_cookies.py strava_cookies.json
    uv run python convert_cookies.py strava_cookies.json --push

The --push flag skips the manual "copy auth_state.json into the GitHub
Secrets UI" step by uploading it straight to the STRAVA_AUTH_STATE repo
secret via the GitHub CLI (`gh`), which must be installed and authenticated
(`gh auth login`).

Pass "-" as the input to read the exported JSON from stdin instead of a
file - handy for piping straight from the clipboard, e.g.:
    pbpaste | uv run python convert_cookies.py - --push
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_INPUT = "strava_cookies.json"
DEFAULT_OUTPUT = "auth_state.json"
DEFAULT_SECRET_NAME = "STRAVA_AUTH_STATE"

SAME_SITE_MAP = {
    "strict": "Strict",
    "lax": "Lax",
    "no_restriction": "None",
    "none": "None",
    "unspecified": "Lax",
}

EXPORT_INSTRUCTIONS = """
To fix this:
  1. Log into strava.com in your regular, non-automated browser.
  2. Open the Cookie-Editor extension while on strava.com.
  3. Choose Export -> Export as JSON (this copies the cookies to your
     clipboard).
  4. Re-run this command right away, e.g.:
       pbpaste | uv run python convert_cookies.py -
     or, using the Makefile:
       make refresh
""".strip()


class CookieInputError(Exception):
    """Raised when the cookie JSON is missing, empty, or malformed."""


def parse_cookie_json(raw_text: str) -> list:
    if not raw_text.strip():
        raise CookieInputError("No cookie data was given (input was empty).")

    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise CookieInputError(f"Input isn't valid JSON ({exc}).") from exc

    if not isinstance(parsed, list):
        raise CookieInputError(
            f"Expected a JSON array of cookies, got {type(parsed).__name__}."
        )
    if not parsed:
        raise CookieInputError("Cookie list is empty - nothing to convert.")

    return parsed


def convert(raw_cookies: list) -> dict:
    cookies = []
    for i, c in enumerate(raw_cookies):
        for required_field in ("name", "value", "domain"):
            if required_field not in c:
                raise CookieInputError(
                    f"Cookie #{i} is missing required field '{required_field}' - "
                    "this doesn't look like a Cookie-Editor export."
                )
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


def push_secret(output_path: Path, secret_name: str, repo: str | None) -> None:
    """Upload output_path's contents to a GitHub Actions repo secret via the
    gh CLI, so it doesn't have to be copy-pasted into the Secrets UI."""
    gh_cmd = ["gh", "secret", "set", secret_name]
    if repo:
        gh_cmd += ["--repo", repo]
    try:
        subprocess.run(gh_cmd, stdin=output_path.open("rb"), check=True)
    except FileNotFoundError:
        print(
            "gh CLI not found - install it (https://cli.github.com/) and run "
            "`gh auth login`, or skip --push and paste the secret manually.",
            file=sys.stderr,
        )
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(f"gh secret set failed (exit {exc.returncode}).", file=sys.stderr)
        sys.exit(1)
    print(f"Pushed {output_path} to secret '{secret_name}'.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", nargs="?", default=DEFAULT_INPUT, help="Cookie-Editor JSON export, or '-' to read from stdin")
    parser.add_argument("output", nargs="?", default=DEFAULT_OUTPUT, help="Playwright storage_state output path")
    parser.add_argument(
        "--push", action="store_true", help=f"also upload the result to the {DEFAULT_SECRET_NAME} GitHub secret via gh"
    )
    parser.add_argument("--secret-name", default=DEFAULT_SECRET_NAME, help=f"secret name to use with --push (default {DEFAULT_SECRET_NAME})")
    parser.add_argument("--repo", default=None, help="owner/repo to use with --push (default: inferred by gh from the current directory)")
    args = parser.parse_args()

    output_path = Path(args.output)

    if args.input == "-":
        raw_text = sys.stdin.read()
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            print(f"Error: input file not found: {input_path}\n", file=sys.stderr)
            print(EXPORT_INSTRUCTIONS, file=sys.stderr)
            sys.exit(1)
        raw_text = input_path.read_text()

    try:
        raw_cookies = parse_cookie_json(raw_text)
        storage_state = convert(raw_cookies)
    except CookieInputError as exc:
        print(f"Error: {exc}\n", file=sys.stderr)
        print(EXPORT_INSTRUCTIONS, file=sys.stderr)
        sys.exit(1)

    output_path.write_text(json.dumps(storage_state, indent=2))
    print(f"Wrote {len(storage_state['cookies'])} cookies to {output_path}")

    if args.push:
        push_secret(output_path, args.secret_name, args.repo)


if __name__ == "__main__":
    main()
