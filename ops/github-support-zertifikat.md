# GitHub-Support-Ticket: Zertifikat fuer sundsconnect.de haengt

Stand 01.09.2026, 14:40 Uhr. Einreichen unter https://support.github.com/request, angemeldet als
`sundsoffice-tech`, Produkt "GitHub Pages". Text unten 1:1 einfuegen (Englisch, damit der
Support ohne Umweg antwortet).

Gemessen vor dem Ticket:
- `GET /repos/sundsoffice-tech/connect/pages`: `https_certificate.state = "new"` seit 21.08.2026,
  auch nach Entfernen/Neusetzen der Domain am 01.09.2026 11:31 UTC (90 Minuten beobachtet).
- `GET .../pages/health`: beide Domains `is_valid`, `is_served_by_pages`, `is_https_eligible`,
  `caa_error: null`; www: `https_error: peer_failed_verification`.
- DNS (Google DoH): Apex A 185.199.108.153, keine AAAA, keine CAA; www CNAME sundsoffice-tech.github.io.
- Ausgeliefertes Zertifikat: nur SAN sundsconnect.de, gueltig bis 2026-10-06.
- Andere Repos des Kontos (Zahnzusatz, Tierversicherung): Zertifikat `approved`.

---

**Subject:** GitHub Pages certificate stuck in state "new" for sundsconnect.de since 2026-08-21

**Message:**

Repository: sundsoffice-tech/connect (GitHub Pages, source: branch main)
Custom domain: sundsconnect.de (apex, A record to 185.199.108.153) plus www.sundsconnect.de (CNAME to sundsoffice-tech.github.io)

Since 2026-08-21 the HTTPS certificate for this site has been stuck in state "new" ("This domain was recently added. The certificate request process will begin shortly."). The Pages health check (GET /repos/sundsoffice-tech/connect/pages/health) reports both domains as valid, served by Pages and HTTPS eligible, with no CAA error. There are no AAAA or CAA records.

The certificate currently served covers only sundsconnect.de (issued 2026-07-08, expires 2026-10-06). www.sundsconnect.de fails TLS because the *.github.io certificate is served. "Enforce HTTPS" cannot be enabled ("certificate has not yet been issued").

What we already tried: removed and re-added the custom domain via the REST API on 2026-09-01 at 11:31 UTC. The state went back to "new" and did not progress within 90 minutes. We also requested a new Pages build. Other repositories in the same account (Zahnzusatz, Tierversicherung) have certificates in state "approved", so certificate issuance works for the account in general.

Request: please re-trigger or unblock certificate provisioning for sundsconnect.de and www.sundsconnect.de, or tell us what is blocking it. The apex certificate expires on 2026-10-06; if renewal is blocked as well, the whole site goes offline on that date.

Thank you.
