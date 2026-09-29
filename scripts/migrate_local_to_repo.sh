#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

VERSION="0.5.0"
REPO="https://github.com/inenger/home-energy-coordinator-ha"
APP_ROOT="${HEC_APP_ROOT:-/local_apps}"
WORK=""
trap '[[ -z "${WORK:-}" || ! -d "$WORK" ]] || rm -rf -- "$WORK"' EXIT

fail() {
  printf '\nCHYBA: %s\n' "$*" >&2
  exit 1
}

for c in curl tar sha256sum awk bash ha jq grep mktemp; do
  command -v "$c" >/dev/null || fail "Chybí příkaz $c. Nic nezměněno."
done

[[ -d "$APP_ROOT" && ! -L "$APP_ROOT" ]] || fail "Chybí adresář lokálních aplikací $APP_ROOT. Nic neměním."
if [[ -z ${HEC_APP_ROOT:-} ]]; then
  awk -v path="$APP_ROOT" '$5 == path { found=1 } END { exit !found }' /proc/self/mountinfo ||
    fail "$APP_ROOT není připojený adresář lokálních aplikací. Nic neměním."
fi

WORK=$(mktemp -d /tmp/hec-migrate.XXXXXX)

printf 'Stahuji veřejný HA repository release %s...\n' "$VERSION"
curl -fL --retry 3 --connect-timeout 15   "$REPO/archive/refs/heads/main.tar.gz"   -o "$WORK/repo.tar.gz"

mkdir "$WORK/repo"
tar -xzf "$WORK/repo.tar.gz" -C "$WORK/repo" --strip-components=1

[[ -f "$WORK/repo/energy_coordinator/config.yaml" ]] ||
  fail 'Stažený HA repository neobsahuje config.yaml.'
[[ -f "$WORK/repo/scripts/upgrade_local_app.sh" ]] ||
  fail 'Stažený HA repository neobsahuje upgrade_local_app.sh.'
[[ -f "$WORK/repo/scripts/recover_missing_local_source.sh" ]] ||
  fail 'Stažený HA repository neobsahuje rescue skript.'

grep -Fxq "version: \"$VERSION\"" "$WORK/repo/energy_coordinator/config.yaml" ||
  fail "Repo neobsahuje očekávanou verzi $VERSION."

tar -czf "$WORK/app.tar.gz" -C "$WORK/repo/energy_coordinator" .
SHA=$(sha256sum "$WORK/app.tar.gz" | awk '{print $1}')

FOUND=0
for candidate in "$APP_ROOT"/*; do
  [[ -d "$candidate" && ! -L "$candidate" && -f "$candidate/config.yaml" ]] || continue
  if grep -Eq '^[[:space:]]*slug:[[:space:]]*"?energy_coordinator"?[[:space:]]*$' "$candidate/config.yaml"; then
    FOUND=$((FOUND+1))
  fi
done

if [[ $FOUND -eq 0 ]]; then
  printf 'Lokální source pod /addons chybí; přepínám na rescue postup.\n'
  bash "$WORK/repo/scripts/recover_missing_local_source.sh"
  exit $?
fi

if [[ $FOUND -gt 1 ]]; then
  fail 'Nalezeno více source adresářů pro energy_coordinator; odmítám hádat.'
fi

printf 'Povyšuji stávající lokální aplikaci na %s a vytvářím HA backup...\n' "$VERSION"
bash "$WORK/repo/scripts/upgrade_local_app.sh"   "$WORK/app.tar.gz" "$SHA" "$VERSION"

printf 'Čekám na konzistentní portable databázi v /share...\n'
for _ in $(seq 1 90); do
  if [[ -s /share/home-energy-coordinator/evidence.sqlite &&
        -s /share/home-energy-coordinator/evidence.json ]]; then
    printf '\nHOTOVO. Portable databáze je připravena.\n'
    printf 'DALŠÍ KROK: přidej do HA App Store repository:\n%s\n' "$REPO"
    printf 'Před prvním startem repo verze zastav local_energy_coordinator; starou app zatím nemaž.\n'
    exit 0
  fi
  sleep 2
done

fail 'Portable databáze nevznikla do 180 s. Starou aplikaci nemaž.'
