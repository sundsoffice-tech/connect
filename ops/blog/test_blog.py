#!/usr/bin/env python3
"""Tests für ops/blog/blog.py: python ops/blog/test_blog.py (nur Standardbibliothek).

Jede Abbruchprüfung hat eine Rotprobe: eine eingesäte Verletzung in einer Kopie des Baums muss Exit 1 mit
Datei:Zeile und der Prüfnummer geben, derselbe Baum ohne Verletzung Exit 0. Die Kopie schützt das Repo,
blog.py rechnet immer relativ zu seinem eigenen Ort.
BLOG_ROTPROBEN=1 druckt am Ende die Rotproben als Tabelle.
"""
from __future__ import annotations

import difflib
import hashlib
import http.server
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.parse
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SLUG = "sicherheitsluecken-2026"
QUELLE = f"inhalt/blog/{SLUG}.md"
# Absolute Pfade eines Rechners: Laufwerk mit Benutzerordner, Linux-Systemorte, Sitzungsordner
INTERNE_PFADE = r"[A-Za-z]:[\\/]Users[\\/]|/home/|/opt/|/etc/|/root/|\.claude[\\/]"
GEPRUEFT = REPO / "ops" / "blog" / "testdaten" / "sicherheit-2026-6a8c20d.html"
GEPRUEFT_COMMIT = "6a8c20d"
FUND = re.compile(r"^\S.*:\d+: \[P\d+\] ", re.M)
ROTPROBEN: list[tuple[str, int, str]] = []

# Was der Blog-Bau gegenüber der geprüften Seite zusätzlich zeigen darf, und sonst nichts: Brotkrumen,
# Lesezeit und der Blog-Link der Fußzeile. Die neue Beschreibung steht nur im Kopf und ist nicht sichtbar.
ERLAUBTE_ZUSAETZE = [
    re.compile(r"\d+ Min\. Lesezeit"),
    re.compile(r"Startseite Blog"),
    re.compile(r"Blog"),
]


# Freigegebene Textänderungen seit der geprüften Seite: Auflagen A4 und B5 bis B12 der Rolle IT-Recht, von Fabrice am
# 02.11.2026 übernommen, dazu Fassung 1.2. Jede Ersetzung muss genau einmal greifen; alles andere bleibt ein Fund.
FREIGEGEBENE_AENDERUNGEN = [
    ("Stand 1. November 2026, Fassung 1.1", "Stand 2. November 2026, Fassung 1.2"),
    ("Fassung 1.1, Stand 1. November 2026", "Fassung 1.2, Stand 2. November 2026"),
    ("%mehr Erpressungsangriffe in Deutschland in einem Jahr,",
     "%von Microsoft erfasste Erpressungsfälle in Deutschland, von 59 auf 222 in einem Jahr,"),
    ("Kriminelle nutzen dieselbe KI-Technik und bauen aus einem veröffentlichten Update binnen Minuten bis Stunden einen funktionierenden Angriff.",
     "Kriminelle nutzen dieselbe Technik, und laut BSI lässt sich aus einem veröffentlichten Update binnen Minuten bis Stunden ableiten, wie ein Angriff aussehen kann."),
    ("Cybersicherheit und schreibt wörtlich,", "Cybersicherheit und schreibt in seiner Sicherheitsinformation vom 22. Juni 2026 wörtlich,"),
    ("Deutschland ist laut Microsoft das einzige EU-Land unter den zehn weltweit am häufigsten angegriffenen Ländern.",
     "Deutschland ist das einzige EU-Land unter den zehn Ländern, die in Microsofts Daten am häufigsten angegriffen werden, laut Berichterstattung zum Microsoft-Bericht."),
    ("Stecker ziehen, nichts bezahlen,", "Vom Netz trennen (Kabel ziehen, WLAN aus), nichts bezahlen,"),
    ("Bund, Länder und Kommunen fördern den Check, in vielen Bundesländern mit der Hälfte der Kosten oder mehr.",
     "Der Ergebnisbericht nennt passende Förderprogramme von Bund, Ländern und Kommunen; Höhe und Bedingungen unterscheiden sich."),
    ("deckt aber Betriebsunterbrechung und Wiederherstellung. Versicherer fragen die Punkte von oben beim Abschluss ab.",
     "deckt aber je nach Vertrag Betriebsunterbrechung und Wiederherstellung. Versicherer fragen die Punkte von oben häufig beim Abschluss ab."),
    ("von ein bis zwei Stunden. Anfrage per Mail",
     "von ein bis zwei Stunden. Das ist eine eigene Durchsicht von uns, kein CyberRisikoCheck des BSI. Anfrage per Mail"),
    ("fasst öffentliche Quellen zusammen und ersetzt keine Prüfung Ihrer Systeme. Lizenz: CC BY-ND 4.0.",
     "fasst öffentliche Quellen zusammen, ist allgemein gehalten und ersetzt weder eine Prüfung Ihrer Systeme noch eine Beratung im "
     "Einzelfall. Vor Änderungen an Servern, Online-Shop und Geschäftsanwendungen bitte zuerst sichern. Lizenz für den Text dieses "
     "Beitrags: CC BY-ND 4.0; ausgenommen sind Logo, Marken und wörtliche Zitate aus den genannten Quellen."),
    # Fassung 1.3: Handynummer statt Büronummer, am Bildschirm "Beitrag" und im Druck "Blatt" (beide Spannen stehen im
    # Quelltext, CSS blendet je Medium eine aus), dritte Kachel kurz, Fassungsangabe nur noch im Kopf.
    ("Stand 2. November 2026, Fassung 1.2", "Stand 2. November 2026, Fassung 1.3"),
    ("Online-Shop betreibt. Dieses Blatt sagt", "Online-Shop betreibt. Dieser Beitrag Dieses Blatt sagt"),
    ("+276 %von Microsoft erfasste Erpressungsfälle in Deutschland, von 59 auf 222 in einem Jahr, laut Berichterstattung zum "
     "Microsoft-Bericht, Oktober 2026",
     "59 → 222Erpressungsfälle in Deutschland, Vorjahr zu diesem Jahr, von Microsoft erfasst, laut Presseberichten"),
    ("ausnutzen. Diese Zeit ist weg.", "ausnutzen. Erstens ist diese Zeit weg."),
    ("Kontakt siehe unten. Dieses Blatt ist", "Kontakt siehe unten. Dieser Beitrag Dieses Blatt ist"),
    ("02166 6459958", "+49 151 40322125"),
    ("Fassung 1.2, Stand 2. November 2026, nächste Prüfung 1. Februar 2027.", ""),
]


def freigegeben_geaendert(worte: list[str]) -> list[str]:
    """Die geprüfte Seite mit den freigegebenen Änderungen; eine Ersetzung, die nicht genau einmal greift, ist ein Fehler."""
    text = " ".join(worte)
    for alt, neu in FREIGEGEBENE_AENDERUNGEN:
        if text.count(alt) != 1:
            raise AssertionError(f"freigegebene Änderung greift {text.count(alt)}x statt 1x: {alt[:60]}")
        text = text.replace(alt, neu)
    return text.split()  # eine Ersetzung durch "" hinterließe sonst ein leeres Wort


def erlaubt(zusatz: str) -> bool:
    """Ein Einschub ist erlaubt, wenn er ganz aus erlaubten Stücken besteht, jedes höchstens einmal."""
    rest = zusatz
    for muster in ERLAUBTE_ZUSAETZE:
        rest = muster.sub("", rest, count=1).strip()
    return rest == ""


def tearDownModule() -> None:
    if os.environ.get("BLOG_ROTPROBEN"):
        print("\nRotprobe | Exit | erste Fundzeile")
        for name, code, zeile in ROTPROBEN:
            print(f"{name} | {code} | {zeile[:150]}")


class SichtbarerText(HTMLParser):
    BLOCK = {"p", "div", "li", "ol", "ul", "h1", "h2", "h3", "br", "main", "footer", "nav", "section", "figure", "figcaption", "blockquote", "header", "article"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.teile: list[str] = []
        self.tiefe = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("head", "style", "script", "svg"):
            self.tiefe += 1
        if tag in self.BLOCK:
            self.teile.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("head", "style", "script", "svg"):
            self.tiefe -= 1
        if tag in self.BLOCK:
            self.teile.append(" ")

    def handle_data(self, data: str) -> None:
        if not self.tiefe:
            self.teile.append(data)


def sichtbar(text: str) -> list[str]:
    p = SichtbarerText()
    p.feed(text)
    return " ".join("".join(p.teile).split()).split(" ")


def abweichungen(alt: list[str], neu: list[str]) -> list[str]:
    """Jede Stelle, an der der neue Text mehr oder anderes zeigt als die geprüfte Seite und nicht erlaubt ist."""
    funde = []
    for op, a1, a2, n1, n2 in difflib.SequenceMatcher(None, alt, neu, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        zusatz = " ".join(neu[n1:n2])
        if op == "insert" and erlaubt(zusatz):
            continue
        funde.append(f"{op}: alt={' '.join(alt[a1:a2])!r} neu={zusatz!r}")
    return funde


class Baum(unittest.TestCase):
    """Eine frische Kopie des Blog-Teils des Repos je Test."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.w = Path(self._tmp.name) / "site"
        self.w.mkdir()
        for ordner in ("ops/blog", "inhalt", "css", "assets/fonts", "js", "blog", "sicherheit-2026", "impressum", "datenschutz", "services", "contact", "projects", "promo"):
            if (REPO / ordner).is_dir():
                shutil.copytree(REPO / ordner, self.w / ordner, ignore=shutil.ignore_patterns("__pycache__"))
        (self.w / "assets/img").mkdir(parents=True, exist_ok=True)
        for datei in (REPO / "assets/img").glob("*"):
            if datei.name.startswith(("favicon", "og-", "logo")):
                shutil.copy2(datei, self.w / "assets/img" / datei.name)
        for datei in REPO.glob("*"):
            if datei.is_file() and datei.suffix in (".html", ".txt", ".xml"):
                shutil.copy2(datei, self.w / datei.name)
        shutil.copy2(REPO / "ops/veroeffentlichen.liste", self.w / "ops/veroeffentlichen.liste")

    def lauf(self, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
        umgebung = dict(os.environ, PYTHONIOENCODING="utf-8", **(env or {}))
        return subprocess.run([sys.executable, str(self.w / "ops/blog/blog.py"), *args], cwd=self.w, capture_output=True,
                              encoding="utf-8", env=umgebung, timeout=60, check=False)

    def neu_freigeben(self, slug: str = SLUG) -> None:
        """Wer in einem Test die Quelle ändert und Grün erwartet, braucht ein neues Wort: P8 bindet es an die Fassung."""
        lauf = self.lauf("freigeben", slug, "--wortlaut", "Testwort", "--zeit", "12:00", "--datum", "2026-11-03")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)

    def lies(self, pfad: str) -> str:
        return (self.w / pfad).read_bytes().decode("utf-8")

    def schreib(self, pfad: str, text: str) -> None:
        ziel = self.w / pfad
        ziel.parent.mkdir(parents=True, exist_ok=True)
        ziel.write_bytes(text.encode("utf-8"))

    def zeile(self, schluessel: str) -> str:
        """Die erste Kopfzeile `schluessel = ...` der Beitragsquelle, damit Proben nicht an einer alten Fassung oder Freigabe hängen."""
        m = re.search(rf"^{re.escape(schluessel)} = .*$", self.lies(QUELLE), re.M)
        self.assertIsNotNone(m, f"Kopfzeile {schluessel} fehlt")
        return m.group(0)

    def ersetze(self, pfad: str, alt: str, neu: str) -> None:
        text = self.lies(pfad)
        self.assertIn(alt, text, f"Anker fehlt in {pfad}: {alt[:60]}")
        self.schreib(pfad, text.replace(alt, neu, 1))

    def rot(self, name: str, pruefung: str, befehl: tuple = ("pruefen",)) -> str:
        """Der Baum enthält die Verletzung: Exit 1, die Prüfnummer und Datei:Zeile müssen kommen."""
        lauf = self.lauf(*befehl)
        fundzeilen = [z for z in lauf.stdout.splitlines() if f"[{pruefung}]" in z]
        ROTPROBEN.append((f"{pruefung} {name}", lauf.returncode, fundzeilen[0] if fundzeilen else lauf.stdout[:150]))
        self.assertEqual(lauf.returncode, 1, f"{name}: {lauf.stdout}{lauf.stderr}")
        self.assertTrue(fundzeilen, f"{name}: keine Zeile [{pruefung}]: {lauf.stdout}")
        self.assertRegex(fundzeilen[0], FUND)
        self.assertNotIn("Traceback", lauf.stdout + lauf.stderr)
        return lauf.stdout


class KopierListeImBau(unittest.TestCase):
    """ops/sunds-hub/bauen.sh --nur-kopieren in einem Mini-Baum, weil eine Blogkopie nicht alle gelisteten Ordner hat."""

    def setUp(self) -> None:
        self.bash = shutil.which("bash")
        if not self.bash:
            self.skipTest("bash fehlt hier")
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.w = Path(tmp.name)
        (self.w / "q/ops").mkdir(parents=True)
        (self.w / "q/x").mkdir()
        (self.w / "q/index.html").write_text("x", encoding="utf-8")
        (self.w / "q/x/a.txt").write_text("a", encoding="utf-8")
        (self.w / "q/ops/veroeffentlichen.liste").write_text("index.html\nx\n", encoding="utf-8")

    def lauf(self) -> subprocess.CompletedProcess:
        skript = (REPO / "ops/sunds-hub/bauen.sh").as_posix()
        return subprocess.run([self.bash, skript, "--nur-kopieren", "q", "ziel"], cwd=self.w, capture_output=True, text=True, encoding="utf-8", timeout=60, check=False)

    def test_ohne_entwurf_geht_durch(self) -> None:
        lauf = self.lauf()
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        self.assertTrue((self.w / "ziel/x/a.txt").is_file())

    def test_entwurf_exit_3_vor_dem_kopieren(self) -> None:
        (self.w / "q/x/ENTWURF.txt").write_text("Entwurf", encoding="utf-8")
        lauf = self.lauf()
        self.assertEqual(lauf.returncode, 3, lauf.stderr)
        self.assertIn("ist ein Entwurf", lauf.stderr)
        self.assertFalse((self.w / "ziel/x").exists())

    def test_symlink_exit_3(self) -> None:
        try:
            os.symlink(self.w / "q/index.html", self.w / "q/x/link.html")
        except OSError:
            self.skipTest("Symlinks hier nicht erlaubt")
        lauf = self.lauf()
        self.assertEqual(lauf.returncode, 3, lauf.stderr)
        self.assertIn("symbolischen Link", lauf.stderr)


class Verzeichnis(unittest.TestCase):
    """Wissenschaftler: nie ein leeres oder einzeiliges Verzeichnis, auch bei 1.500 Wörtern."""

    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.spec_from_file_location("blog_einheit", REPO / "ops/blog/blog.py")
        cls.blog = importlib.util.module_from_spec(spec)
        sys.modules["blog_einheit"] = cls.blog
        spec.loader.exec_module(cls.blog)
        cls.haus = cls.blog.haus_laden()

    def faelle(self, anker: int, woerter: int) -> str:
        b = self.blog.Beitrag(pfad=Path("x.md"), anker=[(f"a{i}", f"A {i}") for i in range(anker)], woerter=woerter)
        return self.blog.verzeichnis_html(b, self.haus)

    def test_schwellen(self) -> None:
        self.assertEqual(self.faelle(0, 2000), "")
        self.assertEqual(self.faelle(2, 2000), "")
        self.assertIn("inhaltsverzeichnis", self.faelle(3, 1500))
        self.assertEqual(self.faelle(3, 1499), "")
        self.assertIn("inhaltsverzeichnis", self.faelle(5, 10))

    def test_csp_streng_lehnt_verwandte_ab(self) -> None:
        streng = self.haus["csp"]
        self.assertTrue(self.blog.csp_streng(streng))
        for zusatz in ("script-src-elem https:", "script-src-attr 'unsafe-inline'", "worker-src *", "frame-src https:"):
            self.assertFalse(self.blog.csp_streng(f"{streng}; {zusatz}"), zusatz)

    def test_robots_regeln(self) -> None:
        for regel in ("/", "/*/", "/blog", "/blog/", "/blog/x/", "/*.xml", "/*.md$", "/BLOG/"):
            self.assertTrue(self.blog.robots_sperrt_blog(regel), regel)
        for regel in ("/.git/", "/.github/", "/css/", "/*.pdf$"):
            self.assertFalse(self.blog.robots_sperrt_blog(regel), regel)


class Gruen(Baum):
    def test_kontrolle_ohne_verletzung_exit_0(self) -> None:
        lauf = self.lauf("pruefen")
        self.assertEqual(lauf.returncode, 0, lauf.stdout + lauf.stderr)
        self.assertIn("grün", lauf.stdout)

    def test_bauen_zweimal_bytegleich(self) -> None:
        lauf = self.lauf("bauen")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        self.assertIn(" 0 geschrieben", lauf.stdout)

    def test_stempel_aendert_nichts_am_blog(self) -> None:
        """ops/stempel.py läuft bei jedem Deploy über alle HTML-Dateien; pruefen muss danach grün bleiben."""
        shutil.copy2(REPO / "ops/stempel.py", self.w / "ops/stempel.py")
        vorher = self.lies("index.html")
        blog = self.lies(f"blog/{SLUG}/index.html")
        lauf = subprocess.run([sys.executable, str(self.w / "ops/stempel.py"), "probe123"], cwd=self.w, capture_output=True, encoding="utf-8", timeout=60, check=False)
        self.assertEqual(lauf.returncode, 0, lauf.stderr)
        self.assertNotEqual(self.lies("index.html"), vorher, "Gegenprobe: der Stempel hat die Startseite wirklich geändert")
        self.assertIn("?v=probe123", self.lies("index.html"))
        self.assertEqual(self.lies(f"blog/{SLUG}/index.html"), blog)
        lauf = self.lauf("pruefen")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)

    def test_telefon_gewaehlt_handseiten_stimmen(self) -> None:
        lauf = self.lauf("pruefen")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        self.assertNotIn("Abweichungen", lauf.stdout)
        self.assertIn('telefon_gewaehlt = true', self.lies("ops/blog/haus.toml"))

    def test_impressum_traegt_die_mail(self) -> None:
        self.assertIn("mailto:info@sundsconnect.de", self.lies("impressum/index.html"))
        self.assertIn("impressum/index.html", re.search(r"^mail_pflicht = .*$", self.lies("ops/blog/haus.toml"), re.M).group(0))

    def test_stand_gruen(self) -> None:
        lauf = self.lauf("stand", "--json", "--heute", "2026-11-02")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        daten = json.loads(lauf.stdout)
        self.assertEqual(daten["veroeffentlicht"], 1)
        self.assertEqual(daten["ausgaben"]["veraltet"], [])
        self.assertEqual(daten["verzeichnisse"]["atom"]["gefunden"], 1)

    def test_stand_prueftermin_faellig(self) -> None:
        daten = json.loads(self.lauf("stand", "--json", "--heute", "2027-01-15").stdout)
        self.assertEqual(daten["pruefdaten_faellig"], [SLUG])

    def test_halbgeviert_zwischen_ziffern_erlaubt(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", f"2019{chr(0x2013)}2026 Seitdem reißt")
        self.neu_freigeben()
        self.assertEqual(self.lauf("bauen").returncode, 0)

    def test_ausgaben_tragen_die_marke(self) -> None:
        for pfad in ("blog/index.html", f"blog/{SLUG}/index.html", f"blog/{SLUG}/index.html.md", "blog/feed.xml", "blog/rss.xml", "sitemap.xml", "llms.txt", "sicherheit-2026/index.html"):
            self.assertIn("erzeugt von ops/blog/blog.py", self.lies(pfad)[:300], pfad)

    def test_keine_internen_pfade_in_quellen_und_ausgaben(self) -> None:
        for pfad in [QUELLE, "ops/blog/haus.toml", "blog/index.html", f"blog/{SLUG}/index.html", f"blog/{SLUG}/index.html.md", "blog/feed.xml", "llms.txt"]:
            self.assertNotRegex(self.lies(pfad), INTERNE_PFADE, pfad)

    def test_keine_internen_angaben_in_allem_was_ausgeliefert_wird(self) -> None:
        """Über die echte Kopierliste, also auch Altbestand wie js/main.js und css/style.css: Pfad, Servername, Vorname."""
        namen, ordner, dateien = [], [], []
        for zeile in (REPO / "ops/veroeffentlichen.liste").read_text(encoding="utf-8").splitlines():
            if zeile.startswith("ordner-muster "):
                ordner.append(re.compile(zeile.split(" ", 1)[1]))
            elif zeile.startswith("datei-muster "):
                dateien.append(re.compile(zeile.split(" ", 1)[1]))
            elif zeile and not zeile.startswith("#"):
                namen.append(zeile)
        namen += [p.name for p in REPO.iterdir() if (p.is_dir() and any(m.search(p.name) for m in ordner)) or (p.is_file() and any(m.search(p.name) for m in dateien))]
        gesehen = 0
        for name in namen:
            pfad = REPO / name
            for datei in ([pfad] if pfad.is_file() else sorted(pfad.rglob("*"))):
                if datei.is_file() and datei.suffix in (".html", ".js", ".css", ".txt", ".xml", ".md", ".json", ".svg"):
                    gesehen += 1
                    text = datei.read_bytes().decode("utf-8", "replace")
                    rel = datei.relative_to(REPO).as_posix()
                    if rel == "datenschutz/index.html":  # nennt den Hoster, das verlangt die Erklärung
                        text = re.sub(r"(?i)contabo", "", text)
                    # Der volle Name steht als Pflichtangabe in Impressum, Datenschutz und Kontakt (Fabrice 02.11.2026); der Vorname allein bleibt verboten
                    self.assertNotRegex(text, INTERNE_PFADE + r"|Fabrice(?! Noel Schippers)|_HUB|sunds-hub|(?i:contabo)", rel)
        self.assertGreater(gesehen, 20, "die Liste muss wirklich gelesen sein")

    def test_feeds_und_sitemap(self) -> None:
        ns = {"a": "http://www.w3.org/2005/Atom"}
        atom = ET.fromstring(self.lies("blog/feed.xml"))
        self.assertEqual(atom.find("a:entry/a:id", ns).text, f"https://sundsconnect.de/blog/{SLUG}/")
        inhalt = atom.find("a:entry/a:content", ns).text
        self.assertNotIn('href="#', inhalt)
        self.assertIn(f"https://sundsconnect.de/blog/{SLUG}/#schritte", inhalt)
        self.assertEqual(len(atom.findall("a:entry/a:category", ns)), 2)
        rss = ET.fromstring(self.lies("blog/rss.xml"))
        self.assertEqual(rss.find("channel/item/guid").text, f"https://sundsconnect.de/blog/{SLUG}/")
        karte = self.lies("sitemap.xml")
        self.assertIn(f"/blog/{SLUG}/</loc>", karte)
        self.assertNotIn("/sicherheit-2026/", karte, "Kurzadressen gehören nicht in die Sitemap")

    def test_jsonld_und_kopf(self) -> None:
        seite = self.lies(f"blog/{SLUG}/index.html")
        block = re.search(r'<script type="application/ld\+json">(.*?)</script>', seite, re.S).group(1)
        graph = {g["@type"]: g for g in json.loads(block)["@graph"]}
        posting = graph["BlogPosting"]
        self.assertEqual(graph["Organization"]["@id"], "https://sundsconnect.de/#organisation")
        self.assertEqual(graph["Organization"]["telephone"], "+4915140322125")
        self.assertIn("tel:+4915140322125", seite, "die sichtbare Handynummer bleibt")
        self.assertEqual(posting["inLanguage"], "de-DE")
        self.assertEqual(len(posting["citation"]), 12)
        self.assertEqual(posting["timeRequired"], f"PT{max(1, -(-posting['wordCount'] // 200))}M")
        self.assertEqual(posting["image"]["width"], 1200)
        self.assertEqual(seite.count('<link rel="canonical"'), 1)
        self.assertEqual(seite.count('name="robots"'), 1)
        self.assertEqual(seite.count('name="description"'), 1)
        self.assertEqual(seite.count("<title>"), 1)

    def test_beschreibung_in_der_grenze(self) -> None:
        kopf = re.search(r'^beschreibung = "(.*)"$', self.lies(QUELLE), re.M).group(1)
        self.assertTrue(70 <= len(kopf) <= 140, len(kopf))
        self.assertEqual(len(kopf), 131)

    def test_markdown_fassung_absolut(self) -> None:
        md = self.lies(f"blog/{SLUG}/index.html.md")
        self.assertTrue(md.startswith("# Sicherheitslücken 2026"))
        self.assertIn(f"Adresse: https://sundsconnect.de/blog/{SLUG}/", md)
        self.assertNotIn(":::", md)
        self.assertNotIn("{#", md)
        self.assertIn("](https://www.anthropic.com/glasswing)", md)

    def test_jsonld_kann_den_block_nicht_beenden(self) -> None:
        self.ersetze(QUELLE, 'bild_alt = "Drei', 'bild_alt = "</script><img src=x> Drei')
        self.neu_freigeben()
        self.assertEqual(self.lauf("bauen").returncode, 0)
        seite = self.lies(f"blog/{SLUG}/index.html")
        self.assertNotIn("</script><img", seite)

    def test_verwandte_nach_schlagwort(self) -> None:
        zweit = self.lies(QUELLE).replace(SLUG, "zweiter-beitrag").replace("Sicherheitslücken 2026: Was passiert ist und was jetzt zählt", "Ein zweiter Beitrag mit eigenem Titel")
        zweit = zweit.replace("KI findet Sicherheitslücken schneller", "Andere Beschreibung: KI ist schneller").replace('kurzadressen = ["/sicherheit-2026/"]\n', "").replace("Sicherheitslücken 2026: Was jetzt zählt", "Ein zweiter Beitrag")
        zweit = re.sub(r"\[\[anhaenge\]\]\n.*?\n\n", "", zweit, count=1, flags=re.S)
        self.schreib("inhalt/blog/zweiter-beitrag.md", zweit)
        self.neu_freigeben("zweiter-beitrag")
        self.assertEqual(self.lauf("bauen").returncode, 0, self.lauf("bauen").stdout)
        self.assertIn('href="../zweiter-beitrag/"', self.lies(f"blog/{SLUG}/index.html"))
        self.assertEqual(self.lauf("pruefen").returncode, 0)


class Rotproben(Baum):
    def test_p1_jedes_zeichen_in_der_quelle(self) -> None:
        for cp in (0x2014, 0x2013, 0x00B7, 0x2022, 0x2011):
            with self.subTest(hex(cp)):
                alt = self.lies(QUELLE)
                self.ersetze(QUELLE, "Seitdem reißt", f"Seitdem {chr(cp)} reißt")
                aus = self.rot(f"U+{cp:04X} in der Quelle", "P1")
                self.assertIn(f"{QUELLE}:", aus)
                self.schreib(QUELLE, alt)

    def test_p1_in_der_ausgabe_nicht_in_der_quelle(self) -> None:
        self.ersetze("ops/blog/sitemap-seiten.xml", "<urlset", f"<!-- {chr(0x2014)} -->\n<urlset")
        self.assertIn("sitemap.xml:", self.rot("nur in der Ausgabe (Sitemap)", "P1"))

    def test_p1_als_entity_in_der_ausgabe(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "</main>", "&mdash;</main>")
        self.assertIn(f"blog/{SLUG}/index.html:", self.rot("&mdash; als Entity", "P1"))

    def test_p2_titel_zu_kurz(self) -> None:
        self.ersetze(QUELLE, 'titel = "Sicherheitslücken 2026: Was passiert ist und was jetzt zählt"', 'titel = "Zu kurz"')
        self.rot("titel zu kurz", "P2")

    def test_p2_beschreibung_255(self) -> None:
        text = re.sub(r'^beschreibung = ".*"$', 'beschreibung = "' + "x" * 255 + '"', self.lies(QUELLE), count=1, flags=re.M)
        self.schreib(QUELLE, text)
        self.assertIn(":4:", self.rot("beschreibung 255 Zeichen", "P2"))

    def test_p2_seitentitel_zu_lang(self) -> None:
        self.ersetze(QUELLE, 'seitentitel = "Sicherheitslücken 2026: Was jetzt zählt"', 'seitentitel = "' + "y" * 61 + '"')
        self.rot("seitentitel 61 Zeichen", "P2")

    def test_p2_slug_ungleich_datei(self) -> None:
        self.ersetze(QUELLE, f'slug = "{SLUG}"', 'slug = "anderer-slug"')
        self.rot("slug ungleich Dateiname", "P2")

    def test_p2_slug_kollidiert_mit_ordner(self) -> None:
        self.schreib("inhalt/blog/services.md", self.lies(QUELLE).replace(f'slug = "{SLUG}"', 'slug = "services"').replace('titel = "Sicherheitslücken 2026: Was passiert', 'titel = "Anderer Titel 2026: Was passiert'))
        self.rot("slug kollidiert mit Ordner", "P2")

    def test_p2_pflichtfeld_fehlt(self) -> None:
        self.ersetze(QUELLE, self.zeile("fassung") + "\n", "")
        self.rot("Pflichtfeld fassung fehlt", "P2")

    def test_p2_falscher_typ(self) -> None:
        self.ersetze(QUELLE, self.zeile("fassung"), self.zeile("fassung").replace('"', ""))
        self.rot("fassung als Zahl", "P2")

    def test_p2_datum_ohne_zeitzone(self) -> None:
        self.ersetze(QUELLE, "datum = 2026-11-01T23:58:28+01:00", "datum = 2026-11-01T23:58:28")
        self.rot("datum ohne Zeitzone", "P2")

    def test_p2_geaendert_vor_datum(self) -> None:
        self.ersetze(QUELLE, self.zeile("geaendert"), "geaendert = 2026-10-01T23:58:28+01:00")
        self.rot("geaendert vor datum", "P2")

    def test_p2_pruefen_bis_ueber_183_tage(self) -> None:
        self.ersetze(QUELLE, "pruefen_bis = 2027-02-01", "pruefen_bis = 2028-02-01")
        self.rot("pruefen_bis zu spät", "P2")

    def test_p2_schlagwort_unbekannt(self) -> None:
        self.ersetze(QUELLE, '"it-sicherheit"', '"it-security"')
        self.rot("Schlagwort nicht in der Liste", "P2")

    def test_p2_kurzadresse_ueberschreibt_feste_seite(self) -> None:
        self.ersetze(QUELLE, 'kurzadressen = ["/sicherheit-2026/"]', 'kurzadressen = ["/services/"]')
        self.rot("Kurzadresse auf feste Seite", "P2", ("bauen",))
        self.assertNotIn("erzeugt von", self.lies("services/index.html"), "die feste Seite blieb unberührt")

    def test_p2_toml_kaputt(self) -> None:
        self.ersetze(QUELLE, self.zeile("fassung"), self.zeile("fassung")[:-1])
        self.rot("TOML kaputt", "P2")

    def test_p2_zahlen_ohne_quellen(self) -> None:
        text = re.sub(r"\[\[quellen\]\].*?(?=\n\+\+\+|\[freigabe\])", "", self.lies(QUELLE), flags=re.S)
        self.schreib(QUELLE, text)
        self.rot("Zahlen ohne Quellen", "P2")

    def test_p3_bild_alt_leer(self) -> None:
        self.ersetze(QUELLE, 'bild_alt = "Drei', 'bild_alt = "')
        text = re.sub(r'^bild_alt = ".*"$', 'bild_alt = ""', self.lies(QUELLE), count=1, flags=re.M)
        self.schreib(QUELLE, text)
        self.rot("bild_alt leer", "P3")

    def test_p3_inline_bild_ohne_alt(self) -> None:
        self.ersetze(QUELLE, "## Was passiert ist\n", '## Was passiert ist\n\n![](foto.png "Unterschrift")\n')
        self.rot("Bild im Text ohne Alt", "P3")

    def test_p3_vorschaubild_falsche_masse(self) -> None:
        kopf = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + (100).to_bytes(4, "big") + (100).to_bytes(4, "big")
        (self.w / "assets/img/og-sicherheit-2026.png").write_bytes(kopf + b"\0" * 20)
        self.rot("Vorschaubild 100 mal 100", "P3")

    def test_p4_kaputter_interner_link(self) -> None:
        self.ersetze(QUELLE, "## Was passiert ist\n", "## Was passiert ist\n\nSiehe [hier](/gibt-es-nicht/).\n")
        self.assertIn(f"blog/{SLUG}/index.html:", self.rot("Link auf fehlende Seite", "P4"))

    def test_p4_kaputte_marke(self) -> None:
        self.ersetze(QUELLE, "(#schritte)", "(#gibt-es-nicht)")
        self.rot("Sprungmarke fehlt", "P4")

    def test_p5_stylesheet_fremd(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "</head>", '<link rel="stylesheet" href="https://example.com/a.css">\n</head>')
        self.rot("Stylesheet fremd", "P5")

    def test_p5_bild_fremd(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "</main>", '<img src="https://example.com/a.png" alt="x"></main>')
        self.rot("Bild fremd", "P5")

    def test_p5_sperrliste_in_gewoehnlichem_link(self) -> None:
        self.ersetze(QUELLE, "## Was passiert ist\n", "## Was passiert ist\n\nSiehe [hier](https://www.googletagmanager.com/x).\n")
        self.rot("Sperrliste im Link", "P5")

    def test_p5_url_fremd_im_css(self) -> None:
        text = self.lies("css/blog.css") + '\n.x{background:url("https://example.com/a.png")}\n'
        self.schreib("css/blog.css", text)
        self.assertIn("css/blog.css:", self.rot("url() fremd im CSS", "P5"))

    def test_p5_fremder_link_ohne_noopener(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "</main>", '<a href="https://example.com/">x</a></main>')
        self.rot("Fremder Link ohne noopener", "P5")

    def test_p6_ohne_csp(self) -> None:
        text = re.sub(r'<meta http-equiv="Content-Security-Policy"[^>]*>\n?', "", self.lies("ops/blog/vorlagen/weiterleitung.html"))
        self.schreib("ops/blog/vorlagen/weiterleitung.html", text)
        self.assertIn("sicherheit-2026/index.html:", self.rot("Weiterleitung ohne CSP", "P6"))

    def test_p6_csp_aufgeweicht(self) -> None:
        self.ersetze("ops/blog/haus.toml", "script-src 'none'", "script-src 'self'")
        self.rot("script-src aufgeweicht", "P6")

    def test_p6_style_block(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "</head>", "<style>a{color:red}</style>\n</head>")
        self.rot("style-Block", "P6")

    def test_p6_skript(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "</main>", "<script>alert(1)</script></main>")
        self.rot("Skript in der Vorlage", "P6")

    def test_p7_rohes_html(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", "<b>Seitdem</b> reißt")
        self.assertIn(f"{QUELLE}:", self.rot("rohes HTML", "P7"))

    def test_p7_skript_im_text(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", "<script>alert(1)</script> Seitdem reißt")
        self.rot("Skript im Text", "P7")

    def test_p7_h1_und_h4(self) -> None:
        for zeile in ("# Zu hoch", "#### Zu tief"):
            with self.subTest(zeile):
                alt = self.lies(QUELLE)
                self.ersetze(QUELLE, "## Was passiert ist\n", f"{zeile}\n\n## Was passiert ist\n")
                self.rot(f"Überschrift {zeile[:5]}", "P7")
                self.schreib(QUELLE, alt)

    def test_p7_unbekannter_block(self) -> None:
        self.ersetze(QUELLE, "::: klein\n", "::: gross\n")
        self.rot("unbekannter Block", "P7")

    def test_p7_block_nicht_geschlossen(self) -> None:
        self.ersetze(QUELLE, "::: kasten angebot\n", "::: kasten angebot\n::: zwei\n")
        self.rot("Block falsch verschachtelt", "P7")

    def test_p7_schema_javascript(self) -> None:
        self.ersetze(QUELLE, "(#schritte)", "(javascript:alert)")
        self.rot("Link-Schema javascript", "P7")

    def test_p7_fett_ohne_ende(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", "**Seitdem reißt")
        self.rot("** ohne Gegenstück", "P7")

    def test_p7_tabelle(self) -> None:
        self.ersetze(QUELLE, "## Was passiert ist\n", "## Was passiert ist\n\n| a | b |\n")
        self.rot("Tabelle", "P7")

    def test_web_druck_wortlaut(self) -> None:
        """{web:...|druck:...}: Seite trägt beide Spannen, Feed und Markdown-Fassung nur den Bildschirmwortlaut."""
        self.ersetze(QUELLE, "Seitdem reißt", "{web:Bildschirmwort|druck:Papierwort} Seitdem reißt")
        self.neu_freigeben()
        lauf = self.lauf("bauen")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        seite = self.lies(f"blog/{SLUG}/index.html")
        self.assertIn('<span class="nur-web">Bildschirmwort</span> <span class="nur-druck">Papierwort</span> Seitdem', seite)
        for ausgabe in (f"blog/{SLUG}/index.html.md", "blog/feed.xml", "blog/rss.xml"):
            with self.subTest(ausgabe):
                text = self.lies(ausgabe)
                self.assertIn("Bildschirmwort Seitdem", text)
                self.assertNotIn("Papierwort", text)
                self.assertNotIn("{web:", text)

    def test_pfeil_als_bild_nur_auf_der_seite(self) -> None:
        """Kennzahl mit →: die Seite zeichnet den Pfeil als SVG und trägt das Zeichen genau einmal unsichtbar;
        Feed, RSS und Markdown-Fassung behalten „59 → 222“ als Text ohne SVG."""
        self.neu_freigeben()
        lauf = self.lauf("bauen")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        self.assertIn("**59 → 222**", self.lies(QUELLE), "Gegenprobe: die Kachel trägt den Pfeil")
        seite = self.lies(f"blog/{SLUG}/index.html")
        self.assertIn('<b>59 <span class="pfeil"><svg', seite)
        self.assertEqual(seite.count('<span class="unsichtbar">→</span>'), 1)
        self.assertNotIn("<b>59 → 222</b>", seite)
        for ausgabe in (f"blog/{SLUG}/index.html.md", "blog/feed.xml", "blog/rss.xml"):
            with self.subTest(ausgabe):
                text = self.lies(ausgabe)
                self.assertIn("59 → 222", text)
                self.assertNotIn("M3 12h17", text)
                self.assertNotIn("pfeil", text)
                self.assertNotIn("unsichtbar", text)

    def test_vorschaubild_mit_versionsteil(self) -> None:
        """og:image und twitter:image tragen ?v= aus den Bytes des Bildes; neue Bytes geben eine neue Adresse."""
        self.neu_freigeben()
        bild = self.w / "assets/img/og-sicherheit-2026.png"

        def adressen() -> list[str]:
            lauf = self.lauf("bauen")
            self.assertEqual(lauf.returncode, 0, lauf.stdout)
            seite = self.lies(f"blog/{SLUG}/index.html")
            return re.findall(r'(?:property="og:image"|name="twitter:image") content="([^"]+)"', seite)

        alt = adressen()
        erwartet = "https://sundsconnect.de/assets/img/og-sicherheit-2026.png?v=" + hashlib.sha256(bild.read_bytes()).hexdigest()[:8]
        self.assertEqual(alt, [erwartet, erwartet])
        bild.write_bytes(bild.read_bytes() + b"\0")
        neu = adressen()
        self.assertEqual(len(neu), 2)
        self.assertNotEqual(neu, alt)
        uebersicht = self.lies("blog/index.html")
        self.assertRegex(uebersicht, r'property="og:image" content="https://sundsconnect\.de/[^"?]+\.png\?v=[0-9a-f]{8}"')

    def test_wortzahl_ohne_zeichen(self) -> None:
        """Ein freistehendes Zeichen wie der Pfeil ist kein Wort: wordCount bleibt gleich."""
        self.neu_freigeben()
        self.assertEqual(self.lauf("bauen").returncode, 0)
        vorher = re.search(r'"wordCount": ?(\d+)', self.lies(f"blog/{SLUG}/index.html")).group(1)
        self.ersetze(QUELLE, "Seitdem reißt", "→ → Seitdem reißt")
        self.neu_freigeben()
        lauf = self.lauf("bauen")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        nachher = re.search(r'"wordCount": ?(\d+)', self.lies(f"blog/{SLUG}/index.html")).group(1)
        self.assertEqual(vorher, nachher)

    def test_p7_web_druck_kaputt(self) -> None:
        for name, kaputt in (("ohne schließende Klammer", "{web:Bildschirmwort|druck:Papierwort Seitdem reißt"),
                             ("ohne |druck:", "{web:Bildschirmwort|Papierwort} Seitdem reißt"),
                             ("zweimal |druck:", "{web:a|druck:b|druck:c} Seitdem reißt"),
                             ("leerer Bildschirmteil", "{web:|druck:Papierwort} Seitdem reißt"),
                             ("leerer Druckteil", "{web:Bildschirmwort|druck: } Seitdem reißt")):
            with self.subTest(name):
                alt = self.lies(QUELLE)
                self.ersetze(QUELLE, "Seitdem reißt", kaputt)
                self.assertIn(f"{QUELLE}:", self.rot(name, "P7"))
                self.schreib(QUELLE, alt)

    def test_p8_entwurf_im_repo(self) -> None:
        self.ersetze(QUELLE, 'status = "veroeffentlicht"', 'status = "entwurf"')
        self.rot("status entwurf im Repo", "P8")

    def test_p8_ohne_freigabe(self) -> None:
        text = re.sub(r"\[freigabe\].*?(?=\+\+\+)", "", self.lies(QUELLE), flags=re.S)
        self.schreib(QUELLE, text)
        self.rot("veroeffentlicht ohne freigabe", "P8")

    def test_p8_freigabe_von_anderen(self) -> None:
        self.ersetze(QUELLE, 'von = "Fabrice"', 'von = "Claude"')
        self.rot("freigabe nicht von Fabrice", "P8")

    def test_p8_text_geaendert_altes_wort(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", "Rufen Sie uns an. Seitdem reißt")
        self.assertIn("alten Fassung", self.rot("Text geändert, altes Wort", "P8"))

    def test_p8_anhang_geaendert_altes_wort(self) -> None:
        pfad = self.w / f"inhalt/blog/{SLUG}/Infoblatt_Sicherheitsluecken_2026.pdf"
        pfad.write_bytes(pfad.read_bytes() + b"x")
        self.assertIn("alten Fassung", self.rot("PDF geändert, altes Wort", "P8"))

    def test_p8_lizenz_geaendert_altes_wort(self) -> None:
        # Lizenzblock aus haus.toml liegt im inhalt_sha256 (L1); Vorlagen und CSS liegen bewusst nicht darin
        self.ersetze("ops/blog/haus.toml", 'vorbehalt = "ausgenommen sind', 'vorbehalt = "ausgenommen ist nichts, auch nicht')
        self.assertIn("alten Fassung", self.rot("Lizenz geändert, altes Wort", "P8"))

    def test_p8_neues_wort_macht_wieder_gruen(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", "Seitdem  reißt")
        self.neu_freigeben()
        self.assertEqual(self.lauf("bauen").returncode, 0)
        self.assertEqual(self.lauf("pruefen").returncode, 0)

    def test_p8_wort_vor_der_aenderung(self) -> None:
        self.ersetze(QUELLE, self.zeile("am"), "am = 2026-11-01T10:00:00+01:00")
        self.assertIn("vor geaendert", self.rot("freigabe.am vor geaendert", "P8"))

    def test_freigeben_vor_geaendert_exit_2(self) -> None:
        self.assertEqual(self.lauf("freigeben", SLUG, "--wortlaut", "ja", "--zeit", "10:00", "--datum", "2026-11-01").returncode, 2)

    def test_p8_entwurf_mit_freigabeblock(self) -> None:
        self.ersetze(QUELLE, 'status = "veroeffentlicht"', 'status = "entwurf"')
        lauf = self.lauf("pruefen", "--nur-quelle", str(self.w / QUELLE))
        self.assertEqual(lauf.returncode, 1, lauf.stdout)
        self.assertIn("Entwurf mit [freigabe]", lauf.stdout)

    def test_beitrag1_traegt_den_hash_seines_worts(self) -> None:
        # Fassung 1.3, Freigabe vom 03.11.2026 01:46. Der Hash ist ungesalzen: ein kurzer Satz lässt sich aus ihm
        # zurückraten. Vor Beitrag 2 bekommt er ein Salz außerhalb des Repos.
        self.assertIn('wortlaut_sha256 = "aa32e7eaa111d22182715f51a62a9140c6a4181ced0a1ae81270e292d1519f84"', self.lies(QUELLE))

    def test_p13_fremde_nummer_aus_der_vorlage_in_der_ausgabe(self) -> None:
        self.ersetze("ops/blog/vorlagen/uebersicht.html", "</main>", "<p>02166 6459958</p></main>")
        self.rot("Nummer aus der Vorlage", "P13", ("bauen",))

    def test_p15_entwurfsordner_gelistet(self) -> None:
        (self.w / "kanal").mkdir()
        (self.w / "ops/veroeffentlichen.liste").write_text(self.lies("ops/veroeffentlichen.liste") + "kanal\n", encoding="utf-8")
        self.assertEqual(self.lauf("pruefen").returncode, 0, "ohne ENTWURF.txt geht der Ordner durch")
        (self.w / "kanal/ENTWURF.txt").write_text("Entwurf\n", encoding="utf-8")
        self.assertIn("kanal ist ein Entwurf", self.rot("gelisteter Ordner mit ENTWURF.txt", "P15"))

    def test_p15_kurzadresse_nicht_gelistet(self) -> None:
        self.ersetze("ops/veroeffentlichen.liste", "sicherheit-2026\n", "")
        self.rot("Kurzadresse nicht in der Kopierliste", "P15")

    def test_p15_liste_fehlt_ist_rot(self) -> None:
        (self.w / "ops/veroeffentlichen.liste").unlink()
        self.rot("Kopierliste fehlt", "P15")

    def test_p8_wortlaut_im_klartext(self) -> None:
        self.ersetze(QUELLE, "wortlaut_sha256 = ", 'wortlaut = "Ja, veröffentlichen"\nwortlaut_sha256 = ')
        self.assertIn("freigabe.wortlaut gehört nicht", self.rot("Satz im Klartext im Kopf", "P8"))

    def test_p8_hash_kaputt(self) -> None:
        text = re.sub(r'^wortlaut_sha256 = "[0-9a-f]{64}"', 'wortlaut_sha256 = "abc"', self.lies(QUELLE), count=1, flags=re.M)
        self.assertNotEqual(text, self.lies(QUELLE), "Anker fehlt: wortlaut_sha256")
        self.schreib(QUELLE, text)
        self.rot("wortlaut_sha256 nicht 64 Hexzeichen", "P8")

    def test_freigabe_gelangt_in_keine_ausgabe(self) -> None:
        for pfad in ("blog/index.html", f"blog/{SLUG}/index.html", f"blog/{SLUG}/index.html.md", "blog/feed.xml",
                     "blog/rss.xml", "llms.txt", "sitemap.xml", "sicherheit-2026/index.html"):
            text = self.lies(pfad)
            for wort in ("Fabrice", "wortlaut", "freigabe"):
                self.assertNotIn(wort, text, pfad)

    def test_p8_doppelter_titel_und_beschreibung(self) -> None:
        zweit = self.lies(QUELLE).replace(f'slug = "{SLUG}"', 'slug = "zweiter-beitrag"').replace('kurzadressen = ["/sicherheit-2026/"]\n', "")
        self.schreib("inhalt/blog/zweiter-beitrag.md", zweit)
        aus = self.rot("doppelter Titel", "P8")
        self.assertIn("titel doppelt", aus)
        self.assertIn("beschreibung doppelt", aus)

    def test_p9_jsonld_kaputt(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "$jsonld", "{kaputt")
        self.rot("JSON-LD nicht lesbar", "P9")

    def test_p9_jsonld_ohne_pflichtfeld(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "$jsonld", '{"@graph":[{"@type":"BlogPosting","headline":"x"}]}')
        self.rot("JSON-LD ohne Pflichtfelder", "P9")

    def test_p9_sitemap_kein_xml(self) -> None:
        self.ersetze("ops/blog/sitemap-seiten.xml", "</url>\n", "\n", )
        self.assertIn("sitemap.xml:", self.rot("Sitemap kein XML", "P9"))

    def test_p10_handaenderung(self) -> None:
        self.ersetze(f"blog/{SLUG}/index.html", "<h1>", "<h1>Von Hand ")
        self.assertIn(f"blog/{SLUG}/index.html:", self.rot("Handänderung", "P10"))

    def test_p10_bauen_vergessen(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", "Seither reißt")
        self.neu_freigeben()
        self.rot("Bauen vergessen", "P10")

    def test_p10_ausgabe_fehlt(self) -> None:
        (self.w / "blog/rss.xml").unlink()
        self.rot("Ausgabe fehlt", "P10")

    def test_p10_verwaist(self) -> None:
        self.schreib("blog/alt/index.html", "alt")
        self.rot("Datei ohne Quelle", "P10")

    def test_p10_slug_verschwunden(self) -> None:
        self.schreib("vorher.xml", "<urlset><url><loc>https://sundsconnect.de/blog/alter-slug/</loc></url></urlset>")
        self.rot("Slug verschwunden", "P10", ("pruefen", "--vorher", "vorher.xml"))

    def test_p11_firmendaten_startseite(self) -> None:
        self.ersetze("index.html", '"streetAddress": "Nobelstraße 3-5"', '"streetAddress": "Andere Straße 1"')
        self.assertIn("index.html:", self.rot("Adresse Startseite weicht ab", "P11"))

    def test_p12_robots_sperrt_blog(self) -> None:
        self.schreib("robots.txt", "User-agent: *\nDisallow: /blog/\nSitemap: https://sundsconnect.de/sitemap.xml\n")
        self.assertIn("robots.txt:2", self.rot("robots sperrt Blog", "P12"))

    def test_p12_robots_ohne_sitemap(self) -> None:
        self.schreib("robots.txt", "User-agent: *\nAllow: /\n")
        self.rot("robots ohne Sitemap", "P12")

    def test_haus_toml_kaputt_nennt_datei_und_zeile(self) -> None:
        self.ersetze("ops/blog/haus.toml", 'land = "DE"', 'land = "DE')
        lauf = self.lauf("pruefen")
        ROTPROBEN.append(("P2 haus.toml kein TOML", lauf.returncode, lauf.stdout.strip()[:150]))
        self.assertEqual(lauf.returncode, 1)
        self.assertRegex(lauf.stdout, r"ops/blog/haus\.toml:\d+")
        self.assertNotIn("Traceback", lauf.stdout + lauf.stderr)

    def test_schlagwort_falscher_typ_ohne_stacktrace(self) -> None:
        self.ersetze(QUELLE, 'schlagwoerter = ["it-sicherheit", "kleine-unternehmen"]', 'schlagwoerter = [["it-sicherheit"]]')
        self.rot("Schlagwort als Liste", "P2")

    def test_p0_vorlage_unbekannte_variable(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "</main>", "$gibt_es_nicht</main>")
        self.assertIn("beitrag.html:", self.rot("Vorlage mit fremder Variable", "P0"))


class Firmendaten(Baum):
    """Die Regel des Datenarchitekten: 11 eingesäte Fehler, jeder muss erkannt werden, mit Datei, Zeile und Soll."""

    # Datei, Anker, Ersatz, Name: dieselben Mutationen wie in der Messprobe des Datenarchitekten
    MUTATIONEN = [
        ("impressum/index.html", "Nobelstraße 3-5<br>", "Nobelstraße 7<br>", "Impressum Hausnummer"),
        ("contact/index.html", '"name": "S&S Connect GbR"', '"name": "Schippers GbR"', "Kontakt JSON-LD Name"),
        ("services/index.html", "<p>41189 Mönchengladbach</p>", "<p>41179 Mönchengladbach</p>", "Fußzeile PLZ"),
        ("projects/index.html", f"Nobelstraße 3{chr(0x2013)}5", "Nobelstraße 9", "Handymenü Straße"),
        ("datenschutz/index.html", "Nobelstraße 3-5<br>", "Marienstraße 37<br>", "Datenschutz Anschrift"),
        ("index.html", '"streetAddress": "Nobelstraße 3-5"', '"streetAddress": "Nobelstraße 7"', "Startseite JSON-LD Straße"),
        ("contact/index.html", "mailto:info@sundsconnect.de", "mailto:a@b.de", "Kontakt Mail fehlt"),
        ("index.html", "assets/img/favicon-512.png", "assets/img/favicon-48.png", "Startseite Logo"),
        ("impressum/index.html", "S&S Connect GbR<br>", "Schippers & Singh GbR<br>", "Impressum Name"),
        ("index.html", f"Nobelstraße 3{chr(0x2013)}5", "Nobelstraße 3 bis 5", "Startseite Handymenü"),
        ("contact/index.html", "info@sundsconnect.de", "kontakt@sundsconnect.de", "Kontakt Mail fremd"),
    ]

    def test_elf_von_elf(self) -> None:
        self.assertEqual(self.lauf("pruefen").returncode, 0, "Kontrolle ohne Verletzung: 0 Fehlalarme")
        erkannt = 0
        for datei, anker, ersatz, name in self.MUTATIONEN:
            with self.subTest(name):
                alt = self.lies(datei)
                self.assertIn(anker, alt, f"Mutation greift nicht: {name}")
                self.schreib(datei, alt.replace(anker, ersatz))
                aus = self.rot(name, "P11")
                self.assertIn(f"{datei}:", aus)
                self.assertIn("Soll", aus, "Die Meldung nennt das Soll")
                erkannt += 1
                self.schreib(datei, alt)
        self.assertEqual(erkannt, 11)
        self.assertEqual(self.lauf("pruefen").returncode, 0, "nach dem Zurückdrehen wieder grün")

    def test_js_wird_mitgeprueft(self) -> None:
        self.schreib("js/main.js", self.lies("js/main.js") + "\nvar a = 'vertrieb@sundsconnect.de';\n")
        self.assertIn("js/main.js:", self.rot("fremde Adresse im JS", "P11"))

    def test_unbekannter_schluessel_in_firma(self) -> None:
        self.ersetze("ops/blog/haus.toml", 'land = "DE"', 'land = "DE"\nsteuernummer = "123"')
        self.assertIn("haus.toml:", self.rot("unbekannter Schlüssel in firma", "P11"))

    def test_anzeige_ergibt_nicht_e164(self) -> None:
        self.ersetze("ops/blog/haus.toml", 'telefon_anzeige = "+49 151 40322125"', 'telefon_anzeige = "+49 151 40322126"')
        self.assertIn("ergibt nicht telefon_e164", self.rot("telefon_anzeige ungleich e164", "P11"))

    def test_logo_zu_klein(self) -> None:
        self.ersetze("ops/blog/haus.toml", 'logo = "assets/img/favicon-512.png"', 'logo = "assets/img/favicon-48.png"')
        self.assertIn("Soll: PNG, quadratisch, mindestens 112 Pixel", self.rot("Logo unter 112 Pixel", "P11"))

    def test_anhang_ohne_firmendaten(self) -> None:
        text = re.sub(r"^firmendaten = .*\n", "", self.lies(QUELLE), count=1, flags=re.M)
        self.schreib(QUELLE, text)
        self.assertIn(f"{QUELLE}:", self.rot("Anhang ohne firmendaten", "P11"))

    def test_anhang_weicht_ab(self) -> None:
        self.ersetze(QUELLE, 'telefon = "+49 151 40322125"', 'telefon = "02166 6459958"')
        self.rot("Anhang Telefon weicht ab", "P11")

    def test_blogausgabe_tel_und_mail(self) -> None:
        self.ersetze("ops/blog/vorlagen/beitrag.html", "</main>", '<a href="tel:+4921666459958">x</a></main>')
        self.assertIn(f"blog/{SLUG}/index.html:", self.rot("Blogausgabe tel weicht ab", "P11"))
        self.ersetze("ops/blog/vorlagen/beitrag.html", 'tel:+4921666459958', 'mailto:a@b.de')
        self.assertIn("mailto:a@b.de", self.rot("Blogausgabe mailto weicht ab", "P11"))

    def test_telefon_gewaehlt_falsche_nummer_bricht_ab(self) -> None:
        self.ersetze("index.html", "tel:+4915140322125", "tel:+4915140322126")
        aus = self.rot("Telefon nach der Wahl", "P11", ("bauen",))
        self.assertIn("Soll: +4915140322125", aus)

    def test_frueher_als_klartext(self) -> None:
        self.ersetze("services/index.html", "</body>", "<p>02166 6459958</p></body>")
        self.assertIn("im Klartext", self.rot("frühere Nummer im Klartext", "P11"))

    def test_richtige_id_bleibt_gruen(self) -> None:
        for datei in ("index.html", "contact/index.html"):
            self.assertIn('"@id": "https://sundsconnect.de/#organisation"', self.lies(datei), "Gegenprobe: die Kennung steht wirklich dort")
        self.assertEqual(self.lauf("pruefen").returncode, 0, self.lauf("pruefen").stdout)

    def test_id_der_firma(self) -> None:
        self.ersetze("index.html", '"@id": "https://sundsconnect.de/#organisation"', '"@id": "https://example.com/#x"')
        self.assertIn("index.html:", self.rot("Handseite mit fremder @id", "P11"))

    def test_p13_telefon_mail_strasse_in_der_quelle(self) -> None:
        for name, satz in (("Telefon", "Rufen Sie uns an: 02166 6459958."),
                           ("Telefon international", "Rufen Sie uns an: +49 151 40322125."),
                           ("Mail", "Schreiben Sie an info@sundsconnect.de."),
                           ("fremde Mail", "Schreiben Sie an a@example.org."),
                           ("Straße", "Besuchen Sie uns in der Nobelstraße 3-5."),
                           ("andere Straße", "Besuchen Sie uns in der Marienstraße 37."),
                           ("mailto-Link", "[Schreiben](mailto:x)")):
            with self.subTest(name):
                alt = self.lies(QUELLE)
                self.ersetze(QUELLE, "## Was passiert ist\n", f"## Was passiert ist\n\n{satz}\n")
                self.assertIn(f"{QUELLE}:", self.rot(name, "P13"))
                self.schreib(QUELLE, alt)

    def test_p13_zahlen_im_text_sind_kein_telefon(self) -> None:
        self.ersetze(QUELLE, "## Was passiert ist\n", "## Was passiert ist\n\nAm 08.05.2026 waren es 129.000 von 1.400 Fällen, 27 Jahre, Windows 10.\n")
        self.neu_freigeben()
        self.assertEqual(self.lauf("bauen").returncode, 0, self.lauf("bauen").stdout)

    def test_p14_style_css_und_main_js(self) -> None:
        for name, tag in (("style.css in der Ausgabe", '<link rel="stylesheet" href="../../css/style.css">'),
                          ("main.js als Link", '<a href="../../js/main.js">x</a>')):
            with self.subTest(name):
                alt = self.lies("ops/blog/vorlagen/beitrag.html")
                self.ersetze("ops/blog/vorlagen/beitrag.html", "</main>", f"{tag}</main>")
                self.assertIn(f"blog/{SLUG}/index.html:", self.rot(name, "P14"))
                self.schreib("ops/blog/vorlagen/beitrag.html", alt)

    def test_indexnow_schluessel_leer(self) -> None:
        text = re.sub(r'^schluessel = "[^"]*"', 'schluessel = ""', self.lies("ops/blog/haus.toml"), count=1, flags=re.M)
        self.schreib("ops/blog/haus.toml", text)
        self.assertIn("haus.toml:", self.rot("IndexNow-Schlüssel leer", "P2"))

    def test_anhang_traegt_was_der_kopf_sagt(self) -> None:
        pdftotext = shutil.which("pdftotext")
        if not pdftotext:
            self.skipTest("pdftotext fehlt hier")
        lauf = subprocess.run([pdftotext, "-enc", "UTF-8", str(self.w / f"inhalt/blog/{SLUG}/Infoblatt_Sicherheitsluecken_2026.pdf"), "-"], capture_output=True, timeout=60, check=False)
        text = " ".join(lauf.stdout.decode("utf-8", "replace").split())
        for erwartet in ("Nobelstraße 3-5", "info@sundsconnect.de", "+49 151 40322125"):
            self.assertIn(erwartet, text)


class Befehle(Baum):
    def test_bauen_schreibt_bei_fund_nichts(self) -> None:
        vorher = self.lies("blog/feed.xml")
        self.ersetze(QUELLE, "Seitdem reißt", "<b>x</b> Seitdem reißt")
        self.assertEqual(self.lauf("bauen").returncode, 1)
        self.assertEqual(self.lies("blog/feed.xml"), vorher)

    def test_bauen_ohne_node_exit_3(self) -> None:
        text = re.sub(r'^bild = ".*"$', 'bild = ""', self.lies(QUELLE), count=1, flags=re.M)
        self.schreib(QUELLE, text)
        self.neu_freigeben()
        lauf = self.lauf("bauen", env={"PATH": ""})
        self.assertEqual(lauf.returncode, 3, lauf.stdout + lauf.stderr)

    @unittest.skipIf(os.name == "nt", "der Ersatz für node ist ein Skript mit Shebang")
    def test_bauen_zweiter_durchgang_nach_neuem_og(self) -> None:
        """Nach einem neu erzeugten og.png trägt die Seite dessen Versionsteil. Ohne den zweiten Durchgang in
        befehl_bauen stünde dort die Adresse ohne Versionsteil, weil das Bild beim ersten Durchgang noch fehlte."""
        text = re.sub(r'^bild = ".*"$', 'bild = ""', self.lies(QUELLE), count=1, flags=re.M)
        self.schreib(QUELLE, text)
        self.neu_freigeben()
        og = self.w / "blog" / SLUG / "og.png"
        self.assertFalse(og.exists(), "Ausgangszustand: noch kein og.png")
        # Ersatz für node und ops/schirmfoto.mjs (auf dem Prüfrechner gibt es kein Chrome): schreibt ein schwarzes PNG
        # in der Größe aus haus.toml an den Zielpfad, den blog.py als drittes Argument übergibt.
        self.schreib("ops/schirmfoto.mjs", "// Ersatz, wird nicht ausgeführt\n")
        ersatz = Path(self._tmp.name) / "ersatz-bin"
        ersatz.mkdir()
        node = ersatz / "node"
        node.write_text(
            f"#!{sys.executable}\n"
            "import struct, sys, zlib\n"
            "b, h = 1200, 630\n"
            "def stueck(art, daten):\n"
            "    return struct.pack('>I', len(daten)) + art + daten + struct.pack('>I', zlib.crc32(art + daten) & 0xffffffff)\n"
            "roh = b''.join(b'\\x00' + b'\\x00' * (b * 3) for _ in range(h))\n"
            "png = b'\\x89PNG\\r\\n\\x1a\\n' + stueck(b'IHDR', struct.pack('>IIBBBBB', b, h, 8, 2, 0, 0, 0)) "
            "+ stueck(b'IDAT', zlib.compress(roh)) + stueck(b'IEND', b'')\n"
            "open(sys.argv[3], 'wb').write(png)\n", encoding="utf-8")
        node.chmod(0o755)
        lauf = self.lauf("bauen", env={"PATH": f"{ersatz}{os.pathsep}{os.environ.get('PATH', '')}"})
        self.assertEqual(lauf.returncode, 0, lauf.stdout + lauf.stderr)
        self.assertTrue(og.is_file(), "der Ersatz hat kein og.png geschrieben")
        version = hashlib.sha256(og.read_bytes()).hexdigest()[:8]
        self.assertIn(f"/blog/{SLUG}/og.png?v={version}", self.lies(f"blog/{SLUG}/index.html"))

    def test_pruefen_schreibt_nichts(self) -> None:
        (self.w / "blog/rss.xml").unlink()
        self.assertEqual(self.lauf("pruefen").returncode, 1)
        self.assertFalse((self.w / "blog/rss.xml").exists())

    def test_nur_quelle_ohne_repo(self) -> None:
        ort = Path(self._tmp.name) / "ohne-repo"
        ort.mkdir()
        shutil.copy2(self.w / "ops/blog/blog.py", ort)
        shutil.copy2(self.w / "ops/blog/haus.toml", ort)
        entwurf = ort / f"{SLUG}.md"
        text = re.sub(r"\[freigabe\].*?(?=\+\+\+)", "", self.lies(QUELLE), flags=re.S).replace('status = "veroeffentlicht"', 'status = "entwurf"')
        entwurf.write_bytes(text.encode("utf-8"))
        (ort / SLUG).mkdir()
        shutil.copy2(self.w / f"inhalt/blog/{SLUG}/Infoblatt_Sicherheitsluecken_2026.pdf", ort / SLUG)
        lauf = subprocess.run([sys.executable, str(ort / "blog.py"), "pruefen", "--nur-quelle", str(entwurf)], capture_output=True, encoding="utf-8", timeout=60, check=False, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(lauf.returncode, 0, lauf.stdout + lauf.stderr)
        entwurf.write_bytes(text.replace("Seitdem reißt", "<i>x</i>").encode("utf-8"))
        lauf = subprocess.run([sys.executable, str(ort / "blog.py"), "pruefen", "--nur-quelle", str(entwurf)], capture_output=True, encoding="utf-8", timeout=60, check=False, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(lauf.returncode, 1)
        self.assertIn("[P7]", lauf.stdout)

    def test_vorschau_ausserhalb_und_nie_im_repo(self) -> None:
        ziel = Path(self._tmp.name) / "vorschau"
        entwurf = Path(self._tmp.name) / f"{SLUG}.md"
        ohne = re.sub(r"\[freigabe\].*?(?=\+\+\+)", "", self.lies(QUELLE), flags=re.S)
        entwurf.write_bytes(ohne.replace('status = "veroeffentlicht"', 'status = "entwurf"').encode("utf-8"))
        shutil.copytree(self.w / f"inhalt/blog/{SLUG}", Path(self._tmp.name) / SLUG)
        lauf = self.lauf("vorschau", str(entwurf), "--ziel", str(ziel))
        self.assertEqual(lauf.returncode, 0, lauf.stdout + lauf.stderr)
        self.assertTrue((ziel / f"blog/{SLUG}/index.html").is_file())
        self.assertTrue((ziel / "css/blog.css").is_file())
        lauf = self.lauf("vorschau", str(entwurf), "--ziel", str(self.w / "blog/entwurf"))
        self.assertEqual(lauf.returncode, 2)
        self.assertFalse((self.w / "blog/entwurf").exists())

    def test_freigeben_ohne_wortlaut_exit_2(self) -> None:
        self.assertEqual(self.lauf("freigeben", SLUG, "--zeit", "02:14").returncode, 2)
        self.assertEqual(self.lauf("freigeben", SLUG, "--wortlaut", "  ", "--zeit", "02:14").returncode, 2)

    def test_freigeben_falsche_zeit_exit_2(self) -> None:
        self.assertEqual(self.lauf("freigeben", SLUG, "--wortlaut", "ja", "--zeit", "25:00").returncode, 2)
        self.assertEqual(self.lauf("freigeben", SLUG, "--wortlaut", "ja", "--zeit", "02:1x").returncode, 2)

    def test_freigeben_setzt_status_und_freigabe(self) -> None:
        text = re.sub(r"\[freigabe\].*?(?=\+\+\+)", "", self.lies(QUELLE), flags=re.S)
        text = text.replace('status = "veroeffentlicht"', 'status = "entwurf"')
        self.schreib(QUELLE, text)
        koerper = text.split("\n+++\n", 1)[1]
        satz = 'Ja, so "raus" damit'
        lauf = self.lauf("freigeben", SLUG, "--wortlaut", satz, "--zeit", "09:30", "--datum", "2026-11-03")  # nach geaendert der Fassung 1.2
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        neu = self.lies(QUELLE)
        self.assertEqual(neu.count('status = "veroeffentlicht"'), 1)
        self.assertEqual(neu.count("[freigabe]"), 1)
        kopf = neu.split("\n+++\n", 1)[0]
        self.assertIn(f'wortlaut_sha256 = "{hashlib.sha256(satz.encode("utf-8")).hexdigest()}"', kopf)
        self.assertNotIn("damit", kopf, "der Satz selbst steht nie im Kopf")
        self.assertNotRegex(kopf, r"(?m)^wortlaut\s*=")
        self.assertEqual(neu.split("\n+++\n", 1)[1], koerper, "Der Text bleibt unberührt")
        self.assertEqual(self.lauf("pruefen").returncode, 0, self.lauf("pruefen").stdout)
        # Ein zweites Mal ersetzt, statt zu verdoppeln
        self.assertEqual(self.lauf("freigeben", SLUG, "--wortlaut", "Neu", "--zeit", "10:00", "--datum", "2026-11-03").returncode, 0)
        neu = self.lies(QUELLE)
        self.assertEqual(neu.count("[freigabe]"), 1)
        self.assertIn(f'wortlaut_sha256 = "{hashlib.sha256(b"Neu").hexdigest()}"', neu)
        self.assertEqual(neu.split("\n+++\n", 1)[0].count("wortlaut_sha256"), 1)

    def test_stand_mutationen(self) -> None:
        fall = [
            ("Feed-Eintrag gelöscht", "blog/feed.xml", lambda t: re.sub(r"  <entry>.*</entry>\n", "", t, flags=re.S), "atom: 0 von 1"),
            ("RSS-Eintrag gelöscht", "blog/rss.xml", lambda t: re.sub(r"    <item>.*</item>\n", "", t, flags=re.S), "rss: 0 von 1"),
            ("Sitemap veraltet", "sitemap.xml", lambda t: t.replace(f"/blog/{SLUG}/", "/blog/alt/"), "sitemap: 1 von 1"),
            ("llms ohne Beitrag", "llms.txt", lambda t: t.replace(f"/blog/{SLUG}/index.html.md", "/x"), "llms: 0 von 1"),
            ("Handänderung", "blog/index.html", lambda t: t + " ", "1 veraltet"),
        ]
        for name, pfad, wandel, erwartet in fall:
            with self.subTest(name):
                alt = self.lies(pfad)
                self.schreib(pfad, wandel(alt))
                lauf = self.lauf("stand")
                ROTPROBEN.append((f"stand {name}", lauf.returncode, erwartet))
                self.assertEqual(lauf.returncode, 1, lauf.stdout)
                self.assertIn(erwartet, lauf.stdout)
                self.schreib(pfad, alt)
        self.assertEqual(self.lauf("stand").returncode, 0)

    def test_stand_verwaist(self) -> None:
        self.schreib("blog/alt/index.html", "alt")
        lauf = self.lauf("stand")
        self.assertEqual(lauf.returncode, 1)
        self.assertIn("1 verwaist", lauf.stdout)

    def test_kurzadresse_uebernehmen(self) -> None:
        self.schreib("sicherheit-2026/index.html", "<!doctype html><title>von Hand</title>")
        self.rot("Kurzadresse ohne Übernahme", "P2", ("bauen",))
        lauf = self.lauf("bauen", "--uebernehmen", "sicherheit-2026")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        self.assertIn("erzeugt von", self.lies("sicherheit-2026/index.html"))


class Antwort(http.server.BaseHTTPRequestHandler):
    wurzel: Path
    kurz_mit_301 = True
    kaputt: set = set()
    indexnow_status = 200
    gemeldet: list = []

    def log_message(self, *args: object) -> None:
        return

    def do_POST(self) -> None:
        laenge = int(self.headers.get("Content-Length", 0))
        Antwort.gemeldet.append(json.loads(self.rfile.read(laenge)))
        self.send_response(Antwort.indexnow_status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        teil = urllib.parse.urlsplit(self.path)
        if teil.path.startswith("/sicherheit-2026/") and Antwort.kurz_mit_301:
            self.send_response(301)
            ziel = f"/blog/{SLUG}/" + (f"?{teil.query}" if teil.query else "")
            self.send_header("Location", ziel)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        pfad = self.wurzel / urllib.parse.unquote(teil.path.lstrip("/"))
        if pfad.is_dir():
            pfad = pfad / "index.html"
        if not pfad.is_file():
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        daten = pfad.read_bytes()
        if teil.path in Antwort.kaputt:
            daten += b" "
        art = {".md": "text/markdown; charset=utf-8", ".xml": "text/xml; charset=utf-8", ".html": "text/html; charset=utf-8",
               ".pdf": "application/pdf", ".txt": "text/plain; charset=utf-8"}.get(pfad.suffix, "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", art)
        self.send_header("Content-Length", str(len(daten)))
        self.end_headers()
        self.wfile.write(daten)


class MitServer(Baum):
    def setUp(self) -> None:
        super().setUp()
        Antwort.wurzel = self.w
        Antwort.kurz_mit_301 = True
        Antwort.kaputt = set()
        Antwort.indexnow_status = 200
        Antwort.gemeldet = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Antwort)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.basis = f"http://127.0.0.1:{self.server.server_port}"

    def live(self) -> subprocess.CompletedProcess:
        return self.lauf("stand", "--live", "--ohne-quellen", "--basis", self.basis)

    def test_live_gruen(self) -> None:
        lauf = self.live()
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        self.assertIn("0 Abweichungen", lauf.stdout)

    def test_live_md5_weicht_ab(self) -> None:
        Antwort.kaputt = {"/blog/feed.xml"}
        lauf = self.live()
        ROTPROBEN.append(("live md5 weicht ab", lauf.returncode, "blog/feed.xml"))
        self.assertEqual(lauf.returncode, 1)
        self.assertIn("feed.xml: md5", lauf.stdout)

    def test_live_kurzadresse_ohne_301(self) -> None:
        Antwort.kurz_mit_301 = False
        lauf = self.live()
        ROTPROBEN.append(("live Kurzadresse ohne 301", lauf.returncode, "erwartet 301"))
        self.assertEqual(lauf.returncode, 1)
        self.assertIn("erwartet 301", lauf.stdout)

    def test_live_seite_fehlt(self) -> None:
        (self.w / "blog/rss.xml").rename(self.w / "weg.xml")
        kopie = self.lauf("stand", "--live", "--ohne-quellen", "--basis", self.basis, "--json")
        self.assertEqual(kopie.returncode, 1)

    def test_indexnow_trocken_sendet_nichts(self) -> None:
        stand = self.w.parent / "stand.json"
        lauf = self.lauf("indexnow", "--trocken", "--stand-datei", str(stand), "--endpunkt", f"{self.basis}/indexnow")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        self.assertIn(f"https://sundsconnect.de/blog/{SLUG}/", lauf.stdout)
        self.assertEqual(Antwort.gemeldet, [])
        self.assertFalse(stand.exists())

    def test_indexnow_meldet_nur_aenderungen(self) -> None:
        stand = self.w.parent / "stand.json"
        args = ("indexnow", "--stand-datei", str(stand), "--endpunkt", f"{self.basis}/indexnow")
        self.assertEqual(self.lauf(*args).returncode, 0)
        meldung = Antwort.gemeldet[0]
        self.assertEqual(meldung["host"], "sundsconnect.de")
        self.assertEqual(sorted(meldung["urlList"]), ["https://sundsconnect.de/blog/", f"https://sundsconnect.de/blog/{SLUG}/"])
        self.assertTrue(meldung["keyLocation"].endswith(f"{meldung['key']}.txt"))
        lauf = self.lauf(*args)
        self.assertIn("keine geänderten", lauf.stdout)
        self.assertEqual(len(Antwort.gemeldet), 1)

    def test_indexnow_fehler_behaelt_den_stand(self) -> None:
        stand = self.w.parent / "stand.json"
        Antwort.indexnow_status = 500
        lauf = self.lauf("indexnow", "--stand-datei", str(stand), "--endpunkt", f"{self.basis}/indexnow")
        self.assertEqual(lauf.returncode, 1)
        self.assertFalse(stand.exists())


class Inhaltsgleich(unittest.TestCase):
    def setUp(self) -> None:
        self.alt = freigegeben_geaendert(sichtbar(GEPRUEFT.read_bytes().decode("utf-8")))
        self.neu = sichtbar((REPO / f"blog/{SLUG}/index.html").read_bytes().decode("utf-8"))

    def test_beitrag1_inhaltsgleich(self) -> None:
        """Sichtbarer Text der geprüften Seite plus freigegebene Änderungen gegen den Beitrag. Erlaubt: Brotkrumen, Lesezeit, Blog-Fußzeile."""
        self.assertEqual(abweichungen(self.alt, self.neu), [])

    def test_freigegebene_aenderung_greift_genau_einmal(self) -> None:
        """Rotprobe: eine Ersetzung ohne Treffer und eine mit zwei Treffern brechen ab, statt still nichts zu tun."""
        with self.assertRaises(AssertionError):
            freigegeben_geaendert(["nichts", "davon"])
        doppelt = sichtbar(GEPRUEFT.read_bytes().decode("utf-8"))
        with self.assertRaises(AssertionError):
            freigegeben_geaendert(doppelt + doppelt)

    def test_erlaubte_zusaetze_sind_eng(self) -> None:
        self.assertTrue(erlaubt("5 Min. Lesezeit Startseite Blog"))
        self.assertTrue(erlaubt("Blog"))
        self.assertFalse(erlaubt("Blog Blog"))
        self.assertFalse(erlaubt("5 Min. Lesezeit Neu"))
        self.assertFalse(erlaubt("Kostenlos anrufen"))

    def test_beitrag1_zeuge_schlaegt_an(self) -> None:
        """Rotprobe des Zeugen: ein geändertes, ein gelöschtes und ein eingefügtes Wort müssen auffallen."""
        i = self.neu.index("Seitdem")
        for name, mutiert in (("geändert", self.neu[:i] + ["Seither"] + self.neu[i + 1:]),
                              ("gelöscht", self.neu[:i] + self.neu[i + 1:]),
                              ("eingefügt", self.neu[:i] + ["Neu"] + self.neu[i:])):
            with self.subTest(name):
                self.assertTrue(abweichungen(self.alt, mutiert), name)

    def test_vergleichsdatei_ist_der_gepruefte_commit(self) -> None:
        git = shutil.which("git")
        lauf = subprocess.run([git, "show", f"{GEPRUEFT_COMMIT}:sicherheit-2026/index.html"], cwd=REPO, capture_output=True, timeout=30, check=False) if git else None
        if lauf is None or lauf.returncode != 0:
            self.skipTest("Commit hier nicht vorhanden (flache CI-Kopie); die Vergleichsdatei gilt dort unverglichen")
        self.assertEqual(lauf.stdout.replace(b"\r\n", b"\n"), GEPRUEFT.read_bytes().replace(b"\r\n", b"\n"))

    def test_sichtbar_ohne_maschinen_zeichen(self) -> None:
        text = " ".join(self.neu)
        for cp in (0x2014, 0x00B7, 0x2022, 0x2011):
            self.assertNotIn(chr(cp), text)

    def test_repo_pruefen_gruen(self) -> None:
        lauf = subprocess.run([sys.executable, str(REPO / "ops/blog/blog.py"), "pruefen"], cwd=REPO, capture_output=True, encoding="utf-8", timeout=60, check=False, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        self.assertEqual(lauf.returncode, 0, lauf.stdout + lauf.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
