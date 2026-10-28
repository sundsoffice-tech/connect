# stempel.py -- Versionsstempel gegen den 24-Stunden-Cache.
#
# Caddy auf sunds-hub liefert /css und /js mit "Cache-Control: public, max-age=86400".
# Ohne Stempel zeigt ein Browser nach einem Deploy bis zu einen Tag das alte CSS
# (gemessen 28.10.2026: Fabrice sah am Desktop den alten Stand, der Server war aktuell).
# Dieses Skript schreibt in jede HTML-Datei ?v=<stempel> hinter css/style.css und
# js/main.js; ein neuer Stempel ersetzt den alten. ops/deploy.sh ruft es vor dem Push.
#
#   python ops/stempel.py            Stempel = Datum und Uhrzeit (JJJJMMTT-HHMM)
#   python ops/stempel.py 1a2b3c4    eigener Stempel
import io, os, re, sys, datetime

WURZEL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
stempel = sys.argv[1] if len(sys.argv) > 1 else datetime.datetime.now().strftime("%Y%m%d-%H%M")
muster = re.compile(r'((?:\.\./|\./)?(?:css/style\.css|js/main\.js))(?:\?v=[\w.-]+)?')
geaendert = 0
for ordner, unter, dateien in os.walk(WURZEL):
    unter[:] = [u for u in unter if u not in (".git", "node_modules", "ops")]
    for name in dateien:
        if not name.endswith(".html"):
            continue
        pfad = os.path.join(ordner, name)
        alt = io.open(pfad, encoding="utf-8", newline="").read()
        neu = muster.sub(lambda m: m.group(1) + "?v=" + stempel, alt)
        if neu != alt:
            io.open(pfad, "w", encoding="utf-8", newline="").write(neu)
            geaendert += 1
print("Stempel", stempel, "in", geaendert, "HTML-Dateien")
