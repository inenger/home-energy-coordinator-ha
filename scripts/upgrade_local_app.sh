#!/usr/bin/env bash
# Upgrade only the existing HEC local application. No uninstallation, data restore or Core restart.
# Usage: bash upgrade_local_app.sh SOURCE.tar.gz SHA256 VERSION
set -Eeuo pipefail
umask 077
APP_ROOT=/addons
SLUG=local_energy_coordinator
DEST=""
HISTORY=/share/hec-upgrades
ARCHIVE=${1:-}
EXPECTED_SHA=${2:-}
VERSION=${3:-}
WORK=''
BACKUP_DIR=''
LOCKED=0
STOPPED=0
SOURCE_MOVED=0
NEW_SOURCE=0
SUCCESS=0
PREVIOUS_STATE=''
HA=(ha --raw-json --no-progress --log-level error)
fail() { printf '\nCHYBA: %s\n' "$*" >&2; exit 1; }
cli() {
  local outfile=$1; shift
  "${HA[@]}" "$@" > "$outfile" || return 1
  jq -e '.result == "ok"' "$outfile" >/dev/null || return 1
}
cleanup() {
  local rc=$?
  trap - EXIT INT TERM
  if [[ $SUCCESS -ne 1 && $SOURCE_MOVED -eq 1 ]]; then
    printf '\nUpgrade nebyl potvrzen. Obnovuji pouze předchozí zdroj aplikace.\n' >&2
    if cli "$WORK/rollback-stop.json" addons stop "$SLUG"; then
      if [[ -d "$DEST" ]]; then
        mv -- "$DEST" "$BACKUP_DIR/failed-source" || { printf 'Nelze odložit nový zdroj. Obnova vyžaduje kontrolu.\n' >&2; exit 1; }
      fi
      if [[ ! -e "$DEST" ]] && mv -- "$BACKUP_DIR/previous-source" "$DEST"; then
        if cli "$WORK/rollback-reload.json" addons reload && cli "$WORK/rollback-build.json" addons rebuild "$SLUG"; then
          if [[ $PREVIOUS_STATE != started ]] || cli "$WORK/rollback-start.json" addons start "$SLUG"; then
            printf 'Předchozí zdroj byl obnoven. Zkontroluj provoz v HA. Databáze nebyla přepsána.\n' >&2
          else printf 'Zdroj obnoven, ale start nepotvrzen. Otevři protokol aplikace v HA.\n' >&2; fi
        else printf 'Zdroj obnoven, ale rebuild selhal. Záloha: %s\n' "$BACKUP_DIR" >&2; fi
      else printf 'Automatická obnova zdroje selhala. Záloha: %s\n' "$BACKUP_DIR" >&2; fi
    else
      printf 'Nelze potvrdit zastavení. Zdroj neměním za běhu; použij zálohu %s.\n' "$BACKUP_DIR" >&2
    fi
    rc=1
  elif [[ $SUCCESS -ne 1 && $STOPPED -eq 1 && $PREVIOUS_STATE == started ]]; then
    cli "$WORK/restart-previous.json" addons start "$SLUG" || true
    rc=1
  fi
  if [[ -n $WORK && -d $WORK && -n $BACKUP_DIR ]]; then
    # Diagnostic JSON may include app options: the backup directory is private, never upload it publicly.
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
  command -v "$command" >/dev/null || fail "Chybí příkaz $command; aplikace nebyla změněna."
done
[[ -f $ARCHIVE && $EXPECTED_SHA =~ ^[0-9a-f]{64}$ && $VERSION =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'Neplatný balíček, kontrolní součet nebo verze.'

# Local app source directory is not guaranteed to equal the Supervisor slug.
# Discover exactly one local source by its own config.yaml slug instead of guessing a path.
CANDIDATES=()
for candidate in "$APP_ROOT"/*; do
  [[ -d $candidate && ! -L $candidate && -f $candidate/config.yaml ]] || continue
  if grep -Eq '^[[:space:]]*slug:[[:space:]]*"?energy_coordinator"?[[:space:]]*$' "$candidate/config.yaml"; then
    CANDIDATES+=("$candidate")
  fi
done
if [[ ${#CANDIDATES[@]} -eq 0 ]]; then
  fail "Nenalezen lokální zdroj se slugem energy_coordinator pod $APP_ROOT. Nic nezměněno."
fi
if [[ ${#CANDIDATES[@]} -ne 1 ]]; then
  printf 'Kandidáti:\n' >&2
  printf '  %s\n' "${CANDIDATES[@]}" >&2
  fail 'Nalezeno více zdrojových adresářů pro energy_coordinator; odmítám hádat.'
fi
DEST="${CANDIDATES[0]}"
printf 'Nalezen zdroj lokální aplikace: %s\n' "$DEST"

[[ $(sha256sum "$ARCHIVE" | awk '{print $1}') == "$EXPECTED_SHA" ]] || fail 'Nesouhlasí SHA-256. Nic nezměněno.'
mkdir "$APP_ROOT/.hec-upgrade-lock" 2>/dev/null || fail 'Jiný upgrade již běží, nebo zůstal jeho zámek. Nic nezměněno.'
LOCKED=1
WORK=$(mktemp -d /tmp/hec-upgrade.XXXXXX)
mkdir "$WORK/stage"
# The hash pins the tested archive; also reject absolute/parent paths and special entries.
tar -tzf "$ARCHIVE" > "$WORK/paths"
if grep -Eq '(^/|(^|/)\.\.(/|$))' "$WORK/paths"; then fail 'Nebezpečná cesta v archivu.'; fi
if tar -tvzf "$ARCHIVE" | awk 'substr($0,1,1)!="-" && substr($0,1,1)!="d" {bad=1} END {exit bad?0:1}'; then fail 'Speciální soubor nebo odkaz v archivu.'; fi
tar -xzf "$ARCHIVE" -C "$WORK/stage"
grep -Fxq "version: \"$VERSION\"" "$WORK/stage/config.yaml" || fail 'Nesouhlasí verze v konfiguraci balíčku.'
grep -Fxq 'slug: energy_coordinator' "$WORK/stage/config.yaml" || fail 'Nesouhlasí slug aplikace.'
[[ -f $WORK/stage/Dockerfile && -f $WORK/stage/energy/runtime.py ]] || fail 'Neúplný balíček.'
cli "$WORK/system.json" info || fail 'Home Assistant CLI nekomunikuje se Supervisorem. Nic nezměněno.'
jq -e '.data.arch == "aarch64" and .data.machine == "raspberrypi4-64"' "$WORK/system.json" >/dev/null || fail 'Tento balíček je určen pro HA OS na 64bitovém RPi4.'
cli "$WORK/before.json" addons info "$SLUG" || fail 'Nelze načíst stávající aplikaci.'
PREVIOUS_STATE=$(jq -r '.data.state' "$WORK/before.json")
[[ $PREVIOUS_STATE == started || $PREVIOUS_STATE == stopped ]] || fail 'Aplikace právě mění stav. Vyčkej na dokončení předchozí operace.'

mkdir -p "$HISTORY"
BACKUP_DIR=$(mktemp -d "$HISTORY/pre-$VERSION-$(date +%Y%m%d-%H%M%S).XXXXXX")
printf '1/6 Vytvářím zálohu pouze Energetického koordinátoru včetně jeho dat...\n'
cli "$WORK/backup.json" backups new --addons "$SLUG" --name "HEC před $VERSION $(date +%Y-%m-%d_%H:%M:%S)" || fail 'Záloha se nezdařila; zdroj nebyl změněn.'
BACKUP_SLUG=$(jq -er '.data.slug | select(type=="string" and length>0)' "$WORK/backup.json") || fail 'Supervisor nepotvrdil dokončenou zálohu.'
cli "$WORK/backup-info.json" backups info "$BACKUP_SLUG" || fail 'Nelze ověřit vytvořenou zálohu.'
jq -e --arg slug "$SLUG" '.data.addons | any(.[]; (.slug? // .) == $slug)' "$WORK/backup-info.json" >/dev/null || fail 'Záloha neobsahuje očekávanou aplikaci.'
printf '%s\n' "$BACKUP_SLUG" > "$BACKUP_DIR/ha-backup-slug.txt"
tar -czf "$BACKUP_DIR/source.tar.gz" -C "$DEST" .
cp "$WORK/before.json" "$BACKUP_DIR/before.json"
printf 'Záloha dat HA: %s | záloha zdroje: %s\n' "$BACKUP_SLUG" "$BACKUP_DIR"

printf '2/6 Zastavuji pouze Energetický koordinátor...\n'
cli "$WORK/stop.json" addons stop "$SLUG" || fail 'Zastavení selhalo; zdroj neměním.'
STOPPED=1
cli "$WORK/stopped.json" addons info "$SLUG" || fail 'Nelze ověřit zastavení.'
jq -e '.data.state == "stopped"' "$WORK/stopped.json" >/dev/null || fail 'Zastavení nebylo potvrzeno.'
printf '3/6 Měním pouze zdroj; trvalý svazek s databází zůstává...\n'
mv -- "$DEST" "$BACKUP_DIR/previous-source"
SOURCE_MOVED=1
mv -- "$WORK/stage" "$DEST"
NEW_SOURCE=1
printf '4/6 Obnovuji katalog a sestavuji obraz; Python a testy běží uvnitř obrazu...\n'
cli "$WORK/reload.json" addons reload || fail 'Obnovení katalogu selhalo.'
cli "$WORK/build.json" addons rebuild "$SLUG" || fail 'Sestavení selhalo; spouštím obnovu původního zdroje.'
printf '5/6 Spouštím novou verzi...\n'
cli "$WORK/start.json" addons start "$SLUG" || fail 'Start selhal.'
printf '6/6 Kontroluji verzi a stabilní stav po dobu 60 sekund...\n'
for check in 1 2 3; do
  sleep 20
  cli "$WORK/after-$check.json" addons info "$SLUG" || fail 'Nelze ověřit novou aplikaci.'
  jq -e --arg version "$VERSION" '.data.version == $version and .data.state == "started"' "$WORK/after-$check.json" >/dev/null || fail 'Supervisor nepotvrdil očekávanou verzi a stav.'
done
SUCCESS=1
printf '\nHOTOVO: Supervisor hlásí %s a started.\n' "$VERSION"
printf 'Otevři webové rozhraní a ověř čerstvý čas sběru a počasí; toto není důkaz správnosti fyzických měření.\n'
printf 'Data nebyla mazána ani obnovována. Záloha a diagnostika: %s\n' "$BACKUP_DIR"
