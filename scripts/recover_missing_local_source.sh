#!/usr/bin/env bash
# One-time rescue for a local HEC app whose source directory disappeared,
# while Supervisor still has the local_energy_coordinator app/data volume.
set -Eeuo pipefail
umask 077

VERSION="0.4.1"
SLUG="local_energy_coordinator"
PUBLIC_REPO="https://github.com/inenger/home-energy-coordinator-ha"
PUBLIC_COMMIT="f8c88c9e2b3536ec47cdb5a9737f96cd86d12e78"
APP_ROOT="${HEC_APP_ROOT:-/addons}"
SHARE_ROOT="${HEC_SHARE_ROOT:-/share}"
DEST="${HEC_DEST:-$APP_ROOT/energy_coordinator}"
HISTORY="$SHARE_ROOT/hec-recovery"
PORTABLE="$SHARE_ROOT/home-energy-coordinator/evidence.sqlite"
PORTABLE_META="$SHARE_ROOT/home-energy-coordinator/evidence.json"
SOURCE_TARBALL="${HEC_SOURCE_TARBALL:-}"

WORK=""
BACKUP_DIR=""
BACKUP_SLUG=""
PREVIOUS_STATE=""
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
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ $SUCCESS -ne 1 && -n $WORK && -d $WORK ]]; then
    if [[ $SOURCE_MOVED -eq 1 && $HAD_SOURCE -eq 1 && -d "$BACKUP_DIR/previous-source" ]]; then
      printf '\nObnovuji původní zdrojový adresář...\n' >&2
      cli "$WORK/cleanup-stop.json" addons stop "$SLUG" || true
      [[ ! -e "$DEST" ]] || mv -- "$DEST" "$BACKUP_DIR/failed-source" || true
      if [[ ! -e "$DEST" ]]; then
        mv -- "$BACKUP_DIR/previous-source" "$DEST" || true
        cli "$WORK/cleanup-reload.json" addons reload || true
        cli "$WORK/cleanup-rebuild.json" addons rebuild "$SLUG" || true
      fi
    fi
    if [[ $PREVIOUS_STATE == started ]]; then
      cli "$WORK/cleanup-start.json" addons start "$SLUG" || true
    fi
  fi
  [[ -z $WORK || ! -d $WORK ]] || rm -rf -- "$WORK"
  exit "$rc"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

for c in ha jq tar sha256sum mktemp grep awk date cp mv mkdir sleep curl; do
  command -v "$c" >/dev/null || fail "Chybí příkaz $c. Nic nezměněno."
done

WORK=$(mktemp -d /tmp/hec-recover.XXXXXX)
mkdir -p "$WORK/stage" "$HISTORY"

printf '0/7 Ověřuji Home Assistant a stávající aplikaci...\n'
cli "$WORK/system.json" info || fail 'Home Assistant CLI nekomunikuje se Supervisorem.'
jq -e '.data.arch == "aarch64" and .data.machine == "raspberrypi4-64"' "$WORK/system.json" >/dev/null ||
  fail 'Tento rescue skript je určen pro 64bitový Raspberry Pi 4.'
cli "$WORK/before.json" addons info "$SLUG" || fail 'Supervisor nezná local_energy_coordinator; nic neměním.'
PREVIOUS_STATE=$(jq -r '.data.state' "$WORK/before.json")
[[ $PREVIOUS_STATE == started || $PREVIOUS_STATE == stopped ]] ||
  fail 'Aplikace právě mění stav; vyčkej a spusť skript znovu.'

printf '1/7 Stahuji připnutý distribuční zdroj 0.4.1...\n'
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
   -f "$WORK/repo/energy_coordinator/energy/runtime.py" ]] || fail 'Stažený distribuční repozitář je neúplný.'
grep -Fxq "version: \"$VERSION\"" "$WORK/repo/energy_coordinator/config.yaml" ||
  fail 'Distribuce nemá očekávanou verzi 0.4.1.'
grep -Fxq 'slug: energy_coordinator' "$WORK/repo/energy_coordinator/config.yaml" ||
  fail 'Distribuce má neočekávaný slug.'
tar -czf "$WORK/app.tar.gz" -C "$WORK/repo/energy_coordinator" .
sha256sum "$WORK/app.tar.gz" > "$WORK/app.sha256"

printf '2/7 Vytvářím Supervisor backup dat stávající aplikace...\n'
BACKUP_DIR=$(mktemp -d "$HISTORY/pre-recovery-$VERSION-$(date +%Y%m%d-%H%M%S).XXXXXX")
cli "$WORK/backup.json" backups new --addons "$SLUG" --name "HEC rescue před $VERSION $(date +%Y-%m-%d_%H:%M:%S)" ||
  fail 'Supervisor backup selhal; zdroj nebyl změněn.'
BACKUP_SLUG=$(jq -er '.data.slug | select(type=="string" and length>0)' "$WORK/backup.json") ||
  fail 'Supervisor nepotvrdil identifikátor backupu.'
cli "$WORK/backup-info.json" backups info "$BACKUP_SLUG" || fail 'Nelze ověřit vytvořený backup.'
jq -e --arg slug "$SLUG" '.data.addons | any(.[]; (.slug? // .) == $slug)' "$WORK/backup-info.json" >/dev/null ||
  fail 'Backup neobsahuje local_energy_coordinator.'
printf '%s\n' "$BACKUP_SLUG" > "$BACKUP_DIR/ha-backup-slug.txt"
cp "$WORK/before.json" "$BACKUP_DIR/before.json"

if [[ -e "$DEST" ]]; then
  [[ -d $DEST && ! -L $DEST ]] || fail "Cíl $DEST existuje, ale není běžný adresář."
  HAD_SOURCE=1
  tar -czf "$BACKUP_DIR/source-before.tar.gz" -C "$DEST" .
fi

printf '3/7 Zastavuji pouze local_energy_coordinator...\n'
cli "$WORK/stop.json" addons stop "$SLUG" || fail 'Aplikaci se nepodařilo zastavit.'
cli "$WORK/stopped.json" addons info "$SLUG" || fail 'Nelze ověřit zastavení.'
jq -e '.data.state == "stopped"' "$WORK/stopped.json" >/dev/null || fail 'Supervisor nepotvrdil stav stopped.'

printf '4/7 Obnovuji lokální source adresář z otestované 0.4.1...\n'
if [[ $HAD_SOURCE -eq 1 ]]; then
  mv -- "$DEST" "$BACKUP_DIR/previous-source"
  SOURCE_MOVED=1
fi
mkdir -p "$DEST"
tar -xzf "$WORK/app.tar.gz" -C "$DEST"

printf '5/7 Obnovuji katalog, sestavuji ARM64 image a spouštím aplikaci...\n'
cli "$WORK/reload.json" addons reload || fail 'addons reload selhal.'
cli "$WORK/rebuild.json" addons rebuild "$SLUG" || fail 'rebuild selhal; data zůstávají v Supervisor backupu.'
cli "$WORK/start.json" addons start "$SLUG" || fail 'start nové lokální verze selhal.'

printf '6/7 Ověřuji version=0.4.1 a stabilní started...\n'
for check in 1 2 3; do
  sleep 20
  cli "$WORK/after-$check.json" addons info "$SLUG" || fail 'Nelze ověřit běžící aplikaci.'
  jq -e --arg version "$VERSION" '.data.version == $version and .data.state == "started"' "$WORK/after-$check.json" >/dev/null ||
    fail 'Supervisor nepotvrdil version=0.4.1 a state=started.'
done

printf '7/7 Čekám na portable SQLite backup do /share...\n'
for i in $(seq 1 90); do
  if [[ -s "$PORTABLE" && -s "$PORTABLE_META" ]]; then
    SUCCESS=1
    printf '\nHOTOVO. Lokální aplikace běží na 0.4.1 a portable DB je připravena.\n'
    printf 'Supervisor backup: %s\n' "$BACKUP_SLUG"
    printf 'Portable DB: %s\n' "$PORTABLE"
    printf 'DALŠÍ KROK: přidej do HA App Store repository %s\n' "$PUBLIC_REPO"
    printf 'Potom nainstaluj repo verzi 0.4.1. Starou lokální aplikaci zatím nemaž.\n'
    exit 0
  fi
  sleep 2
done
fail 'Aplikace 0.4.1 běží, ale portable DB nevznikla do 180 s. Repo verzi zatím neinstaluj.'
