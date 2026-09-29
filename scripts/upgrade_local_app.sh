#!/usr/bin/env bash
# Upgrade the existing local Home Energy Coordinator safely.
# Uses current Home Assistant CLI naming (apps/store, --app) and waits for async state transitions.
# Usage: bash upgrade_local_app.sh SOURCE.tar.gz SHA256 VERSION
set -Eeuo pipefail
umask 077

APP_ROOT="${HEC_APP_ROOT:-/local_apps}"
SLUG="${HEC_LOCAL_SLUG:-local_energy_coordinator}"
HISTORY="${HEC_HISTORY_ROOT:-/share/hec-upgrades}"
ARCHIVE=${1:-}
EXPECTED_SHA=${2:-}
VERSION=${3:-}
DEST=""
WORK=""
BACKUP_DIR=""
LOCKED=0
STOPPED=0
SOURCE_MOVED=0
SUCCESS=0
PREVIOUS_STATE=""
PREVIOUS_VERSION=""
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
  printf 'Poslední stav aplikace: %s\n' "$state" >&2
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
  printf 'Store neukazuje očekávanou verzi %s (version_latest=%s, state=%s).\n' "$expected" "$latest" "$state" >&2
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
  if [[ $state == stopped ]]; then STOPPED=1; return 0; fi
  [[ $state == started ]] || { printf 'Nelze bezpečně zastavit aplikaci ze stavu %s.\n' "$state" >&2; return 1; }
  cli "$WORK/stop.json" apps stop "$SLUG" || return 1
  wait_state stopped 120 stop-wait || return 1
  STOPPED=1
}

start_previous_if_needed() {
  [[ $PREVIOUS_STATE == started ]] || return 0
  local tmp="$WORK/recovery-current.json" state=""
  if app_info "$tmp"; then state=$(jq -r '.data.state // "unknown"' "$tmp"); fi
  if [[ $state != started ]]; then
    cli "$WORK/recovery-start.json" apps start "$SLUG" || return 1
    wait_state started 120 recovery-start-wait || return 1
  fi
}

cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ $SUCCESS -ne 1 && $SOURCE_MOVED -eq 1 && -n $BACKUP_DIR && -d "$BACKUP_DIR/previous-source" ]]; then
    printf '\nUpgrade nebyl potvrzen. Obnovuji předchozí source...\n' >&2
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
    if app_info "$WORK/rollback-version.json"; then
      local installed
      installed=$(jq -r '.data.version // ""' "$WORK/rollback-version.json")
      if [[ $installed != "$PREVIOUS_VERSION" ]]; then
        cli "$WORK/rollback-update.json" apps update "$SLUG" ||
          printf 'Rollback verze selhal; použij Supervisor backup %s.\n' "${BACKUP_SLUG:-unknown}" >&2
      fi
    fi
    start_previous_if_needed || true
    rc=1
  elif [[ $SUCCESS -ne 1 && $STOPPED -eq 1 ]]; then
    start_previous_if_needed || true
    rc=1
  fi
  if [[ -n $WORK && -d $WORK && -n $BACKUP_DIR ]]; then
    cp "$WORK"/*.json "$BACKUP_DIR/" 2>/dev/null || true
  fi
  [[ -z $WORK || ! -d $WORK ]] || rm -rf -- "$WORK"
  if [[ $LOCKED -eq 1 ]]; then rmdir "$APP_ROOT/.hec-upgrade-lock" 2>/dev/null || true; fi
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for command in ha jq tar sha256sum mktemp grep awk date cp mv mkdir sleep; do
  command -v "$command" >/dev/null || fail "Chybí příkaz $command; nic nezměněno."
done
[[ -f $ARCHIVE && $EXPECTED_SHA =~ ^[0-9a-f]{64}$ && $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] ||
  fail 'Neplatný balíček, kontrolní součet nebo verze.'
[[ $(sha256sum "$ARCHIVE" | awk '{print $1}') == "$EXPECTED_SHA" ]] ||
  fail 'Nesouhlasí SHA-256. Nic nezměněno.'

[[ -d "$APP_ROOT" && ! -L "$APP_ROOT" ]] || fail "Chybí adresář lokálních aplikací $APP_ROOT. Nic neměním."
if [[ -z ${HEC_APP_ROOT:-} ]]; then
  awk -v path="$APP_ROOT" '$5 == path { found=1 } END { exit !found }' /proc/self/mountinfo ||
    fail "$APP_ROOT není připojený adresář lokálních aplikací. Nic neměním."
fi

CANDIDATES=()
for candidate in "$APP_ROOT"/*; do
  [[ -d "$candidate" && ! -L "$candidate" && -f "$candidate/config.yaml" ]] || continue
  if grep -Eq '^[[:space:]]*slug:[[:space:]]*"?energy_coordinator"?[[:space:]]*$' "$candidate/config.yaml"; then
    CANDIDATES+=("$candidate")
  fi
done
[[ ${#CANDIDATES[@]} -eq 1 ]] ||
  fail "Očekávám právě jeden lokální source se slugem energy_coordinator, nalezeno ${#CANDIDATES[@]}."
DEST="${CANDIDATES[0]}"
printf 'Nalezen source: %s\n' "$DEST"

mkdir "$APP_ROOT/.hec-upgrade-lock" 2>/dev/null ||
  fail 'Jiný upgrade již běží, nebo zůstal jeho zámek.'
LOCKED=1
WORK=$(mktemp -d /tmp/hec-upgrade.XXXXXX)
mkdir "$WORK/stage"

tar -tzf "$ARCHIVE" >"$WORK/paths"
if grep -Eq '(^/|(^|/)\.\.(/|$))' "$WORK/paths"; then fail 'Nebezpečná cesta v archivu.'; fi
if tar -tvzf "$ARCHIVE" | awk 'substr($0,1,1)!="-" && substr($0,1,1)!="d" {bad=1} END {exit bad?0:1}'; then
  fail 'Speciální soubor nebo odkaz v archivu.'
fi
tar -xzf "$ARCHIVE" -C "$WORK/stage"
grep -Fxq "version: \"$VERSION\"" "$WORK/stage/config.yaml" || fail 'Nesouhlasí verze v balíčku.'
grep -Fxq 'slug: energy_coordinator' "$WORK/stage/config.yaml" || fail 'Nesouhlasí slug v balíčku.'
[[ -f "$WORK/stage/Dockerfile" && -f "$WORK/stage/energy/runtime.py" ]] || fail 'Neúplný balíček.'

cli "$WORK/system.json" info || fail 'Home Assistant CLI nekomunikuje se Supervisorem.'
jq -e '.data.arch == "aarch64" and .data.machine == "raspberrypi4-64"' "$WORK/system.json" >/dev/null ||
  fail 'Balíček je určen pro HA OS na 64bitovém RPi4.'
app_info "$WORK/before.json" || fail 'Nelze načíst stávající aplikaci.'
PREVIOUS_STATE=$(jq -r '.data.state // "unknown"' "$WORK/before.json")
PREVIOUS_VERSION=$(jq -r '.data.version // ""' "$WORK/before.json")
[[ $PREVIOUS_STATE == started || $PREVIOUS_STATE == stopped ]] ||
  fail "Aplikace je v přechodném stavu $PREVIOUS_STATE. Nic neměním."

mkdir -p "$HISTORY"
BACKUP_DIR=$(mktemp -d "$HISTORY/pre-$VERSION-$(date +%Y%m%d-%H%M%S).XXXXXX")
printf '1/6 Vytvářím Supervisor backup dat aplikace...\n'
cli "$WORK/backup.json" backups new --app "$SLUG" --name "HEC před $VERSION $(date +%Y-%m-%d_%H:%M:%S)" ||
  fail 'Backup selhal; nic dalšího nebylo změněno.'
BACKUP_SLUG=$(jq -er '.data.slug | select(type=="string" and length>0)' "$WORK/backup.json") ||
  fail 'Supervisor nepotvrdil identifikátor backupu.'
cli "$WORK/backup-info.json" backups info "$BACKUP_SLUG" || fail 'Nelze ověřit backup.'
jq -e --arg slug "$SLUG" '((.data.apps // .data.addons // []) | any(.[]; (.slug? // .) == $slug))' "$WORK/backup-info.json" >/dev/null ||
  fail 'Backup neobsahuje očekávanou aplikaci.'
printf '%s\n' "$BACKUP_SLUG" >"$BACKUP_DIR/ha-backup-slug.txt"
tar -czf "$BACKUP_DIR/source.tar.gz" -C "$DEST" .
cp "$WORK/before.json" "$BACKUP_DIR/before.json"

printf '2/6 Zastavuji aplikaci a čekám na potvrzený stav stopped...\n'
stop_app || fail 'Aplikace se do 120 s nepotvrdila jako stopped. Source jsem nezměnil.'

printf '3/6 Nahrazuji pouze source; persistentní /data zůstává v Supervisor volume...\n'
mv -- "$DEST" "$BACKUP_DIR/previous-source"
SOURCE_MOVED=1
mv -- "$WORK/stage" "$DEST"

printf '4/6 Načítám local store a čekám, až Supervisor uvidí verzi %s...\n' "$VERSION"
cli "$WORK/store-reload.json" store reload || fail 'Store reload selhal.'
wait_latest_version "$VERSION" 90 || fail 'Supervisor v local store nevidí nový source.'
cli "$WORK/update.json" apps update "$SLUG" || fail 'Update selhal.'

printf '5/6 Spouštím novou verzi...\n'
cli "$WORK/start.json" apps start "$SLUG" || fail 'Start selhal.'

printf '6/6 Čekám na stabilní started + očekávanou verzi...\n'
wait_started_version "$VERSION" 120 || fail 'Nová verze nebyla stabilně potvrzena.'
SUCCESS=1
STOPPED=0
printf '\nHOTOVO: Supervisor stabilně hlásí version=%s a state=started.\n' "$VERSION"
printf 'Supervisor backup: %s\n' "$BACKUP_SLUG"
printf 'Source/diagnostika: %s\n' "$BACKUP_DIR"
