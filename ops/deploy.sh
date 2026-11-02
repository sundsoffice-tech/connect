#!/usr/bin/env bash
# deploy.sh -- Connect-Website veroeffentlichen: erst GitHub (Quelle; die CI prueft nur),
# dann sunds-hub (post-receive-Hook baut /opt/sunds-connect-website/site synchron).
# Scheitert der Bau auf dem Hub, ist dort NICHTS halb live (Galabau-Muster). git push meldet
# das nicht, weil git den Exit-Code von post-receive nicht auswertet; deshalb vergleicht der
# Schluss den Commit in /gesund mit HEAD, Exit 1 bei Abweichung.
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
python ops/stempel.py >/dev/null && git add -A -- "*.html" && { git commit -q -m "chore(stempel): Versionsstempel $(date +%Y%m%d-%H%M)" || true; }
# Vor dem ersten Push, nach dem Stempel: bei Rot verlaesst nichts den PC. Auf dem Hub setzt ein roter Bau
# die Referenz trotzdem um, und ein zweiter Push desselben Commits baut nicht mehr.
vorher=$(mktemp)
git show origin/main:sitemap.xml > "$vorher"
if ! python ops/blog/blog.py pruefen --vorher "$vorher"; then
    rm -f "$vorher"
    echo "blog.py pruefen rot: nichts gepusht" >&2
    exit 1
fi
rm -f "$vorher"
echo "-> GitHub (origin)"; git push origin main
echo "-> sunds-hub (hub)";  git push hub main
echo "-> Probe"
soll=$(git rev-parse HEAD | cut -c1-7)
antwort=$(curl -s -m 10 --resolve sundsconnect.de:443:169.58.211.51 https://sundsconnect.de/gesund || true)
echo "$antwort"
case "$antwort" in
    *"\"commit\":\"$soll\""*) echo "live: $soll" ;;
    *) echo "FEHLER: /gesund zeigt nicht Commit $soll. Der Bau auf dem Hub ist gescheitert, der alte Webroot laeuft weiter; Grund steht oben in den remote-Zeilen. Danach neuer Commit, ein zweiter Push desselben Commits baut nicht." >&2
       exit 1 ;;
esac
