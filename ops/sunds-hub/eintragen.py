#!/usr/bin/env python3
"""Traegt die Connect-Website dort ein, wo das Oekosystem sie finden muss:
beim Lead-Endpunkt (kunden.json: Kunde ``connect``), im Register
/opt/sunds-hub/projekte.json (Projekt ``connect-website`` + ``leads``-Ergaenzung)
und in den Zielen des Aussenwaechters. Idempotent, laeuft ohne Schaden zweimal.

    sudo python3 eintragen.py

Die Website selbst laeuft NICHT auf sunds-hub (GitHub Pages, Repo
sundsoffice-tech/connect, CNAME sundsconnect.de). Dieser Eintrag ist die
Sichtbarkeit nach KONVENTION.md § 8: ein Vertrag, den die Gegenseite nicht
findet, ist keiner. Muster: ss-messebau-website/ops/sunds-hub/eintragen.py.

Quelle der Wahrheit fuer kunden.json ist der SERVER (/opt/sunds-leads/kunden.json,
Entscheidung leadmaschine-53, 21.08.2026) — deshalb schreibt dieses Skript dort
und nie in die Repo-Kopie. Nach dem Eintrag: ``sudo systemctl restart sunds-leads``
(die Datei wird beim Start gelesen).
"""
import io
import json
import os
import shutil
import sys
import time

REGISTER = "/opt/sunds-hub/projekte.json"
KUNDEN = "/opt/sunds-leads/kunden.json"
ZIELE = "/opt/sunds-waechter/ziele.json"
NAME = "connect-website"
VERTRAG = "/opt/sunds-hub/schnittstellen/connect-website-leads.md"
LIVE = "https://sundsconnect.de/"

# Empfaenger laut Leitstand-Session (21.08.2026): Info@sundsconnect.de wird alle
# 3 Minuten gelesen, Firma connect, Triage laeuft. Kopie sunds.connect@gmail.com
# (Connect-Anmeldekonto, im Leitstand nur lesend = Backup). NICHT sunds.office@gmail.com
# — das ist das Messebau-Anmeldekonto und wuerde der falschen Firma zuordnen.
KUNDE = {
    "name": "S&S Connect",
    "betreff": "Neue Anfrage (Website sundsconnect.de)",
    "empfaenger": ["Info@sundsconnect.de"],
    "kopie": ["sunds.connect@gmail.com"],
    "telefon_pflicht": False,
    "nachricht_titel": "Nachricht:",
    "herkunft": [
        "https://sundsconnect.de",
        "https://www.sundsconnect.de",
        "https://sundsoffice-tech.github.io",
    ],
}

EINTRAG = {
    # Seit 01.09.2026 auf sunds-hub (ops/HOSTING-SUNDS-HUB.md). Werte am 18.10.2026 dem laufenden Register
    # angeglichen; vorher schrieb ein erneuter Lauf GitHub-Pages-Werte zurueck (Programmierer r2, KANN 2).
    "zweck": "Website + Kontaktformular der S&S Connect GbR (Firma 'connect'); "
             "statisch, Formular nur an den Lead-Endpunkt (Formspree seit 18.10.2026 abgeschaltet)",
    "domain": "sundsconnect.de",
    "port": None,
    "dienst": "Caddy statisch (kein Daemon), Webroot /opt/sunds-connect-website/site",
    "benutzer": None,
    "gesund": "/gesund",
    "daten": "keine (Formulardaten gehen an den Lead-Endpunkt, nicht an die Website)",
    "kunden": [],
    "server": "sunds-hub (169.58.211.51), Caddy-Block sundsconnect.de + www -> Apex",
    "quelle": ("GitHub sundsoffice-tech/connect main = Quelle; Deploy: git push hub main (post-receive baut "
               "site/), GitHub Pages bleibt Zweitausgabe"),
    "seit": "2026-08-21",
    "hinweis": (
        "Seit 2026-09-01 auf sunds-hub (Umzug wegen haengendem GitHub-Pages-Zertifikat). Lokale Kopie: "
        "Desktop/_Projekte/_S&S_Connect/S&S_CONNECT/website. Formular sendet seit 18.10.2026 nur an den "
        "Lead-Endpunkt (kunde=connect); Formspree abgeschaltet, ausser Selbstauskunftsseite d-c8df. Offen: "
        "Custom Domain im GitHub-Repo connect entfernen, sobald DNS ueberall umgestellt ist."),
    "schnittstellen": {
        "bietet": [],
        "braucht": {"leads": ["POST /lead (kunde=connect)"]},
        "vertraege": [VERTRAG],
    },
}

LEADS_ERGAENZUNG = {
    "kunden": ["connect"],
    "schnittstellen": {
        "bietet": ["POST /lead (kunde=connect)"],
        "genutzt_von": [NAME],
        "vertraege": [VERTRAG],
    },
}

ZIELE_NEU = [
    {
        "name": "Connect-Website sundsconnect.de",
        "typ": "url",
        "kunde": "S&S Connect",
        "url": LIVE,
        "max_sekunden": 5.0,
        "muss_enthalten": ["S&amp;S Connect", "contact-form"],
    },
]


def lade(pfad, standard):
    try:
        return json.load(io.open(pfad, encoding="utf-8"))
    except Exception:
        return standard


def vereinige(alt, neu):
    aus = list(alt or [])
    for x in neu:
        if x not in aus:
            aus.append(x)
    return aus


def sichere(pfad):
    ziel = "%s.vor-connect-%s" % (pfad, time.strftime("%Y-%m-%d-%H%M"))
    shutil.copy2(pfad, ziel)
    return ziel


def main():
    if os.geteuid() != 0:
        sys.exit("Muss als root laufen (sudo).")

    # 1) Lead-Endpunkt: Kunde connect
    kunden = lade(KUNDEN, None)
    if kunden is None:
        sys.exit("kunden.json nicht lesbar: %s" % KUNDEN)
    if kunden.get("connect") == KUNDE:
        print("kunden.json: 'connect' war schon aktuell")
        neu_kunde = False
    else:
        st = os.stat(KUNDEN)
        print("kunden.json: Sicherung ->", sichere(KUNDEN))
        kunden["connect"] = KUNDE
        json.dump(kunden, io.open(KUNDEN, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        os.chown(KUNDEN, st.st_uid, st.st_gid)
        os.chmod(KUNDEN, st.st_mode & 0o777)
        print("kunden.json: 'connect' geschrieben (Dienst neu starten: sudo systemctl restart sunds-leads)")
        neu_kunde = True

    # 2) Register
    register = lade(REGISTER, {})
    vorher = json.dumps(register, sort_keys=True)
    register.setdefault(NAME, {}).update(EINTRAG)
    leads = register.setdefault("leads", {})
    leads["kunden"] = vereinige(leads.get("kunden"), LEADS_ERGAENZUNG["kunden"])
    ls = leads.setdefault("schnittstellen", {})
    for k in ("bietet", "genutzt_von", "vertraege"):
        ls[k] = vereinige(ls.get(k), LEADS_ERGAENZUNG["schnittstellen"][k])
    if json.dumps(register, sort_keys=True) != vorher:
        json.dump(register, io.open(REGISTER, "w", encoding="utf-8"),
                  ensure_ascii=False, indent=2, sort_keys=True)
        print("projekte.json: '%s' geschrieben, 'leads' ergaenzt" % NAME)
    else:
        print("projekte.json: war schon aktuell")

    # 3) Aussenwaechter
    ziele = lade(ZIELE, [])
    vorhanden = {z.get("name") for z in ziele}
    ergaenzt = [z for z in ZIELE_NEU if z["name"] not in vorhanden]
    if ergaenzt:
        ziele.extend(ergaenzt)
        json.dump(ziele, io.open(ZIELE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        st = os.stat("/opt/sunds-waechter")
        os.chown(ZIELE, st.st_uid, st.st_gid)
        print("ziele.json: %d Ziel(e) ergaenzt, jetzt %d Ziele" % (len(ergaenzt), len(ziele)))
    else:
        print("ziele.json: alle Ziele waren schon vorhanden")
    return 1 if neu_kunde else 0   # 1 = Dienst-Neustart noetig


if __name__ == "__main__":
    sys.exit(main())
