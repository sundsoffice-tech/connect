#!/usr/bin/env python3
"""QA-Rotproben zu ops/blog/blog.py (Blog Stufe 1, Entwurf Abschnitt 4, Schritt 5).

Eigene eingesäte Verletzungen, nicht die aus test_blog.py: je Abbruchprüfung P0 bis P14 mindestens eine neue.
Jede Probe läuft in einer frischen Kopie des Baums (Baum aus test_blog.py), nie am Repo.
Ablauf je Probe: `bauen` (alle Quell- und Ausgabeprüfungen); gibt es Exit 0, danach `pruefen` (das Deploy-Tor).
Erwartet: ein Lauf endet mit Exit 1 und einer Zeile `<datei>:<zeile>: [Pn] ...`.
Proben auf Ausgaben (P10) laufen nur mit `pruefen`, weil `bauen` die Handänderung reparieren würde.

Eine Probe, die hier rot ist, ist ein Fund: die Prüfung lässt die eingesäte Verletzung durch.
QA_TABELLE=<datei> schreibt je Probe eine JSON-Zeile (Prüfung, Probe, Exit-Codes, Fundzeile).
Aufruf: python ops/blog/test_qa_rotproben.py
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_blog as tb  # noqa: E402

SLUG = tb.SLUG
QUELLE = tb.QUELLE
BEITRAG = "ops/blog/vorlagen/beitrag.html"
UEBERSICHT = "ops/blog/vorlagen/uebersicht.html"
WEITER = "ops/blog/vorlagen/weiterleitung.html"
TABELLE = os.environ.get("QA_TABELLE")
ABSATZ = "## Was passiert ist\n"


def protokoll(eintrag: dict) -> None:
    if TABELLE:
        with open(TABELLE, "a", encoding="utf-8") as f:
            f.write(json.dumps(eintrag, ensure_ascii=False) + "\n")


class QA(tb.Baum):
    def setUp(self) -> None:
        super().setUp()
        # Wie im echten Checkout (bauen.sh, CI): ops/ liegt mit seinen Dateien daneben, wird aber nie ausgeliefert
        for datei in (tb.REPO / "ops").glob("*"):
            if datei.is_file():
                shutil.copy2(datei, self.w / "ops" / datei.name)
        shutil.copytree(tb.REPO / "ops/sunds-hub", self.w / "ops/sunds-hub", dirs_exist_ok=True)
        self.assertEqual(self.lauf("pruefen").returncode, 0, "Kontrolle: die frische Kopie muss grün sein")

    # ----- Hilfen -------------------------------------------------------------------------------
    def kopf(self, alt: str, neu: str) -> None:
        self.ersetze(QUELLE, alt, neu)

    def text(self, zeile: str) -> None:
        """Eine Zeile als eigenen Absatz unter die erste Überschrift."""
        self.ersetze(QUELLE, ABSATZ, f"{ABSATZ}\n{zeile}\n")

    def kopf_re(self, muster: str, neu: str) -> None:
        alt = self.lies(QUELLE)
        text = re.sub(muster, neu, alt, count=1, flags=re.M)
        self.assertNotEqual(text, alt, f"Anker fehlt: {muster}")
        self.schreib(QUELLE, text)

    def anhaengen(self, pfad: str, zusatz: str) -> None:
        self.schreib(pfad, self.lies(pfad) + zusatz)

    def probe(self, pruefung: str, name: str, datei: str | None = None, befehl: tuple = ("bauen", "pruefen"),
              text: str | None = None, args: tuple = (), zeuge: tuple | None = None) -> None:
        codes, zeile, ausgabe = [], "", ""
        for b in befehl:
            lauf = self.lauf(b, *args) if b == "pruefen" else self.lauf(b)
            codes.append(f"{b}={lauf.returncode}")
            ausgabe = lauf.stdout + lauf.stderr
            treffer = [z for z in lauf.stdout.splitlines() if f"[{pruefung}]" in z]
            if lauf.returncode != 0:
                zeile = treffer[0] if treffer else (lauf.stdout.strip().splitlines() or [""])[0]
                break
        ok = lauf.returncode == 1 and bool(treffer) and bool(tb.FUND.match(treffer[0])) \
            and (datei is None or any(t.startswith(f"{datei}:") for t in treffer)) \
            and (text is None or any(text in t for t in treffer)) and "Traceback" not in ausgabe
        beleg = ""
        if zeuge and not ok:
            # Gegenprobe des Funds: die Verletzung steht wirklich in der Ausgabe, die ausgeliefert würde
            pfad, stueck = zeuge
            beleg = f"Zeuge {pfad}: {'enthält' if stueck in self.lies(pfad) else 'FEHLT'} {stueck!r}"
        protokoll({"pruefung": pruefung, "probe": name, "exit": ", ".join(codes), "zeile": (zeile or beleg)[:200], "gehalten": ok})
        self.assertNotIn("Traceback", ausgabe, ausgabe[-800:])
        self.assertEqual(lauf.returncode, 1, f"{name}: Verletzung durchgelassen ({', '.join(codes)})\n{ausgabe[-600:]}")
        self.assertTrue(treffer, f"{name}: Exit 1, aber keine Zeile [{pruefung}]:\n{ausgabe[-600:]}")
        self.assertRegex(treffer[0], tb.FUND)
        if datei:
            self.assertTrue(any(t.startswith(f"{datei}:") for t in treffer), f"{name}: Datei {datei} fehlt in {treffer[:3]}")
        if text:
            self.assertTrue(any(text in t for t in treffer), f"{name}: Text {text!r} fehlt in {treffer[:3]}")

    def gruen(self, name: str) -> None:
        """Gegenprobe ohne Verletzung: bauen und pruefen Exit 0. Geänderte Quelle braucht ein neues Wort (P8 bindet es an die Fassung)."""
        self.neu_freigeben()
        codes = []
        for b in ("bauen", "pruefen"):
            lauf = self.lauf(b)
            codes.append(f"{b}={lauf.returncode}")
            if lauf.returncode:
                break
        protokoll({"pruefung": "Gegenprobe", "probe": name, "exit": ", ".join(codes), "zeile": "", "gehalten": lauf.returncode == 0})
        self.assertEqual(lauf.returncode, 0, f"{name}: Fehlalarm {codes}\n{lauf.stdout[-600:]}")


# ---------------------------------------------------------------------------------------------------
# P0 Vorlagen
# ---------------------------------------------------------------------------------------------------
class P0(QA):
    def test_vorlage_fehlt(self) -> None:
        (self.w / UEBERSICHT).unlink()
        self.probe("P0", "uebersicht.html gelöscht", datei=UEBERSICHT)

    def test_platzhalter_ungueltig(self) -> None:
        self.ersetze(WEITER, "</main>", "Preis $5</main>")
        self.probe("P0", "ungültiger Platzhalter $5 in weiterleitung.html", datei=WEITER)

    def test_variable_einer_anderen_vorlage(self) -> None:
        self.ersetze(BEITRAG, "</main>", "$liste</main>")
        self.probe("P0", "$liste (nur Übersicht) in beitrag.html", datei=BEITRAG)

    def test_css_fehlt(self) -> None:
        (self.w / "css/blog.css").unlink()
        self.probe("P0", "css/blog.css gelöscht", datei="css/blog.css")

    def test_quellen_aus_vorlage_entfernt(self) -> None:
        self.ersetze(BEITRAG, "  $quellen\n", "\n")
        self.probe("P0", "beitrag.html ohne $quellen (Quellen verschwinden von der Seite)", datei=BEITRAG, zeuge=(f"blog/{SLUG}/index.html", '<ol class="quellen">'))  # Zeuge meldet FEHLT


# ---------------------------------------------------------------------------------------------------
# P1 Maschinen-Zeichen
# ---------------------------------------------------------------------------------------------------
class P1(QA):
    def test_aufzaehlungspunkt_in_haus_toml(self) -> None:
        self.ersetze("ops/blog/haus.toml", 'vorspann = "Beiträge für', f'vorspann = "Beiträge {chr(0x2022)} für')
        self.probe("P1", "U+2022 im Vorspann in haus.toml", datei="ops/blog/haus.toml")

    def test_mittelpunkt_im_css(self) -> None:
        self.anhaengen("css/blog.css", f"\n/* a {chr(0xB7)} b */\n")
        self.probe("P1", "U+00B7 im Kommentar von css/blog.css", datei="css/blog.css")

    def test_geschuetzter_bindestrich_im_titel(self) -> None:
        self.kopf('titel = "Sicherheitslücken 2026:', f'titel = "Sicherheits{chr(0x2011)}lücken 2026:')
        self.probe("P1", "U+2011 im Kopffeld titel", datei=QUELLE)

    def test_numerische_entity_in_vorlage(self) -> None:
        self.ersetze(UEBERSICHT, "</main>", "a&#8211;b</main>")
        self.probe("P1", "&#8211; zwischen Buchstaben in uebersicht.html", datei="blog/index.html")


# ---------------------------------------------------------------------------------------------------
# P2 Kopfdaten
# ---------------------------------------------------------------------------------------------------
class P2(QA):
    def test_beschreibung_69(self) -> None:
        self.kopf_re(r'^beschreibung = ".*"$', 'beschreibung = "' + "b" * 69 + '"')
        self.probe("P2", "beschreibung 69 Zeichen (Untergrenze 70)", datei=QUELLE)

    def test_pruefen_bis_gleich_geaendert(self) -> None:
        self.kopf("pruefen_bis = 2027-02-01", "pruefen_bis = 2026-11-01")
        self.probe("P2", "pruefen_bis am Tag von geaendert", datei=QUELLE)

    def test_autor_unbekannt(self) -> None:
        self.kopf('autor = "firma"', 'autor = "fabrice"')
        self.probe("P2", "autor nicht in haus.toml", datei=QUELLE)

    def test_lizenz_unbekannt(self) -> None:
        self.kopf('lizenz = "cc-by-nd-4.0"', 'lizenz = "cc-by-4.0"')
        self.probe("P2", "lizenz nicht in haus.toml", datei=QUELLE)

    def test_sechs_schlagwoerter(self) -> None:
        self.kopf('schlagwoerter = ["it-sicherheit", "kleine-unternehmen"]',
                  'schlagwoerter = ["it-sicherheit", "ki", "updates", "kleine-unternehmen", "ki", "updates"]')
        self.probe("P2", "6 Schlagwörter mit Doppelten", datei=QUELLE)

    def test_quelle_http(self) -> None:
        self.kopf('url = "https://www.bsi.bund.de/SharedDocs', 'url = "http://www.bsi.bund.de/SharedDocs')
        self.probe("P2", "quellen.url mit http://", datei=QUELLE)

    def test_kurzadresse_im_blogordner(self) -> None:
        self.kopf('kurzadressen = ["/sicherheit-2026/"]', 'kurzadressen = ["/blog/kurz/"]')
        self.probe("P2", "Kurzadresse unter /blog/", datei=QUELLE)

    def test_slug_reserviert(self) -> None:
        alt = self.lies(QUELLE).replace(f'slug = "{SLUG}"', 'slug = "feed"').replace('kurzadressen = ["/sicherheit-2026/"]\n', "")
        (self.w / QUELLE).unlink()
        self.schreib("inhalt/blog/feed.md", alt)
        self.probe("P2", "slug feed (reserviert)", datei="inhalt/blog/feed.md")

    def test_anhang_mit_pfad(self) -> None:
        self.kopf('datei = "Infoblatt_Sicherheitsluecken_2026.pdf"', 'datei = "../Infoblatt_Sicherheitsluecken_2026.pdf"')
        self.probe("P2", "Anhang ../datei", datei=QUELLE)

    def test_geprueft_kein_datum(self) -> None:
        self.kopf("pruefen_bis = 2027-02-01", 'pruefen_bis = 2027-02-01\ngeprueft = "gestern"')
        self.probe("P2", "geprueft als Text", datei=QUELLE)

    def test_indexnow_grossbuchstaben(self) -> None:
        self.ersetze("ops/blog/haus.toml", 'schluessel = "5b8819eaaf02442fbbb5823f4eb95e71"', 'schluessel = "5B8819EAAF02442FBBB5823F4EB95E71"')
        self.probe("P2", "IndexNow-Schlüssel in Großbuchstaben", datei="ops/blog/haus.toml")

    def test_fassung_mit_zeilenende(self) -> None:
        fassung = self.zeile("fassung").split('"')[1]  # Anker aus der Quelle, nicht aus einer festen Fassung
        self.kopf(f'fassung = "{fassung}"', f'fassung = "{fassung}\\n"')
        self.probe("P2", f'fassung = "{fassung}\\n" (Regel: Text wie 1.1)', datei=QUELLE, zeuge=(f"blog/{SLUG}/index.html", f"{fassung}\n"))


# ---------------------------------------------------------------------------------------------------
# P3 Bild
# ---------------------------------------------------------------------------------------------------
class P3(QA):
    def test_bild_alt_nur_leerzeichen(self) -> None:
        self.kopf_re(r'^bild_alt = ".*"$', 'bild_alt = "   "')
        self.probe("P3", "bild_alt nur Leerzeichen", datei=QUELLE)

    def test_bild_fehlt(self) -> None:
        self.kopf('bild = "assets/img/og-sicherheit-2026.png"', 'bild = "assets/img/gibt-es-nicht.png"')
        self.probe("P3", "bild zeigt auf fehlende Datei", datei=QUELLE)

    def test_bild_kein_png(self) -> None:
        self.schreib("assets/img/falsch.png", "GIF89a kein PNG")
        self.kopf('bild = "assets/img/og-sicherheit-2026.png"', 'bild = "assets/img/falsch.png"')
        self.probe("P3", "bild ist kein PNG (Textdatei .png)", datei=QUELLE)

    def test_og_png_fehlt(self) -> None:
        self.kopf('bild = "assets/img/og-sicherheit-2026.png"', 'bild = ""')
        self.neu_freigeben()
        self.probe("P3", "bild leer und blog/<slug>/og.png fehlt", datei=QUELLE, befehl=("pruefen",))

    def test_bild_ausserhalb_der_auslieferung(self) -> None:
        # inhalt/ steht nicht in ops/veroeffentlichen.liste: og:image wäre live 404
        shutil.copy2(self.w / "assets/img/og-sicherheit-2026.png", self.w / f"inhalt/blog/{SLUG}/vorschau.png")
        self.kopf('bild = "assets/img/og-sicherheit-2026.png"', f'bild = "inhalt/blog/{SLUG}/vorschau.png"')
        self.assertNotIn("inhalt", [z.strip() for z in self.lies("ops/veroeffentlichen.liste").splitlines()], "Gegenprobe: inhalt/ wird nicht ausgeliefert")
        self.probe("P3", "bild liegt in inhalt/ (nicht ausgeliefert, og:image 404)", zeuge=(f"blog/{SLUG}/index.html", f'content="https://sundsconnect.de/inhalt/blog/{SLUG}/vorschau.png?v='))

    def test_bild_mit_punktpunkt_ausserhalb_des_repos(self) -> None:
        shutil.copy2(self.w / "assets/img/og-sicherheit-2026.png", self.w.parent / "aussen.png")
        self.kopf('bild = "assets/img/og-sicherheit-2026.png"', 'bild = "assets/../../aussen.png"')
        self.probe("P3", "bild = assets/../../aussen.png (Datei außerhalb des Repos)", zeuge=(f"blog/{SLUG}/index.html", "https://sundsconnect.de/assets/../../aussen.png"))

    def test_inline_bild_fehlt(self) -> None:
        self.text('![Grafik der Lücken](grafik.png "Unterschrift")')
        self.probe("P3", "Bild im Text, Datei fehlt", datei=QUELLE)


# ---------------------------------------------------------------------------------------------------
# P4 interne Links
# ---------------------------------------------------------------------------------------------------
class P4(QA):
    def test_absolut_eigene_domain(self) -> None:
        self.text("Siehe [hier](https://sundsconnect.de/gibt-es-nicht/).")
        self.probe("P4", "absoluter Link auf eigene Domain ins Leere", datei=f"blog/{SLUG}/index.html")

    def test_www_eigene_domain(self) -> None:
        self.text("Siehe [hier](https://www.sundsconnect.de/blog/gibt-es-nicht/).")
        self.probe("P4", "www.sundsconnect.de ins Leere", datei=f"blog/{SLUG}/index.html")

    def test_ueber_die_wurzel(self) -> None:
        self.text("Siehe [hier](../../../../x/).")
        self.probe("P4", "relativer Link über die Site-Wurzel hinaus", datei=f"blog/{SLUG}/index.html")

    def test_marke_in_handseite(self) -> None:
        self.text("Siehe [Impressum](/impressum/#gibt-es-nicht).")
        self.probe("P4", "Marke fehlt in einer Handseite", datei=f"blog/{SLUG}/index.html")

    def test_css_url_ins_leere(self) -> None:
        self.anhaengen("css/blog.css", '\n.x{background:url("../assets/img/gibt-es-nicht.png")}\n')
        self.probe("P4", "url() im CSS ins Leere", datei="css/blog.css")

    def test_link_auf_ops(self) -> None:
        # ops/ wird nie ausgeliefert (bauen.sh, veroeffentlichen.liste): live 404
        self.text("Siehe [Skript](/ops/deploy.sh).")
        self.probe("P4", "Link auf /ops/deploy.sh (nicht ausgeliefert)", datei=f"blog/{SLUG}/index.html", zeuge=(f"blog/{SLUG}/index.html", 'href="../../ops/deploy.sh"'))

    def test_link_auf_inhalt(self) -> None:
        self.text(f"Siehe [PDF](/inhalt/blog/{SLUG}/Infoblatt_Sicherheitsluecken_2026.pdf).")
        self.probe("P4", "Link auf /inhalt/... (nicht ausgeliefert)", datei=f"blog/{SLUG}/index.html", zeuge=(f"blog/{SLUG}/index.html", 'href="../../inhalt/blog/'))


# ---------------------------------------------------------------------------------------------------
# P5 Fremdquellen
# ---------------------------------------------------------------------------------------------------
class P5(QA):
    def test_icon_fremd(self) -> None:
        self.ersetze(UEBERSICHT, "</head>", '<link rel="icon" href="https://example.com/f.ico">\n</head>')
        self.probe("P5", "fremdes Icon in uebersicht.html", datei="blog/index.html")

    def test_protokollrelativ(self) -> None:
        self.ersetze(BEITRAG, "</main>", '<img src="//cdn.example.com/a.png" alt="x"></main>')
        self.probe("P5", "protokollrelatives img src", datei=f"blog/{SLUG}/index.html")

    def test_sperrliste_in_quellen_url(self) -> None:
        self.kopf('url = "https://www.anthropic.com/glasswing"', 'url = "https://fonts.googleapis.com/css2?family=Inter"')
        self.probe("P5", "Sperrliste in quellen.url (Kopf)", datei=f"blog/{SLUG}/index.html")

    def test_sperrliste_grossbuchstaben(self) -> None:
        self.text("Siehe [Schrift](https://FONTS.GOOGLEAPIS.COM/css2?family=Inter).")
        self.probe("P5", "Sperrliste in Großbuchstaben", datei=f"blog/{SLUG}/index.html", zeuge=(f"blog/{SLUG}/index.html", "https://FONTS.GOOGLEAPIS.COM/css2"))

    def test_css_import_als_text(self) -> None:
        self.schreib("css/blog.css", '@import "https://fonts.googleapis.com/css2?family=Inter";\n' + self.lies("css/blog.css"))
        self.probe("P5", '@import "https://fonts.googleapis.com/..." in blog.css', datei="css/blog.css", zeuge=("css/blog.css", '@import "https://fonts.googleapis.com'))

    def test_css_url_grossgeschrieben(self) -> None:
        self.anhaengen("css/blog.css", "\n.x{background:URL(https://example.com/a.png)}\n")
        self.probe("P5", "URL(https://example.com/...) in blog.css", datei="css/blog.css", zeuge=("css/blog.css", "URL(https://example.com"))

    def test_srcset_fremd(self) -> None:
        self.ersetze(BEITRAG, "</main>", '<img src="../../assets/img/og-sicherheit-2026.png" srcset="https://example.com/a.png 2x" alt="x"></main>')
        self.probe("P5", "img srcset auf fremden Host", datei=f"blog/{SLUG}/index.html", zeuge=(f"blog/{SLUG}/index.html", 'srcset="https://example.com/a.png 2x"'))


# ---------------------------------------------------------------------------------------------------
# P6 CSP
# ---------------------------------------------------------------------------------------------------
class P6(QA):
    def test_csp_im_body(self) -> None:
        csp = '<meta http-equiv="Content-Security-Policy" content="$csp">\n'
        self.ersetze(WEITER, csp, "")
        self.ersetze(WEITER, "<body>\n", "<body>\n" + csp)
        self.probe("P6", "CSP-Meta im body statt im head (Browser ignorieren sie)", datei="sicherheit-2026/index.html", zeuge=("sicherheit-2026/index.html", '<body>\n<meta http-equiv="Content-Security-Policy"'))

    def test_style_attribut_uebersicht(self) -> None:
        self.ersetze(UEBERSICHT, "</main>", '<p style="color:red">x</p></main>')
        self.probe("P6", "style-Attribut in uebersicht.html", datei="blog/index.html")

    def test_skript_mit_src(self) -> None:
        self.ersetze(WEITER, "</main>", '<script src="../js/x.js"></script></main>')
        self.probe("P6", "externes Skript in weiterleitung.html", datei="sicherheit-2026/index.html")

    def test_script_src_elem_weicht_auf(self) -> None:
        self.ersetze("ops/blog/haus.toml", "form-action 'none'\"", "form-action 'none'; script-src-elem https:\"")
        self.probe("P6", "haus.toml csp + script-src-elem https:", datei=f"blog/{SLUG}/index.html", zeuge=(f"blog/{SLUG}/index.html", "script-src-elem https:"))


# ---------------------------------------------------------------------------------------------------
# P7 Haus-Markdown
# ---------------------------------------------------------------------------------------------------
class P7(QA):
    def test_ueberschrift_ohne_leerzeichen(self) -> None:
        self.text("##Neue Überschrift")
        self.probe("P7", "##ohne Leerzeichen", datei=QUELLE)

    def test_kasten_unbekannt(self) -> None:
        self.text("::: kasten warnung\nText\n:::")
        self.probe("P7", "::: kasten warnung", datei=QUELLE)

    def test_spalte_ausserhalb(self) -> None:
        self.text("::: spalte Links\nText\n:::")
        self.probe("P7", "::: spalte außerhalb ::: zwei", datei=QUELLE)

    def test_codeblock(self) -> None:
        self.text("```\ncode\n```")
        self.probe("P7", "Codeblock ```", datei=QUELLE)

    def test_trennlinie(self) -> None:
        self.text("---")
        self.probe("P7", "Trennlinie ---", datei=QUELLE)

    def test_schema_data(self) -> None:
        self.text("Siehe [hier](data:text/html,hallo).")
        self.probe("P7", "Link-Schema data:", datei=QUELLE)

    def test_eingerueckt(self) -> None:
        self.text("  eingerückter Satz")
        self.probe("P7", "eingerückte Zeile", datei=QUELLE)

    def test_link_ohne_ende(self) -> None:
        self.text("Siehe [hier](kein-ende")
        self.probe("P7", "[Text](Ziel ohne Klammer zu", datei=QUELLE)

    def test_autolink(self) -> None:
        self.text("Siehe <https://example.com>.")
        self.probe("P7", "Autolink in spitzen Klammern", datei=QUELLE)


# ---------------------------------------------------------------------------------------------------
# P8 Status und Freigabe, Doppelte
# ---------------------------------------------------------------------------------------------------
class P8(QA):
    def zweiter(self, titel: str | None = None, beschreibung: str | None = None) -> None:
        t = self.lies(QUELLE).replace(f'slug = "{SLUG}"', 'slug = "zweiter-beitrag"').replace('kurzadressen = ["/sicherheit-2026/"]\n', "")
        if titel is not None:
            t = re.sub(r'^titel = ".*"$', f'titel = "{titel}"', t, count=1, flags=re.M)
        if beschreibung is not None:
            t = re.sub(r'^beschreibung = ".*"$', f'beschreibung = "{beschreibung}"', t, count=1, flags=re.M)
        self.schreib("inhalt/blog/zweiter-beitrag.md", t)
        (self.w / "inhalt/blog/zweiter-beitrag").mkdir(exist_ok=True)
        shutil.copy2(self.w / f"inhalt/blog/{SLUG}/Infoblatt_Sicherheitsluecken_2026.pdf", self.w / "inhalt/blog/zweiter-beitrag/")

    def test_freigabe_am_ohne_zeitzone(self) -> None:
        self.kopf(self.zeile("am"), self.zeile("am").rsplit("+", 1)[0])
        self.probe("P8", "freigabe.am ohne Zeitzone", datei=QUELLE)

    def test_von_kleingeschrieben(self) -> None:
        self.kopf('von = "Fabrice"', 'von = "fabrice"')
        self.probe("P8", 'freigabe.von = "fabrice"', datei=QUELLE)

    def test_beschreibung_doppelt_in_grossschrift(self) -> None:
        self.zweiter(titel="Ein ganz anderer Titel für den zweiten Beitrag",
                     beschreibung="KI FINDET SICHERHEITSLÜCKEN SCHNELLER, ALS UNTERNEHMEN UPDATES EINSPIELEN. SIEBEN SCHRITTE FÜR KLEINE UNTERNEHMEN, OHNE FACHWISSEN.")
        self.probe("P8", "beschreibung doppelt, nur Großschrift", datei="inhalt/blog/zweiter-beitrag.md", text="beschreibung doppelt")

    def test_titel_doppelt_mit_doppeltem_leerzeichen(self) -> None:
        self.zweiter(titel="Sicherheitslücken 2026:  Was passiert ist und was jetzt zählt",
                     beschreibung="Eine andere Beschreibung des zweiten Beitrags, lang genug für die Untergrenze von siebzig Zeichen.")
        self.probe("P8", "titel doppelt bis auf ein zweites Leerzeichen (im Browser gleich)", text="titel doppelt", zeuge=("blog/zweiter-beitrag/index.html", "<h1>Sicherheitslücken 2026:  Was"))

    def test_sha_mit_zeilenende(self) -> None:
        sha = self.zeile("wortlaut_sha256").split('"')[1]
        self.kopf(f'wortlaut_sha256 = "{sha}"', f'wortlaut_sha256 = "{sha}\\n"')
        self.probe("P8", "wortlaut_sha256 mit \\n (65 Zeichen)", datei=QUELLE, zeuge=(QUELLE, f"{sha[-6:]}\\n"))


# ---------------------------------------------------------------------------------------------------
# P9 JSON-LD und XML
# ---------------------------------------------------------------------------------------------------
class P9(QA):
    def test_steuerzeichen_im_text(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", "Seitdem \x01 reißt")
        self.probe("P9", "U+0001 im Text: Feed kein XML", text="kein lesbares XML")

    def test_zwei_jsonld_bloecke(self) -> None:
        self.ersetze(BEITRAG, "</main>", '<script type="application/ld+json">{}</script></main>')
        self.probe("P9", "zweiter JSON-LD-Block in beitrag.html", datei=f"blog/{SLUG}/index.html")

    def test_uebersicht_ohne_blog(self) -> None:
        # csp und jsonld sind keine Pflichtvariablen: P9 prüft das Ergebnis
        self.ersetze(UEBERSICHT, "$jsonld", '{"@graph":[{"@type":"Organization","@id":"x","name":"x","address":"x","email":"x","logo":"x"},{"@type":"WebSite"}]}')
        self.probe("P9", "Übersicht JSON-LD ohne Blog", datei="blog/index.html", text="JSON-LD ohne Blog")


# ---------------------------------------------------------------------------------------------------
# P10 Abweichung vom frischen Bau
# ---------------------------------------------------------------------------------------------------
class P10(QA):
    def test_pdf_ein_byte(self) -> None:
        pfad = self.w / f"blog/{SLUG}/Infoblatt_Sicherheitsluecken_2026.pdf"
        daten = bytearray(pfad.read_bytes())
        daten[-2] ^= 0x01
        pfad.write_bytes(bytes(daten))
        self.probe("P10", "ein Byte im ausgelieferten PDF", datei=f"blog/{SLUG}/Infoblatt_Sicherheitsluecken_2026.pdf", befehl=("pruefen",))

    def test_kurzseite_handaenderung(self) -> None:
        self.ersetze("sicherheit-2026/index.html", "<h1>", "<h1>Hand ")
        self.probe("P10", "Handänderung an der Weiterleitungsseite", datei="sicherheit-2026/index.html", befehl=("pruefen",))

    def test_llms_handaenderung(self) -> None:
        self.anhaengen("llms.txt", "- [Neu](https://sundsconnect.de/x)\n")
        self.probe("P10", "Zeile an llms.txt angehängt", datei="llms.txt", befehl=("pruefen",))

    def test_indexnow_datei_fehlt(self) -> None:
        (self.w / "5b8819eaaf02442fbbb5823f4eb95e71.txt").unlink()
        self.probe("P10", "IndexNow-Schlüsseldatei gelöscht", datei="5b8819eaaf02442fbbb5823f4eb95e71.txt", befehl=("pruefen",))

    def test_slug_umbenannt_mit_alten_ausgaben_entfernt(self) -> None:
        shutil.copy2(self.w / "sitemap.xml", self.w / "vorher.xml")
        neu = "sicherheitsluecken-2026-neu"
        text = self.lies(QUELLE).replace(f'slug = "{SLUG}"', f'slug = "{neu}"')
        (self.w / QUELLE).unlink()
        self.schreib(f"inhalt/blog/{neu}.md", text)
        shutil.move(str(self.w / f"inhalt/blog/{SLUG}"), str(self.w / f"inhalt/blog/{neu}"))
        shutil.rmtree(self.w / f"blog/{SLUG}")
        self.neu_freigeben(neu)
        lauf = self.lauf("bauen")
        self.assertEqual(lauf.returncode, 0, lauf.stdout)
        self.probe("P10", "Slug umbenannt, alte Ausgaben gelöscht, --vorher alte Sitemap", befehl=("pruefen",),
                   args=("--vorher", "vorher.xml"), text=f"Slug {SLUG}")

    def test_alte_ausgabe_nach_umbenennen_meldet_p10_nicht_p11(self) -> None:
        """Alte Beitragsseite bleibt liegen: erwartet P10 verwaist; bauen soll sie nur melden (Docstring befehl_bauen)."""
        neu = "sicherheitsluecken-2026-neu"
        text = self.lies(QUELLE).replace(f'slug = "{SLUG}"', f'slug = "{neu}"')
        (self.w / QUELLE).unlink()
        self.schreib(f"inhalt/blog/{neu}.md", text)
        shutil.move(str(self.w / f"inhalt/blog/{SLUG}"), str(self.w / f"inhalt/blog/{neu}"))
        self.neu_freigeben(neu)
        lauf = self.lauf("bauen")
        self.assertIn(f"verwaist (bleibt liegen, nichts wird gelöscht): blog/{SLUG}/index.html", lauf.stdout)
        p11 = [z for z in lauf.stdout.splitlines() if "[P11]" in z and f"blog/{SLUG}/" in z]
        protokoll({"pruefung": "P10", "probe": "Slug umbenannt, alte Ausgabe liegt noch: bauen meldet P11 Fremdfirmen statt verwaist",
                   "exit": f"bauen={lauf.returncode}", "zeile": (p11 or lauf.stdout.splitlines() or [""])[0][:200], "gehalten": not p11})
        self.assertEqual(p11, [], "alte Blogausgabe wird als Handseite gegen haus.toml verglichen")

    def test_verwaiste_kurzseite(self) -> None:
        self.kopf('kurzadressen = ["/sicherheit-2026/"]\n', "")
        self.neu_freigeben()
        self.assertIn("erzeugt von ops/blog/blog.py", self.lies("sicherheit-2026/index.html"))
        self.probe("P10", "Kurzadresse aus der Quelle entfernt, erzeugte Seite bleibt liegen und wird ausgeliefert",
                   datei="sicherheit-2026/index.html")


# ---------------------------------------------------------------------------------------------------
# P11 Firmendaten (eigene Werte, nicht die 11 des Datenarchitekten)
# ---------------------------------------------------------------------------------------------------
class P11(QA):
    def test_plz_fusszeile(self) -> None:
        self.ersetze("services/index.html", "<p>41189 Mönchengladbach</p>", "<p>41198 Mönchengladbach</p>")
        self.probe("P11", "PLZ 41198 in der Fußzeile services", datei="services/index.html")

    def test_jsonld_land(self) -> None:
        self.ersetze("index.html", '"addressCountry": "DE"', '"addressCountry": "AT"')
        self.probe("P11", "JSON-LD addressCountry AT", datei="index.html")

    def test_strasse_abgekuerzt(self) -> None:
        self.ersetze("impressum/index.html", "Nobelstraße 3-5<br>", "Nobelstr. 5<br>")
        self.probe("P11", "Impressum Nobelstr. 5", datei="impressum/index.html")

    def test_hausnummer_mit_praefix(self) -> None:
        self.ersetze("services/index.html", "<p>Nobelstraße 3-5</p>", "<p>Nobelstraße 3-57</p>")
        self.probe("P11", "Fußzeile services Nobelstraße 3-57", datei="services/index.html", zeuge=("services/index.html", "<p>Nobelstraße 3-57</p>"))

    def test_mailto_andere_domain_mit_praefix(self) -> None:
        alt = self.lies("contact/index.html")
        self.assertIn("mailto:info@sundsconnect.de", alt)
        self.schreib("contact/index.html", alt.replace("mailto:info@sundsconnect.de", "mailto:info@sundsconnect.dev"))
        self.probe("P11", "alle mailto: der Kontaktseite auf info@sundsconnect.dev", datei="contact/index.html", zeuge=("contact/index.html", "mailto:info@sundsconnect.dev"))


# ---------------------------------------------------------------------------------------------------
# P12 robots.txt
# ---------------------------------------------------------------------------------------------------
class P12(QA):
    ROBOTS = "User-agent: *\nAllow: /\n{zeile}\nSitemap: https://sundsconnect.de/sitemap.xml\n"

    def robots(self, zeile: str) -> None:
        self.schreib("robots.txt", self.ROBOTS.format(zeile=zeile))

    def test_kleinschrift(self) -> None:
        self.robots("disallow: /blog/")
        self.probe("P12", "disallow: /blog/ klein", datei="robots.txt")

    def test_sitemap_auskommentiert(self) -> None:
        self.schreib("robots.txt", "User-agent: *\nAllow: /\n# Sitemap: https://sundsconnect.de/sitemap.xml\n")
        self.probe("P12", "Sitemap nur als Kommentar", datei="robots.txt")

    def test_beitrag_gesperrt(self) -> None:
        self.robots(f"Disallow: /blog/{SLUG}/")
        self.probe("P12", "Disallow: /blog/<slug>/", datei="robots.txt")

    def test_feed_gesperrt(self) -> None:
        self.robots("Disallow: /blog/feed.xml")
        self.probe("P12", "Disallow: /blog/feed.xml", datei="robots.txt")

    def test_platzhalter(self) -> None:
        self.robots("Disallow: /*/")
        self.probe("P12", "Disallow: /*/ (sperrt jeden Ordner)", datei="robots.txt")

    def test_eingerueckt(self) -> None:
        self.robots("  Disallow: /blog/")
        self.probe("P12", "eingerückt '  Disallow: /blog/'", datei="robots.txt")


# ---------------------------------------------------------------------------------------------------
# P13 Firmendaten in der Beitragsquelle
# ---------------------------------------------------------------------------------------------------
class P13(QA):
    def test_seitentitel_mit_telefon(self) -> None:
        self.kopf('seitentitel = "Sicherheitslücken 2026: Was jetzt zählt"', 'seitentitel = "Sicherheit 2026, Hilfe: 02166 6459958"')
        self.probe("P13", "Telefon im seitentitel", datei=QUELLE)

    def test_tel_link(self) -> None:
        self.text("[Rufen Sie an](tel:+4921666459958)")
        self.probe("P13", "tel:-Link im Text", datei=QUELLE)

    def test_bild_alt_mit_telefon(self) -> None:
        self.kopf_re(r'^bild_alt = ".*"$', 'bild_alt = "Infoblatt, Fragen unter 0151 40322125"')
        self.probe("P13", "Telefon im bild_alt (og:image:alt, twitter:image:alt)", datei=QUELLE, zeuge=(f"blog/{SLUG}/index.html", "0151 40322125"))

    def test_anhang_knopf_mit_mail(self) -> None:
        self.kopf('knopf = "Als PDF herunterladen"', 'knopf = "PDF, Fragen an kontakt@example.org"')
        self.probe("P13", "Mail im anhaenge.knopf", datei=QUELLE, zeuge=(f"blog/{SLUG}/index.html", "kontakt@example.org"))

    def test_anhang_hinweis_mit_telefon(self) -> None:
        self.kopf('hinweis = "Zwei Seiten A4, zum Ausdrucken und Weitergeben."', 'hinweis = "Rückfragen: 0151 40322125."')
        self.probe("P13", "Telefon im anhaenge.hinweis", datei=QUELLE, zeuge=(f"blog/{SLUG}/index.html", "0151 40322125"))

    def test_netz_satz_mit_strasse(self) -> None:
        self.kopf('netz_satz = "Dieses Blatt im Netz:"', 'netz_satz = "Abholen in der Marienstraße 37, im Netz:"')
        self.probe("P13", "Straße im netz_satz", datei=QUELLE, zeuge=(f"blog/{SLUG}/index.html", "Marienstraße 37"))

    def test_quelle_adresse_mit_mail(self) -> None:
        self.kopf('adresse = "anthropic.com/glasswing"', 'adresse = "Kopie bei info@sundsconnect.de"')
        self.probe("P13", "Mail im quellen.adresse", datei=QUELLE, zeuge=(f"blog/{SLUG}/index.html", "Kopie bei info@sundsconnect.de"))


# ---------------------------------------------------------------------------------------------------
# P14 Stempel-Ziele in der Blogausgabe
# ---------------------------------------------------------------------------------------------------
class P14(QA):
    def test_markdown_link_auf_style_css(self) -> None:
        self.text("Die [Formatvorlage](/css/style.css) der Site.")
        self.probe("P14", "Markdown-Link auf /css/style.css", datei=f"blog/{SLUG}/index.html")

    def test_uebersicht_main_js(self) -> None:
        self.ersetze(UEBERSICHT, "</main>", '<a href="../js/main.js?v=1">x</a></main>')
        self.probe("P14", "uebersicht.html verlinkt js/main.js?v=1", datei="blog/index.html")


# ---------------------------------------------------------------------------------------------------
# Gegenproben (ohne Verletzung Exit 0), stand, Determinismus
# ---------------------------------------------------------------------------------------------------
class Gegenproben(QA):
    def test_kontrolle(self) -> None:
        self.gruen("unveränderte Kopie")

    def test_cdata_ende_im_text(self) -> None:
        self.ersetze(QUELLE, "Seitdem reißt", "Seitdem ]]> reißt")
        self.gruen("]]> im Text ist keine Verletzung")

    def test_neuer_absatz_mit_zahlen_und_quelle(self) -> None:
        self.text("Im Jahr 2026 waren es 3–5 Fälle je Woche, Version 0.9.1 von 12.10.2026.")
        self.gruen("Absatz mit Spanne 3–5, Version und Datum")

    def test_fremder_link_mit_noopener(self) -> None:
        self.text("Mehr beim [BSI](https://www.bsi.bund.de/).")
        self.gruen("fremder Link im Text bekommt rel=noopener")


class Stand(QA):
    def stand(self, name: str, erwartet: str) -> None:
        lauf = self.lauf("stand")
        protokoll({"pruefung": "stand", "probe": name, "exit": f"stand={lauf.returncode}",
                   "zeile": next((z for z in lauf.stdout.splitlines() if erwartet in z), lauf.stdout.splitlines()[0] if lauf.stdout else ""),
                   "gehalten": lauf.returncode == 1 and erwartet in lauf.stdout})
        self.assertEqual(lauf.returncode, 1, lauf.stdout)
        self.assertIn(erwartet, lauf.stdout)

    def test_kontrolle(self) -> None:
        lauf = self.lauf("stand")
        protokoll({"pruefung": "stand", "probe": "Kontrolle", "exit": f"stand={lauf.returncode}", "zeile": lauf.stdout.splitlines()[1] if lauf.stdout else "", "gehalten": lauf.returncode == 0})
        self.assertEqual(lauf.returncode, 0, lauf.stdout)

    def test_feed_datei_geloescht(self) -> None:
        (self.w / "blog/feed.xml").unlink()
        self.stand("blog/feed.xml gelöscht", "fehlt: blog/feed.xml")

    def test_feed_eintrag_id_geaendert(self) -> None:
        self.ersetze("blog/feed.xml", f"<id>https://sundsconnect.de/blog/{SLUG}/</id>", "<id>https://sundsconnect.de/blog/x/</id>")
        self.stand("Feed-Eintrag: id auf anderen Slug", "atom: 1 von 1, fehlt")

    def test_sitemap_lastmod_veraltet(self) -> None:
        text = self.lies("sitemap.xml")
        stelle = text.index(f"/blog/{SLUG}/</loc>")
        lm = re.compile(r"<lastmod>[^<]+</lastmod>")
        m = lm.search(text, stelle)
        self.assertIsNotNone(m)
        self.schreib("sitemap.xml", text[:m.start()] + "<lastmod>2026-10-01</lastmod>" + text[m.end():])
        self.stand("Sitemap: lastmod des Beitrags veraltet", "veraltet: sitemap.xml")

    def test_sitemap_eintrag_fehlt(self) -> None:
        text = self.lies("sitemap.xml")
        neu = re.sub(r"\s*<url>\s*<loc>[^<]*/blog/" + SLUG + r"/</loc>.*?</url>", "", text, count=1, flags=re.S)
        self.assertNotEqual(neu, text)
        self.schreib("sitemap.xml", neu)
        self.stand("Sitemap: Beitrag gelöscht", "sitemap: 0 von 1")

    def test_handaenderung_beitrag(self) -> None:
        self.ersetze(f"blog/{SLUG}/index.html.md", "\n", "\n\nVon Hand.\n")
        self.stand("Handänderung an index.html.md", f"veraltet: blog/{SLUG}/index.html.md")

    def test_handaenderung_crlf(self) -> None:
        pfad = self.w / "blog/index.html"
        pfad.write_bytes(pfad.read_bytes().replace(b"\n", b"\r\n"))
        self.stand("blog/index.html mit CRLF", "veraltet: blog/index.html")


class Determinismus(QA):
    def summen(self) -> dict:
        aus = {}
        for pfad in sorted(self.w.rglob("*")):
            rel = pfad.relative_to(self.w).as_posix()
            if pfad.is_file() and (rel.startswith(("blog/", "sicherheit-2026/")) or rel in ("sitemap.xml", "llms.txt", "5b8819eaaf02442fbbb5823f4eb95e71.txt")):
                aus[rel] = hashlib.md5(pfad.read_bytes()).hexdigest()
        return aus

    def test_zweimal_bauen_md5_gleich_und_gleich_dem_repo(self) -> None:
        vorher = self.summen()
        for datei in list(vorher):
            (self.w / datei).unlink()
        erst = self.lauf("bauen")
        self.assertEqual(erst.returncode, 0, erst.stdout)
        a = self.summen()
        zweit = self.lauf("bauen", env={"TZ": "Pacific/Kiritimati"})
        self.assertEqual(zweit.returncode, 0, zweit.stdout)
        self.assertIn("0 geschrieben", zweit.stdout)
        b = self.summen()
        protokoll({"pruefung": "bauen", "probe": f"zweimal bauen ({len(a)} Ausgaben, zweiter Lauf TZ=Pacific/Kiritimati)",
                   "exit": f"bauen={erst.returncode}, bauen={zweit.returncode}",
                   "zeile": hashlib.md5(json.dumps(b, sort_keys=True).encode()).hexdigest(), "gehalten": a == b == vorher})
        self.assertEqual(a, b)
        self.assertEqual(a, vorher, "frisch gebaut gleich dem eingecheckten Stand")
        print("\nMD5-Liste:", json.dumps(b, sort_keys=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
