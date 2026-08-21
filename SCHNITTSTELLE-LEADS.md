# Schnittstelle Connect-Website → Lead-Endpunkt (sunds-hub)

Vertrag nach `/opt/sunds-hub/KONVENTION.md` § 8. Kopien: hier (Repo der Website,
`sundsoffice-tech/connect`), `/opt/sunds-hub/schnittstellen/connect-website-leads.md`
(Server) und `/opt/sunds-leads/SCHNITTSTELLE-CONNECT-WEBSITE.md` (Projektordner des
Endpunkts). Registereintrag: `projekte.json` → `connect-website` (braucht) und `leads`
(bietet). Muster: `ss-messebau-website/SCHNITTSTELLE-LEADS.md`.

Stand: 2026-08-21 · Entscheidung (Messebau-Muster): **parallel zu Formspree**, bis der
Lead-Weg vier Wochen sauber läuft. Danach wird entschieden, ob Formspree bleibt.

## 1 · Was die Website braucht und warum

Das Kontaktformular (`contact/index.html`, `js/main.js`) schickt heute per Formspree
(`xqeyelgr`) eine Mail. Fällt Formspree aus oder landet die Mail im Spam, existiert die
Anfrage nirgends — und niemand merkt es. Der Lead-Endpunkt dreht die Reihenfolge um:
**speichern (fsync), dann 200, dann Mail, bei Fehler alle 5 min nachsenden + ntfy.** Die
Website sendet **zusätzlich**, nie statt. Erfolgsbedingung des Formulars: Formspree
**oder** Lead-Endpunkt hat angenommen; erst wenn beide scheitern, sieht der Besucher die
Fehlermeldung. Danach läuft der Lead automatisch: Website → leads → anfragen (Filter
Firma connect) → Cockpit (Kachel „Anfragen").

## 2 · Der Aufruf

```
POST https://leads.sundsconnect.de/lead
Origin: https://sundsconnect.de   (Browser setzt ihn; Endpunkt prüft gegen kunden.json)
Content-Type: application/json
{
  "kunde":     "connect",
  "name":      "Erika Muster",                  Pflicht, ≥ 2 Zeichen, ≤ 120
  "telefon":   "+49 2161 123456" | "",          optional (telefon_pflicht=false), ≤ 60
  "email":     "erika@example.org",             Pflicht auf der Website; ≤ 180
  "firma":     "",                              Website hat kein Firmenfeld
  "plz":       "",                              Website hat kein PLZ-Feld
  "nachricht": "…",                             ≤ 4000, siehe § 3
  "seite":     "/contact/",                     ≤ 300, Pfad der Seite
  "botcheck":  ""                               Honigtopf, MUSS leer bleiben
}
→ 200 {"ok": true, "vorgang": "a1b2c3d4e5"}     gespeichert (Mail folgt)
→ 200 {"ok": true}                              Honigtopf gefüllt: NICHTS gespeichert
→ 400 {"ok": false, "fehler": "…"}              Validierung (Text ist für Besucher formuliert)
→ 403 {"ok": false, "fehler": "Herkunft nicht freigegeben"}
→ 413 Nutzlast > 16 KB · 429 mehr als 5 Anfragen/IP/Stunde · 500 technischer Fehler
```

**Zusagenliste (KONVENTION § 8.4):** Die Website sendet genau diese neun Schlüssel und
keinen weiteren (`buildLeadPayload` in `js/main.js`; geprüft mit Node gegen die sortierte
Schlüsselliste).

## 3 · Abbildung Website → Endpunkt

| Website-Feld | Lead-Feld | Hinweis |
|---|---|---|
| `name` | `name` | |
| `phone` | `telefon` | optional |
| `email` | `email` | Pflicht auf der Website |
| `message` | `nachricht` (Kopf) | |
| `subject` (general/vertrieb/automation/ai/project) | `nachricht` (Block „— Angaben aus dem Formular —", Zeile `Betreff: <Label>`) | deutsches Label |
| `dsgvo-consent` | — | wird clientseitig geprüft, nicht übertragen (Formspree bekommt es weiter) |
| `_gotcha` (unsichtbares Feld, Formspree-Konvention) | `botcheck` | Honigtopf — Formspree verwirft gefüllte Einsendungen selbst (204), der Endpunkt antwortet 200 ohne `vorgang` |
| `window.location.pathname` | `seite` | |

Implementierung: `js/main.js` (`buildLeadPayload`, `relayLeadToHub`); wirft nie
(`fetch … .catch(() => false)`, `keepalive: true`). Aufruf **parallel** zu Formspree
(`Promise.all`).

## 4 · Was der Endpunkt dafür zugesagt hat (Seite sunds-hub)

- `kunden.json` → `connect` (Quelle ist der **Server**, geschrieben über
  `ops/sunds-hub/eintragen.py`): Empfänger `Info@sundsconnect.de` (Leitstand liest
  dieses Postfach alle 3 Minuten, Firma `connect`, Triage läuft), Kopie
  `sunds.connect@gmail.com` (Connect-Anmeldekonto, im Leitstand nur lesend = Backup).
  **Nicht** `sunds.office@gmail.com` — Messebau-Anmeldekonto, falsche Firma. Betreff
  „Neue Anfrage (Website sundsconnect.de)" (trifft die Triage-Regel `angebotsanfrage`,
  Domain in der Klammer macht die Herkunft maschinenlesbar). `telefon_pflicht: false`,
  `herkunft` = `https://sundsconnect.de`, `https://www.sundsconnect.de`,
  `https://sundsoffice-tech.github.io`.
- Absender ist der feste Domain-Absender des Dienstes (`ABSENDER_MAIL`, kein no-reply),
  **Reply-To = Adresse des Anfragenden** (`dienst.py`, SMTP und API) — der Leitstand
  erzeugt damit Antwortentwürfe direkt an den Lead.
- CSP der Website: `connect-src` um `https://leads.sundsconnect.de` erweitert
  (`contact/index.html` **und** `index.html`; beide Metas gelten).

## 5 · Was ausdrücklich nicht gebaut wird

- Keine Rückrichtung (Endpunkt → Website).
- Kein Abschalten von Formspree in dieser Runde.
- Keine Cebula-Discovery-/Selbstauskunfts-Seiten (`d-…/`) — eigener Prozess, eigener
  Vertrag, wenn gewünscht.
- Kein Newsletter, kein Tracking über das Formular hinaus.

## 6 · Abnahme (als Verbraucher gemessen, KONVENTION § 8.5)

1. `GET https://leads.sundsconnect.de/gesund` → `"kunden"` enthält `"connect"`.
2. `OPTIONS /lead` mit `Origin: https://sundsconnect.de` → `Access-Control-Allow-Origin` = Origin.
3. `POST /lead` (Origin wie oben) mit `botcheck: "x"` → `200 {"ok": true}` ohne `vorgang`
   (nichts gespeichert) — testet CORS + Pfad ohne Nebenwirkung.
4. `POST /lead` mit `Origin: https://example.org` → `403`.
5. `POST /lead` ohne Telefon, mit E-Mail → `200 {"ok": true, "vorgang": …}`; Mail landet in
   `Info@sundsconnect.de` mit `Reply-To` des Anfragenden; Leitstand ordnet Firma `connect`
   zu; Cockpit-Kachel „Anfragen" bei Connect zeigt 1.
6. `POST /lead` ohne Telefon **und** ohne E-Mail → `400` mit Besuchertext.
7. Live-Website: CSP-Meta enthält `leads.sundsconnect.de`; `main.js` enthält den Endpunkt;
   Formular-Absenden im Browser zeigt Erfolg (beide Themes, schmal und breit).
8. Außenwächter-Ziel „Connect-Website sundsconnect.de" grün.

## 6a · Abnahme-Protokoll 21.08.2026 (gemessen)

| # | Ergebnis |
|---|---|
| 1 | `/gesund` → kunden enthält `connect` ✓ |
| 2 | OPTIONS mit Origin sundsconnect.de → 204, `Access-Control-Allow-Origin: https://sundsconnect.de` ✓ |
| 3 | Honigtopf → `200 {"ok": true}` ohne vorgang, Journal „Bot abgewiesen" ✓ |
| 4 | Origin example.org → 403 ✓ |
| 5 | Test-Lead `e72ed375c9` 21:18:40 gespeichert + SMTP zugestellt; im Leitstand angekommen (Postfach 66 Firma connect, SPF pass, Reply-To korrekt), Triage **betrugsverdacht** — zu Recht, der Text enthielt „bitte ignorieren/löschen". Zweiter Lead `4f040afedd` mit realistischem Text → anfragen-Dienst holt ihn, Cockpit-Kachel Connect zeigt ihn, ntfy an Fabrice ✓ |
| 6 | ohne Telefon + E-Mail → 400 mit Besuchertext ✓ |
| 7 | Live nach Deploy `ed82c19`: CSP enthält leads.sundsconnect.de, main.js enthält relayLeadToHub, Browser-Absenden (1280 px hell, 390 px dunkel lokal; 1280 px live) zeigt „Vielen Dank", beide POSTs gehen raus. Live-Lauf bekam vom Endpunkt 429 (Ratenlimit 5/IP/h durch die Tests ausgeschöpft) — Formspree nahm an, Besucher sah Erfolg: genau der Parallel-Weg ✓ |
| 8 | Wächter-Ziel „Connect-Website sundsconnect.de" eingetragen (18 Ziele) — Grün beim nächsten 15-min-Lauf |
| + | Keep-Alive-Gegenprobe: 403 → 200 auf derselben Verbindung ✓ |
| 5b | Leitstand (21:35): Lead `4f040afedd` → **angebotsanfrage / handeln**, Dringlichkeit 3; Antwortentwurf Nr. 47 an die **Reply-To**-Adresse erzeugt (Nur-DB-Modus, nichts gesendet) ✓. Offen beim Leitstand: Connect-Signatur (Impressumsdaten geliefert, Absendername = Fabrices Entscheidung) |
| 5c | Sammler (21:35): Test deckte **Doppel-Push** auf — derselbe Lead kam als Formular (#122) und als Leitstand-Mail (#123). Behoben in `anfragen`: Mails vom Endpunkt-Absender gelten als Echo-Dublette des jüngsten Formular-Leads derselben Firma (±6 h) ✓ |

## 7 · Betrieb

- Offene (nicht zugestellte) Leads: `GET /gesund` → `"offen"`. Dauerhaft > 0 → Mailweg kaputt.
- Protokoll: `sudo journalctl -u sunds-leads -f` auf sunds-hub.
- Wer `kunden.json` ändert: `sudo systemctl restart sunds-leads` (Datei wird beim Start gelesen).
- Website-Deploy: Push auf `main` in `sundsoffice-tech/connect` → GitHub-Pages-Workflow.

## 8 · Bekannte Befunde der Website (Stufe B, nicht Teil dieses Vertrags)

- `www.sundsconnect.de`: DNS zeigt auf GitHub Pages, aber das Pages-Zertifikat deckt nur
  `sundsconnect.de` → TLS-Handshake scheitert (gemessen 21.08.: Code 000).
- HTTP → HTTPS nicht erzwungen (`https_enforced: false` in den Pages-Einstellungen;
  `http://sundsconnect.de/` antwortet 200). Beides Repo-Einstellung, Operator-Handlung.
- Cookie-Banner deckt auf 390 px etwa zwei Drittel des Viewports (gesehen 21.08., Screenshot).
- Behoben 21.08. (`ed82c19`): GSAP lief live nie (Inline-Loader von der CSP blockiert).
