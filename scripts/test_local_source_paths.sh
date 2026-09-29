#!/usr/bin/env bash
# Simulates the SSH app's /local_apps mount and Supervisor catalog refresh.
set -Eeuo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/local_apps/energy_coordinator" "$tmp/addons/energy_coordinator" "$tmp/share"
printf 'version: "0.3.1"\nslug: energy_coordinator\n' > "$tmp/local_apps/energy_coordinator/config.yaml"
printf 'version: "0.4.1"\nslug: energy_coordinator\n' > "$tmp/addons/energy_coordinator/config.yaml"
printf 'stopped\n' > "$tmp/state"
printf '0.3.1\n' > "$tmp/installed-version"
tar -czf "$tmp/source.tar.gz" --exclude=.git -C "$(dirname "$repo")" "$(basename "$repo")"

cat > "$tmp/bin/ha" <<'HA'
#!/usr/bin/env bash
set -Eeuo pipefail
shift 4 # --raw-json --no-progress --log-level error
case "$1 ${2:-}" in
  'info ') printf '{"result":"ok","data":{"arch":"aarch64","machine":"raspberrypi4-64"}}\n' ;;
  'apps info')
    latest=0.3.1
    if [[ -f "$HEC_APP_ROOT/energy_coordinator/config.yaml" ]]; then
      latest=$(sed -n 's/^version: "\([^"]*\)"/\1/p' "$HEC_APP_ROOT/energy_coordinator/config.yaml" | head -1)
    fi
    printf '{"result":"ok","data":{"state":"%s","version":"%s","version_latest":"%s"}}\n' "$(cat "$FAKE_STATE")" "$(cat "$FAKE_INSTALLED_VERSION")" "${latest:-0.3.1}" ;;
  'backups new') printf '{"result":"ok","data":{"slug":"test-backup"}}\n' ;;
  'backups info') printf '{"result":"ok","data":{"apps":[{"slug":"local_energy_coordinator"}]}}\n' ;;
  'apps stop') printf 'stopped\n' > "$FAKE_STATE"; printf '{"result":"ok"}\n' ;;
  'apps rebuild')
    printf '{"result":"error","message":"Local and store versions differ, use Update instead of Rebuild"}\n'
    exit 1 ;;
  'apps update')
    sed -n 's/^version: "\([^"]*\)"/\1/p' "$HEC_APP_ROOT/energy_coordinator/config.yaml" > "$FAKE_INSTALLED_VERSION"
    printf '{"result":"ok"}\n' ;;
  'apps start')
    if [[ -n ${FAKE_FAIL_START_ONCE:-} && -f $FAKE_FAIL_START_ONCE ]]; then
      rm "$FAKE_FAIL_START_ONCE"
      printf '{"result":"error","message":"simulated start failure"}\n'
      exit 1
    fi
    printf 'started\n' > "$FAKE_STATE"
    mkdir -p "$HEC_SHARE_ROOT/home-energy-coordinator"
    printf 'test' > "$HEC_SHARE_ROOT/home-energy-coordinator/evidence.sqlite"
    printf '{}' > "$HEC_SHARE_ROOT/home-energy-coordinator/evidence.json"
    printf '{"result":"ok"}\n' ;;
  'store reload') printf '{"result":"ok"}\n' ;;
  *) printf 'Unexpected HA call: %s\n' "$*" >&2; exit 1 ;;
esac
HA
chmod +x "$tmp/bin/ha"
export PATH="$tmp/bin:$PATH" HEC_APP_ROOT="$tmp/local_apps" HEC_SHARE_ROOT="$tmp/share"
export HEC_SOURCE_TARBALL="$tmp/source.tar.gz" FAKE_STATE="$tmp/state"
export FAKE_INSTALLED_VERSION="$tmp/installed-version"
export HEC_HISTORY_ROOT="$tmp/share/hec-upgrades"
tar -czf "$tmp/app.tar.gz" -C "$repo/energy_coordinator" .
sha=$(sha256sum "$tmp/app.tar.gz" | awk '{print $1}')
bash "$repo/scripts/upgrade_local_app.sh" "$tmp/app.tar.gz" "$sha" 0.4.1 > "$tmp/upgrade.log"
test "$(cat "$tmp/installed-version")" = '0.4.1'
test "$(cat "$tmp/state")" = 'started'
test "$(find "$HEC_HISTORY_ROOT" -name previous-source -type d | wc -l)" = 1
# A failure after the version update must update back to the saved 0.3.1 source.
printf 'version: "0.3.1"\nslug: energy_coordinator\n' > "$tmp/local_apps/energy_coordinator/config.yaml"
printf '0.3.1\n' > "$tmp/installed-version"
printf 'started\n' > "$tmp/state"
export FAKE_FAIL_START_ONCE="$tmp/fail-start-once"
touch "$FAKE_FAIL_START_ONCE"
if bash "$repo/scripts/upgrade_local_app.sh" "$tmp/app.tar.gz" "$sha" 0.4.1 > "$tmp/failed-upgrade.log" 2>&1; then
  printf 'Expected a simulated start failure\n' >&2
  exit 1
fi
test "$(cat "$tmp/installed-version")" = '0.3.1'
test "$(cat "$tmp/state")" = 'started'
test "$(sed -n 's/^version: "\([^"]*\)"/\1/p' "$tmp/local_apps/energy_coordinator/config.yaml")" = '0.3.1'
unset FAKE_FAIL_START_ONCE
# Reset the simulated installed source for the separate missing-source recovery case.
printf 'version: "0.3.1"\nslug: energy_coordinator\n' > "$tmp/local_apps/energy_coordinator/config.yaml"
printf '0.3.1\n' > "$tmp/installed-version"
printf 'stopped\n' > "$tmp/state"
bash "$repo/scripts/recover_missing_local_source.sh" > "$tmp/log"
test -f "$tmp/local_apps/energy_coordinator/energy/runtime.py"
test "$(cat "$tmp/installed-version")" = '0.4.1'
test "$(cat "$tmp/state")" = 'started'
test "$(sed -n 's/^version: "\([^"]*\)"/\1/p' "$tmp/addons/energy_coordinator/config.yaml")" = '0.4.1'
test "$(find "$tmp/share/hec-recovery" -name previous-source -type d | wc -l)" = 1
printf 'PASS: upgrade and recovery use /local_apps, stale /addons untouched, app started on 0.4.1\n'
