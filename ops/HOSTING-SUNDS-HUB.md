# Hosting der Connect-Website auf sunds-hub

Stand 01.09.2026. Entscheidung Fabrice: "ja oder ueber server hosten", nachdem GitHub Pages
seit 21.08.2026 kein Zertifikat mehr ausstellt (Zustand "new", www mit TLS-Fehler, Apex-
Zertifikat laeuft 06.10.2026 ab; alle API-Wege am 01.09. ausgeschoepft, Messwerte in
`ops/github-support-zertifikat.md`).

## Wie es gebaut ist (Galabau-Muster, /opt/sunds-hub/KONVENTION.md)

| | |
|---|---|
| Server | sunds-hub, 169.58.211.51 (IPv6 2a02:c207:3020:4163::1), Caddy terminiert TLS |
| Projektordner | `/opt/sunds-connect-website/` mit `repo.git` (bare), `checkout/`, `site/` (Webroot), `bauen.sh`, `caddy-block.txt`, `umschalt.log` |
| Deploy | `ops/deploy.sh` = `git push origin main` + `git push hub main`; der post-receive-Hook checkt aus und ruft `bauen.sh` (gleiche Kopierliste wie `.github/workflows/deploy.yml`, also ohne ops/, ohne SCHNITTSTELLE-LEADS.md) |
| Gesund | `https://sundsconnect.de/gesund` -> `gesund.json` (Commit, Zeit), schreibt `bauen.sh` |
| Caddy | Block in `caddy-block.txt`; www -> 301 auf Apex; Sicherheitsheader; CSP bleibt als Meta in den Seiten |
| Umschaltung | `/opt/sunds-hub/connect-umstellen.sh` (`--pruefen`, `--umstellen`, `--automatisch`, `--trocken`); Timer `sunds-connect-umschalt` prueft alle 5 Minuten die DNS und schaltet Caddy scharf, sobald Apex und www auf 169.58.211.51 zeigen, dann beendet er sich selbst |
| Register | `/opt/sunds-hub/projekte.json` -> `connect-website` (das Umschaltskript aktualisiert den Eintrag) |
| Waechter | `/opt/sunds-waechter/ziele.json` prueft https://sundsconnect.de/, /contact/ und www; www steht bis zur Umstellung auf "wartet_auf_entscheidung" |

## Was Fabrice bei Strato setzen muss (der einzige Schritt von Hand)

Siehe `/opt/sunds-hub/ANLEITUNG-STRATO-DNS.md`, Abschnitt Connect-Website. Kurz:

```
sundsconnect.de       A     169.58.211.51            (statt 185.199.108.153)
sundsconnect.de       AAAA  2a02:c207:3020:4163::1   (neu, wie galabaupremio.de)
www.sundsconnect.de   A     169.58.211.51            (statt CNAME sundsoffice-tech.github.io)
www.sundsconnect.de   AAAA  2a02:c207:3020:4163::1   (neu)
MX und TXT unveraendert lassen.
```

Danach passiert alles automatisch: Timer erkennt die DNS, haengt den Caddy-Block an, Caddy
holt die Zertifikate, `/gesund` antwortet, Register wird fortgeschrieben. Waehrend der DNS-
Verbreitung liefert GitHub Pages den identischen Stand weiter aus (kein Ausfall).

## Danach (Mensch, einmalig)

- Wenn `dig +short A sundsconnect.de @8.8.8.8` und `@1.1.1.1` beide 169.58.211.51 zeigen:
  Custom Domain im GitHub-Repo `connect` entfernen
  (`gh api -X PUT repos/sundsoffice-tech/connect/pages -F cname=null`) und die Datei `CNAME`
  aus dem Repo nehmen. GitHub Pages bleibt als Zweitausgabe unter
  sundsoffice-tech.github.io/connect/ bestehen.
- Waechter-Ziel "S&S-Connect-Website (GitHub Pages)" umbenennen, `wartet_auf_entscheidung`
  bei www entfernen.

## Pruefen

```
ssh sunds-hub "sudo /opt/sunds-hub/connect-umstellen.sh --pruefen"
ssh sunds-hub "tail -5 /opt/sunds-connect-website/umschalt.log; cat /opt/sunds-connect-website/site/gesund.json"
curl -s --resolve sundsconnect.de:443:169.58.211.51 https://sundsconnect.de/gesund
```
