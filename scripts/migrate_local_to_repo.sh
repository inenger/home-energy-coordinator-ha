#!/usr/bin/env bash
set -Eeuo pipefail
VERSION=0.4.1
REPO=https://github.com/inenger/home-energy-coordinator-ha
WORK=$(mktemp -d /tmp/hec-migrate.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
for c in curl tar sha256sum awk bash ha jq; do command -v "$c" >/dev/null || { echo "CHYBA: chybí $c" >&2; exit 1; }; done
echo "Stahuji veřejný HA repository release $VERSION..."
curl -fL --retry 3 --connect-timeout 15 "$REPO/archive/refs/heads/main.tar.gz" -o "$WORK/repo.tar.gz"
mkdir "$WORK/repo"
tar -xzf "$WORK/repo.tar.gz" -C "$WORK/repo" --strip-components=1
grep -Fxq "version: \"$VERSION\"" "$WORK/repo/energy_coordinator/config.yaml" || { echo "CHYBA: repo neobsahuje očekávanou verzi $VERSION" >&2; exit 1; }
tar -czf "$WORK/app.tar.gz" -C "$WORK/repo/energy_coordinator" .
SHA=$(sha256sum "$WORK/app.tar.gz" | awk '{print $1}')
# If the original local source directory disappeared during an older failed upgrade,
# use the dedicated rescue path. Supervisor data are backed up before any source change.
FOUND=0
for candidate in /addons/*; do
  [[ -d $candidate && -f $candidate/config.yaml ]] || continue
  if grep -Eq '^[[:space:]]*slug:[[:space:]]*"?energy_coordinator"?[[:space:]]*bash "$WORK/repo/scripts/upgrade_local_app.sh" "$WORK/app.tar.gz" "$SHA" "$VERSION"
echo "Čekám na konzistentní portable databázi v /share..."
for i in $(seq 1 90); do
  if [[ -s /share/home-energy-coordinator/evidence.sqlite && -s /share/home-energy-coordinator/evidence.json ]]; then
    echo "Portable databáze je připravena."
    echo "DALŠÍ KROK: v HA přidej repository $REPO, nainstaluj Energetický koordinátor 0.4.1 z tohoto repa a spusť ho."
    echo "Nová repo aplikace při prvním startu portable databázi automaticky načte."
    echo "Starou local_energy_coordinator zatím NEODINSTALOVÁVEJ; nejdřív ověř data v nové aplikaci."
    exit 0
  fi
  sleep 2
done
echo "CHYBA: portable databáze nevznikla do 180 s. Starou aplikaci nemaž." >&2
exit 1
 "$candidate/config.yaml"; then
    FOUND=$((FOUND+1))
  fi
done
if [[ $FOUND -eq 0 ]]; then
  echo "Lokální source pod /addons chybí; přepínám na otestovaný rescue postup."
  bash "$WORK/repo/scripts/recover_missing_local_source.sh"
  exit $?
fi
if [[ $FOUND -gt 1 ]]; then
  echo "CHYBA: nalezeno více source adresářů pro energy_coordinator; odmítám hádat." >&2
  exit 1
fi

echo "Povyšuji stávající lokální aplikaci na $VERSION a vytvářím HA backup..."
bash "$WORK/repo/scripts/upgrade_local_app.sh" "$WORK/app.tar.gz" "$SHA" "$VERSION"
echo "Čekám na konzistentní portable databázi v /share..."
for i in $(seq 1 90); do
  if [[ -s /share/home-energy-coordinator/evidence.sqlite && -s /share/home-energy-coordinator/evidence.json ]]; then
    echo "Portable databáze je připravena."
    echo "DALŠÍ KROK: v HA přidej repository $REPO, nainstaluj Energetický koordinátor 0.4.1 z tohoto repa a spusť ho."
    echo "Nová repo aplikace při prvním startu portable databázi automaticky načte."
    echo "Starou local_energy_coordinator zatím NEODINSTALOVÁVEJ; nejdřív ověř data v nové aplikaci."
    exit 0
  fi
  sleep 2
done
echo "CHYBA: portable databáze nevznikla do 180 s. Starou aplikaci nemaž." >&2
exit 1
