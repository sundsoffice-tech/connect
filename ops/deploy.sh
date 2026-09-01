#!/usr/bin/env bash
# deploy.sh -- Connect-Website veroeffentlichen: erst GitHub (Quelle, Pages-Zweitausgabe),
# dann sunds-hub (post-receive-Hook baut /opt/sunds-connect-website/site synchron).
# Scheitert der Push zum Hub, ist dort NICHTS halb live (Galabau-Muster).
#
#   ops/deploy.sh                 pusht den aktuellen Stand von main
#   ops/deploy.sh "Nachricht"     committet vorher alles Offene mit dieser Nachricht
set -euo pipefail
cd "$(dirname "$0")/.."
if [ -n "${1:-}" ]; then
    git add -A
    git commit -q -m "$1" || true
fi
[ "$(git branch --show-current)" = "main" ] || { echo "nicht auf main" >&2; exit 2; }
git remote get-url hub >/dev/null 2>&1 || git remote add hub sunds-hub:/opt/sunds-connect-website/repo.git
echo "-> GitHub (origin)"; git push origin main
echo "-> sunds-hub (hub)";  git push hub main
echo "-> Probe"
curl -s -m 10 --resolve sundsconnect.de:443:169.58.211.51 https://sundsconnect.de/gesund 2>/dev/null \
    || echo "(Hub antwortet noch nicht ueber die Domain: DNS zeigt noch auf GitHub, siehe ops/HOSTING-SUNDS-HUB.md)"
