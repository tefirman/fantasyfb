#!/bin/bash
# Daily SFB refresh on this laptop: the same steps as
# .github/workflows/sfb-refresh.yml (update the injury list, then collect,
# simulate, build and publish the odds page), run by launchd each morning.
# The workflow stays as a manual backup. See app/sfb_site/README.md.
#
# Everything lives in its own clones under $SFB_DAILY_HOME (default
# ~/.sfb-daily), reset to their remotes on every run, so your working copies
# are never touched. Pushes use your own git credentials.
#
#   scripts/sfb_daily.sh            # the real thing: commits and publishes
#   scripts/sfb_daily.sh --dry-run  # same steps, shows the diffs, pushes nothing
#
# Environment: SFB_GA_ID (required), SFB_DAILY_HOME, CLAUDE (path to the
# claude CLI), SFB_DAILY_REPO and SFB_DAILY_REF (which fantasyfb to run,
# default main on GitHub), PYTHON (to create the venv).
# -E so the ERR trap's notification also fires inside functions.
set -Eeuo pipefail

ROOT="${SFB_DAILY_HOME:-$HOME/.sfb-daily}"
REPO="${SFB_DAILY_REPO:-git@github.com:tefirman/fantasyfb.git}"
REF="${SFB_DAILY_REF:-main}"
DRY_RUN=false

log() { echo "$(date '+%F %T') $*"; }

notify() {
  osascript -e "display notification \"$1\" with title \"SFB refresh\"" >/dev/null 2>&1 || true
}

# Clones $1 into $2 on the first run, then resets it to $3 every run.
sync() {
  if [ ! -d "$2/.git" ]; then
    git clone -q "$1" "$2"
  fi
  git -C "$2" remote set-url origin "$1"
  git -C "$2" fetch -q origin "$3"
  git -C "$2" reset -q --hard FETCH_HEAD
}

find_claude() {
  if [ -n "${CLAUDE:-}" ]; then
    echo "$CLAUDE"
  elif command -v claude >/dev/null; then
    command -v claude
  else
    # The binary bundled with the VS Code extension, newest version first.
    ls -d "$HOME"/.vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude 2>/dev/null | sort -V | tail -1
  fi
}

# Bash ignores set -e inside a function called from `||`, so every step here
# returns on failure explicitly. A failure never blocks the refresh.
update_injuries() {
  rm -rf scan && mkdir scan
  sfb-field injuries site/inputs/leagues.csv --injured-list fantasy-data/fantasyfb/injured_list.csv \
    --out-dir scan | tee scan/scan.log || return 1
  local week
  week=$(sed -nE 's/^week ([0-9]+):.*/\1/p' scan/scan.log)
  if [ "$(wc -l < scan/new_injuries.csv)" -le 1 ] && [ "$(wc -l < scan/old_injuries.csv)" -le 1 ]; then
    log "No injuries to research."
    return 0
  fi

  local claude
  claude=$(find_claude)
  [ -x "$claude" ] || { log "claude CLI not found; set CLAUDE in the launchd plist." >&2; return 1; }
  # A normal sign-in can lapse within days, so unattended runs use a token from
  # `claude setup-token` saved in the Keychain (see app/sfb_site/README.md),
  # falling back to whatever sign-in the CLI has.
  local token
  if token=$(security find-generic-password -s sfb-daily-claude -a "$USER" -w 2>/dev/null); then
    export CLAUDE_CODE_OAUTH_TOKEN="$token"
  fi
  cp fantasy-data/fantasyfb/injured_list.csv scan/injured_list.before.csv
  sed -e "s/{WEEK_PLUS_3}/$((week + 3))/g" -e "s/{WEEK}/$week/g" \
    fantasyfb/.github/prompts/sfb-injuries.md > scan/prompt.md || return 1
  # Unlike on a GitHub runner, everything you own is reachable here, so on top
  # of the workflow's tool limits: --restricted ignores your Claude settings,
  # hooks and permission rules and confines file access to this directory, and
  # --strict-mcp-config loads no MCP servers. No API key, so it runs on the
  # subscription you are logged in with.
  log "Researching with $claude"
  (cd "$ROOT" && env -u ANTHROPIC_API_KEY "$claude" -p "$(cat scan/prompt.md)" \
    --model claude-sonnet-5-5 --max-turns 60 --restricted --strict-mcp-config \
    --no-session-persistence --tools "WebSearch,WebFetch,Read,Edit" \
    --allowedTools "WebSearch" "WebFetch" "Read" "Edit(fantasy-data/fantasyfb/injured_list.csv)") \
    | tee scan/summary.md || return 1
  sfb-field check-injuries scan/injured_list.before.csv fantasy-data/fantasyfb/injured_list.csv || return 1

  if git -C fantasy-data diff --quiet; then
    log "Injury list unchanged."
    return 0
  fi
  git -C fantasy-data --no-pager diff
  if $DRY_RUN; then
    log "Dry run: not committing the injury list."
    return 0
  fi
  git -C fantasy-data commit -qam "Update injured list (automated, week $week)" || return 1
  git -C fantasy-data push -q origin HEAD:main || return 1

  # raw.githubusercontent.com is cached for a few minutes, and collect reads
  # the list from there, so wait until it serves the new file.
  local want got i
  want=$(shasum -a 256 < fantasy-data/fantasyfb/injured_list.csv | cut -d' ' -f1)
  for i in $(seq 1 20); do
    got=$(curl -fsS https://raw.githubusercontent.com/tefirman/fantasy-data/main/fantasyfb/injured_list.csv | shasum -a 256 | cut -d' ' -f1)
    [ "$got" = "$want" ] && return 0
    sleep 30
  done
  log "The new list was not being served after 10 minutes; the refresh may use the old one." >&2
}

refresh() {
  # Start clean: collect merges into existing files, which would keep leagues
  # dropped from the list and hide a failed one behind yesterday's data.
  rm -rf sfb
  if ! sfb-field collect site/inputs/leagues.csv --out-dir sfb/data > collect.log 2>&1; then
    if grep -q "429 Client Error\|Too Many Requests" collect.log; then
      log "Sleeper rate-limited the run; not retrying." >&2
      return 1
    fi
    local failed
    failed=$(grep -oE '^FAILED [0-9]+' collect.log | awk '{print $2}' | paste -sd, -)
    [ -n "$failed" ] || { log "collect failed without naming any leagues; see $ROOT/collect.log" >&2; return 1; }
    log "Retrying: $failed"
    sfb-field collect site/inputs/leagues.csv --out-dir sfb/data --only "$failed"
  fi
  tail -1 collect.log

  sfb-field simulate sfb/data --out-dir sfb
  python fantasyfb/app/sfb_site/build.py --odds sfb/odds.csv --cut-line sfb/cut_line.csv \
    --leaderboard site/inputs/SFB16Leaderboard.html --data sfb/data \
    --players sfb/players.csv --out sfb/index.html --ga-id "$SFB_GA_ID"
  python - <<'EOF'
import pandas as pd
odds = pd.read_csv("sfb/odds.csv")
assert len(odds) > 4500, f"only {len(odds)} teams"
assert not odds.isna().any().any(), "NaN in odds.csv"
assert abs(odds.win.sum() - 1) < 1e-6, f"win odds sum to {odds.win.sum()}"
assert "googletagmanager" in open("sfb/index.html", encoding="utf-8").read(), "analytics tag missing"
print(f"{len(odds)} teams, win sums to {odds.win.sum():.6f}")
EOF

  local week
  week=$(python -c "import pandas as pd; print(int(pd.read_parquet('sfb/data/settings.parquet').first_week.min()) - 1)")
  cp sfb/index.html site/index.html
  if git -C site diff --quiet; then
    log "Page unchanged; nothing to publish."
    return 0
  fi
  if $DRY_RUN; then
    git -C site --no-pager diff --stat
    log "Dry run: not publishing. The page is at $ROOT/sfb/index.html"
    return 0
  fi
  git -C site commit -qam "Refresh the odds through week $week (automated)"
  git -C site push -q origin HEAD:main
  notify "Published the odds through week $week."
}

main() {
  [ "${1:-}" = "--dry-run" ] && DRY_RUN=true
  : "${SFB_GA_ID:?Set SFB_GA_ID to the Google Analytics measurement ID.}"
  mkdir -p "$ROOT"
  # launchd can start a second run if the first is still going after a wake.
  if ! mkdir "$ROOT/.lock" 2>/dev/null; then
    log "Another run is in progress ($ROOT/.lock); exiting."
    exit 0
  fi
  trap 'rmdir "$ROOT/.lock"' EXIT
  trap 'notify "Failed; see ~/Library/Logs/sfb-daily.log"' ERR
  cd "$ROOT"
  if $DRY_RUN; then log "Starting (dry run)"; else log "Starting"; fi

  # After a wake from sleep the network can take a while to come back.
  local i
  for i in $(seq 1 30); do
    curl -fsS -o /dev/null https://api.sleeper.app/v1/state/nfl && break
    if [ "$i" = 30 ]; then
      log "No network after 5 minutes." >&2
      notify "No network after 5 minutes; skipped today's refresh."
      exit 1
    fi
    sleep 10
  done

  sync "$REPO" fantasyfb "$REF"
  sync git@github.com:tefirman/fantasy-data.git fantasy-data main
  sync git@github.com:tefirman/sfb-odds.git site main
  [ -x venv/bin/python ] || "${PYTHON:-python3}" -m venv venv
  venv/bin/python -m pip install -q -e ./fantasyfb
  export PATH="$ROOT/venv/bin:$PATH"

  update_injuries || log "Injury step failed; refreshing with the list as it is." >&2
  refresh
  log "Done."
}

# Everything runs from main, which bash reads in full before running, so the
# reset of the clone this script lives in can't change it mid-run.
main "$@"
exit
