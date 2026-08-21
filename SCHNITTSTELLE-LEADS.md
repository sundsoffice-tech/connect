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
| `botcheck` (unsichtbares Feld) | `botcheck` | Honigtopf |
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
