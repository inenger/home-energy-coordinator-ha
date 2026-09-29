#!/usr/bin/env bash
# One-time rescue when Supervisor still knows local_energy_coordinator
# but the local source directory disappeared. Runs only on HA OS / RPi4.
set -Eeuo pipefail
umask 077

VERSION="0.4.1"
SLUG="local_energy_coordinator"
PUBLIC_REPO="https://github.com/inenger/home-energy-coordinator-ha"
PUBLIC_COMMIT="f8c88c9e2b3536ec47cdb5a9737f96cd86d12e78"
APP_ROOT="${HEC_APP_ROOT:-/addons}"
SHARE_ROOT="${HEC_SHARE_ROOT:-/share}"
DEST="${HEC_DEST:-$APP_ROOT/energy_coordinator}"
LEGACY_WRONG_DEST="${HEC_LEGACY_WRONG_DEST:-/addons/local/energy_coordinator}"
HISTORY="$SHARE_ROOT/hec-recovery"
PORTABLE="$SHARE_ROOT/home-energy-coordinator/evidence.sqlite"
PORTABLE_META="$SHARE_ROOT/home-energy-coordinator/evidence.json"
SOURCE_TARBALL="${HEC_SOURCE_TARBALL:-}"

WORK=""
BACKUP_DIR=""
BACKUP_SLUG=""
PREVIOUS_STATE=""
PREVIOUS_VERSION=""
HAD_SOURCE=0
SOURCE_MOVED=0
SUCCESS=0
HA=(ha --raw-json --no-progress --log-level error)

fail() { printf '\nCHYBA: %s\n' "$*" >&2; exit 1; }

cli() {
  local outfile=$1; shift
  "${HA[@]}" "$@" >"$outfile" || return 1
  jq -e '.result == "ok"' "$outfile" >/dev/null || return 1
}

app_info() {
  local outfile=$1
  cli "$outfile" apps info "$SLUG"
}

wait_state() {
  local expected=$1 timeout=${2:-120} prefix=${3:-state}
  local loops=$((timeout / 2)) state="unknown"
  (( loops > 0 )) || loops=1
  for ((i=1;i<=loops;i++)); do
    if app_info "$WORK/${prefix}-${i}.json"; then
      state=$(jq -r '.data.state // "unknown"' "$WORK/${prefix}-${i}.json")
      if [[ $state == "$expected" ]]; then return 0; fi
    fi
    sleep 2
  done
  printf 'Poslední stav: %s, očekáváno: %s\n' "$state" "$expected" >&2
  return 1
}

wait_latest_version() {
  local expected=$1 timeout=${2:-90}
  local loops=$((timeout / 2)) latest="" state=""
  (( loops > 0 )) || loops=1
  for ((i=1;i<=loops;i++)); do
    if app_info "$WORK/catalog-${i}.json"; then
      latest=$(jq -r '.data.version_latest // ""' "$WORK/catalog-${i}.json")
      state=$(jq -r '.data.state // "unknown"' "$WORK/catalog-${i}.json")
      if [[ $latest == "$expected" ]]; then return 0; fi
    fi
    sleep 2
  done
  printf 'Store neukazuje verzi %s (version_latest=%s, state=%s).\n' "$expected" "$latest" "$state" >&2
  return 1
}

wait_started_version() {
  local expected=$1 timeout=${2:-120}
  local loops=$((timeout / 2)) state="" version="" good=0
  (( loops > 0 )) || loops=1
  for ((i=1;i<=loops;i++)); do
    if app_info "$WORK/started-${i}.json"; then
      state=$(jq -r '.data.state // "unknown"' "$WORK/started-${i}.json")
      version=$(jq -r '.data.version // ""' "$WORK/started-${i}.json")
      if [[ $state == started && $version == "$expected" ]]; then
        good=$((good+1))
        if (( good >= 3 )); then return 0; fi
      else
        good=0
      fi
    fi
    sleep 2
  done
  printf 'Poslední stav/version: %s / %s, očekáváno started / %s.\n' "$state" "$version" "$expected" >&2
  return 1
}

stop_app() {
  local state
  app_info "$WORK/pre-stop.json" || return 1
  state=$(jq -r '.data.state // "unknown"' "$WORK/pre-stop.json")
  if [[ $state == stopped ]]; then return 0; fi
  [[ $state == started ]] || { printf 'Aplikace je v přechodném stavu %s.\n' "$state" >&2; return 1; }
  cli "$WORK/stop.json" apps stop "$SLUG" || return 1
  wait_state stopped 120 stop-wait
}

start_previous_if_needed() {
  [[ $PREVIOUS_STATE == started ]] || return 0
  local state=""
  if app_info "$WORK/recovery-current.json"; then state=$(jq -r '.data.state // "unknown"' "$WORK/recovery-current.json"); fi
  if [[ $state != started ]]; then
    cli "$WORK/recovery-start.json" apps start "$SLUG" || return 1
    wait_state started 120 recovery-start-wait || return 1
  fi
}

cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ $SUCCESS -ne 1 && $SOURCE_MOVED -eq 1 && $HAD_SOURCE -eq 1 && -n $BACKUP_DIR && -d "$BACKUP_DIR/previous-source" ]]; then
    printf '\nRescue nebyl potvrzen. Obnovuji původní source...\n' >&2
    if app_info "$WORK/rollback-info.json"; then
      local s
      s=$(jq -r '.data.state // "unknown"' "$WORK/rollback-info.json")
      if [[ $s != stopped ]]; then
        cli "$WORK/rollback-stop.json" apps stop "$SLUG" || true
        wait_state stopped 60 rollback-stop-wait || true
      fi
    fi
    if [[ -d "$DEST" ]]; then mv -- "$DEST" "$BACKUP_DIR/failed-source" || true; fi
    if [[ ! -e "$DEST" ]]; then mv -- "$BACKUP_DIR/previous-source" "$DEST" || true; fi
    cli "$WORK/rollback-store.json" store reload || true
    cli "$WORK/rollback-build.json" apps rebuild "$SLUG" --force || true
    start_previous_if_needed || true
    rc=1
  elif [[ $SUCCESS -ne 1 ]]; then
    start_previous_if_needed || true
    rc=1
  fi
  if [[ -n $WORK && -d $WORK && -n $BACKUP_DIR ]]; then
    cp "$WORK"/*.json "$BACKUP_DIR/" 2>/dev/null || true
  fi
  [[ -z $WORK || ! -d $WORK ]] || rm -rf -- "$WORK"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for x in ha jq tar sha256sum mktemp grep awk date cp mv mkdir sleep curl; do
  command -v "$x" >/dev/null || fail "Chybí příkaz $x. Nic nezměněno."
done

WORK=$(mktemp -d /tmp/hec-recover.XXXXXX)
mkdir -p "$WORK/stage" "$HISTORY"

printf '0/7 Ověřuji HA OS a stávající aplikaci...\n'
cli "$WORK/system.json" info || fail 'Home Assistant CLI nekomunikuje se Supervisorem.'
jq -e '.data.arch == "aarch64" and .data.machine == "raspberrypi4-64"' "$WORK/system.json" >/dev/null ||
  fail 'Rescue je určen pro 64bitový Raspberry Pi 4.'
app_info "$WORK/before.json" || fail 'Supervisor nezná local_energy_coordinator; nic neměním.'
PREVIOUS_STATE=$(jq -r '.data.state // "unknown"' "$WORK/before.json")
PREVIOUS_VERSION=$(jq -r '.data.version // ""' "$WORK/before.json")
[[ $PREVIOUS_STATE == started || $PREVIOUS_STATE == stopped ]] ||
  fail "Aplikace je v přechodném stavu $PREVIOUS_STATE; vyčkej a spusť znovu."

printf '1/7 Stahuji připnutý distribuční zdroj %s...\n' "$VERSION"
if [[ -n $SOURCE_TARBALL ]]; then
  [[ -f $SOURCE_TARBALL ]] || fail 'HEC_SOURCE_TARBALL neexistuje.'
  cp "$SOURCE_TARBALL" "$WORK/repo.tar.gz"
else
  curl -fL --retry 3 --connect-timeout 15 "$PUBLIC_REPO/archive/$PUBLIC_COMMIT.tar.gz" -o "$WORK/repo.tar.gz"
fi
mkdir "$WORK/repo"
tar -xzf "$WORK/repo.tar.gz" -C "$WORK/repo" --strip-components=1
[[ -f "$WORK/repo/energy_coordinator/config.yaml" &&
   -f "$WORK/repo/energy_coordinator/Dockerfile" &&
   -f "$WORK/repo/energy_coordinator/energy/runtime.py" ]] ||
  fail 'Stažená distribuce je neúplná.'
grep -Fxq "version: \"$VERSION\"" "$WORK/repo/energy_coordinator/config.yaml" ||
  fail 'Distribuce nemá očekávanou verzi.'
grep -Fxq 'slug: energy_coordinator' "$WORK/repo/energy_coordinator/config.yaml" ||
  fail 'Distribuce má neočekávaný slug.'
tar -czf "$WORK/app.tar.gz" -C "$WORK/repo/energy_coordinator" .
sha256sum "$WORK/app.tar.gz" >"$WORK/app.sha256"

printf '2/7 Vytvářím Supervisor backup dat...\n'
BACKUP_DIR=$(mktemp -d "$HISTORY/pre-recovery-$VERSION-$(date +%Y%m%d-%H%M%S).XXXXXX")
cli "$WORK/backup.json" backups new --app "$SLUG" --name "HEC rescue před $VERSION $(date +%Y-%m-%d_%H:%M:%S)" ||
  fail 'Supervisor backup selhal; source nebyl změněn.'
BACKUP_SLUG=$(jq -er '.data.slug | select(type=="string" and length>0)' "$WORK/backup.json") ||
  fail 'Supervisor nepotvrdil identifikátor backupu.'
cli "$WORK/backup-info.json" backups info "$BACKUP_SLUG" || fail 'Nelze ověřit backup.'
jq -e --arg slug "$SLUG" '((.data.apps // .data.addons // []) | any(.[]; (.slug? // .) == $slug))' "$WORK/backup-info.json" >/dev/null ||
  fail 'Backup neobsahuje local_energy_coordinator.'
printf '%s\n' "$BACKUP_SLUG" >"$BACKUP_DIR/ha-backup-slug.txt"
cp "$WORK/before.json" "$BACKUP_DIR/before.json"

if [[ -e "$DEST" ]]; then
  [[ -d $DEST && ! -L $DEST ]] || fail "Cíl $DEST existuje, ale není běžný adresář."
  HAD_SOURCE=1
  tar -czf "$BACKUP_DIR/source-before.tar.gz" -C "$DEST" .
fi
if [[ "$LEGACY_WRONG_DEST" != "$DEST" && -e "$LEGACY_WRONG_DEST" ]]; then
  [[ -d "$LEGACY_WRONG_DEST" && ! -L "$LEGACY_WRONG_DEST" ]] ||
    fail "Starý chybný source $LEGACY_WRONG_DEST není běžný adresář."
  tar -czf "$BACKUP_DIR/legacy-wrong-source.tar.gz" -C "$LEGACY_WRONG_DEST" .
fi

printf '3/7 Zastavuji aplikaci a čekám na skutečný stav stopped...\n'
stop_app || fail 'Aplikace se do 120 s nepotvrdila jako stopped.'

printf '4/7 Obnovuji lokální source 0.4.1 do %s...\n' "$DEST"
if [[ "$LEGACY_WRONG_DEST" != "$DEST" && -d "$LEGACY_WRONG_DEST" ]]; then
  mv -- "$LEGACY_WRONG_DEST" "$BACKUP_DIR/legacy-wrong-source"
fi
mkdir -p "$APP_ROOT"
if [[ $HAD_SOURCE -eq 1 ]]; then
  mv -- "$DEST" "$BACKUP_DIR/previous-source"
  SOURCE_MOVED=1
fi
mkdir -p "$DEST"
tar -xzf "$WORK/app.tar.gz" -C "$DEST"

printf '5/7 Reload store -> čekám na version_latest=%s -> rebuild -> start...\n' "$VERSION"
cli "$WORK/store-reload.json" store reload || fail 'Store reload selhal.'
wait_latest_version "$VERSION" 90 || fail 'Supervisor v local store nevidí nový source.'
cli "$WORK/rebuild.json" apps rebuild "$SLUG" --force || fail 'Rebuild selhal; data zůstávají v Supervisor backupu.'
cli "$WORK/start.json" apps start "$SLUG" || fail 'Start selhal.'

printf '6/7 Ověřuji stabilní version=%s + started...\n' "$VERSION"
wait_started_version "$VERSION" 120 || fail 'Nová lokální verze nebyla stabilně potvrzena.'

printf '7/7 Čekám na portable SQLite backup do /share...\n'
for ((i=1;i<=90;i++)); do
  if [[ -s "$PORTABLE" && -s "$PORTABLE_META" ]]; then
    SUCCESS=1
    printf '\nHOTOVO. Lokální aplikace běží na %s a portable DB je připravena.\n' "$VERSION"
    printf 'Supervisor backup: %s\n' "$BACKUP_SLUG"
    printf 'Portable DB: %s\n' "$PORTABLE"
    printf 'DALŠÍ KROK: přidej do HA Store repository %s\n' "$PUBLIC_REPO"
    printf 'Před prvním startem repo aplikace zastav local_energy_coordinator; starou app zatím nemaž.\n'
    exit 0
  fi
  sleep 2
done
fail 'Portable DB nevznikla do 180 s. Repo verzi zatím neinstaluj.'
