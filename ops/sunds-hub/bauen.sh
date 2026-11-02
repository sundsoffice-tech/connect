#!/usr/bin/env bash
# bauen.sh -- baut den Webroot der Connect-Website aus dem Checkout. Kopiert wird nur, was in
# ops/veroeffentlichen.liste steht, nichts Internes (kein ops/, kein SCHNITTSTELLE-LEADS.md, kein .git).
#
# Repo-Fassung: ops/sunds-hub/bauen.sh. Eingesetzt wird sie von Hand im Rollout als
# /opt/sunds-connect-website/bauen.sh; ein Push aendert die Server-Fassung nicht.
#
#   bauen.sh                               vom post-receive-Hook mit COMMIT=<sha>; laeuft als ubuntu
#   bauen.sh --nur-kopieren <quelle> <ziel>  nur Liste pruefen und kopieren (Pruefschritt in .github/workflows/deploy.yml)
#
# Ablauf: Liste pruefen, blog.py pruefen, kopieren, tauschen. Jeder Abbruch vor dem Tausch laesst
# den laufenden Webroot unberuehrt.
# Exit: 0 gebaut, 2 falscher Aufruf, 3 Liste ungueltig, 4 blog.py pruefen nicht gruen.
#
# Der post-receive-Hook laeuft NACH dem Umsetzen der Referenz, und git wertet seinen Exit-Code nicht aus:
# Nach einem Abbruch steht repo.git/main und checkout schon auf dem neuen Commit, und ein zweiter
# Push desselben Commits startet keinen Bau. ops/deploy.sh erkennt das am Commit in /gesund.
set -euo pipefail

LISTE=ops/veroeffentlichen.liste

abbruch() {
    local code=$1
    shift
    echo "bauen.sh ABBRUCH: $*" >&2
    exit "$code"
}

name_pruefen() {
    local name=$1 stelle=$2
    case "$name" in
        */* | *..* | ops | .git)
            abbruch 3 "$stelle: '$name' ist nicht erlaubt (kein /, kein .., nicht ops, nicht .git)" ;;
    esac
    [[ $name =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] ||
        abbruch 3 "$stelle: '$name' ist kein einfacher Name (erlaubt: Buchstaben, Ziffern, . _ -)"
}

# Fuellt NAMEN aus der Liste. Bricht ab, bevor irgendetwas kopiert ist.
liste_lesen() {
    local quelle=$1 datei="$1/$LISTE" zeile nr=0 art muster pfad name
    NAMEN=()
    [ -f "$datei" ] || abbruch 3 "$datei fehlt. Stand ohne Liste (etwa nach einem Revert): erst die alte bauen.sh einsetzen, dann deployen"
    while IFS= read -r zeile || [ -n "$zeile" ]; do
        nr=$((nr + 1))
        case "$zeile" in
            '' | '#'*) continue ;;
            'ordner-muster '* | 'datei-muster '*)
                art=${zeile%% *}
                muster=${zeile#* }
                for pfad in "$quelle"/*; do
                    name=${pfad##*/}
                    [[ $name =~ $muster ]] || continue
                    if [ "$art" = ordner-muster ]; then [ -d "$pfad" ] || continue; else [ -f "$pfad" ] || continue; fi
                    name_pruefen "$name" "$LISTE:$nr"
                    NAMEN+=("$name")
                done
                ;;
            *)
                name_pruefen "$zeile" "$LISTE:$nr"
                [ -e "$quelle/$zeile" ] || abbruch 3 "$LISTE:$nr: '$zeile' fehlt im Checkout"
                NAMEN+=("$zeile")
                ;;
        esac
    done <"$datei"
    [ -f "$quelle/index.html" ] && printf '%s\n' "${NAMEN[@]}" | grep -qx index.html ||
        abbruch 3 "$LISTE: index.html fehlt in Liste oder Checkout"
    for name in "${NAMEN[@]}"; do
        # Riegel: ein Entwurf geht nicht auf die Domain, auch wenn er versehentlich gelistet ist
        if [ -e "$quelle/$name/ENTWURF.txt" ]; then
            abbruch 3 "$LISTE: '$name' ist ein Entwurf ($name/ENTWURF.txt); erst freigeben, dann listen"
        fi
        # Ein Symlink im Checkout koennte Dateien von ausserhalb in den Webroot ziehen
        if [ -n "$(find "$quelle/$name" -type l -print -quit)" ]; then
            abbruch 3 "$LISTE: '$name' enthaelt einen symbolischen Link; das ist nicht erlaubt"
        fi
    done
}

kopieren() {
    local quelle=$1 ziel=$2 name
    for name in "${NAMEN[@]}"; do
        cp -r "$quelle/$name" "$ziel/"
    done
}

if [ "${1:-}" = "--nur-kopieren" ]; then
    [ $# -eq 3 ] || abbruch 2 "Aufruf: bauen.sh --nur-kopieren <quelle> <ziel>"
    liste_lesen "$2"
    mkdir -p "$3"
    kopieren "$2" "$3"
    exit 0
fi
[ $# -eq 0 ] || abbruch 2 "unbekannte Angabe: $1"

# Der Ordner, in dem das Skript liegt: im Betrieb /opt/sunds-connect-website. Eine Kopie zum Proben
# kann so den echten Webroot nicht treffen.
WURZEL=$(cd "$(dirname "$0")" && pwd -P)
QUELLE=$WURZEL/checkout
ZIEL=$WURZEL/site
NEU=$ZIEL.neu
ALT=$ZIEL.alt
COMMIT=${COMMIT:-$(git --git-dir="$WURZEL/repo.git" rev-parse --short main 2>/dev/null || echo unbekannt)}

# Zwei Kopien dieses Skripts (Server und Repo): Abweichung melden, nicht abbrechen.
cmp -s "$0" "$QUELLE/ops/sunds-hub/bauen.sh" ||
    echo "bauen.sh WARNUNG: $0 weicht von ops/sunds-hub/bauen.sh im Checkout ab (md5sum und diff in beide Richtungen, Skill rollout)" >&2

liste_lesen "$QUELLE"

# Blog pruefen, solange der alte Webroot noch steht. Seine Sitemap ist die letzte Veroeffentlichung.
VORHER=()
[ -f "$ZIEL/sitemap.xml" ] && VORHER=(--vorher "$ZIEL/sitemap.xml")
rc=0
(cd "$QUELLE" && PYTHONDONTWRITEBYTECODE=1 timeout "${BAUEN_PRUEF_SEKUNDEN:-120}" python3 ops/blog/blog.py pruefen "${VORHER[@]}") || rc=$?
if [ "$rc" -ne 0 ]; then
    abbruch 4 "blog.py pruefen Exit $rc bei Commit ${COMMIT:0:7}. Der Webroot bleibt unveraendert: $(cat "$ZIEL/gesund.json" 2>/dev/null || echo 'kein gesund.json'). Nach der Behebung braucht es einen neuen Commit, ein zweiter Push desselben Commits baut nicht"
fi

python3 - "$NEU" "$ALT" <<'EOF'
import shutil, sys, os
for p in sys.argv[1:]:
    if os.path.isdir(p):
        shutil.rmtree(p)
EOF
mkdir -p "$NEU"

kopieren "$QUELLE" "$NEU"

printf '{"status":"ok","projekt":"connect-website","commit":"%s","zeit":"%s"}\n' \
    "${COMMIT:0:7}" "$(date -Is)" > "$NEU/gesund.json"
chmod -R a+rX "$NEU"

# Atomar tauschen: erst das Neue an die Stelle des Alten, dann das Alte weg
if [ -d "$ZIEL" ]; then mv "$ZIEL" "$ALT"; fi
mv "$NEU" "$ZIEL"
python3 - "$ALT" <<'EOF'
import shutil, sys, os
if os.path.isdir(sys.argv[1]):
    shutil.rmtree(sys.argv[1])
EOF

echo "gebaut: $ZIEL ($(find "$ZIEL" -type f | wc -l) Dateien, Commit ${COMMIT:0:7})"
