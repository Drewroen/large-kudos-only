# Strava Kudos Bot

A Playwright bot that scrolls your Strava activity feed to find the first
activity that hasn't been given kudos yet, then works its way back up giving
kudos to everything above it — skipping your own activities — with
randomized, human-like timing. Each run gives a random number of kudos
between 50 and 75 (or fewer if the feed runs out).

The bot never automates Strava's login form — even a hand-driven Playwright
browser gets 403'd by Strava's bot detection there. Instead it reuses a
session built from cookies you export out of your everyday, non-automated
browser.

## Setup

Requires [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run playwright install chromium
```

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

`kudos_bot.py` loads `.env` automatically (via `python-dotenv`) — no need to
`export` anything yourself.

### Create a session from your browser's cookies

1. Log into [strava.com](https://www.strava.com) normally in your everyday
   browser (Chrome, Firefox, etc.) — no automation involved here at all.
2. Install the [Cookie-Editor](https://cookie-editor.com/) extension.
3. While on strava.com, open Cookie-Editor and choose **Export → Export as
   JSON**. Save that to a file, e.g. `strava_cookies.json`.
4. Convert it into the session format `kudos_bot.py` expects:

   ```bash
   uv run python convert_cookies.py strava_cookies.json
   ```

   This writes `auth_state.json` (or whatever `AUTH_STATE_PATH` points to).

   You don't need to save the export to a file first — Cookie-Editor's
   "Export" also copies the JSON to your clipboard, so you can pipe it in
   directly by passing `-` as the input:

   ```bash
   pbpaste | uv run python convert_cookies.py -           # macOS
   xclip -selection clipboard -o | uv run python convert_cookies.py -   # Linux (X11)
   wl-paste | uv run python convert_cookies.py -           # Linux (Wayland)
   ```

Repeat this whenever your session expires — `kudos_bot.py` will tell you
clearly if that's happened.

If you're running on GitHub Actions (see below), add `--push` to skip the
manual copy-paste into the Secrets UI and upload the result straight to the
`STRAVA_AUTH_STATE` secret instead — combine it with `-` to go straight from
clipboard to secret with no intermediate files at all:

```bash
pbpaste | uv run python convert_cookies.py - --push
```

This requires the [GitHub CLI](https://cli.github.com/) (`gh`), authenticated
via `gh auth login`.

## Running locally

Watch it work with a visible browser:

```bash
HEADLESS=false uv run python kudos_bot.py
```

Or run headless, same as CI:

```bash
HEADLESS=true uv run python kudos_bot.py
```

## Configuration

All configuration is via environment variables:

| Var | Purpose | Default |
|-----|---------|---------|
| `AUTH_STATE_PATH` | path to the session file from `convert_cookies.py` | `auth_state.json` |
| `HEADLESS` | `true`/`false` | `true` |
| `MIN_KUDOS` | lower bound of random target per run | `50` |
| `MAX_KUDOS` | upper bound of random target per run | `75` |
| `OWN_NAME` | athlete display name to skip (can't kudos yourself) | `Drew Roen` |

## Running on GitHub Actions

The workflow at `.github/workflows/kudos.yml` runs the bot on a daily cron
(`0 13 * * *` UTC by default — adjust as you like) and can also be triggered
manually via the "Run workflow" button (`workflow_dispatch`).

Since there's no interactive browser in CI, the session has to be supplied as
a secret:

1. Follow the steps above locally to produce `auth_state.json`.
2. Either run `convert_cookies.py` with `--push` (fastest — see above) to
   upload it directly, or copy its full contents and add a repository secret
   named `STRAVA_AUTH_STATE` under **Settings → Secrets and variables →
   Actions** by hand.

The workflow writes the secret to `auth_state.json` at the start of each run,
runs headless, and uploads a screenshot artifact (`screenshots/`) if the run
fails, to help diagnose what went wrong.

**The session will eventually expire** (Strava session cookies aren't
indefinite). When scheduled runs start failing with "saved session ... has
expired," repeat the steps above to refresh the `STRAVA_AUTH_STATE` secret —
steps 1-4 under "Create a session from your browser's cookies," then
`convert_cookies.py ... --push`, is the fastest path.

## Notes / troubleshooting

- **Why not automate login?** Strava's login page runs reCAPTCHA Enterprise
  and other bot-detection signals that flag any Playwright-driven browser on
  sight, regardless of whether a human is typing into it. Building the
  session from cookies exported out of a real, non-automated browser
  sidesteps that entirely.
- **2FA**: works fine with this approach, since you complete 2FA yourself in
  your normal browser, well before the cookies are ever exported.
- **Selectors**: Strava's feed is a React app whose markup can change over
  time. All CSS selectors used to find feed entries, athlete names, and the
  kudos button are centralized as constants near the top of `kudos_bot.py`
  (`FEED_ENTRY_SELECTOR`, `ATHLETE_NAME_SELECTOR`, `KUDOS_BUTTON_SELECTOR`). If
  the bot stops finding activities or correctly detecting kudos state, inspect
  the live feed DOM and update these selectors.
