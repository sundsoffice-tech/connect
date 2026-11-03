#!/usr/bin/env python3
"""Blog-Generator für sundsconnect.de: baut aus inhalt/blog/*.md die Ausgaben unter blog/.

Warum ein eigenes Programm: Die Website ist statisch, das Repo öffentlich, und Entwürfe kommen später
vom eigenen Modell. Deshalb ein strenger Markdown-Ausschnitt ohne rohes HTML, Prüfungen, die den
Bau abbrechen, und eine Freigabesperre je Beitrag. Nur Python-Standard (3.12), weil das Programm auf
dem PC, auf dem Server und in der CI gleich laufen muss.

Der Bau ist deterministisch: keine aktuelle Uhrzeit in einer Ausgabe. Deshalb kann `pruefen` byte-genau
gegen die eingecheckten Ausgaben vergleichen.

Befehle: bauen, pruefen, stand [--live], vorschau, freigeben, indexnow.
Exit: 0 grün, 1 Prüfung oder Abweichung, 2 falscher Aufruf, 3 Vorschaubild fehlt und kein Chrome/Node.
"""
from __future__ import annotations

import argparse
import datetime as dt
import functools
import hashlib
import html
import http.client
import json
import math
import os
import posixpath
import re
import shutil
import string
import struct
import subprocess
import sys
import tempfile
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable

HIER = Path(__file__).resolve().parent
WURZEL = HIER.parent.parent
QUELLEN = WURZEL / "inhalt" / "blog"
VORLAGEN = HIER / "vorlagen"
CSS = WURZEL / "css" / "blog.css"
OG_MARKEN = HIER / "og-marken.json"
RESERVIERTE_SLUGS = ("thema", "index", "feed", "rss")  # belegen Ausgaben des Generators unter blog/
FREIGABE_VON = "Fabrice"
FREIGABE_FELDER = ("von", "am", "wortlaut_sha256", "inhalt_sha256")  # nur Hashes; ungesalzen, ein kurzer Satz ist zurückratbar
SHA256_MUSTER = re.compile(r"^[0-9a-f]{64}\Z")
KOPIERLISTE = WURZEL / "ops" / "veroeffentlichen.liste"
# Was eine Vorlage nennen muss; string.Template bemerkt nur Unbekanntes, nicht Fehlendes. csp und jsonld fehlen hier,
# weil P6 und P9 sie auf der fertigen Seite genauer prüfen
PFLICHT_VARIABLEN = {
    "beitrag.html": {"wurzel", "seitentitel", "beschreibung", "kanonisch", "kopf_meta", "css", "brotkrumen", "meta_stand",
                     "titel", "vorspann", "anhaenge", "inhaltsverzeichnis", "inhalt", "verwandte", "kontakt", "quellen", "lizenz"},
    "uebersicht.html": {"wurzel", "seitentitel", "beschreibung", "kanonisch", "kopf_meta", "css", "kontakt", "liste"},
    "weiterleitung.html": {"ziel_absolut", "ziel_relativ", "titel"},
}
HALBGEVIERT = chr(0x2013)
STRICHE = {cp: "-" for cp in (0x2010, 0x2011, 0x2012, 0x2013, 0x2014, 0x2212)}
FIRMA_SCHLUESSEL = {"name", "kurzname", "strasse", "plz", "ort", "land", "mail", "telefon_e164", "telefon_anzeige",
                    "telefon_gewaehlt", "telefon_frueher", "logo", "same_as"}
# Was ops/stempel.py beim Deploy umschreibt: trägt eine Blogseite das, sperrt der Byte-Vergleich den Deploy
STEMPEL_MUSTER = re.compile(r"css/style\.css|js/main\.js")
TEL_MUSTER = re.compile(r"(?<![\d.,-])(?:\+49|0049|0\d{2,5})[\s/().-]*\d[\d\s/().-]{4,}\d")
MAIL_MUSTER = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
STRASSEN_MUSTER = re.compile(r"Nobelstr|\b[\wäöüßÄÖÜ-]*(?:straße|strasse|str\.)\s+\d", re.IGNORECASE)

MARKE = "erzeugt von ops/blog/blog.py, nicht von Hand ändern"
ATOM = "http://www.w3.org/2005/Atom"
ZEITGRENZE_S = 10
BENUTZERKENNUNG = "SundS-Blog-Stand/1"

MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]
SLUG_MUSTER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*\Z")
KURZ_MUSTER = re.compile(r"^/[a-z0-9-]+(?:/[a-z0-9-]+)*/\Z")
BILD_MUSTER = re.compile(r"^(?!.*\.\.)[A-Za-z0-9_-]+(?:/[A-Za-z0-9_.-]+)*\.png\Z")
DATEI_MUSTER = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*\Z")
ANKER_MUSTER = re.compile(r"^[a-z0-9][a-z0-9-]*\Z")
PDF_SVG = ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="2" '
           'stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/>'
           '<path d="M4 19h16"/></svg>')
# Die Hausschriften (Latin-Teilmengen) haben keinen Pfeil U+2192; ohne Ersatzschrift zeichnet ihn ein SVG,
# das Zeichen selbst bleibt unsichtbar im Text für Vorleser, Suche und Textauszug.
PFEIL_HTML = ('<span class="pfeil"><svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
              'stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M3 12h17"/><path d="m13 5 7 7-7 7"/>'
              '</svg><span class="unsichtbar">→</span></span>')


def zahl_html(zahl: str, bezug: "Bezug") -> str:
    """Kennzahl der Seite; Feed und Markdown-Fassung behalten das Zeichen, weil dort kein Stilbogen wirkt."""
    if bezug.absolut or "→" not in zahl:
        return tx(zahl)
    return PFEIL_HTML.join(tx(teil) for teil in zahl.split("→"))


# ---------------------------------------------------------------------------------------------------
# Funde: jede Abbruchprüfung meldet Datei:Zeile und ihre Nummer aus dem Entwurf (2.5)
# ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Fund:
    datei: str
    zeile: int
    pruefung: str
    text: str

    def __str__(self) -> str:
        return f"{self.datei}:{self.zeile}: [{self.pruefung}] {self.text}"


class Funde(list):
    telefon: list = []  # Telefon-Abweichungen der Handseiten, bis zur Wahl nur gezählt

    def neu(self, datei: str | Path, zeile: int, pruefung: str, text: str) -> None:
        self.append(Fund(relativ(datei), max(zeile, 1), pruefung, text))


def relativ(pfad: str | Path) -> str:
    if isinstance(pfad, str):
        return pfad
    try:
        return pfad.resolve().relative_to(WURZEL).as_posix()
    except ValueError:
        return str(pfad)


def lesen(pfad: Path) -> str:
    """Text ohne Zeilenende-Unterschiede: ein CRLF aus einem Windows-Checkout darf nichts ändern."""
    return pfad.read_bytes().decode("utf-8").replace("\r\n", "\n")


def md5(daten: bytes) -> str:
    return hashlib.md5(daten).hexdigest()


# ---------------------------------------------------------------------------------------------------
# Kopierliste: was ops/sunds-hub/bauen.sh ausliefert; ein Ziel außerhalb wäre live 404
# ---------------------------------------------------------------------------------------------------
@functools.lru_cache(maxsize=1)
def kopierliste() -> tuple[dict, list] | None:
    """Liest die Liste wie bauen.sh: (Name -> Zeile, [(Art, Muster, Zeile)]). None, wenn sie fehlt."""
    if not KOPIERLISTE.is_file():
        return None
    namen: dict[str, int] = {}
    muster: list[tuple[str, re.Pattern, int]] = []
    for nr, zeile in enumerate(lesen(KOPIERLISTE).split("\n"), 1):
        if not zeile or zeile.startswith("#"):
            continue
        if zeile.startswith(("ordner-muster ", "datei-muster ")):
            art, regel = zeile.split(" ", 1)
            muster.append((art, re.compile(regel), nr))
        else:
            namen[zeile] = nr
    return namen, muster


def ausgeliefert(rel: str) -> bool:
    """Liegt der Pfad (relativ zur Site-Wurzel) in einem gelisteten Eintrag? Ohne Liste: nein, fail-closed."""
    liste = kopierliste()
    if liste is None:
        return False
    namen, muster = liste
    kopf, trenner, _ = rel.partition("/")
    if kopf in namen:
        return True
    art = "ordner-muster" if trenner else "datei-muster"
    return any(a == art and m.search(kopf) for a, m, _ in muster)


def liste_pruefen(funde: Funde) -> None:
    """Riegel für Entwürfe: ein gelisteter Ordner mit ENTWURF.txt geht nicht auf die Domain, auch nicht aus Versehen."""
    try:
        liste = kopierliste()
    except re.error as fehler:
        funde.neu(KOPIERLISTE, 1, "P15", f"Muster ungültig: {fehler}")
        return
    if liste is None:
        funde.neu(KOPIERLISTE, 1, "P15", "Kopierliste fehlt")
        return
    namen, muster = liste
    ordner = dict(namen)
    for art, m, nr in muster:
        if art == "ordner-muster" and WURZEL.is_dir():
            ordner.update({p.name: nr for p in WURZEL.iterdir() if p.is_dir() and m.search(p.name)})
    for name, nr in sorted(ordner.items()):
        if (WURZEL / name / "ENTWURF.txt").exists():
            funde.neu(KOPIERLISTE, nr, "P15", f"{name} ist ein Entwurf ({name}/ENTWURF.txt); erst freigeben, dann listen")


# ---------------------------------------------------------------------------------------------------
# Haus-Daten
# ---------------------------------------------------------------------------------------------------
def haus_laden() -> dict:
    """Liest haus.toml und legt Abgeleitetes daneben; die Datei selbst bleibt die eine Quelle."""
    try:
        haus = tomllib.loads(lesen(HIER / "haus.toml"))
    except tomllib.TOMLDecodeError as fehler:
        treffer = re.search(r"line (\d+)", str(fehler))
        raise ValueError(f"ops/blog/haus.toml:{treffer.group(1) if treffer else 1}: {fehler}") from fehler
    site, pruefung = haus["site"], haus["pruefung"]
    haus["basis"] = site["basis"]
    haus["sprache"] = site["sprache"]
    haus["og_locale"] = site["sprache"].replace("-", "_")
    wirt = urllib.parse.urlsplit(site["basis"]).hostname
    haus["eigene_hosts"] = [wirt, f"www.{wirt}"]
    haus["csp"] = pruefung["csp"]
    haus["sperren"] = {"zeichen": pruefung["maschinen_zeichen"], "hosts": pruefung["sperrliste"], "slugs": RESERVIERTE_SLUGS}
    for autor in haus["autoren"].values():
        if autor.get("typ") == "organisation":
            autor["typ"] = "Organization"
            autor["name"] = haus["firma"]["name"]
    return haus


def haus_zeile(schluessel: str) -> int:
    for nr, zeile in enumerate(lesen(HIER / "haus.toml").split("\n"), 1):
        if re.match(rf"\s*{re.escape(schluessel)}\s*=", zeile):
            return nr
    return 1


# ---------------------------------------------------------------------------------------------------
# Quelle: Kopfdaten in TOML zwischen +++, danach Haus-Markdown
# ---------------------------------------------------------------------------------------------------
@dataclass
class Beitrag:
    pfad: Path
    kopf: dict = field(default_factory=dict)
    kopf_text: str = ""
    koerper: str = ""
    koerper_zeile: int = 1
    knoten: list = field(default_factory=list)
    vorspann: str = ""
    vorspann_zeile: int = 1
    woerter: int = 0
    anker: list = field(default_factory=list)

    @property
    def slug(self) -> str:
        return self.pfad.stem

    def kopf_zeile(self, schluessel: str, wert: str | None = None) -> int:
        """Zeile eines Kopffelds in der Quelle; mit wert die Zeile, die ihn trägt (für wiederholte Felder). Fehlt es, Zeile 1."""
        erste = 1
        for nr, zeile in enumerate(self.kopf_text.split("\n"), 2):
            if re.match(rf"\s*{re.escape(schluessel)}\s*=", zeile):
                if wert is None or wert in zeile:
                    return nr
                erste = erste if erste > 1 else nr
        return erste


def quelle_lesen(pfad: Path, funde: Funde) -> Beitrag | None:
    text = lesen(pfad)
    b = Beitrag(pfad=pfad)
    if not text.startswith("+++\n"):
        funde.neu(pfad, 1, "P2", "Kopfdaten fehlen: die Datei muss mit +++ beginnen")
        return None
    ende = text.find("\n+++\n", 3)
    if ende < 0:
        funde.neu(pfad, 1, "P2", "Kopfdaten nicht geschlossen: zweites +++ fehlt")
        return None
    b.kopf_text = text[4:ende + 1]
    b.koerper = text[ende + 5:]
    b.koerper_zeile = text[:ende + 5].count("\n") + 1
    try:
        b.kopf = tomllib.loads(b.kopf_text)
    except tomllib.TOMLDecodeError as fehler:
        treffer = re.search(r"line (\d+)", str(fehler))
        zeile = int(treffer.group(1)) + 1 if treffer else 1
        funde.neu(pfad, zeile, "P2", f"Kopfdaten kein gültiges TOML: {fehler}")
        return None
    return b


def kopf_ohne_freigabe(kopf_text: str) -> str:
    """Kopf ohne die Tabelle [freigabe], ohne Leerraum am Ende: das, worauf sich eine Freigabe bezieht."""
    behalten: list[str] = []
    in_freigabe = False
    for z in kopf_text.split("\n"):
        if z.strip() == "[freigabe]":
            in_freigabe = True
            continue
        if in_freigabe:
            if not z.lstrip().startswith("["):
                continue
            in_freigabe = False
        behalten.append(z)
    return "\n".join(behalten).rstrip()


def inhalt_hash(pfad: Path, kopf_text: str, koerper: str, kopf: dict) -> str:
    """SHA-256 über Quelle (LF, ohne [freigabe]) und Anhänge: ein Wort gibt genau diese Fassung frei."""
    h = hashlib.sha256()
    h.update(kopf_ohne_freigabe(kopf_text).encode("utf-8") + b"\n+++\n" + koerper.encode("utf-8"))
    anhaenge = kopf.get("anhaenge") if isinstance(kopf.get("anhaenge"), list) else []
    for name in sorted(a["datei"] for a in anhaenge if isinstance(a, dict) and isinstance(a.get("datei"), str)):
        h.update(b"\0" + name.encode("utf-8") + b"\0")
        datei = pfad.parent / pfad.stem / name
        if DATEI_MUSTER.match(name) and datei.is_file():
            h.update(datei.read_bytes())
    # Die Aussage der Lizenz, auf die der Beitrag zeigt, gehört zur freigegebenen Fassung; Vorlagen und CSS bewusst nicht,
    # sonst macht jede Gestaltungsänderung die Freigabe rot.
    lizenz = kopf.get("lizenz")
    if isinstance(lizenz, str):
        liz = haus_laden().get("lizenzen", {}).get(lizenz)
        if isinstance(liz, dict):
            teil = {feld: liz.get(feld) for feld in ("name", "url", "text", "satz", "vorbehalt")}
            h.update(b"\0lizenz\0" + json.dumps(teil, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()


def ist_zeitpunkt(wert: Any) -> bool:
    return isinstance(wert, dt.datetime) and wert.tzinfo is not None


def als_tag(wert: Any) -> dt.date:
    return wert.date() if isinstance(wert, dt.datetime) else wert


def kopf_pruefen(b: Beitrag, haus: dict, funde: Funde, nur_quelle: bool = False) -> None:
    """Prüfung 2 und 8 aus dem Entwurf: Pflichtfelder, Typen, Längen, Datumsreihenfolge, Slug, Status."""
    k, g = b.kopf, haus["grenzen"]
    d = b.pfad

    def fehlt(feld: str, typ: type | tuple) -> bool:
        if feld not in k:
            funde.neu(d, 1, "P2", f"Pflichtfeld {feld} fehlt")
            return True
        if not isinstance(k[feld], typ) or (isinstance(k[feld], str) and not k[feld].strip()):
            funde.neu(d, b.kopf_zeile(feld), "P2", f"Feld {feld} hat den falschen Typ oder ist leer")
            return True
        return False

    def laenge(feld: str, unten: int, oben: int) -> None:
        n = len(k[feld])
        if not unten <= n <= oben:
            funde.neu(d, b.kopf_zeile(feld), "P2", f"{feld} hat {n} Zeichen, erlaubt {unten} bis {oben}")

    if not fehlt("titel", str):
        laenge("titel", g["titel_min"], g["titel_max"])
        if "seitentitel" not in k and len(k["titel"]) > g["seitentitel_max"]:
            funde.neu(d, b.kopf_zeile("titel"), "P2",
                      f"seitentitel fehlt, also gilt titel und muss selbst höchstens {g['seitentitel_max']} Zeichen haben")
    if "seitentitel" in k and not fehlt("seitentitel", str):
        laenge("seitentitel", 1, g["seitentitel_max"])
    if not fehlt("beschreibung", str):
        laenge("beschreibung", g["beschreibung_min"], g["beschreibung_max"])
    if not fehlt("slug", str):
        if k["slug"] != b.slug:
            funde.neu(d, b.kopf_zeile("slug"), "P2", f"slug {k['slug']} ist nicht gleich dem Dateinamen {b.slug}")
        if not SLUG_MUSTER.match(k["slug"]):
            funde.neu(d, b.kopf_zeile("slug"), "P2", "slug: nur a-z 0-9 und Bindestrich")
        if k["slug"] in haus["sperren"]["slugs"]:
            funde.neu(d, b.kopf_zeile("slug"), "P2", f"slug {k['slug']} ist für Ausgaben des Generators reserviert")
        if not nur_quelle and (WURZEL / k["slug"]).is_dir():
            funde.neu(d, b.kopf_zeile("slug"), "P2", f"slug {k['slug']} kollidiert mit einem Ordner der Site")
    for feld in ("datum", "geaendert"):
        if not fehlt(feld, dt.datetime) and not ist_zeitpunkt(k[feld]):
            funde.neu(d, b.kopf_zeile(feld), "P2", f"{feld} braucht eine Zeitzone")
    if not fehlt("pruefen_bis", (dt.date, dt.datetime)) and ist_zeitpunkt(k.get("geaendert")):
        bezug = als_tag(k["geaendert"])
        if "geprueft" in k:
            if not isinstance(k["geprueft"], (dt.date, dt.datetime)):
                funde.neu(d, b.kopf_zeile("geprueft"), "P2", "geprueft ist kein Datum")
            else:
                bezug = max(bezug, als_tag(k["geprueft"]))
        bis = als_tag(k["pruefen_bis"])
        if bis <= bezug:
            funde.neu(d, b.kopf_zeile("pruefen_bis"), "P2", "pruefen_bis muss nach geaendert liegen")
        elif (bis - bezug).days > g["pruefen_bis_tage_max"]:
            funde.neu(d, b.kopf_zeile("pruefen_bis"), "P2",
                      f"pruefen_bis liegt {(bis - bezug).days} Tage nach geaendert, erlaubt {g['pruefen_bis_tage_max']}")
    if ist_zeitpunkt(k.get("datum")) and ist_zeitpunkt(k.get("geaendert")) and k["geaendert"] < k["datum"]:
        funde.neu(d, b.kopf_zeile("geaendert"), "P2", "geaendert liegt vor datum")
    if not fehlt("fassung", str) and not re.match(r"^\d+\.\d+\Z", k["fassung"]):
        funde.neu(d, b.kopf_zeile("fassung"), "P2", "fassung muss wie 1.1 aussehen")
    if not fehlt("autor", str) and k["autor"] not in haus["autoren"]:
        funde.neu(d, b.kopf_zeile("autor"), "P2", f"autor {k['autor']} steht nicht in haus.toml")
    if not fehlt("schlagwoerter", list):
        w = k["schlagwoerter"]
        if not g["schlagwoerter_min"] <= len(w) <= g["schlagwoerter_max"]:
            funde.neu(d, b.kopf_zeile("schlagwoerter"), "P2",
                      f"{len(w)} Schlagwörter, erlaubt {g['schlagwoerter_min']} bis {g['schlagwoerter_max']}")
        for wort in w:
            if not isinstance(wort, str) or wort not in haus["schlagwoerter"]:
                funde.neu(d, b.kopf_zeile("schlagwoerter"), "P2", f"Schlagwort {wort} steht nicht in haus.toml")
        if len(set(map(str, w))) != len(w):
            funde.neu(d, b.kopf_zeile("schlagwoerter"), "P2", "Schlagwort doppelt")
    if not fehlt("lizenz", str) and k["lizenz"] not in haus["lizenzen"]:
        funde.neu(d, b.kopf_zeile("lizenz"), "P2", f"lizenz {k['lizenz']} steht nicht in haus.toml")

    # Prüfung 3: Bild und Alt-Text
    alt = k.get("bild_alt")
    if not isinstance(alt, str) or not alt.strip():
        funde.neu(d, b.kopf_zeile("bild_alt"), "P3", "bild_alt fehlt oder ist leer")
    bild = k.get("bild", "")
    if not isinstance(bild, str):
        funde.neu(d, b.kopf_zeile("bild"), "P2", "bild ist kein Text")
    elif bild and not BILD_MUSTER.match(bild):
        funde.neu(d, b.kopf_zeile("bild"), "P3", "bild muss ein relativer PNG-Pfad ohne .. sein")
    elif bild and not nur_quelle:
        groesse_pruefen(WURZEL / bild, haus, funde, d, b.kopf_zeile("bild"))
        if not ausgeliefert(bild):
            funde.neu(d, b.kopf_zeile("bild"), "P3", f"bild {bild} liegt außerhalb der Kopierliste: og:image wäre live 404")

    for i, anhang in enumerate(k.get("anhaenge", []) if isinstance(k.get("anhaenge", []), list) else [None]):
        if not isinstance(anhang, dict) or not isinstance(anhang.get("datei"), str) or not isinstance(anhang.get("knopf"), str):
            funde.neu(d, b.kopf_zeile("datei"), "P2", f"anhaenge[{i}] braucht datei und knopf")
            continue
        anhang_firmendaten(anhang, b, haus, funde)
        if not DATEI_MUSTER.match(anhang["datei"]):
            funde.neu(d, b.kopf_zeile("datei"), "P2", f"Anhang {anhang['datei']}: nur ein einfacher Dateiname")
        elif not (b.pfad.parent / b.slug / anhang["datei"]).is_file():
            funde.neu(d, b.kopf_zeile("datei"), "P2", f"Anhang {anhang['datei']} fehlt in inhalt/blog/{b.slug}/")

    kurz = k.get("kurzadressen", [])
    if not isinstance(kurz, list):
        funde.neu(d, b.kopf_zeile("kurzadressen"), "P2", "kurzadressen ist keine Liste")
    else:
        for adresse in kurz:
            if not isinstance(adresse, str) or not KURZ_MUSTER.match(adresse):
                funde.neu(d, b.kopf_zeile("kurzadressen"), "P2", f"Kurzadresse {adresse!r} muss wie /name/ aussehen")
            elif adresse.split("/")[1] in ("blog", "ops", "inhalt", "css", "assets", "js"):
                funde.neu(d, b.kopf_zeile("kurzadressen"), "P2", f"Kurzadresse {adresse} liegt in einem belegten Ordner")

    quellen = k.get("quellen", [])
    if not isinstance(quellen, list):
        funde.neu(d, b.kopf_zeile("quellen"), "P2", "quellen ist keine Liste")
        quellen = []
    for i, q in enumerate(quellen):
        if not isinstance(q, dict) or not all(isinstance(q.get(f), str) and q[f].strip() for f in ("titel", "url", "herausgeber")):
            funde.neu(d, b.kopf_zeile("url"), "P2", f"quellen[{i}] braucht titel, url und herausgeber")
            continue
        for feld in ("url", "zusatz_url"):
            if feld in q and not str(q[feld]).startswith("https://"):
                funde.neu(d, b.kopf_zeile(feld), "P2", f"quellen[{i}].{feld} muss mit https:// beginnen")
    if not quellen and re.search(r"\d", b.koerper):
        funde.neu(d, 1, "P2", "Der Text enthält Zahlen, aber quellen fehlt")

    firmendaten_in_quelle(b, funde)

    # Prüfung 8: Status und Freigabe
    status = k.get("status")
    if status not in ("veroeffentlicht", "entwurf"):
        funde.neu(d, b.kopf_zeile("status"), "P2", "status muss veroeffentlicht oder entwurf sein")
    elif status == "entwurf":
        if not nur_quelle:
            funde.neu(d, b.kopf_zeile("status"), "P8", "status = entwurf im Repo: das Repo ist öffentlich, Entwürfe bleiben draußen")
        if "freigabe" in k:
            # Ein Modellentwurf darf keinen fertigen Block mitbringen, sonst fehlte nur noch der Status
            funde.neu(d, b.kopf_zeile("status"), "P8", "Entwurf mit [freigabe]: den Block setzt nur blog.py freigeben")
    elif status == "veroeffentlicht":
        fg = k.get("freigabe")
        if not isinstance(fg, dict) or fg.get("von") != FREIGABE_VON or not ist_zeitpunkt(fg.get("am")) \
                or not isinstance(fg.get("wortlaut_sha256"), str) or not SHA256_MUSTER.match(fg["wortlaut_sha256"]) \
                or not isinstance(fg.get("inhalt_sha256"), str) or not SHA256_MUSTER.match(fg["inhalt_sha256"]):
            funde.neu(d, b.kopf_zeile("status"), "P8",
                      "veroeffentlicht ohne vollständige freigabe (von, am, wortlaut_sha256, inhalt_sha256 mit je 64 Hexzeichen); setzt nur blog.py freigeben")
        if isinstance(fg, dict):
            for feld in sorted(set(fg) - set(FREIGABE_FELDER)):
                funde.neu(d, b.kopf_zeile(feld), "P8",
                          f"freigabe.{feld} gehört nicht ins öffentliche Repo; erlaubt sind nur {', '.join(FREIGABE_FELDER)}")
            if ist_zeitpunkt(fg.get("am")) and ist_zeitpunkt(k.get("geaendert")) and fg["am"] < k["geaendert"]:
                funde.neu(d, b.kopf_zeile("am"), "P8", "freigabe.am liegt vor geaendert: das Wort gilt einer älteren Fassung")


def freigabe_bindung_pruefen(b: Beitrag, funde: Funde) -> None:
    """Zuletzt, nicht in kopf_pruefen: Wer den Text ändert, soll zugleich alle anderen Funde der neuen Fassung sehen."""
    fg = b.kopf.get("freigabe")
    if b.kopf.get("status") == "veroeffentlicht" and isinstance(fg, dict) and isinstance(fg.get("inhalt_sha256"), str) \
            and SHA256_MUSTER.match(fg["inhalt_sha256"]) and fg["inhalt_sha256"] != inhalt_hash(b.pfad, b.kopf_text, b.koerper, b.kopf):
        funde.neu(b.pfad, b.kopf_zeile("inhalt_sha256"), "P8", "Inhalt geändert, die Freigabe gilt der alten Fassung; neues Wort, dann blog.py freigeben")


def ziffern(nummer: str) -> str:
    return re.sub(r"\D", "", nummer)


def anhang_firmendaten(anhang: dict, b: Beitrag, haus: dict, funde: Funde) -> None:
    """Ein PDF kann pruefen ohne Fremdpaket nicht lesen; deshalb nennt der Kopf, was es eingebrannt trägt."""
    f = haus["firma"]
    zeile = b.kopf_zeile("firmendaten")
    daten = anhang.get("firmendaten")
    if not isinstance(daten, dict):
        funde.neu(b.pfad, b.kopf_zeile("datei"), "P11", f"Anhang {anhang['datei']}: firmendaten = {{telefon, strasse, mail}} fehlt")
        return
    if ziffern(str(daten.get("telefon", ""))) not in (ziffern(f["telefon_anzeige"]), ziffern(f["telefon_e164"])):
        funde.neu(b.pfad, zeile, "P11", f"Anhang {anhang['datei']}: telefon {daten.get('telefon')}, Soll {f['telefon_anzeige']}")
    if daten.get("strasse") != f["strasse"]:
        funde.neu(b.pfad, zeile, "P11", f"Anhang {anhang['datei']}: strasse {daten.get('strasse')}, Soll {f['strasse']}")
    if daten.get("mail") != f["mail"]:
        funde.neu(b.pfad, zeile, "P11", f"Anhang {anhang['datei']}: mail {daten.get('mail')}, Soll {f['mail']}")


def firmendaten_in_quelle(b: Beitrag, funde: Funde) -> None:
    """Telefon, Straße und Mail kommen nur über $kontakt. So bleibt eine Änderung in haus.toml genug."""
    felder = [(feld, b.kopf.get(feld)) for feld in ("titel", "seitentitel", "beschreibung", "bild_alt", "netz_satz", "rubrik")]
    for liste, namen in (("anhaenge", ("knopf", "hinweis")), ("quellen", ("adresse", "titel", "herausgeber", "zusatz_text", "zusatz_titel"))):
        eintraege = b.kopf.get(liste) if isinstance(b.kopf.get(liste), list) else []
        felder.extend((feld, e.get(feld)) for e in eintraege if isinstance(e, dict) for feld in namen)
    zeilen = [(b.kopf_zeile(feld, wert), wert) for feld, wert in felder if isinstance(wert, str)]
    zeilen.extend((b.koerper_zeile + i, z) for i, z in enumerate(b.koerper.split("\n")))
    for nr, zeile in zeilen:
        for muster, art in ((TEL_MUSTER, "Telefonnummer"), (MAIL_MUSTER, "Mailadresse"), (STRASSEN_MUSTER, "Straße")):
            treffer = muster.search(zeile)
            if treffer:
                funde.neu(b.pfad, nr, "P13", f"eigene {art} in der Beitragsquelle: {treffer.group(0)}; Soll: nur über den Kontaktblock aus haus.toml")
        if re.search(r"\]\((?:tel|mailto):", zeile):
            funde.neu(b.pfad, nr, "P13", "tel: oder mailto: in der Beitragsquelle; Soll: nur über den Kontaktblock aus haus.toml")


def groesse_pruefen(pfad: Path, haus: dict, funde: Funde, datei: str | Path, zeile: int) -> None:
    g = haus["grenzen"]
    masse = png_masse(pfad)
    if masse is None:
        funde.neu(datei, zeile, "P3", f"{relativ(pfad)} fehlt oder ist kein PNG")
    elif masse != (g["bild_breite"], g["bild_hoehe"]):
        funde.neu(datei, zeile, "P3", f"{relativ(pfad)} ist {masse[0]} mal {masse[1]}, verlangt {g['bild_breite']} mal {g['bild_hoehe']}")


def png_masse(pfad: Path) -> tuple[int, int] | None:
    try:
        with pfad.open("rb") as f:
            kopf = f.read(24)
    except OSError:
        return None
    if len(kopf) < 24 or kopf[:8] != b"\x89PNG\r\n\x1a\n" or kopf[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", kopf[16:24])


# ---------------------------------------------------------------------------------------------------
# Haus-Markdown: erlaubt ist nur, was hier steht; alles andere ist Prüfung 7
# ---------------------------------------------------------------------------------------------------
LISTE_U = re.compile(r"^- (.*)$")
LISTE_O = re.compile(r"^\d+\. (.*)$")
BILD = re.compile(r'^!\[([^\]]*)\]\(([^()\s]+)(?:\s+"([^"]*)")?\)$')
KENNZAHL = re.compile(r"^\*\*(.+?)\*\*\s+(.+)$")
UEBERSCHRIFT = re.compile(r"^(##|###) (.+?)(?:\s+\{#([^}]*)\})?$")
BLOCK_AUF = re.compile(r"^:::\s*(\S.*)$")
LINK = re.compile(r"\[([^\[\]]*)\]\(([^()\s]*)\)")
LINK_KAPUTT = re.compile(r"\[[^\[\]]*\]\(")


def inline_parsen(text: str, melde: Callable[[str], None]) -> list:
    """Zerlegt **fett**, *kursiv*, [Text](Ziel) und {web:Bildschirm|druck:Papier}. Ungeschlossenes ist ein Fehler.

    {web:...|druck:...} trägt zwei Wortlaute: die Seite zeigt den ersten am Bildschirm und den zweiten im Druck (PDF);
    Feed, Markdown-Fassung und Wortzahl nehmen den ersten."""
    aus: list = []
    puffer = ""
    i = 0

    def leeren() -> None:
        nonlocal puffer
        if puffer:
            aus.append(("text", puffer))
            puffer = ""

    while i < len(text):
        if text.startswith("**", i):
            j = text.find("**", i + 2)
            if j < 0:
                melde("** ohne Gegenstück")
                puffer += text[i:]
                break
            leeren()
            aus.append(("fett", inline_parsen(text[i + 2:j], melde)))
            i = j + 2
        elif text[i] == "*":
            j = text.find("*", i + 1)
            if j < 0:
                melde("* ohne Gegenstück")
                puffer += text[i:]
                break
            leeren()
            aus.append(("kursiv", inline_parsen(text[i + 1:j], melde)))
            i = j + 1
        elif text.startswith("{web:", i):
            j = text.find("}", i)
            innen = text[i + 5:j] if j >= 0 else ""
            if j < 0 or innen.count("|druck:") != 1:
                melde("{web:...|druck:...} ohne schließende Klammer oder ohne genau ein |druck:")
                puffer += text[i:]
                break
            web, druck = innen.split("|druck:")
            if not web.strip() or not druck.strip():
                # Feed und Markdown-Fassung nehmen den Bildschirmteil: leer verlöre das Wort dort still
                melde("{web:...|druck:...} mit leerem Bildschirm- oder Druckteil")
                puffer += text[i:]
                break
            leeren()
            aus.append(("medien", inline_parsen(web, melde), inline_parsen(druck, melde)))
            i = j + 1
        elif text[i] == "[":
            m = LINK.match(text, i)
            if m:
                leeren()
                ziel_pruefen(m.group(2), melde)
                aus.append(("link", inline_parsen(m.group(1), melde), m.group(2)))
                i = m.end()
            else:
                if LINK_KAPUTT.match(text, i):
                    melde("kaputter Link: [Text](Ziel) ohne gültiges Ziel")
                puffer += text[i]
                i += 1
        else:
            puffer += text[i]
            i += 1
    leeren()
    return aus


def ziel_pruefen(ziel: str, melde: Callable[[str], None]) -> None:
    if not ziel:
        melde("Link ohne Ziel")
        return
    if "\\" in ziel:
        melde(f"Link-Ziel mit Backslash: {ziel}")
        return
    teil = urllib.parse.urlsplit(ziel)
    if teil.scheme and teil.scheme not in ("http", "https", "mailto", "tel"):
        melde(f"Link-Schema nicht erlaubt: {teil.scheme}")


def koerper_parsen(b: Beitrag, funde: Funde) -> None:
    zeilen = b.koerper.split("\n")
    d = b.pfad
    start = b.koerper_zeile

    def fehler(nr: int, text: str) -> None:
        funde.neu(d, nr, "P7", text)

    for i, zeile in enumerate(zeilen):
        if "<" in zeile:
            fehler(start + i, "rohes HTML: jedes < im Text bricht ab")

    wurzel: list = []
    stapel: list[dict] = []  # offene Blöcke

    def ziel() -> list:
        return stapel[-1]["kinder"] if stapel else wurzel

    def inl(text: str, nr: int) -> list:
        return inline_parsen(text, lambda m: fehler(nr, m))

    i = 0
    n = len(zeilen)
    while i < n:
        roh = zeilen[i]
        nr = start + i
        zeile = roh.rstrip()
        if not zeile.strip():
            i += 1
            continue
        aktuell = stapel[-1]["art"] if stapel else None

        if zeile.startswith(":::"):
            auf = BLOCK_AUF.match(zeile)
            if zeile.strip() == ":::":
                if not stapel:
                    fehler(nr, "::: ohne offenen Block")
                else:
                    stapel.pop()
                i += 1
                continue
            if not auf:
                fehler(nr, f"unbekannter Block: {zeile}")
                i += 1
                continue
            teile = auf.group(1).split(None, 1)
            art, rest = teile[0], (teile[1] if len(teile) > 1 else "")
            block: dict | None = None
            if art == "kennzahlen" and not rest and aktuell is None:
                block = {"art": "kennzahlen", "kinder": [], "zeile": nr}
            elif art == "kasten" and rest in ("hinweis", "angebot") and aktuell is None:
                block = {"art": "kasten", "unterart": rest, "kinder": [], "zeile": nr}
            elif art == "zwei" and not rest and aktuell is None:
                block = {"art": "zwei", "kinder": [], "zeile": nr}
            elif art == "spalte" and rest and aktuell == "zwei":
                block = {"art": "spalte", "label": rest, "kinder": [], "zeile": nr}
            elif art == "klein" and not rest and aktuell in (None, "spalte", "kasten"):
                block = {"art": "klein", "kinder": [], "zeile": nr}
            if block is None:
                fehler(nr, f"unbekannter oder hier nicht erlaubter Block: {zeile}")
                i += 1
                continue
            ziel().append(block)
            stapel.append(block)
            i += 1
            continue

        if aktuell == "zwei":
            fehler(nr, "in ::: zwei sind nur ::: spalte erlaubt")
            i += 1
            continue
        if aktuell == "kennzahlen":
            m = KENNZAHL.match(zeile)
            if not m:
                fehler(nr, "Kennzahl muss **Zahl** Text sein")
            else:
                ziel().append({"art": "kennzahl", "zahl": m.group(1), "text": inl(m.group(2), nr), "zeile": nr})
            i += 1
            continue

        if roh[0] in " \t":
            fehler(nr, "eingerückter Text ist nicht erlaubt (auch keine verschachtelten Listen)")
            i += 1
            continue
        if zeile.startswith("#"):
            m = UEBERSCHRIFT.match(zeile)
            if not m:
                fehler(nr, f"Überschrift: nur ## und ### erlaubt: {zeile[:40]}")
            elif aktuell is not None:
                fehler(nr, "Überschriften nur außerhalb von Blöcken")
            else:
                anker = m.group(3)
                if anker is not None and not ANKER_MUSTER.match(anker):
                    fehler(nr, f"Anker {anker}: nur a-z 0-9 und Bindestrich")
                ziel().append({"art": "ueberschrift", "ebene": len(m.group(1)), "roh": m.group(2),
                               "text": inl(m.group(2), nr), "anker": anker, "zeile": nr})
            i += 1
            continue
        if zeile.startswith(("```", "~~~", "|", "---", "***", "___", "    ")):
            fehler(nr, f"nicht erlaubte Zeile: {zeile[:40]}")
            i += 1
            continue
        if zeile.startswith("!["):
            m = BILD.match(zeile)
            if not m:
                fehler(nr, "Bild muss eigene Zeile ![Alt](datei.png \"Unterschrift\") sein")
            elif not m.group(1).strip():
                funde.neu(d, nr, "P3", "Bild ohne Alt-Text")
            elif not DATEI_MUSTER.match(m.group(2)):
                fehler(nr, f"Bild {m.group(2)}: nur ein einfacher Dateiname aus inhalt/blog/{b.slug}/")
            else:
                ziel().append({"art": "bild", "alt": m.group(1), "datei": m.group(2), "unterschrift": m.group(3) or "", "zeile": nr})
            i += 1
            continue
        if zeile.startswith("> "):
            texte = []
            while i < n and zeilen[i].startswith("> "):
                texte.append(zeilen[i][2:].strip())
                i += 1
            ziel().append({"art": "zitat", "text": inl(" ".join(texte), nr), "zeile": nr})
            continue
        if LISTE_U.match(zeile) or LISTE_O.match(zeile):
            muster, geordnet = (LISTE_O, True) if LISTE_O.match(zeile) else (LISTE_U, False)
            eintraege = []
            while i < n and muster.match(zeilen[i].rstrip()):
                eintraege.append(inl(muster.match(zeilen[i].rstrip()).group(1), start + i))
                i += 1
            ziel().append({"art": "liste", "geordnet": geordnet, "eintraege": eintraege, "zeile": nr})
            continue
        # Absatz bis zur Leerzeile oder bis zum nächsten Block
        teile = []
        while i < n and zeilen[i].strip():
            z = zeilen[i].rstrip()
            if teile and (z.startswith((":::", "#", "- ", "> ", "![")) or LISTE_O.match(z)):
                break
            teile.append(z.strip())
            i += 1
        ziel().append({"art": "absatz", "text": inl(" ".join(teile), nr), "zeile": nr})

    for offen in stapel:
        fehler(offen["zeile"], f"Block {offen['art']} nicht geschlossen")

    if wurzel and wurzel[0]["art"] == "absatz":
        vorspann = wurzel.pop(0)
        b.vorspann = vorspann["text"]
        b.vorspann_zeile = vorspann["zeile"]
    else:
        fehler(start, "Der Text muss mit einem Absatz beginnen (Vorspann)")
        b.vorspann = []
    b.knoten = wurzel
    anker_vergeben(b, funde)
    b.woerter = wortzahl(klartext_knoten(b))


def anker_vergeben(b: Beitrag, funde: Funde) -> None:
    gesehen: dict[str, int] = {}
    for knoten in b.knoten:
        if knoten["art"] != "ueberschrift":
            continue
        anker = knoten["anker"] or sprechender_anker(klartext(knoten["text"]))
        if anker in gesehen:
            funde.neu(b.pfad, knoten["zeile"], "P7", f"Anker {anker} doppelt (zuerst Zeile {gesehen[anker]})")
        gesehen[anker] = knoten["zeile"]
        knoten["anker"] = anker
        if knoten["ebene"] == 2:
            b.anker.append((anker, klartext(knoten["text"])))


def sprechender_anker(text: str) -> str:
    text = text.lower()
    for alt, neu in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(alt, neu)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-") or "abschnitt"


def klartext(teile: list) -> str:
    aus = []
    for teil in teile:
        if teil[0] == "text":
            aus.append(teil[1])
        else:
            aus.append(klartext(teil[1]))
    return "".join(aus)


def wortzahl(text: str) -> int:
    """Wörter für Lesezeit und wordCount: Stücke mit mindestens einem Buchstaben oder einer Ziffer (ein freistehender Pfeil zählt nicht)."""
    return sum(1 for stueck in text.split() if any(z.isalnum() for z in stueck))


def klartext_knoten(b: Beitrag) -> str:
    """Fließtext für Lesezeit und wordCount: Vorspann und Abschnitte, ohne Kontakt und Quellen."""
    aus = [klartext(b.vorspann)]

    def geh(knoten: list) -> None:
        for k in knoten:
            art = k["art"]
            if art in ("absatz", "zitat", "ueberschrift"):
                aus.append(klartext(k["text"]))
            elif art == "liste":
                aus.extend(klartext(e) for e in k["eintraege"])
            elif art == "kennzahl":
                aus.append(k["zahl"] + " " + klartext(k["text"]))
            elif art == "bild":
                aus.append(k["unterschrift"])
            else:
                if art == "spalte":
                    aus.append(k["label"])
                geh(k["kinder"])
    geh(b.knoten)
    return " ".join(aus)


# ---------------------------------------------------------------------------------------------------
# Darstellung
# ---------------------------------------------------------------------------------------------------
@dataclass
class Bezug:
    """Wohin Links zeigen: relativ auf der Seite, absolut in Feed und Markdown-Fassung."""
    kanonisch: str
    wurzel: str
    absolut: bool
    hosts: tuple
    basis: str

    def ziel(self, ziel: str) -> str:
        if self.absolut:
            return urllib.parse.urljoin(self.kanonisch, ziel)
        if ziel.startswith("/") and not ziel.startswith("//"):
            return (self.wurzel + ziel[1:]) or "./"
        return ziel

    def ist_fremd(self, ziel: str) -> bool:
        teil = urllib.parse.urlsplit(ziel)
        return teil.scheme in ("http", "https") and teil.hostname not in self.hosts


def tx(text: str) -> str:
    return html.escape(text, quote=False)


def at(text: str) -> str:
    """Für Attribute in doppelten Anführungszeichen. Apostrophe bleiben, damit die CSP lesbar im Quelltext steht."""
    return html.escape(text, quote=False).replace('"', "&quot;")


def inline_html(teile: list, bezug: Bezug, stark: str = "b") -> str:
    aus = []
    for teil in teile:
        if teil[0] == "text":
            aus.append(tx(teil[1]))
        elif teil[0] == "fett":
            aus.append(f"<{stark}>{inline_html(teil[1], bezug, stark)}</{stark}>")
        elif teil[0] == "kursiv":
            aus.append(f"<em>{inline_html(teil[1], bezug, stark)}</em>")
        elif teil[0] == "medien":
            # Feed und Markdown-Fassung kennen kein Druckmedium: dort nur der Bildschirmwortlaut
            if bezug.absolut:
                aus.append(inline_html(teil[1], bezug, stark))
            else:
                aus.append(f'<span class="nur-web">{inline_html(teil[1], bezug, stark)}</span> '
                           f'<span class="nur-druck">{inline_html(teil[2], bezug, stark)}</span>')
        else:
            rel = ' rel="noopener"' if bezug.ist_fremd(teil[2]) else ""
            aus.append(f'<a href="{at(bezug.ziel(teil[2]))}"{rel}>{inline_html(teil[1], bezug, stark)}</a>')
    return "".join(aus)


def knoten_html(knoten: list, bezug: Bezug, einzug: str = "", stark: str = "b", klasse: str = "") -> list[str]:
    aus: list[str] = []
    for k in knoten:
        art = k["art"]
        if art == "absatz":
            cl = f' class="{klasse}"' if klasse else ""
            aus.append(f"{einzug}<p{cl}>{inline_html(k['text'], bezug, stark)}</p>")
        elif art == "ueberschrift":
            e = k["ebene"]
            aus.append(f'{einzug}<h{e} id="{at(k["anker"])}">{inline_html(k["text"], bezug, stark)}</h{e}>')
        elif art == "liste":
            tag = "ol" if k["geordnet"] else "ul"
            cl = ' class="liste"' if k["geordnet"] else ""
            aus.append(f"{einzug}<{tag}{cl}>")
            aus.extend(f"{einzug}  <li>{inline_html(e, bezug, stark)}</li>" for e in k["eintraege"])
            aus.append(f"{einzug}</{tag}>")
        elif art == "zitat":
            aus.append(f"{einzug}<blockquote><p>{inline_html(k['text'], bezug, stark)}</p></blockquote>")
        elif art == "bild":
            ziel = bezug.ziel(k["datei"])
            aus.append(f"{einzug}<figure>")
            aus.append(f'{einzug}  <img src="{at(ziel)}" alt="{at(k["alt"])}" loading="lazy">')
            if k["unterschrift"]:
                aus.append(f"{einzug}  <figcaption>{tx(k['unterschrift'])}</figcaption>")
            aus.append(f"{einzug}</figure>")
        elif art == "kennzahlen":
            aus.append(f'{einzug}<div class="kennzahlen">')
            aus.extend(knoten_html(k["kinder"], bezug, einzug + "  "))
            aus.append(f"{einzug}</div>")
        elif art == "kennzahl":
            aus.append(f"{einzug}<div><b>{zahl_html(k['zahl'], bezug)}</b><span>{inline_html(k['text'], bezug)}</span></div>")
        elif art == "kasten":
            innen_stark = "strong" if k["unterart"] == "hinweis" else "b"
            aus.append(f'{einzug}<div class="karte {k["unterart"]}">')
            aus.extend(knoten_html(k["kinder"], bezug, einzug + "  ", innen_stark))
            aus.append(f"{einzug}</div>")
        elif art == "zwei":
            aus.append(f'{einzug}<div class="zwei">')
            aus.extend(knoten_html(k["kinder"], bezug, einzug + "  "))
            aus.append(f"{einzug}</div>")
        elif art == "spalte":
            aus.append(f'{einzug}<div class="karte">')
            aus.append(f'{einzug}  <p class="label">{tx(k["label"])}</p>')
            aus.extend(knoten_html(k["kinder"], bezug, einzug + "  "))
            aus.append(f"{einzug}</div>")
        elif art == "klein":
            aus.extend(knoten_html(k["kinder"], bezug, einzug, stark, "klein"))
    return aus


def inline_md(teile: list, bezug: Bezug) -> str:
    aus = []
    for teil in teile:
        if teil[0] == "text":
            aus.append(teil[1])
        elif teil[0] == "fett":
            aus.append(f"**{inline_md(teil[1], bezug)}**")
        elif teil[0] == "kursiv":
            aus.append(f"*{inline_md(teil[1], bezug)}*")
        elif teil[0] == "medien":
            aus.append(inline_md(teil[1], bezug))
        else:
            aus.append(f"[{inline_md(teil[1], bezug)}]({bezug.ziel(teil[2])})")
    return "".join(aus)


def knoten_md(knoten: list, bezug: Bezug) -> list[str]:
    aus: list[str] = []
    for k in knoten:
        art = k["art"]
        if art == "absatz":
            aus.append(inline_md(k["text"], bezug))
        elif art == "ueberschrift":
            aus.append("#" * k["ebene"] + " " + inline_md(k["text"], bezug))
        elif art == "liste":
            if k["geordnet"]:
                aus.append("\n".join(f"{i}. {inline_md(e, bezug)}" for i, e in enumerate(k["eintraege"], 1)))
            else:
                aus.append("\n".join(f"- {inline_md(e, bezug)}" for e in k["eintraege"]))
        elif art == "zitat":
            aus.append("> " + inline_md(k["text"], bezug))
        elif art == "bild":
            zusatz = f' "{k["unterschrift"]}"' if k["unterschrift"] else ""
            aus.append(f"![{k['alt']}]({bezug.ziel(k['datei'])}{zusatz})")
        elif art == "kennzahlen":
            aus.append("\n".join(f"- **{z['zahl']}** {inline_md(z['text'], bezug)}" for z in k["kinder"]))
        elif art == "spalte":
            aus.append(f"### {k['label']}")
            aus.extend(knoten_md(k["kinder"], bezug))
        else:
            aus.extend(knoten_md(k["kinder"], bezug))
    return aus


def datum_lang(wert: Any) -> str:
    tag = als_tag(wert)
    return f"{tag.day}. {MONATE[tag.month - 1]} {tag.year}"


def zeit_html(wert: Any) -> str:
    tag = als_tag(wert)
    return f'<time datetime="{tag.isoformat()}">{datum_lang(tag)}</time>'


def lesezeit(b: Beitrag, haus: dict) -> int:
    return max(1, math.ceil(b.woerter / haus["grenzen"]["lesetempo_woerter_je_minute"]))


def lesezeit_text(minuten: int) -> str:
    return f"{minuten} Min. Lesezeit"


def kanonisch(haus: dict, slug: str) -> str:
    return f"{haus['basis']}/blog/{slug}/"


def bild_adresse(b: Beitrag, haus: dict) -> str:
    return bild_mit_version(b.kopf.get("bild") or f"blog/{b.slug}/og.png", haus)


def bild_mit_version(bild: str, haus: dict) -> str:
    """Absolute Bildadresse mit Versionsteil aus den Bytes: Messenger und Netzwerke halten ein Vorschaubild
    unter derselben Adresse lange im Speicher und holen ein neues nur unter einer neuen Adresse."""
    adresse = f"{haus['basis']}/{bild}"
    datei = (WURZEL / bild).resolve()
    if datei.is_file() and datei.is_relative_to(WURZEL.resolve()):
        adresse += f"?v={hashlib.sha256(datei.read_bytes()).hexdigest()[:8]}"
    return adresse


def css_verweis(wurzel: str) -> str:
    """Versionsanhang aus dem Inhalt: Caddy speichert /css/ einen Tag zwischen."""
    daten = lesen(CSS).encode("utf-8") if CSS.is_file() else b""
    return f"{wurzel}css/blog.css?v={hashlib.sha256(daten).hexdigest()[:8]}"


def meta(name: str, wert: str) -> str:
    return f'<meta name="{name}" content="{at(wert)}">'


def eig(name: str, wert: str) -> str:
    return f'<meta property="{name}" content="{at(wert)}">'


def alternate_links(haus: dict, wurzel: str, markdown: str | None) -> list[str]:
    marke = haus["firma"]["kurzname"]
    zeilen = [
        f'<link rel="alternate" type="application/atom+xml" title="{at(marke)}, Blog (Atom)" href="{wurzel}blog/feed.xml">',
        f'<link rel="alternate" type="application/rss+xml" title="{at(marke)}, Blog (RSS)" href="{wurzel}blog/rss.xml">',
    ]
    if markdown:
        zeilen.append(f'<link rel="alternate" type="text/markdown" title="Klartext-Fassung" href="{markdown}">')
    return zeilen


def kopf_meta_beitrag(b: Beitrag, haus: dict, wurzel: str) -> str:
    k = b.kopf
    bild = bild_adresse(b, haus)
    g = haus["grenzen"]
    z = [
        meta("author", haus["autoren"][k["autor"]]["name"]),
        eig("og:type", "article"),
        eig("og:locale", haus["og_locale"]),
        eig("og:site_name", haus["firma"]["kurzname"]),
        eig("og:url", kanonisch(haus, b.slug)),
        eig("og:title", k["titel"]),
        eig("og:description", k["beschreibung"]),
        eig("og:image", bild),
        eig("og:image:width", str(g["bild_breite"])),
        eig("og:image:height", str(g["bild_hoehe"])),
        eig("og:image:alt", k["bild_alt"]),
        eig("article:published_time", k["datum"].isoformat()),
        eig("article:modified_time", k["geaendert"].isoformat()),
    ]
    z.extend(eig("article:tag", w) for w in worte(b, haus))
    z.extend([
        meta("twitter:card", "summary_large_image"),
        meta("twitter:title", k["titel"]),
        meta("twitter:description", k["beschreibung"]),
        meta("twitter:image", bild),
        meta("twitter:image:alt", k["bild_alt"]),
    ])
    z.extend(alternate_links(haus, wurzel, "index.html.md"))
    return "\n".join(z)


def kopf_meta_uebersicht(haus: dict, wurzel: str) -> str:
    blog = haus["blog"]
    bild = bild_mit_version(blog["bild"], haus)
    masse = png_masse(WURZEL / blog["bild"])
    z = [
        meta("author", haus["firma"]["name"]),
        eig("og:type", "website"),
        eig("og:locale", haus["og_locale"]),
        eig("og:site_name", haus["firma"]["kurzname"]),
        eig("og:url", f"{haus['basis']}/blog/"),
        eig("og:title", blog["seitentitel"]),
        eig("og:description", blog["beschreibung"]),
        eig("og:image", bild),
        *([eig("og:image:width", str(masse[0])), eig("og:image:height", str(masse[1]))] if masse else []),
        eig("og:image:alt", blog["bild_alt"]),
        meta("twitter:card", "summary_large_image"),
        meta("twitter:title", blog["seitentitel"]),
        meta("twitter:description", blog["beschreibung"]),
        meta("twitter:image", bild),
        meta("twitter:image:alt", blog["bild_alt"]),
    ]
    z.extend(alternate_links(haus, wurzel, None))
    return "\n".join(z)


def organisation(haus: dict) -> dict:
    f = haus["firma"]
    knoten = {
        "@type": "Organization",
        "@id": f"{haus['basis']}/#organisation",
        "name": f["name"],
        "url": f"{haus['basis']}/",
        "logo": {"@type": "ImageObject", "url": f"{haus['basis']}/{f['logo']}"},
        "email": f["mail"],
        "address": {
            "@type": "PostalAddress",
            "streetAddress": f["strasse"],
            "postalCode": f["plz"],
            "addressLocality": f["ort"],
            "addressCountry": f["land"],
        },
    }
    # Bis zur Wahl keine Nummer: eine Firma hätte sonst mit gleicher @id zwei telephone-Werte im Netz
    if f["telefon_gewaehlt"]:
        knoten["telephone"] = f["telefon_e164"]
    if f["same_as"]:
        knoten["sameAs"] = f["same_as"]
    return knoten


def website(haus: dict) -> dict:
    return {
        "@type": "WebSite",
        "@id": f"{haus['basis']}/#website",
        "url": f"{haus['basis']}/",
        "name": haus["firma"]["kurzname"],
        "publisher": {"@id": f"{haus['basis']}/#organisation"},
    }


def jsonld_html(daten: dict) -> str:
    """Nur das JSON, die Vorlage setzt den Script-Rahmen. < wird maskiert, damit kein Wert den Block beenden kann."""
    return json.dumps(daten, ensure_ascii=False, indent=2, sort_keys=False).replace("<", chr(92) + "u003c")


def quelle_als_werk(q: dict) -> list[dict]:
    werke = []
    werk: dict = {"@type": "CreativeWork", "name": q["titel"], "url": q["url"],
                  "publisher": {"@type": "Organization", "name": q["herausgeber"]}}
    if isinstance(q.get("datum"), (dt.date, dt.datetime)):
        werk["datePublished"] = als_tag(q["datum"]).isoformat()
    werke.append(werk)
    if q.get("zusatz_url"):
        zusatz: dict = {"@type": "CreativeWork", "name": q.get("zusatz_titel", ""), "url": q["zusatz_url"]}
        if q.get("zusatz_herausgeber"):
            zusatz["publisher"] = {"@type": "Organization", "name": q["zusatz_herausgeber"]}
        werke.append(zusatz)
    return werke


def jsonld_beitrag(b: Beitrag, haus: dict) -> str:
    k, g = b.kopf, haus["grenzen"]
    url = kanonisch(haus, b.slug)
    org_id = f"{haus['basis']}/#organisation"
    autor = haus["autoren"][k["autor"]]
    citation = [w for q in k.get("quellen", []) for w in quelle_als_werk(q)]
    posting: dict = {
        "@type": "BlogPosting",
        "@id": f"{url}#beitrag",
        "headline": k["titel"],
        "description": k["beschreibung"],
        "datePublished": k["datum"].isoformat(),
        "dateModified": k["geaendert"].isoformat(),
        "author": {"@id": org_id} if autor["typ"] == "Organization" else {"@type": autor["typ"], "name": autor["name"]},
        "publisher": {"@id": org_id},
        "image": {"@type": "ImageObject", "url": bild_adresse(b, haus), "width": g["bild_breite"], "height": g["bild_hoehe"]},
        "mainEntityOfPage": {"@id": f"{url}#seite"},
        "inLanguage": haus["sprache"],
        "keywords": ", ".join(worte(b, haus)),
        "wordCount": b.woerter,
        "timeRequired": f"PT{lesezeit(b, haus)}M",
        "license": haus["lizenzen"][k["lizenz"]]["url"],
        "isAccessibleForFree": True,
    }
    if citation:
        posting["citation"] = citation
    graph = [
        organisation(haus),
        website(haus),
        {"@type": "WebPage", "@id": f"{url}#seite", "url": url, "name": k["titel"], "inLanguage": haus["sprache"],
         "isPartOf": {"@id": f"{haus['basis']}/#website"}, "breadcrumb": {"@id": f"{url}#brotkrumen"}},
        {"@type": "BreadcrumbList", "@id": f"{url}#brotkrumen", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Startseite", "item": f"{haus['basis']}/"},
            {"@type": "ListItem", "position": 2, "name": haus["blog"]["titel"], "item": f"{haus['basis']}/blog/"},
            {"@type": "ListItem", "position": 3, "name": k["titel"], "item": url},
        ]},
        posting,
    ]
    return jsonld_html({"@context": "https://schema.org", "@graph": graph})


def jsonld_uebersicht(beitraege: list[Beitrag], haus: dict) -> str:
    url = f"{haus['basis']}/blog/"
    graph = [
        organisation(haus),
        website(haus),
        {"@type": "Blog", "@id": f"{url}#blog", "url": url, "name": haus["blog"]["seitentitel"],
         "description": haus["blog"]["beschreibung"], "inLanguage": haus["sprache"],
         "publisher": {"@id": f"{haus['basis']}/#organisation"},
         "blogPost": [{"@type": "BlogPosting", "headline": b.kopf["titel"], "url": kanonisch(haus, b.slug),
                       "datePublished": b.kopf["datum"].isoformat(), "dateModified": b.kopf["geaendert"].isoformat()}
                      for b in beitraege]},
    ]
    return jsonld_html({"@context": "https://schema.org", "@graph": graph})


def brotkrumen_html(eintraege: list[tuple[str, str | None]]) -> str:
    """Nur die Liste, die Vorlage setzt den Rahmen nav.brotkrumen. Das letzte Glied ist die Seite selbst."""
    teile = []
    for text, ziel in eintraege:
        if ziel is None:
            teile.append(f'<li class="hier"><span aria-current="page">{tx(text)}</span></li>')
        else:
            teile.append(f'<li><a href="{at(ziel)}">{tx(text)}</a></li>')
    return "<ol>" + "".join(teile) + "</ol>"


def meta_stand_html(b: Beitrag, haus: dict) -> str:
    k = b.kopf
    rubrik = f'<span class="breit">{tx(k["rubrik"])}<br></span>' if k.get("rubrik") else ""
    # Die einzige Fassungsangabe der Seite; deshalb auch schmal sichtbar, dort fällt nur die Rubrik weg
    return (f'{rubrik}Stand {zeit_html(k["geaendert"])}, Fassung {tx(k["fassung"])}<br>'
            f'Nächste Prüfung {zeit_html(k["pruefen_bis"])}'
            f'<span class="nur-web"><br>{lesezeit_text(lesezeit(b, haus))}</span>')


def anhaenge_html(b: Beitrag) -> str:
    bloecke = []
    for a in b.kopf.get("anhaenge", []):
        z = [f'<a class="knopf" href="{at(a["datei"])}" download>', f"  {PDF_SVG}", f"  {tx(a['knopf'])}", "</a>"]
        if a.get("hinweis"):
            z.append(f'<p class="klein">{tx(a["hinweis"])}</p>')
        bloecke.append("\n".join(z))
    if not bloecke:
        return ""
    return '<div class="werkzeuge nur-web">\n' + "\n".join(bloecke) + "\n</div>"


def verzeichnis_html(b: Beitrag, haus: dict) -> str:
    g = haus["grenzen"]
    if len(b.anker) < g["inhaltsverzeichnis_mindestens"] or (
            len(b.anker) < g["inhaltsverzeichnis_ab_abschnitten"] and b.woerter < g["inhaltsverzeichnis_ab_woertern"]):
        return ""
    punkte = "\n".join(f'    <li><a href="#{at(a)}">{tx(t)}</a></li>' for a, t in b.anker)
    return (f'<nav class="karte inhaltsverzeichnis nur-web" aria-label="Inhalt">\n  <p class="label">Inhalt</p>\n'
            f'  <ol>\n{punkte}\n  </ol>\n</nav>')


def worte(b: Beitrag, haus: dict) -> list[str]:
    """Schlagwörter in der Anzeige; in der Quelle stehen die Schlüssel aus haus.toml."""
    return [haus["schlagwoerter"][w] for w in b.kopf["schlagwoerter"]]


def beitrag_meta(b: Beitrag, haus: dict) -> str:
    k = b.kopf
    schlagwoerter = ", ".join(f'<span class="nb">{tx(w)}</span>' for w in worte(b, haus))
    return f'{zeit_html(k["geaendert"])}, {lesezeit_text(lesezeit(b, haus))}, {schlagwoerter}'


def verwandte_html(b: Beitrag, alle: list[Beitrag], haus: dict) -> str:
    """Bis zu drei Beiträge nach gemeinsamen Schlagwörtern; Gleichstand: jünger zuerst."""
    eigene = set(b.kopf["schlagwoerter"])
    kandidaten = []
    for anderer in alle:
        if anderer.slug == b.slug:
            continue
        gemeinsam = len(eigene & set(anderer.kopf["schlagwoerter"]))
        if gemeinsam:
            kandidaten.append((-gemeinsam, -anderer.kopf["datum"].timestamp(), anderer.slug, anderer))
    kandidaten.sort(key=lambda t: t[:3])
    punkte = [(f'    <li><article><h3 class="beitrag-titel"><a href="../{at(t[3].slug)}/">{tx(t[3].kopf["titel"])}</a></h3>'
               f'<p class="beitrag-meta">{beitrag_meta(t[3], haus)}</p></article></li>')
              for t in kandidaten[:haus["grenzen"]["verwandte_max"]]]
    if not punkte:
        return ""
    return ('<section class="verwandte nur-web" aria-labelledby="verwandte-titel">\n'
            '  <h2 id="verwandte-titel">Verwandte Beiträge</h2>\n  <ul class="beitraege">\n' + "\n".join(punkte) + "\n  </ul>\n</section>")


def kontakt_html(b: Beitrag | None, haus: dict) -> str:
    f = haus["firma"]
    z = ['<p class="label">Kontakt</p>',
         (f'<p>{tx(f["name"])}<br><span class="nb">{tx(f["strasse"])},</span> '
          f'<span class="nb">{tx(f["plz"])} {tx(f["ort"])}</span><br>'
          f'<a href="mailto:{at(f["mail"])}">{tx(f["mail"])}</a><br>'
          f'<a href="tel:{at(f["telefon_e164"])}">{tx(f["telefon_anzeige"])}</a></p>')]
    if b is not None:
        kurz = b.kopf.get("kurzadressen") or []
        pfad = kurz[0] if kurz else f"/blog/{b.slug}/"
        adresse = haus["basis"] + pfad
        anzeige = adresse.split("://", 1)[1]
        satz = b.kopf.get("netz_satz", "Dieser Beitrag im Netz:")
        # Nur im Druck: im Web zeigt die Kurzadresse per Weiterleitung auf dieselbe Seite
        z.append(f'<p class="klein nur-druck">{tx(satz)} <a class="nb" href="{at(adresse)}">{tx(anzeige)}</a></p>')
    return "<div>\n" + "\n".join(z) + "\n</div>"


def quellen_html(b: Beitrag) -> str:
    quellen = b.kopf.get("quellen", [])
    if not quellen:
        return ""
    z = ['<p class="label">Quellen</p>', '<ol class="quellen">']
    for q in quellen:
        eintrag = f'<a href="{at(q["url"])}" rel="noopener">{tx(q["titel"])}</a>'
        if q.get("zusatz_url"):
            eintrag += f'{tx(q.get("zusatz_text", ""))} <a href="{at(q["zusatz_url"])}" rel="noopener">{tx(q.get("zusatz_titel", ""))}</a>'
        if q.get("adresse"):
            eintrag += f' <span class="adresse">{tx(q["adresse"])}</span>'
        z.append(f"  <li>{eintrag}</li>")
    z.append("</ol>")
    return "<div>\n" + "\n".join(z) + "\n</div>"


def lizenz_vorbehalt(liz: dict) -> str:
    """Was die Lizenz nicht erfasst (Lizenzvorbehalt), mit Semikolon angehängt; leer, wenn nichts ausgenommen ist."""
    return f"; {liz['vorbehalt']}" if liz.get("vorbehalt") else ""


def lizenz_html(b: Beitrag, haus: dict) -> str:
    k = b.kopf
    liz = haus["lizenzen"][k["lizenz"]]
    satz = liz.get("satz", "Lizenz:")
    return (f'<p>{tx(liz["text"])} {tx(satz)} <a href="{at(liz["url"])}" rel="noopener">{tx(liz["name"])}</a>'
            f'{tx(lizenz_vorbehalt(liz))}.</p>')


def liste_html(beitraege: list[Beitrag], haus: dict) -> str:
    if not beitraege:
        return '<p class="leer">Noch keine Beiträge.</p>'
    z = ['<ul class="beitraege">']
    for b in beitraege:
        k = b.kopf
        z.extend([
            "  <li><article>",
            f'    <h2 class="beitrag-titel"><a href="{at(b.slug)}/">{tx(k["titel"])}</a></h2>',
            f'    <p class="beitrag-meta">{beitrag_meta(b, haus)}</p>',
            f'    <p>{tx(k["beschreibung"])}</p>',
            "  </article></li>",
        ])
    z.append("</ul>")
    return "\n".join(z)


def markdown_fassung(b: Beitrag, haus: dict) -> str:
    k = b.kopf
    url = kanonisch(haus, b.slug)
    bezug = Bezug(url, "", True, tuple(haus["eigene_hosts"]), haus["basis"])
    liz = haus["lizenzen"][k["lizenz"]]
    teile = [
        f"# {k['titel']}\n<!-- {MARKE} -->",
        "\n".join([
            f"Adresse: {url}",
            f"Stand: {datum_lang(k['geaendert'])}, Fassung {k['fassung']}",
            f"Nächste Prüfung: {datum_lang(k['pruefen_bis'])}",
            f"Herausgeber: {haus['autoren'][k['autor']]['name']}",
            f"Lizenz: {liz['name']} ({liz['url']})",
        ]),
        inline_md(b.vorspann, bezug),
    ]
    for a in k.get("anhaenge", []):
        teile.append(f"[{a['knopf']}]({urllib.parse.urljoin(url, a['datei'])})")
    teile.extend(knoten_md(b.knoten, bezug))
    if k.get("quellen"):
        zeilen = []
        for i, q in enumerate(k["quellen"], 1):
            z = f"{i}. [{q['titel']}]({q['url']})"
            if q.get("zusatz_url"):
                z += f"{q.get('zusatz_text', '')} [{q.get('zusatz_titel', '')}]({q['zusatz_url']})"
            zeilen.append(z)
        teile.append("## Quellen\n\n" + "\n".join(zeilen))
    f = haus["firma"]
    teile.append(f"## Kontakt\n\n{f['name']}, {f['strasse']}, {f['plz']} {f['ort']}, {f['mail']}, {f['telefon_anzeige']}")
    teile.append(f"{liz['text']} {liz.get('satz', 'Lizenz:')} {liz['name']}{lizenz_vorbehalt(liz)}.")
    return "\n\n".join(teile) + "\n"


def feed_inhalt(b: Beitrag, haus: dict) -> str:
    bezug = Bezug(kanonisch(haus, b.slug), "", True, tuple(haus["eigene_hosts"]), haus["basis"])
    teile = [f"<p>{inline_html(b.vorspann, bezug)}</p>"]
    for a in b.kopf.get("anhaenge", []):
        ziel = urllib.parse.urljoin(bezug.kanonisch, a["datei"])
        teile.append(f'<p><a href="{at(ziel)}">{tx(a["knopf"])}</a></p>')
    teile.extend(knoten_html(b.knoten, bezug))
    q = quellen_html(b)
    if q:
        teile.append(q)
    return "\n".join(teile)


def atom_feed(beitraege: list[Beitrag], haus: dict) -> str:
    basis = haus["basis"]
    aktuell = max((b.kopf["geaendert"] for b in beitraege), default=None)
    z = ['<?xml version="1.0" encoding="UTF-8"?>', f"<!-- {MARKE} -->",
         f'<feed xmlns="{ATOM}" xml:lang="{haus["sprache"]}">',
         f"  <title>{tx(haus['blog']['seitentitel'])}</title>",
         f"  <subtitle>{tx(haus['blog']['beschreibung'])}</subtitle>",
         f"  <id>{basis}/blog/</id>",
         f'  <link rel="self" type="application/atom+xml" href="{basis}/blog/feed.xml"/>',
         f'  <link rel="alternate" type="text/html" href="{basis}/blog/"/>',
         f"  <author><name>{tx(haus['firma']['name'])}</name><uri>{basis}/</uri></author>"]
    if aktuell:
        z.append(f"  <updated>{aktuell.isoformat()}</updated>")
    for b in beitraege:
        k = b.kopf
        url = kanonisch(haus, b.slug)
        liz = haus["lizenzen"][k["lizenz"]]
        z.extend(["  <entry>",
                  f"    <id>{url}</id>",
                  f"    <title>{tx(k['titel'])}</title>",
                  f'    <link rel="alternate" type="text/html" href="{url}"/>',
                  f'    <link rel="license" href="{at(liz["url"])}"/>',
                  f"    <published>{k['datum'].isoformat()}</published>",
                  f"    <updated>{k['geaendert'].isoformat()}</updated>",
                  f"    <summary>{tx(k['beschreibung'])}</summary>"])
        z.extend(f'    <category term="{at(w)}"/>' for w in worte(b, haus))
        z.append(f"    <rights>{tx(liz['name'])}</rights>")
        z.append(f'    <content type="html">{tx(feed_inhalt(b, haus))}</content>')
        z.append("  </entry>")
    z.append("</feed>")
    return "\n".join(z) + "\n"


def rfc822(wert: dt.datetime) -> str:
    wtag = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][wert.weekday()]
    monat = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][wert.month - 1]
    versatz = wert.utcoffset() or dt.timedelta()
    minuten = int(versatz.total_seconds() // 60)
    vz = "+" if minuten >= 0 else "-"
    minuten = abs(minuten)
    return f"{wtag}, {wert.day:02d} {monat} {wert.year} {wert:%H:%M:%S} {vz}{minuten // 60:02d}{minuten % 60:02d}"


def rss_feed(beitraege: list[Beitrag], haus: dict) -> str:
    basis = haus["basis"]
    aktuell = max((b.kopf["geaendert"] for b in beitraege), default=None)
    z = ['<?xml version="1.0" encoding="UTF-8"?>', f"<!-- {MARKE} -->",
         f'<rss version="2.0" xmlns:atom="{ATOM}" xmlns:content="http://purl.org/rss/1.0/modules/content/" '
         'xmlns:creativeCommons="http://backend.userland.com/creativeCommonsRssModule">',
         "  <channel>",
         f"    <title>{tx(haus['blog']['seitentitel'])}</title>",
         f"    <link>{basis}/blog/</link>",
         f"    <description>{tx(haus['blog']['beschreibung'])}</description>",
         f"    <language>{haus['sprache'].lower()}</language>",
         f'    <atom:link rel="self" type="application/rss+xml" href="{basis}/blog/rss.xml"/>']
    if aktuell:
        z.append(f"    <lastBuildDate>{rfc822(aktuell)}</lastBuildDate>")
    for b in beitraege:
        k = b.kopf
        url = kanonisch(haus, b.slug)
        z.extend(["    <item>",
                  f"      <title>{tx(k['titel'])}</title>",
                  f"      <link>{url}</link>",
                  f'      <guid isPermaLink="true">{url}</guid>',
                  f"      <pubDate>{rfc822(k['datum'])}</pubDate>",
                  f"      <description>{tx(k['beschreibung'])}</description>"])
        z.extend(f"      <category>{tx(w)}</category>" for w in worte(b, haus))
        z.append(f"      <creativeCommons:license>{tx(haus['lizenzen'][k['lizenz']]['url'])}</creativeCommons:license>")
        z.append(f"      <content:encoded>{tx(feed_inhalt(b, haus))}</content:encoded>")
        z.append("    </item>")
    z.extend(["  </channel>", "</rss>"])
    return "\n".join(z) + "\n"


def sitemap(beitraege: list[Beitrag], haus: dict) -> str:
    feste = lesen(HIER / "sitemap-seiten.xml")
    kopf_ende = feste.index("?>") + 2
    basis = haus["basis"]
    eintraege = []
    jung = max((als_tag(b.kopf["geaendert"]) for b in beitraege), default=None)
    block = [f"  <url>\n    <loc>{basis}/blog/</loc>"]
    if jung:
        block.append(f"    <lastmod>{jung.isoformat()}</lastmod>")
    block.append("  </url>")
    eintraege.append("\n".join(block))
    for b in beitraege:
        eintraege.append(f"  <url>\n    <loc>{kanonisch(haus, b.slug)}</loc>\n"
                         f"    <lastmod>{als_tag(b.kopf['geaendert']).isoformat()}</lastmod>\n  </url>")
    rumpf = feste[kopf_ende:].replace("</urlset>", "\n".join(eintraege) + "\n</urlset>")
    return feste[:kopf_ende] + f"\n<!-- {MARKE} -->" + rumpf


def llms_txt(beitraege: list[Beitrag], haus: dict) -> str:
    basis = haus["basis"]
    z = [f"# {haus['firma']['kurzname']}", f"<!-- {MARKE} -->", "", f"> {haus['llms']['kurzbeschreibung']}", "", "## Beiträge", ""]
    z.extend(f"- [{b.kopf['titel']}]({kanonisch(haus, b.slug)}index.html.md): {b.kopf['beschreibung']}" for b in beitraege)
    z.extend(["", "## Firma", ""])
    z.extend(f"- [{e['titel']}]({basis}/{e['pfad']}): {e['text']}" for e in haus["llms"]["firma"])
    return "\n".join(z) + "\n"


# ---------------------------------------------------------------------------------------------------
# Vorlagen
# ---------------------------------------------------------------------------------------------------
def vorlage(name: str) -> tuple[str, Path]:
    pfad = VORLAGEN / name
    return lesen(pfad), pfad


def einsetzen(name: str, werte: dict, funde: Funde) -> str:
    try:
        text, pfad = vorlage(name)
    except OSError:
        funde.neu(VORLAGEN / name, 1, "P0", "Vorlage fehlt")
        return ""
    vorlage_text = string.Template(text)
    if vorlage_text.is_valid():
        for fehlend in sorted(PFLICHT_VARIABLEN.get(name, set()) - set(vorlage_text.get_identifiers())):
            funde.neu(pfad, 1, "P0", f"Vorlage ohne Pflichtvariable: {fehlend}")
    try:
        return vorlage_text.substitute(werte)
    except KeyError as fehler:
        nr = next((i for i, z in enumerate(text.split("\n"), 1) if f"${fehler.args[0]}" in z), 1)
        funde.neu(pfad, nr, "P0", f"Vorlage nennt eine unbekannte Variable: {fehler.args[0]}")
    except ValueError as fehler:
        funde.neu(pfad, 1, "P0", f"Vorlage ungültig: {fehler}")
    return ""


def marke_einsetzen(text: str) -> str:
    """Die Marke kommt hinter den Doctype: davor schaltet ein Kommentar alte Browser in den Quirks-Modus."""
    kopf = re.match(r"\s*<!doctype html>\s*?\n", text, re.IGNORECASE)
    if kopf:
        return text[:kopf.end()] + f"<!-- {MARKE} -->\n" + text[kopf.end():]
    return f"<!-- {MARKE} -->\n" + text


def seite_beitrag(b: Beitrag, alle: list[Beitrag], haus: dict, funde: Funde) -> str:
    k = b.kopf
    wurzel = "../../"
    bezug = Bezug(kanonisch(haus, b.slug), wurzel, False, tuple(haus["eigene_hosts"]), haus["basis"])
    werte = {
        "wurzel": wurzel,
        "seitentitel": at(k.get("seitentitel") or k["titel"]),
        "beschreibung": at(k["beschreibung"]),
        "kanonisch": at(kanonisch(haus, b.slug)),
        "csp": haus["csp"],
        "kopf_meta": kopf_meta_beitrag(b, haus, wurzel),
        "jsonld": jsonld_beitrag(b, haus),
        "css": at(css_verweis(wurzel)),
        # Sichtbar endet die Krume in jeder Breite bei Blog, der Titel steht gleich darunter; das JSON-LD nennt ihn weiter
        "brotkrumen": brotkrumen_html([("Startseite", wurzel), (haus["blog"]["titel"], "../")]),
        "meta_stand": meta_stand_html(b, haus),
        "titel": tx(k["titel"]),
        "vorspann": f'<p class="lead">{inline_html(b.vorspann, bezug)}</p>',
        "anhaenge": anhaenge_html(b),
        "inhaltsverzeichnis": verzeichnis_html(b, haus),
        "inhalt": "\n".join(knoten_html(b.knoten, bezug)),
        "verwandte": verwandte_html(b, alle, haus),
        "kontakt": kontakt_html(b, haus),
        "quellen": quellen_html(b),
        "lizenz": lizenz_html(b, haus),
    }
    return marke_einsetzen(einsetzen("beitrag.html", werte, funde))


def seite_uebersicht(beitraege: list[Beitrag], haus: dict, funde: Funde) -> str:
    wurzel = "../"
    blog = haus["blog"]
    werte = {
        "wurzel": wurzel,
        "seitentitel": at(blog["seitentitel"]),
        "beschreibung": at(blog["beschreibung"]),
        "kanonisch": at(f"{haus['basis']}/blog/"),
        "csp": haus["csp"],
        "kopf_meta": kopf_meta_uebersicht(haus, wurzel),
        "jsonld": jsonld_uebersicht(beitraege, haus),
        "css": at(css_verweis(wurzel)),
        "brotkrumen": brotkrumen_html([("Startseite", wurzel), (blog["titel"], None)]),
        "titel": tx(blog["titel"]),
        "vorspann": tx(blog["vorspann"]),
        "kontakt": kontakt_html(None, haus),
        "liste": liste_html(beitraege, haus),
    }
    return marke_einsetzen(einsetzen("uebersicht.html", werte, funde))


def seite_weiterleitung(b: Beitrag, kurz: str, haus: dict, funde: Funde) -> str:
    tiefe = kurz.strip("/").count("/") + 1
    werte = {
        "ziel_absolut": at(kanonisch(haus, b.slug)),
        "ziel_relativ": at("../" * tiefe + f"blog/{b.slug}/"),
        "titel": tx(b.kopf["titel"]),
        "csp": haus["csp"],
    }
    return marke_einsetzen(einsetzen("weiterleitung.html", werte, funde))


# ---------------------------------------------------------------------------------------------------
# Bau im Speicher
# ---------------------------------------------------------------------------------------------------
def quellen_laden(funde: Funde, ordner: Path = QUELLEN) -> list[Beitrag]:
    beitraege = []
    if not ordner.is_dir():
        return beitraege
    for pfad in sorted(ordner.glob("*.md")):
        b = quelle_lesen(pfad, funde)
        if b is not None:
            beitraege.append(b)
    return beitraege


def quellzeichen_pruefen(pfade: list[Path], haus: dict, funde: Funde) -> None:
    for pfad in pfade:
        if pfad.is_file():
            zeichen_pruefen(relativ(pfad), lesen(pfad), haus, funde)


def zeichen_pruefen(datei: str, text: str, haus: dict, funde: Funde, entities: bool = False) -> None:
    """Prüfung 1 arbeitet auf Zeichen: U+2013 zwischen zwei Ziffern ist eine Spanne, sonst Satzzeichen."""
    verboten = set(haus["sperren"]["zeichen"]) - {HALBGEVIERT}
    halb = HALBGEVIERT
    for nr, zeile in enumerate(text.split("\n"), 1):
        pruef = html.unescape(zeile) if entities else zeile
        for i, c in enumerate(pruef):
            if c in verboten:
                funde.neu(datei, nr, "P1", f"Maschinen-Zeichen U+{ord(c):04X}")
            elif c == halb and not (0 < i < len(pruef) - 1 and pruef[i - 1].isdigit() and pruef[i + 1].isdigit()):
                funde.neu(datei, nr, "P1", f"Maschinen-Zeichen U+{ord(c):04X} als Satzzeichen")


@dataclass
class Bau:
    ausgaben: dict  # relativer Pfad -> Bytes
    beitraege: list
    kurzadressen: dict  # Kurzadresse -> Beitrag


def bauen_im_speicher(funde: Funde, uebernehmen: tuple = ()) -> Bau:
    haus = haus_laden()
    beitraege = quellen_laden(funde)
    quell_pfade = [b.pfad for b in beitraege] + [HIER / "haus.toml", CSS] + sorted(VORLAGEN.glob("*.html"))
    quellzeichen_pruefen(quell_pfade, haus, funde)
    robots_pruefen(funde)
    liste_pruefen(funde)
    if any(f.pruefung == "P15" and f.text.startswith("Muster ungültig") for f in funde):
        return Bau({}, beitraege, {})
    for b in beitraege:
        kopf_pruefen(b, haus, funde)
        koerper_parsen(b, funde)
    # Die Handseiten schließen aus, was der Generator selbst schreibt: Die Pfade stehen schon vor dem Bau fest
    erzeugt = {f"{k.strip('/')}/index.html": b"" for b in beitraege if isinstance(b.kopf.get("kurzadressen"), list)
               for k in b.kopf["kurzadressen"] if isinstance(k, str)}
    erzeugt.update({f"blog/{b.slug}/index.html": b"" for b in beitraege})
    erzeugt["blog/index.html"] = b""
    firmendaten_pruefen(haus, funde, erzeugt)
    # Doppelte Titel und Beschreibungen über alle Beiträge (Prüfung 8), Kurzadressen eindeutig
    gesehen: dict[tuple, str] = {}
    kurzadressen: dict[str, Beitrag] = {}
    for b in beitraege:
        for feld in ("titel", "beschreibung"):
            wert = b.kopf.get(feld)
            if isinstance(wert, str):
                schluessel = (feld, " ".join(wert.split()).lower())
                if schluessel in gesehen:
                    funde.neu(b.pfad, b.kopf_zeile(feld), "P8", f"{feld} doppelt, zuerst in {gesehen[schluessel]}")
                gesehen[schluessel] = b.slug
        for kurz in b.kopf.get("kurzadressen", []) if isinstance(b.kopf.get("kurzadressen", []), list) else []:
            if not isinstance(kurz, str):
                continue
            if kurz in kurzadressen:
                funde.neu(b.pfad, b.kopf_zeile("kurzadressen"), "P2", f"Kurzadresse {kurz} schon vergeben an {kurzadressen[kurz].slug}")
            if kurz.strip("/") == b.slug:
                funde.neu(b.pfad, b.kopf_zeile("kurzadressen"), "P2", "Kurzadresse gleich dem Slug")
            kurzadressen[kurz] = b
    if funde:
        for b in beitraege:
            freigabe_bindung_pruefen(b, funde)
        return Bau({}, beitraege, kurzadressen)

    beitraege.sort(key=lambda b: (-b.kopf["datum"].timestamp(), b.slug))
    aus: dict[str, bytes] = {}

    def schreibe(pfad: str, text: str) -> None:
        aus[pfad] = text.encode("utf-8")

    for b in beitraege:
        ordner = f"blog/{b.slug}"
        schreibe(f"{ordner}/index.html", seite_beitrag(b, beitraege, haus, funde))
        schreibe(f"{ordner}/index.html.md", markdown_fassung(b, haus))
        for a in b.kopf.get("anhaenge", []):
            aus[f"{ordner}/{a['datei']}"] = (b.pfad.parent / b.slug / a["datei"]).read_bytes()
        for bild in bilder_von(b.knoten):
            q = b.pfad.parent / b.slug / bild
            if q.is_file():
                aus[f"{ordner}/{bild}"] = q.read_bytes()
            else:
                funde.neu(b.pfad, 1, "P3", f"Bild {bild} fehlt in inhalt/blog/{b.slug}/")
        if not b.kopf.get("bild"):
            og = WURZEL / ordner / "og.png"
            if og.is_file():
                aus[f"{ordner}/og.png"] = og.read_bytes()
        for kurz in b.kopf.get("kurzadressen", []):
            ziel = WURZEL / kurz.strip("/") / "index.html"
            if ziel.is_file() and MARKE not in lesen(ziel) and kurz not in uebernehmen:
                funde.neu(b.pfad, b.kopf_zeile("kurzadressen"), "P2",
                          f"{relativ(ziel)} ist keine erzeugte Datei: eine Kurzadresse überschreibt nur mit bauen --uebernehmen {kurz.strip('/')}")
            schreibe(f"{kurz.strip('/')}/index.html", seite_weiterleitung(b, kurz, haus, funde))
    schreibe("blog/index.html", seite_uebersicht(beitraege, haus, funde))
    schreibe("blog/feed.xml", atom_feed(beitraege, haus))
    schreibe("blog/rss.xml", rss_feed(beitraege, haus))
    schreibe("sitemap.xml", sitemap(beitraege, haus))
    schreibe("llms.txt", llms_txt(beitraege, haus))
    schluessel = haus["indexnow"]["schluessel"]
    if not re.match(r"^[a-f0-9]{32}\Z", schluessel):
        funde.neu(HIER / "haus.toml", haus_zeile("schluessel"), "P2", "IndexNow-Schlüssel: Soll 32 Hexzeichen, einmal erzeugt und dann unveränderlich")
    else:
        schreibe(f"{schluessel}.txt", schluessel)
    for pfad in sorted(aus):
        if not ausgeliefert(pfad):
            funde.neu(KOPIERLISTE, 1, "P15", f"{pfad} wird erzeugt, steht aber nicht in der Kopierliste: live 404")
    if not funde:
        ausgaben_pruefen(aus, beitraege, haus, funde)
        ausgaben_abgleichen(aus, haus, funde)
    for b in beitraege:
        freigabe_bindung_pruefen(b, funde)
    return Bau(aus, beitraege, kurzadressen)


def bilder_von(knoten: list) -> list[str]:
    aus = []
    for k in knoten:
        if k["art"] == "bild":
            aus.append(k["datei"])
        elif "kinder" in k:
            aus.extend(bilder_von(k["kinder"]))
    return aus


def norm_text(text: str) -> str:
    """Strichvarianten gelten als gleich: das Handymenü schreibt 3–5, die Quelle 3-5."""
    return re.sub(r"\s+", " ", urllib.parse.unquote(html.unescape(text)).translate(STRICHE))


def org_knoten(daten: Any) -> Any:
    if isinstance(daten, dict):
        typ = daten.get("@type")
        if typ == "Organization" or (isinstance(typ, list) and "Organization" in typ):
            yield daten
        for wert in daten.values():
            yield from org_knoten(wert)
    elif isinstance(daten, list):
        for wert in daten:
            yield from org_knoten(wert)


def traegt_marke(pfad: Path) -> bool:
    with pfad.open("rb") as f:
        return MARKE.encode("utf-8") in f.read(400)


def handseiten(aus: dict) -> Any:
    """Alle ausgelieferten HTML- und JS-Dateien, die nicht vom Generator stammen."""
    for ordner, unter, namen in os.walk(WURZEL):
        unter[:] = sorted(u for u in unter if u not in (".git", "ops", "node_modules", ".claude", "inhalt"))
        for name in sorted(namen):
            if name.endswith((".html", ".js")):
                pfad = Path(ordner) / name
                rel = pfad.relative_to(WURZEL).as_posix()
                # Unter blog/ liegt nur Erzeugtes; eine alte Ausgabe ist verwaist, keine Handseite
                if rel not in aus and not rel.startswith("blog/") and not traegt_marke(pfad):
                    yield rel, pfad


def zeilen_abgleichen(datei: str, text: str, haus: dict, funde: Funde) -> None:
    """Streuung: hinter Nobelstr die Hausnummer, vor dem Ort die PLZ, jede Adresse @sundsconnect.de."""
    f = haus["firma"]
    stamm = f["mail"].split("@", 1)[1].split(".", 1)[0]
    for nr, zeile in enumerate(text.split("\n"), 1):
        t = norm_text(zeile)
        for m in re.finditer("Nobelstr", t):
            danach = t[m.start() + len(f["strasse"]):m.start() + len(f["strasse"]) + 1]
            if not t[m.start():].startswith(f["strasse"]) or danach.isalnum() or danach == "-":
                funde.neu(datei, nr, "P11", f"Anschrift: {t[m.start():m.start() + 30]}; Soll: {f['strasse']}")
        for m in re.finditer(r"\b(\d{5}) " + re.escape(f["ort"]), t):
            if m.group(1) != f["plz"]:
                funde.neu(datei, nr, "P11", f"PLZ: {m.group(0)}; Soll: {f['plz']} {f['ort']}")
        # Auch sundsconnect.dev: nicht die Endung entscheidet, die ganze Adresse muss stimmen
        for m in re.finditer(r"[\w.+-]+@" + re.escape(stamm) + r"(?:\.[\w-]+)+", t, re.IGNORECASE):
            if m.group(0).lower() != f["mail"]:
                funde.neu(datei, nr, "P11", f"Mail: {m.group(0)}; Soll: {f['mail']}")


def jsonld_abgleichen(datei: str, roh: str, haus: dict, funde: Funde) -> list[str]:
    """Jeder Firmeneintrag im JSON-LD einer Handseite gegen haus.toml; gibt die Telefon-Abweichungen zurück."""
    f = haus["firma"]
    basis = haus["basis"]
    telefon: list[str] = []
    for m in re.finditer(r'<script type="application/ld\+json">(.*?)</script>', roh, re.S):
        nr = roh.count("\n", 0, m.start()) + 1
        try:
            daten = json.loads(m.group(1))
        except ValueError as fehler:
            funde.neu(datei, nr, "P11", f"JSON-LD unlesbar: {fehler}")
            continue
        for k in org_knoten(daten):
            logo = k.get("logo")
            logo = logo.get("url") if isinstance(logo, dict) else logo
            pruefen = [("name", k.get("name"), f["name"]), ("logo", logo, f"{basis}/{f['logo']}"), ("email", k.get("email"), f["mail"]),
                       ("@id", k.get("@id"), f"{basis}/#organisation")]
            adresse = k.get("address") if isinstance(k.get("address"), dict) else {}
            pruefen.extend([("streetAddress", adresse.get("streetAddress"), f["strasse"]), ("postalCode", adresse.get("postalCode"), f["plz"]),
                            ("addressLocality", adresse.get("addressLocality"), f["ort"]), ("addressCountry", adresse.get("addressCountry"), f["land"])])
            for feld, ist, soll in pruefen:
                if ist is not None and ist != soll:
                    funde.neu(datei, nr, "P11", f"JSON-LD {feld}: {ist}; Soll: {soll}")
            if "url" in k and str(k["url"]).rstrip("/") != basis:
                funde.neu(datei, nr, "P11", f"JSON-LD url: {k['url']}; Soll: {basis}")
            if "sameAs" in k and sorted(k["sameAs"]) != sorted(f["same_as"]):
                funde.neu(datei, nr, "P11", f"JSON-LD sameAs: {k['sameAs']}; Soll: {f['same_as']}")
            if "telephone" in k and ziffern(str(k["telephone"])) != ziffern(f["telefon_e164"]):
                telefon.append(f"{datei}:{nr}: JSON-LD telephone {k['telephone']}; Soll: {f['telefon_e164']}")
    return telefon


def firmendaten_pruefen(haus: dict, funde: Funde, aus: dict | None = None) -> None:
    """Regel des Datenarchitekten: Handseiten gegen haus.toml, Telefon erst nach Fabrices Wahl."""
    f = haus["firma"]
    toml = HIER / "haus.toml"
    for schluessel in sorted(set(f) - FIRMA_SCHLUESSEL):
        funde.neu(toml, haus_zeile(schluessel), "P11", f"unbekannter Schlüssel in [firma]: {schluessel}; das Repo ist öffentlich")
    anzeige = ziffern(f["telefon_anzeige"])
    anzeige = anzeige if f["telefon_anzeige"].lstrip().startswith("+") else "49" + anzeige.lstrip("0")
    if anzeige != ziffern(f["telefon_e164"]):
        funde.neu(toml, haus_zeile("telefon_anzeige"), "P11", f"telefon_anzeige {f['telefon_anzeige']} ergibt nicht telefon_e164 {f['telefon_e164']}")
    masse = png_masse(WURZEL / f["logo"])
    if masse is None or masse[0] != masse[1] or masse[0] < haus["grenzen"]["logo_min_px"]:
        funde.neu(toml, haus_zeile("logo"), "P11", f"Logo {f['logo']}: {masse}; Soll: PNG, quadratisch, mindestens {haus['grenzen']['logo_min_px']} Pixel")

    telefon: list[str] = []
    aus = aus or {}
    for rel, pfad in handseiten(aus):
        roh = pfad.read_bytes().decode("utf-8", "replace").replace("\r\n", "\n")
        zeilen_abgleichen(rel, roh, haus, funde)
        if rel.endswith(".html"):
            telefon.extend(jsonld_abgleichen(rel, roh, haus, funde))
            for nr, zeile in enumerate(roh.split("\n"), 1):
                for m in re.finditer(r'href="tel:([^"]+)"', zeile):
                    if ziffern(m.group(1)) != ziffern(f["telefon_e164"]):
                        telefon.append(f"{rel}:{nr}: tel:{m.group(1)}; Soll: {f['telefon_e164']}")
        if f["telefon_gewaehlt"]:
            for alt in f["telefon_frueher"]:
                ziff = ziffern(alt)[2:]
                muster = re.compile(r"(?:\+49|0049|0)[\s/().-]*" + r"[\s/().-]*".join(ziff))
                for nr, zeile in enumerate(roh.split("\n"), 1):
                    if muster.search(zeile) and 'href="tel:' not in zeile and '"telephone"' not in zeile:
                        telefon.append(f"{rel}:{nr}: frühere Nummer {alt} im Klartext; Soll: {f['telefon_anzeige']}")

    for rel in haus["abgleich"]["pflichttext"]:
        pfad = WURZEL / rel
        if not pfad.is_file():
            funde.neu(rel, 1, "P11", "Seite fehlt, Pflichtblock nicht prüfbar")
            continue
        text = norm_text(re.sub(r"<[^>]+>", " ", lesen(pfad)))
        muster = re.escape(f["name"]) + r"[^<>]{0,40}? " + re.escape(f["strasse"]) + " " + re.escape(f"{f['plz']} {f['ort']}")
        if not re.search(muster, text):
            funde.neu(rel, zeile_von(lesen(pfad), "Nobelstr"), "P11", f"Pflichtblock fehlt; Soll zusammenhängend: {f['name']}, {f['strasse']}, {f['plz']} {f['ort']}")
    for rel in haus["abgleich"]["mail_pflicht"]:
        pfad = WURZEL / rel
        if not pfad.is_file() or not re.search(rf"mailto:{re.escape(f['mail'])}(?![\w.-])", lesen(pfad)):
            funde.neu(rel, 1, "P11", f"mailto fehlt; Soll: mailto:{f['mail']}")

    if f["telefon_gewaehlt"]:
        for eintrag in telefon:
            datei, nr, text = eintrag.split(":", 2)
            funde.neu(datei, int(nr), "P11", text.strip())
    else:
        funde.telefon = telefon


def zeile_von(text: str, stichwort: str) -> int:
    stelle = text.find(stichwort)
    return text.count("\n", 0, stelle) + 1 if stelle >= 0 else 1


def ausgaben_abgleichen(aus: dict, haus: dict, funde: Funde) -> None:
    """Blogausgabe: tel:, mailto: und Streuung gleich haus.toml; nichts, was ops/stempel.py umschreiben würde."""
    f = haus["firma"]
    telefone = {ziffern(f["telefon_anzeige"]), ziffern(f["telefon_e164"])}
    for pfad, daten in sorted(aus.items()):
        if not pfad.endswith((".html", ".md", ".xml", ".txt")):
            continue
        text = daten.decode("utf-8")
        zeilen_abgleichen(pfad, text, haus, funde)
        for nr, zeile in enumerate(text.split("\n"), 1):
            # Was aus Vorlage oder Kopffeld kommt, fängt die Quellprüfung nicht: hier zählt, was ausgeliefert würde
            for m in TEL_MUSTER.finditer(zeile):
                if ziffern(m.group(0)) not in telefone:
                    funde.neu(pfad, nr, "P13", f"fremde Telefonnummer in der Ausgabe: {m.group(0)}; Soll: {f['telefon_anzeige']}")
            for m in MAIL_MUSTER.finditer(zeile):
                if m.group(0).lower() != f["mail"]:
                    funde.neu(pfad, nr, "P13", f"fremde Mailadresse in der Ausgabe: {m.group(0)}; Soll: {f['mail']}")
            klar = norm_text(zeile)
            for m in STRASSEN_MUSTER.finditer(klar):
                if not klar[m.start():].startswith(f["strasse"]):
                    funde.neu(pfad, nr, "P13", f"fremde Straße in der Ausgabe: {m.group(0)}; Soll: {f['strasse']}")
            for m in re.finditer(r'href="tel:([^"]+)"', zeile):
                if ziffern(m.group(1)) != ziffern(f["telefon_e164"]):
                    funde.neu(pfad, nr, "P11", f"tel:{m.group(1)}; Soll: {f['telefon_e164']}")
            for m in re.finditer(r'href="mailto:([^"?]+)', zeile):
                if m.group(1).lower() != f["mail"]:
                    funde.neu(pfad, nr, "P11", f"mailto:{m.group(1)}; Soll: {f['mail']}")
            if pfad.endswith(".html") and STEMPEL_MUSTER.search(zeile):
                funde.neu(pfad, nr, "P14", "style.css oder main.js in der Blogausgabe: ops/stempel.py schriebe die Datei um und der Byte-Vergleich sperrte den Deploy")


def robots_sperrt_blog(regel: str) -> bool:
    """Greift die Regel unter /blog/? Mit Platzhalter und Endmarke, wie Suchmaschinen sie lesen."""
    if regel.lower().startswith("/blog"):
        return True
    muster = re.escape(regel).replace(r"\*", ".*")
    if muster.endswith(r"\$"):
        muster = muster[:-2] + r"\Z"
    return any(re.match(muster, p) for p in ("/blog/", "/blog/feed.xml", "/blog/rss.xml", "/blog/x/", "/blog/x/index.html", "/blog/x/index.html.md"))


def robots_pruefen(funde: Funde) -> None:
    pfad = WURZEL / "robots.txt"
    if not pfad.is_file():
        funde.neu(pfad, 1, "P12", "robots.txt fehlt")
        return
    zeilen = lesen(pfad).split("\n")
    if not any(z.strip().lower().startswith("sitemap:") for z in zeilen):
        funde.neu(pfad, 1, "P12", "robots.txt ohne Zeile Sitemap:")
    for nr, z in enumerate(zeilen, 1):
        m = re.match(r"(?i)\s*disallow\s*:\s*(\S+)", z)
        if m and robots_sperrt_blog(m.group(1)):
            funde.neu(pfad, nr, "P12", f"robots.txt sperrt das Blog: {z}")


# ---------------------------------------------------------------------------------------------------
# Prüfungen auf den Ausgaben (1, 4, 5, 6, 9)
# ---------------------------------------------------------------------------------------------------
class HtmlScan(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict, int]] = []
        self.ids: set[str] = set()
        self.jsonld: list[tuple[int, str]] = []
        self.styles: list[int] = []
        self.skripte: list[int] = []
        self.csp: list[tuple[str, int, bool]] = []  # Inhalt, Zeile, im head
        self._im_head = False
        self._im_jsonld: int | None = None
        self._puffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        a = {k: (v or "") for k, v in attrs}
        zeile = self.getpos()[0]
        self.tags.append((tag, a, zeile))
        if tag == "head":
            self._im_head = True
        elif tag == "body":
            self._im_head = False
        if tag == "meta" and a.get("http-equiv", "").lower() == "content-security-policy":
            self.csp.append((a.get("content", ""), zeile, self._im_head))
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        if tag == "style":
            self.styles.append(zeile)
        if tag == "script":
            if a.get("type") == "application/ld+json" and "src" not in a:
                self._im_jsonld = zeile
                self._puffer = []
            else:
                self.skripte.append(zeile)

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        self.handle_starttag(tag, attrs)

    def handle_data(self, data: str) -> None:
        if self._im_jsonld is not None:
            self._puffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "head":
            self._im_head = False
        if tag == "script" and self._im_jsonld is not None:
            self.jsonld.append((self._im_jsonld, "".join(self._puffer)))
            self._im_jsonld = None


def eigener_pfad(ziel: str, von: str, hosts: tuple) -> tuple[str, str] | None:
    """Gibt (Pfad relativ zur Site-Wurzel, Marke) für Ziele auf der eigenen Domain; sonst None."""
    teil = urllib.parse.urlsplit(ziel)
    if teil.scheme and teil.scheme not in ("http", "https"):
        return None
    if teil.scheme or teil.netloc:
        if teil.hostname not in hosts:
            return None
        pfad = teil.path.lstrip("/")
        if not teil.path or teil.path.endswith("/"):
            pfad = pfad.rstrip("/") + "/" if pfad else ""
        return urllib.parse.unquote(pfad), teil.fragment
    if not teil.path:
        return von, teil.fragment
    if teil.path.startswith("/"):
        return urllib.parse.unquote(teil.path.lstrip("/")), teil.fragment
    basis = posixpath.dirname(von)
    verbunden = posixpath.normpath(posixpath.join(basis, urllib.parse.unquote(teil.path)))
    if teil.path.endswith("/") or teil.path.endswith("/."):
        verbunden += "/"
    if verbunden in ("./", "."):
        verbunden = ""
    return verbunden, teil.fragment


def ziel_inhalt(pfad: str, ausgaben: dict) -> tuple[str, bytes | None] | None:
    """Findet das Linkziel in den Ausgaben oder in der festen Site, soweit die Kopierliste sie ausliefert; None heißt kaputt."""
    if pfad.startswith(".."):
        return None
    kandidaten = []
    if pfad == "" or pfad.endswith("/"):
        kandidaten.append(pfad + "index.html")
    else:
        kandidaten.extend([pfad, pfad + "/index.html"])
    for k in kandidaten:
        if not ausgeliefert(k):
            continue
        if k in ausgaben:
            return k, ausgaben[k]
        datei = WURZEL / k
        if datei.is_file():
            return k, None
    return None


def ausgaben_pruefen(aus: dict, beitraege: list[Beitrag], haus: dict, funde: Funde) -> None:
    hosts = tuple(haus["eigene_hosts"])
    sperrhosts = haus["sperren"]["hosts"]
    scans: dict[str, HtmlScan] = {}

    def scan_von(pfad: str, daten: bytes | None) -> HtmlScan:
        if pfad not in scans:
            s = HtmlScan()
            s.feed((daten if daten is not None else (WURZEL / pfad).read_bytes()).decode("utf-8", "replace"))
            scans[pfad] = s
        return scans[pfad]

    for pfad, daten in sorted(aus.items()):
        if pfad.endswith((".html", ".xml", ".md", ".txt")):
            zeichen_pruefen(pfad, daten.decode("utf-8"), haus, funde, entities=pfad.endswith(".html"))
    css_pruefen(hosts, aus, funde)

    for pfad, daten in sorted(aus.items()):
        if not pfad.endswith(".html"):
            continue
        s = scan_von(pfad, daten)
        # Prüfung 6: CSP-Meta, und nichts, was sie blockieren würde
        csp = [(inhalt, z) for inhalt, z, im_head in s.csp if im_head]
        for _, z, im_head in s.csp:
            if not im_head:
                funde.neu(pfad, z, "P6", "CSP-Meta außerhalb von head: Browser ignorieren sie dort")
        if not csp or csp[0][0] != haus["csp"]:
            funde.neu(pfad, csp[0][1] if csp else 1, "P6", "CSP-Meta fehlt oder weicht von haus.toml ab")
        elif not csp_streng(csp[0][0]):
            funde.neu(pfad, csp[0][1], "P6", "CSP zu weich; Soll: script-src 'none', object-src 'none', ohne unsafe-inline und unsafe-eval")
        for z in s.skripte:
            funde.neu(pfad, z, "P6", "Skript auf der Seite: script-src 'none' würde es blockieren")
        for z in s.styles:
            funde.neu(pfad, z, "P6", "<style>-Block: die CSP ohne unsafe-inline würde ihn blockieren")
        for tag, attrs, zeile in s.tags:
            if "style" in attrs:
                funde.neu(pfad, zeile, "P6", "style-Attribut: die CSP ohne unsafe-inline würde es blockieren")
            ziele = [(n, attrs[n]) for n in ("href", "src") if attrs.get(n)]
            for n in ("srcset", "imagesrcset"):
                ziele.extend((n, teil.split()[0]) for teil in attrs.get(n, "").split(",") if teil.strip())
            if tag == "meta" and attrs.get("http-equiv", "").lower() == "refresh":
                m = re.search(r"url=(.+)$", attrs.get("content", ""), re.IGNORECASE)
                if m:
                    ziele.append(("refresh", m.group(1).strip()))
            for art, ziel in ziele:
                ziel = html.unescape(ziel)
                roh = urllib.parse.urlsplit(ziel)
                if roh.scheme in ("mailto", "tel", "data"):
                    continue
                if any(h.lower() in ziel.lower() for h in sperrhosts):
                    funde.neu(pfad, zeile, "P5", f"Sperrliste: {ziel}")
                    continue
                aufgeloest = eigener_pfad(ziel, pfad, hosts)
                if aufgeloest is None:
                    # Fremd: nur als <a> mit rel=noopener erlaubt
                    if tag != "a" or art != "href":
                        if not (tag == "link" and attrs.get("rel", "") in ("alternate",)):
                            funde.neu(pfad, zeile, "P5", f"Fremdquelle: <{tag} {art}={ziel}>")
                    elif "noopener" not in attrs.get("rel", ""):
                        funde.neu(pfad, zeile, "P5", f"Fremder Link ohne rel=noopener: {ziel}")
                    continue
                ziel_pfad, marke = aufgeloest
                treffer = ziel_inhalt(ziel_pfad, aus)
                if treffer is None:
                    funde.neu(pfad, zeile, "P4", f"Kaputter Link: {ziel}")
                    continue
                if marke:
                    ziel_datei, ziel_daten = treffer
                    if ziel_datei.endswith(".html") and marke not in scan_von(ziel_datei, ziel_daten).ids:
                        funde.neu(pfad, zeile, "P4", f"Marke #{marke} fehlt in {ziel_datei}")
            if tag == "link" and attrs.get("rel", "").lower() in ("stylesheet", "preload", "icon", "apple-touch-icon"):
                if eigener_pfad(attrs.get("href", ""), pfad, hosts) is None:
                    funde.neu(pfad, zeile, "P5", f"Fremdquelle in <link>: {attrs.get('href')}")
        # Prüfung 9: JSON-LD
        jsonld_pruefen(pfad, s, funde, haus["firma"]["telefon_gewaehlt"])

    for pfad in ("blog/feed.xml", "blog/rss.xml", "sitemap.xml"):
        try:
            ET.fromstring(aus[pfad])
        except ET.ParseError as fehler:
            funde.neu(pfad, fehler.position[0], "P9", f"kein lesbares XML: {fehler}")


CSP_DIREKTIVEN = {"default-src", "style-src", "img-src", "font-src", "script-src", "object-src", "base-uri", "form-action"}


def csp_streng(csp: str) -> bool:
    """Fest im Code, nicht in haus.toml: wer die Richtlinie dort aufweicht, soll trotzdem am Bau scheitern."""
    teile = {s.split()[0]: s.split()[1:] for s in csp.lower().split(";") if s.strip()}
    if set(teile) - CSP_DIREKTIVEN:  # script-src-elem, script-src-attr, worker-src und Verwandte weichen script-src auf
        return False
    if teile.get("script-src") != ["'none'"] or teile.get("object-src") != ["'none'"]:
        return False
    return not any("unsafe" in w or "://" in w or w in ("*", "http:", "https:") for werte in teile.values() for w in werte)


def css_pruefen(hosts: tuple, aus: dict, funde: Funde) -> None:
    if not CSS.is_file():
        funde.neu(CSS, 1, "P0", "css/blog.css fehlt")
        return
    for nr, zeile in enumerate(lesen(CSS).split("\n"), 1):
        for m in re.finditer(r"""(?:url\(\s*|@import\s+(?!url\())['"]?([^'")\s;]+)""", zeile, re.IGNORECASE):
            ziel = m.group(1)
            if ziel.lower().startswith("data:"):
                continue
            aufgeloest = eigener_pfad(ziel, "css/blog.css", hosts)
            if aufgeloest is None:
                funde.neu(CSS, nr, "P5", f"Fremdquelle in url(): {ziel}")
            elif ziel_inhalt(aufgeloest[0], aus) is None:
                funde.neu(CSS, nr, "P4", f"url() zeigt ins Leere: {ziel}")


PFLICHT_POSTING = ("headline", "description", "datePublished", "dateModified", "author", "publisher", "image",
                   "mainEntityOfPage", "inLanguage", "keywords", "wordCount", "timeRequired", "license",
                   "isAccessibleForFree")


def jsonld_pruefen(pfad: str, s: HtmlScan, funde: Funde, telefon_pflicht: bool = False) -> None:
    ist_beitrag = bool(re.match(r"blog/[^/]+/index\.html$", pfad))
    ist_uebersicht = pfad == "blog/index.html"
    if not ist_beitrag and not ist_uebersicht:
        return
    if len(s.jsonld) != 1:
        funde.neu(pfad, 1, "P9", f"{len(s.jsonld)} JSON-LD-Blöcke, verlangt genau einer")
        return
    zeile, text = s.jsonld[0]
    try:
        daten = json.loads(text)
    except json.JSONDecodeError as fehler:
        funde.neu(pfad, zeile + fehler.lineno - 1, "P9", f"JSON-LD nicht lesbar: {fehler.msg}")
        return
    graph = daten.get("@graph") if isinstance(daten, dict) else None
    if not isinstance(graph, list):
        funde.neu(pfad, zeile, "P9", "JSON-LD ohne @graph")
        return
    typen = {g.get("@type"): g for g in graph if isinstance(g, dict)}
    verlangt = ["Organization", "WebSite"] + (["WebPage", "BreadcrumbList", "BlogPosting"] if ist_beitrag else ["Blog"])
    for typ in verlangt:
        if typ not in typen:
            funde.neu(pfad, zeile, "P9", f"JSON-LD ohne {typ}")
    org = typen.get("Organization", {})
    for feld in ("@id", "name", "address", "email", "logo") + (("telephone",) if telefon_pflicht else ()):
        if "Organization" in typen and not org.get(feld):
            funde.neu(pfad, zeile, "P9", f"Organization ohne {feld}")
    if ist_beitrag and "BlogPosting" in typen:
        for feld in PFLICHT_POSTING:
            if typen["BlogPosting"].get(feld) in (None, "", []):
                funde.neu(pfad, zeile, "P9", f"BlogPosting ohne {feld}")


# ---------------------------------------------------------------------------------------------------
# Vergleich mit der Platte (Prüfung 10)
# ---------------------------------------------------------------------------------------------------
def platte_vergleichen(aus: dict) -> tuple[list[str], list[str], list[str]]:
    aktuell, veraltet, fehlt = [], [], []
    for pfad, daten in sorted(aus.items()):
        datei = WURZEL / pfad
        if not datei.is_file():
            fehlt.append(pfad)
        elif datei.read_bytes() == daten:
            aktuell.append(pfad)
        else:
            veraltet.append(pfad)
    return aktuell, veraltet, fehlt


def verwaist(aus: dict) -> list[str]:
    """Dateien unter blog/ ohne Quelle und erzeugte Seiten anderswo, etwa eine aufgegebene Kurzadresse. Thema-Ordner kommen erst in Stufe 2."""
    gefunden = []
    ordner = WURZEL / "blog"
    if ordner.is_dir():
        for datei in sorted(ordner.rglob("*")):
            if datei.is_file():
                rel = datei.relative_to(WURZEL).as_posix()
                if rel not in aus:
                    gefunden.append(rel)
    for wurzel_ordner, unter, namen in os.walk(WURZEL):
        unter[:] = sorted(u for u in unter if u not in (".git", "ops", "node_modules", ".claude", "inhalt", "blog"))
        if "index.html" in namen:
            datei = Path(wurzel_ordner) / "index.html"
            rel = datei.relative_to(WURZEL).as_posix()
            if rel not in aus and traegt_marke(datei):
                gefunden.append(rel)
    return gefunden


def vorher_slugs(sitemap_text: str) -> set[str]:
    return set(re.findall(r"<loc>[^<]*/blog/([a-z0-9-]+)/</loc>", sitemap_text))


def vorher_sitemap(pfad: str | None) -> tuple[str | None, str]:
    if pfad:
        return Path(pfad).read_bytes().decode("utf-8"), pfad
    git = shutil.which("git")
    if git:
        try:
            lauf = subprocess.run([git, "show", "origin/main:sitemap.xml"], cwd=WURZEL, capture_output=True, timeout=20, check=False)
        except (OSError, subprocess.SubprocessError):
            return None, ""
        if lauf.returncode == 0:
            return lauf.stdout.decode("utf-8", "replace"), "origin/main:sitemap.xml"
    return None, ""


def fehler_ausgeben(funde: Funde) -> None:
    for fund in sorted(set(funde), key=lambda f: (f.datei, f.zeile, f.pruefung, f.text)):
        print(fund)


# ---------------------------------------------------------------------------------------------------
# Befehle
# ---------------------------------------------------------------------------------------------------
def befehl_bauen(args: argparse.Namespace) -> int:
    funde = Funde()
    # Ohne führenden Schrägstrich angeben: Git Bash macht aus /name/ sonst einen Windows-Pfad
    bau = bauen_im_speicher(funde, tuple("/" + k.strip("/") + "/" for k in (args.uebernehmen or ())))
    if funde:
        fehler_ausgeben(funde)
        return 1
    haus = haus_laden()
    vorher = og_stand(bau)
    code = og_bilder(bau, haus, funde)
    if code:
        return code
    if funde:
        fehler_ausgeben(funde)
        return 1
    if og_stand(bau) != vorher:
        # Das og.png steht jetzt auf der Platte; die Seiten tragen seinen Versionsteil erst im zweiten Durchgang
        bau = bauen_im_speicher(funde, tuple("/" + k.strip("/") + "/" for k in (args.uebernehmen or ())))
        if funde:
            fehler_ausgeben(funde)
            return 1
    geschrieben = 0
    for pfad, daten in sorted(bau.ausgaben.items()):
        datei = WURZEL / pfad
        if datei.is_file() and datei.read_bytes() == daten:
            continue
        atomar_schreiben(datei, daten)
        geschrieben += 1
    uebrig = verwaist(bau.ausgaben)
    print(f"bauen: {len(bau.beitraege)} Beiträge, {len(bau.ausgaben)} Ausgaben, {geschrieben} geschrieben, {len(uebrig)} verwaist")
    for pfad in uebrig:
        print(f"verwaist (bleibt liegen, nichts wird gelöscht): {pfad}")
    return 0


def atomar_schreiben(datei: Path, daten: bytes) -> None:
    datei.parent.mkdir(parents=True, exist_ok=True)
    griff, zwischen = tempfile.mkstemp(dir=datei.parent, prefix=".blog-")
    try:
        with os.fdopen(griff, "wb") as f:
            f.write(daten)
        os.replace(zwischen, datei)
    except BaseException:
        Path(zwischen).unlink(missing_ok=True)
        raise


def og_stand(bau: Bau) -> dict:
    """Bytes der erzeugten Vorschaubilder auf der Platte, je Beitrag ohne eigenes bild."""
    stand = {}
    for b in bau.beitraege:
        if not b.kopf.get("bild"):
            datei = WURZEL / "blog" / b.slug / "og.png"
            stand[b.slug] = datei.read_bytes() if datei.is_file() else None
    return stand


def og_bilder(bau: Bau, haus: dict, funde: Funde) -> int:
    """Vorschaubild aus og.html, nur wenn sich Titel oder Vorlage geändert haben. Ohne Node oder Chrome Exit 3."""
    offen = [b for b in bau.beitraege if not b.kopf.get("bild")]
    if not offen:
        return 0
    marken = json.loads(lesen(OG_MARKEN)) if OG_MARKEN.is_file() else {}
    for b in offen:
        unterzeile = b.kopf.get("rubrik") or haus["firma"]["kurzname"]
        werte = {"titel": tx(b.kopf["titel"]), "unterzeile": tx(unterzeile), "wurzel": ""}
        # Die Marke rechnet ohne den Ort der Zwischendatei, sonst hinge sie am Ordner des Baus
        marke = hashlib.sha256(einsetzen("og.html", werte, funde).encode("utf-8")).hexdigest()
        seite = einsetzen("og.html", {**werte, "wurzel": WURZEL.as_uri() + "/"}, funde)
        if funde:
            return 0
        ziel = WURZEL / "blog" / b.slug / "og.png"
        if ziel.is_file() and marken.get(b.slug) == marke:
            continue
        node = shutil.which("node")
        skript = WURZEL / "ops" / "schirmfoto.mjs"
        if not node or not skript.is_file():
            print(f"blog/{b.slug}/og.png fehlt oder ist veraltet, und ohne Node oder Chrome lässt es sich nicht erzeugen")
            return 3
        with tempfile.TemporaryDirectory() as tmp:
            quelle = Path(tmp) / "og.html"
            quelle.write_text(seite, encoding="utf-8")
            ziel.parent.mkdir(parents=True, exist_ok=True)
            try:
                lauf = subprocess.run([node, str(skript), quelle.as_uri(), str(ziel), "--breite", "1200", "--hoehe", "630", "--dpr", "1"],
                                      capture_output=True, timeout=120, check=False)
            except (OSError, subprocess.TimeoutExpired) as fehler:
                print(f"blog/{b.slug}/og.png: Schirmfoto gescheitert: {fehler}")
                return 3
        if lauf.returncode != 0 or png_masse(ziel) != (haus["grenzen"]["bild_breite"], haus["grenzen"]["bild_hoehe"]):
            print(f"blog/{b.slug}/og.png: Schirmfoto gescheitert (Exit {lauf.returncode})")
            return 3
        marken[b.slug] = marke
        bau.ausgaben[f"blog/{b.slug}/og.png"] = ziel.read_bytes()
    atomar_schreiben(OG_MARKEN, (json.dumps(marken, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    return 0


def befehl_pruefen(args: argparse.Namespace) -> int:
    if args.nur_quelle:
        return pruefen_nur_quelle(Path(args.nur_quelle))
    funde = Funde()
    bau = bauen_im_speicher(funde)
    if not funde:
        haus = haus_laden()
        for b in bau.beitraege:
            if not b.kopf.get("bild"):
                groesse_pruefen(WURZEL / "blog" / b.slug / "og.png", haus, funde, b.pfad, b.kopf_zeile("bild_alt"))
        _, veraltet, fehlt = platte_vergleichen(bau.ausgaben)
        for pfad in veraltet:
            funde.neu(pfad, abweichung_zeile(pfad, bau.ausgaben[pfad]), "P10", "weicht vom frischen Bau ab (von Hand geändert oder Bauen vergessen)")
        for pfad in fehlt:
            funde.neu(pfad, 1, "P10", "fehlt: Bauen vergessen")
        for pfad in verwaist(bau.ausgaben):
            funde.neu(pfad, 1, "P10", "verwaist: Datei unter blog/ ohne Quelle")
    vorher, herkunft = vorher_sitemap(args.vorher)
    if vorher is None:
        print("Slug-Vergleich: nicht geprüft (keine Sitemap der letzten Veröffentlichung, --vorher fehlt)")
    elif not funde:
        heute = {b.slug for b in bau.beitraege}
        for slug in sorted(vorher_slugs(vorher) - heute):
            funde.neu("inhalt/blog", 1, "P10", f"Slug {slug} ist veröffentlicht ({herkunft}), die Quelle fehlt: ein Slug ist unveränderlich")
    if funde:
        fehler_ausgeben(funde)
        print(f"pruefen: {len(set(funde))} Funde")
        return 1
    print(f"pruefen: grün, {len(bau.beitraege)} Beiträge, {len(bau.ausgaben)} Ausgaben byte-gleich")
    if funde.telefon:
        print(f"Telefon der Handseiten: {len(funde.telefon)} Abweichungen, nur gemeldet, bis telefon_gewaehlt = true")
    return 0


def abweichung_zeile(pfad: str, neu: bytes) -> int:
    try:
        alt = (WURZEL / pfad).read_bytes()
    except OSError:
        return 1
    if b"\0" in neu[:1024]:
        return 1
    for nr, (a, b) in enumerate(zip(alt.split(b"\n"), neu.split(b"\n")), 1):
        if a != b:
            return nr
    return alt.count(b"\n") + 1


def quelle_einzeln(pfad: Path, haus: dict, funde: Funde) -> Beitrag | None:
    b = quelle_lesen(pfad, funde)
    zeichen_pruefen(relativ(pfad), lesen(pfad), haus, funde)
    if b is None:
        return None
    kopf_pruefen(b, haus, funde, nur_quelle=True)
    koerper_parsen(b, funde)
    freigabe_bindung_pruefen(b, funde)
    return b


def pruefen_nur_quelle(pfad: Path) -> int:
    """Ohne Repo: dort liegt nur diese Datei, mit blog.py und haus.toml daneben."""
    if not pfad.is_file():
        print(f"{pfad}: Datei fehlt")
        return 2
    funde = Funde()
    quelle_einzeln(pfad, haus_laden(), funde)
    if funde:
        fehler_ausgeben(funde)
        return 1
    print(f"pruefen --nur-quelle: grün, {pfad.name}")
    return 0


def heute_von(args: argparse.Namespace) -> dt.date:
    return dt.date.fromisoformat(args.heute) if getattr(args, "heute", None) else dt.date.today()


def befehl_stand(args: argparse.Namespace) -> int:
    funde = Funde()
    bau = bauen_im_speicher(funde)
    haus = haus_laden()
    quellen_zahl = len(list(QUELLEN.glob("*.md"))) if QUELLEN.is_dir() else 0
    bericht: dict = {"quellen": quellen_zahl, "veroeffentlicht": 0, "funde": [str(f) for f in sorted(set(funde), key=str)]}
    abweichung = bool(funde)
    if not funde:
        aktuell, veraltet, fehlt = platte_vergleichen(bau.ausgaben)
        uebrig = verwaist(bau.ausgaben)
        slugs = {b.slug for b in bau.beitraege}
        heute = heute_von(args)
        grenze = heute + dt.timedelta(days=haus["grenzen"]["stand_pruefdatum_tage"])
        faellig = sorted(b.slug for b in bau.beitraege if als_tag(b.kopf["pruefen_bis"]) <= grenze)
        verzeichnisse = {
            "sitemap": eintraege_sitemap(),
            "atom": eintraege_atom(),
            "rss": eintraege_rss(),
            "llms": eintraege_llms(),
        }
        bericht.update({
            "veroeffentlicht": len(bau.beitraege),
            "ausgaben": {"aktuell": len(aktuell), "veraltet": veraltet, "fehlt": fehlt, "verwaist": uebrig},
            "verzeichnisse": {name: {"gefunden": len(menge), "soll": len(slugs), "fehlt": sorted(slugs - menge), "zuviel": sorted(menge - slugs)}
                              for name, menge in verzeichnisse.items()},
            "pruefdaten_faellig": faellig,
        })
        abweichung = bool(veraltet or fehlt or uebrig or any(menge != slugs for menge in verzeichnisse.values()))
    if args.live and not funde:
        live = live_messen(bau, haus, args.basis or haus["basis"], not args.ohne_quellen)
        bericht["live"] = live
        abweichung = abweichung or bool(live["abweichungen"])
    if args.json:
        print(json.dumps(bericht, ensure_ascii=False, indent=2))
    else:
        stand_ausgeben(bericht)
    return 1 if abweichung else 0


def stand_ausgeben(b: dict) -> None:
    print(f"Quellen: {b['quellen']}, veröffentlicht: {b['veroeffentlicht']}")
    for f in b["funde"]:
        print(f)
    if "ausgaben" in b:
        a = b["ausgaben"]
        print(f"Ausgaben: {a['aktuell']} aktuell, {len(a['veraltet'])} veraltet, {len(a['fehlt'])} fehlen, {len(a['verwaist'])} verwaist")
        for art in ("veraltet", "fehlt", "verwaist"):
            for pfad in a[art]:
                print(f"  {art}: {pfad}")
        for name, v in b["verzeichnisse"].items():
            zusatz = f", fehlt {v['fehlt']}" if v["fehlt"] else ""
            zusatz += f", zu viel {v['zuviel']}" if v["zuviel"] else ""
            print(f"{name}: {v['gefunden']} von {v['soll']}{zusatz}")
        print(f"Prüfdaten fällig: {len(b['pruefdaten_faellig'])} {b['pruefdaten_faellig'] or ''}".rstrip())
    if "live" in b:
        print(f"Live: {b['live']['geprueft']} Adressen geprüft, {len(b['live']['abweichungen'])} Abweichungen")
        for z in b["live"]["abweichungen"]:
            print(f"  {z}")
        for z in b["live"]["hinweise"]:
            print(f"  Hinweis: {z}")


def eintraege_sitemap() -> set[str]:
    pfad = WURZEL / "sitemap.xml"
    return vorher_slugs(lesen(pfad)) if pfad.is_file() else set()


def eintraege_atom() -> set[str]:
    pfad = WURZEL / "blog" / "feed.xml"
    return set(re.findall(r"<id>[^<]*/blog/([a-z0-9-]+)/</id>", lesen(pfad))) if pfad.is_file() else set()


def eintraege_rss() -> set[str]:
    pfad = WURZEL / "blog" / "rss.xml"
    return set(re.findall(r"<guid[^>]*>[^<]*/blog/([a-z0-9-]+)/</guid>", lesen(pfad))) if pfad.is_file() else set()


def eintraege_llms() -> set[str]:
    pfad = WURZEL / "llms.txt"
    return set(re.findall(r"/blog/([a-z0-9-]+)/index\.html\.md\)", lesen(pfad))) if pfad.is_file() else set()


class OhneWeiterleitung(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def holen(url: str) -> tuple[int, dict, bytes]:
    """GET ohne Weiterleitung mit harter Zeitgrenze; 3xx und 4xx sind Antworten, keine Ausnahmen."""
    oeffner = urllib.request.build_opener(OhneWeiterleitung)
    anfrage = urllib.request.Request(url, headers={"User-Agent": BENUTZERKENNUNG})
    try:
        with oeffner.open(anfrage, timeout=ZEITGRENZE_S) as antwort:
            return antwort.status, dict(antwort.headers.items()), antwort.read()
    except urllib.error.HTTPError as fehler:
        return fehler.code, dict(fehler.headers.items()), b""
    except http.client.HTTPException as fehler:
        raise OSError(f"HTTP-Fehler: {fehler}") from fehler


def live_messen(bau: Bau, haus: dict, basis: str, mit_quellen: bool = True) -> dict:
    abweichungen: list[str] = []
    hinweise: list[str] = []
    kurz_seiten = {f"{k.strip('/')}/index.html" for k in bau.kurzadressen}
    geprueft = 0
    for pfad, daten in sorted(bau.ausgaben.items()):
        if pfad in kurz_seiten:
            continue
        pfad_url = pfad[:-len("index.html")] if pfad.endswith("/index.html") else pfad
        url = f"{basis}/{urllib.parse.quote(pfad_url)}"
        geprueft += 1
        try:
            status, koepfe, koerper = holen(url)
        except OSError as fehler:
            abweichungen.append(f"{url}: nicht erreichbar ({fehler})")
            continue
        if status != 200:
            abweichungen.append(f"{url}: Status {status}, erwartet 200")
            continue
        if md5(koerper) != md5(daten):
            abweichungen.append(f"{url}: md5 {md5(koerper)}, Repo {md5(daten)}")
        art = next((v for k, v in koepfe.items() if k.lower() == "content-type"), "").lower()
        if pfad.endswith(".md") and not ("text/markdown" in art and "utf-8" in art):
            abweichungen.append(f"{url}: Content-Type {art}, erwartet text/markdown mit utf-8")
        if pfad.endswith((".xml")) and "xml" not in art:
            abweichungen.append(f"{url}: Content-Type {art}, erwartet XML")
    for kurz, b in sorted(bau.kurzadressen.items()):
        probe = f"{basis}{kurz}?utm_source=stand"
        ziel_pfad = f"/blog/{b.slug}/"
        geprueft += 1
        try:
            status, koepfe, _ = holen(probe)
        except OSError as fehler:
            abweichungen.append(f"{probe}: nicht erreichbar ({fehler})")
            continue
        ort = next((v for k, v in koepfe.items() if k.lower() == "location"), "")
        if status != 301 or urllib.parse.urlsplit(ort).path != ziel_pfad or "utm_source=stand" not in ort:
            abweichungen.append(f"{probe}: Status {status} nach {ort!r}, erwartet 301 auf {ziel_pfad}?utm_source=stand")
    for b in bau.beitraege if mit_quellen else []:
        for q in b.kopf.get("quellen", []):
            for url in filter(None, (q.get("url"), q.get("zusatz_url"))):
                try:
                    status, _, _ = holen(url)
                except OSError as fehler:
                    hinweise.append(f"Quelle nicht erreichbar: {url} ({fehler})")
                    continue
                if status >= 400:
                    hinweise.append(f"Quelle antwortet {status}: {url}")
    return {"geprueft": geprueft, "abweichungen": abweichungen, "hinweise": hinweise}


def befehl_vorschau(args: argparse.Namespace) -> int:
    """Baut einen Entwurf außerhalb des Repos für Fabrices Blick; schreibt nie ins Repo."""
    quelle = Path(args.datei)
    if not quelle.is_file():
        print(f"{quelle}: Datei fehlt")
        return 2
    ziel = Path(args.ziel).resolve() if args.ziel else Path(tempfile.gettempdir()) / "blog-vorschau"
    if ziel == WURZEL or WURZEL in ziel.parents:
        print(f"{ziel}: die Vorschau gehört nicht ins Repo, das Repo ist öffentlich")
        return 2
    funde = Funde()
    haus = haus_laden()
    b = quelle_einzeln(quelle, haus, funde)
    if funde or b is None:
        fehler_ausgeben(funde)
        return 1
    if b.kopf.get("bild"):
        groesse_pruefen(WURZEL / b.kopf["bild"], haus, funde, quelle, b.kopf_zeile("bild"))
    seite = seite_beitrag(b, [b], haus, funde)
    uebersicht = seite_uebersicht([b], haus, funde)
    if funde:
        fehler_ausgeben(funde)
        return 1
    ausgaben = {f"blog/{b.slug}/index.html": seite.encode("utf-8"), "blog/index.html": uebersicht.encode("utf-8"),
                f"blog/{b.slug}/index.html.md": markdown_fassung(b, haus).encode("utf-8")}
    for a in b.kopf.get("anhaenge", []):
        ausgaben[f"blog/{b.slug}/{a['datei']}"] = (quelle.parent / b.slug / a["datei"]).read_bytes()
    for bild in bilder_von(b.knoten):
        q = quelle.parent / b.slug / bild
        if q.is_file():
            ausgaben[f"blog/{b.slug}/{bild}"] = q.read_bytes()
    for pfad, daten in ausgaben.items():
        atomar_schreiben(ziel / pfad, daten)
    # Stilbogen und Schriften, damit die Seite wie live aussieht
    for quellpfad in ("css/blog.css", "assets/img/favicon-32.png", "assets/img/favicon-48.png", "assets/img/favicon-180.png"):
        von = WURZEL / quellpfad
        if von.is_file():
            atomar_schreiben(ziel / quellpfad, von.read_bytes())
    schriften = WURZEL / "assets" / "fonts"
    if schriften.is_dir():
        for von in schriften.iterdir():
            if von.is_file():
                atomar_schreiben(ziel / "assets" / "fonts" / von.name, von.read_bytes())
    print(f"vorschau: {ziel / 'blog' / b.slug / 'index.html'}")
    return 0


def toml_text(wert: str) -> str:
    """TOML-Grundstring: JSON maskiert Backslash, Anführungszeichen und Steuerzeichen gleich."""
    return json.dumps(wert, ensure_ascii=False)


def befehl_freigeben(args: argparse.Namespace) -> int:
    """Setzt status und freigabe zu Fabrices Satz. Nur dieser Befehl schreibt in den Kopf einer Quelle.

    Der Satz selbst wird nie geschrieben, nur sein SHA-256 (UTF-8, ohne Rand-Leerzeichen): das Repo ist öffentlich.
    Dazu der SHA-256 der Fassung: Ändert sich Text oder Anhang danach, sperrt P8 bis zum nächsten Wort.
    """
    wortlaut = (args.wortlaut or "").strip()
    if not wortlaut:
        print("freigeben: ohne Fabrices Wortlaut keine Freigabe")
        return 2
    if not re.match(r"^([01]\d|2[0-3]):[0-5]\d\Z", args.zeit or ""):
        print("freigeben: --zeit braucht HH:MM")
        return 2
    if not SLUG_MUSTER.match(args.slug):
        print("freigeben: Slug ungültig")
        return 2
    pfad = Path(args.datei) if args.datei else QUELLEN / f"{args.slug}.md"
    if not pfad.is_file():
        print(f"{pfad}: Datei fehlt")
        return 2
    stunde, minute = map(int, args.zeit.split(":"))
    # Die Freigabe fällt in deutscher Zeit; eine Maschine mit TZ=UTC läge sonst eine Stunde und kurz nach Mitternacht
    # einen Tag daneben. Unter Windows fehlen die Zeitzonendaten, dort gilt die Ortszeit der Maschine.
    try:
        from zoneinfo import ZoneInfo
        zone = ZoneInfo("Europe/Berlin")
    except Exception:
        zone = None
    if args.datum:
        tag = dt.date.fromisoformat(args.datum)
    else:
        tag = dt.datetime.now(zone).date() if zone else dt.date.today()
    if zone:
        am = dt.datetime(tag.year, tag.month, tag.day, stunde, minute, tzinfo=zone)
    else:
        am = dt.datetime(tag.year, tag.month, tag.day, stunde, minute).astimezone()

    funde = Funde()
    b = quelle_lesen(pfad, funde)
    if b is None:
        fehler_ausgeben(funde)
        return 1
    if ist_zeitpunkt(b.kopf.get("geaendert")) and am < b.kopf["geaendert"]:
        print(f"{pfad}: --zeit liegt vor geaendert ({b.kopf['geaendert'].isoformat()}): das Wort gilt dieser Fassung nicht")
        return 2
    behalten = [z for z in kopf_ohne_freigabe(b.kopf_text).split("\n") if not re.match(r"\s*status\s*=", z)]
    erste_tabelle = next((i for i, z in enumerate(behalten) if z.lstrip().startswith("[")), None)
    statuszeile = 'status = "veroeffentlicht"'
    if erste_tabelle is None:
        while behalten and not behalten[-1].strip():
            behalten.pop()
        behalten.append(statuszeile)
    else:
        davor = erste_tabelle - 1 if erste_tabelle > 0 and not behalten[erste_tabelle - 1].strip() else erste_tabelle
        behalten.insert(davor, statuszeile)
    while behalten and not behalten[-1].strip():
        behalten.pop()
    wortlaut_sha256 = hashlib.sha256(wortlaut.encode("utf-8")).hexdigest()
    inhalt_sha256 = inhalt_hash(pfad, "\n".join(behalten) + "\n", b.koerper, b.kopf)
    behalten.extend(["", "[freigabe]", f"von = {toml_text(FREIGABE_VON)}", f"am = {am.isoformat()}",
                     f'wortlaut_sha256 = "{wortlaut_sha256}"', f'inhalt_sha256 = "{inhalt_sha256}"', ""])
    neu_kopf = "\n".join(behalten)
    neu = f"+++\n{neu_kopf}+++\n{b.koerper}"
    probe = Funde()
    kopf = quelle_lesen_text(neu, pfad, probe)
    if probe or kopf is None or kopf.get("status") != "veroeffentlicht" \
            or kopf.get("freigabe", {}).get("wortlaut_sha256") != wortlaut_sha256 or set(kopf.get("freigabe", {})) != set(FREIGABE_FELDER):
        fehler_ausgeben(probe)
        print(f"{pfad}: Freigabe nicht geschrieben, das Ergebnis wäre ungültig")
        return 1
    atomar_schreiben(pfad, neu.encode("utf-8"))
    print(f"freigeben: {args.slug}, von {FREIGABE_VON}, am {am.isoformat()}, wortlaut_sha256 {wortlaut_sha256}, inhalt_sha256 {inhalt_sha256}")
    return 0


def quelle_lesen_text(text: str, pfad: Path, funde: Funde) -> dict | None:
    if not text.startswith("+++\n") or "\n+++\n" not in text[3:]:
        funde.neu(pfad, 1, "P2", "Kopfdaten nach der Änderung kaputt")
        return None
    ende = text.find("\n+++\n", 3)
    try:
        return tomllib.loads(text[4:ende + 1])
    except tomllib.TOMLDecodeError as fehler:
        funde.neu(pfad, 1, "P2", f"Kopfdaten nach der Änderung kaputt: {fehler}")
        return None


def befehl_indexnow(args: argparse.Namespace) -> int:
    """Meldet geänderte Blog-Adressen. Der Stand je Adresse liegt außerhalb des Repos, weil das Repo öffentlich ist."""
    funde = Funde()
    bau = bauen_im_speicher(funde)
    if funde:
        fehler_ausgeben(funde)
        return 1
    haus = haus_laden()
    stand_datei = Path(args.stand_datei) if args.stand_datei else Path.home() / ".local" / "state" / "sunds-blog" / "indexnow-stand.json"
    alt = json.loads(stand_datei.read_text(encoding="utf-8")) if stand_datei.is_file() else {}
    adressen = {f"{haus['basis']}/blog/": hashlib.sha256(bau.ausgaben["blog/index.html"]).hexdigest()}
    for b in bau.beitraege:
        adressen[kanonisch(haus, b.slug)] = hashlib.sha256(bau.ausgaben[f"blog/{b.slug}/index.html"]).hexdigest()
    geaendert = sorted(u for u, h in adressen.items() if alt.get(u) != h)
    if not geaendert:
        print("indexnow: keine geänderten Adressen")
        return 0
    if args.trocken:
        print(f"indexnow --trocken: {len(geaendert)} Adressen, nichts gesendet")
        for u in geaendert:
            print(f"  {u}")
        return 0
    host = urllib.parse.urlsplit(haus["basis"]).hostname
    schluessel = haus["indexnow"]["schluessel"]
    nutzlast = {"host": host, "key": schluessel, "keyLocation": f"{haus['basis']}/{schluessel}.txt", "urlList": geaendert}
    anfrage = urllib.request.Request(args.endpunkt or haus["indexnow"]["endpunkt"], data=json.dumps(nutzlast).encode("utf-8"),
                                     headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": BENUTZERKENNUNG}, method="POST")
    try:
        with urllib.request.urlopen(anfrage, timeout=haus["indexnow"]["zeitgrenze_s"]) as antwort:
            status = antwort.status
    except urllib.error.HTTPError as fehler:
        status = fehler.code
    except (OSError, http.client.HTTPException) as fehler:
        print(f"indexnow: nicht erreichbar: {fehler}")
        return 1
    if status not in (200, 202):
        print(f"indexnow: Antwort {status}, Stand bleibt unverändert")
        return 1
    stand_datei.parent.mkdir(parents=True, exist_ok=True)
    atomar_schreiben(stand_datei, (json.dumps({**alt, **adressen}, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print(f"indexnow: {len(geaendert)} Adressen gemeldet, Antwort {status}")
    return 0


def aufbauen() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="blog.py", description="Blog-Generator für sundsconnect.de")
    u = p.add_subparsers(dest="befehl", required=True)
    b = u.add_parser("bauen", help="schreibt alle Ausgaben")
    b.add_argument("--uebernehmen", action="append", metavar="KURZADRESSE", help="eine bisher von Hand gepflegte Seite an einer Kurzadresse ablösen")
    b.set_defaults(lauf=befehl_bauen)
    b = u.add_parser("pruefen", help="baut im Speicher, alle Prüfungen, vergleicht byte-genau, schreibt nichts")
    b.add_argument("--nur-quelle", metavar="DATEI", help="nur eine Entwurfsdatei prüfen, ohne Repo")
    b.add_argument("--vorher", metavar="SITEMAP", help="Sitemap der letzten Veröffentlichung für den Slug-Vergleich")
    b.set_defaults(lauf=befehl_pruefen)
    b = u.add_parser("stand", help="misst den Zustand; Exit 0 grün, 1 Abweichung")
    b.add_argument("--live", action="store_true")
    b.add_argument("--json", action="store_true")
    b.add_argument("--basis", help=argparse.SUPPRESS)
    b.add_argument("--heute", help=argparse.SUPPRESS)
    b.add_argument("--ohne-quellen", action="store_true", help="Quellen-Adressen nicht abrufen")
    b.set_defaults(lauf=befehl_stand)
    b = u.add_parser("vorschau", help="baut einen Entwurf außerhalb des Repos")
    b.add_argument("datei")
    b.add_argument("--ziel")
    b.set_defaults(lauf=befehl_vorschau)
    b = u.add_parser("freigeben", help="setzt status und freigabe mit Fabrices Wortlaut")
    b.add_argument("slug")
    b.add_argument("--wortlaut")
    b.add_argument("--zeit")
    b.add_argument("--datum", help="JJJJ-MM-TT, sonst heute")
    b.add_argument("--datei", help="Quelle außerhalb des Repos")
    b.set_defaults(lauf=befehl_freigeben)
    b = u.add_parser("indexnow", help="meldet geänderte Adressen an IndexNow")
    b.add_argument("--trocken", action="store_true")
    b.add_argument("--stand-datei")
    b.add_argument("--endpunkt", help=argparse.SUPPRESS)
    b.set_defaults(lauf=befehl_indexnow)
    return p


def main(argv: list[str] | None = None) -> int:
    args = aufbauen().parse_args(argv)
    try:
        return args.lauf(args)
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as fehler:
        print(f"blog.py {args.befehl}: {type(fehler).__name__}: {fehler}")
        return 1


if __name__ == "__main__":
    # Windows-Konsolen: Umlaute und Pfade dürfen die Ausgabe nicht abbrechen
    for strom in (sys.stdout, sys.stderr):
        if hasattr(strom, "reconfigure"):
            strom.reconfigure(encoding="utf-8", errors="backslashreplace")
    sys.exit(main())
