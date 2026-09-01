# Hosting der Connect-Website auf sunds-hub

**Live seit 01.09.2026, 16:03 Uhr (Apex) und 16:11 Uhr (www).** Entscheidung Fabrice: "ja oder
ueber server hosten", nachdem GitHub Pages seit 21.08.2026 kein Zertifikat mehr ausstellte (Zustand
"new", www mit TLS-Fehler; alle API-Wege am 01.09. ausgeschoepft, Messwerte in
`ops/github-support-zertifikat.md`, das Ticket ist damit hinfaellig).

## Wie es gebaut ist (Galabau-Muster, /opt/sunds-hub/KONVENTION.md)

| | |
|---|---|
| Server | sunds-hub, 169.58.211.51, Caddy terminiert TLS (Let's Encrypt, erneuert selbst) |
| DNS (Strato) | `sundsconnect.de` A 169.58.211.51; `www` CNAME `sundsconnect.de.`; MX/TXT unveraendert; kein AAAA (Strato bietet fuer diese Domain kein IPv6-Feld) |
| Projektordner | `/opt/sunds-connect-website/` mit `repo.git` (bare), `checkout/`, `site/` (Webroot), `bauen.sh`, `caddy-block.txt`, `umschalt.log` |
| Deploy | `ops/deploy.sh` = `git push origin main` + `git push hub main`; der post-receive-Hook checkt aus und ruft `bauen.sh` (gleiche Kopierliste wie `.github/workflows/deploy.yml`, also ohne ops/, ohne SCHNITTSTELLE-LEADS.md). Gemessen 01.09.: Push bis `/gesund` mit neuem Commit unter 10 s |
| Gesund | `https://sundsconnect.de/gesund` -> `gesund.json` (Commit, Zeit) |
| Caddy | Block in der Caddyfile (Vorlage `caddy-block.txt`); www -> 301 auf Apex; HSTS, nosniff, X-Frame-Options SAMEORIGIN (3D-Hero-iframe); CSP bleibt als Meta in den Seiten |
| Umschaltung | `/opt/sunds-hub/connect-umstellen.sh` hat am 01.09. umgestellt (`NUR_APEX=1`, weil Strato schneller war als der Timer); Timer `sunds-connect-umschalt` ist beendet und deaktiviert |
| GitHub | Repo `sundsoffice-tech/connect` bleibt Quelle; Pages ohne Custom Domain als Zweitausgabe unter https://sundsoffice-tech.github.io/connect/ ; `CNAME` aus Repo und Workflow entfernt |
| Register | `/opt/sunds-hub/projekte.json` -> `connect-website` (Server, Deploy, /gesund eingetragen) |
| Waechter | `/opt/sunds-waechter/ziele.json`: "S&S-Connect-Website (sunds-hub)", www ohne `wartet_auf_entscheidung`, Kontaktformular |

## Formulare nach dem Umzug (gemessen 01.09.2026, 16:13)

- Kontaktformular auf der Live-Seite mit gefuelltem Honigtopf abgeschickt (nichts gespeichert,
  nichts gemailt): `leads.sundsconnect.de/lead` 200, `formspree.io/f/xqeyelgr` 200, Erfolgsmeldung,
  Knopf wieder frei, `herkunft_web` im sessionStorage.
- CORS des Lead-Endpunkts erlaubt `https://sundsconnect.de` und `https://www.sundsconnect.de`
  (kunden.json, unveraendert).
- Selbstauskunftsseiten `d-*/` liefern 200; `d-c8df...` sendet an Formspree (eigene CSP in der Seite).

## Zwei Fallen beim Scharfschalten (BEFUNDE.md Punkt 28)

1. `caddy validate` als root legt die Logdatei des neuen Blocks root:root 600 an; Caddy (Benutzer
   `caddy`) kann sie nicht oeffnen, Reload scheitert. Fix im Skript: `chown caddy:caddy` nach validate.
2. `cp -p` vom 600er Backup zurueck macht `/etc/caddy/Caddyfile` fuer Caddy unlesbar. Fix: Modus vorher
   merken, nach dem Kopieren wiederherstellen. Beide Muster liegen auch in `hub-umstellen.sh`.

## Werkzeuge

- `ops/schirmfoto.mjs`: Headless-Screenshot per CDP (`--scrollen`, `--js`).
- `ops/fernchrome.mjs`: sichtbares Chrome per CDP steuern, wenn die Claude-Erweiterung nicht gekoppelt
  ist (Kontowechsel). Mensch tippt Zugangsdaten selbst. Nach Gebrauch `stop` und das Wegwerf-Profil in
  `%TEMP%\fernchrome-profil` entfernen (enthaelt Sitzungscookies).

## Pruefen

```
curl -s https://sundsconnect.de/gesund
curl -sI https://www.sundsconnect.de/ | head -3          # 301 -> https://sundsconnect.de/
ssh sunds-hub "tail -5 /opt/sunds-connect-website/umschalt.log; sudo journalctl -u caddy -n 20 --no-pager -o cat | grep -i sundsconnect"
```
