#!/usr/bin/env bash
# Simulates the SSH app's /addons mount and Supervisor catalog refresh.
set -Eeuo pipefail
repo=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
mkdir -p "$tmp/bin" "$tmp/addons/local/energy_coordinator" "$tmp/share"
printf 'version: "0.3.1"\nslug: energy_coordinator\n' > "$tmp/addons/local/energy_coordinator/config.yaml"
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
    sed -n 's/^version: "\([^"]*\)"/\1/p' "$HEC_APP_ROOT/energy_coordinator/config.yaml" > "$FAKE_INSTALLED_VERSION"
    printf '{"result":"ok"}\n' ;;
  'apps start')
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
export PATH="$tmp/bin:$PATH" HEC_APP_ROOT="$tmp/addons" HEC_SHARE_ROOT="$tmp/share"
export HEC_LEGACY_WRONG_DEST="$tmp/addons/local/energy_coordinator"
export HEC_SOURCE_TARBALL="$tmp/source.tar.gz" FAKE_STATE="$tmp/state"
export FAKE_INSTALLED_VERSION="$tmp/installed-version"
bash "$repo/scripts/recover_missing_local_source.sh" > "$tmp/log"
test -f "$tmp/addons/energy_coordinator/energy/runtime.py"
test "$(cat "$tmp/installed-version")" = '0.4.1'
test "$(cat "$tmp/state")" = 'started'
test ! -e "$tmp/addons/local/energy_coordinator"
test "$(find "$tmp/share/hec-recovery" -name legacy-wrong-source -type d | wc -l)" = 1
printf 'PASS: root /addons source discovered, nested source archived, app started on 0.4.1\n'
