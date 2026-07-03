CLIPBOARD := $(shell \
	if command -v pbpaste >/dev/null 2>&1; then echo pbpaste; \
	elif command -v wl-paste >/dev/null 2>&1; then echo wl-paste; \
	elif command -v xclip >/dev/null 2>&1; then echo "xclip -selection clipboard -o"; \
	else echo ""; fi)

.PHONY: refresh refresh-local

# Convert the Strava cookies currently on your clipboard and push them
# straight to the STRAVA_AUTH_STATE GitHub secret. Requires the gh CLI
# (gh auth login) and one of pbpaste/wl-paste/xclip.
refresh:
ifeq ($(CLIPBOARD),)
	$(error No clipboard tool found (need pbpaste, wl-paste, or xclip))
endif
	$(CLIPBOARD) | uv run python convert_cookies.py - --push

# Same as refresh, but just writes auth_state.json locally instead of
# pushing it to GitHub.
refresh-local:
ifeq ($(CLIPBOARD),)
	$(error No clipboard tool found (need pbpaste, wl-paste, or xclip))
endif
	$(CLIPBOARD) | uv run python convert_cookies.py -
