#!/usr/bin/env python3
"""Seiten eines verschwundenen Blogs aus der Wayback Machine holen, je Seite die jüngste Aufnahme.

Aufruf:
  python3 wayback.py PRÄFIX ZIEL [--auch-feeds] [--pause 1.5]

PRÄFIX  Adresse ohne https://, etwa schedulae.ifwo.eu
ZIEL    Ordner für die Ergebnisse:
          ZIEL/roh/<pfad>.html   die Seite, wie das Archiv sie gespeichert hat (ohne Wayback-Leiste)
          ZIEL/seiten.json       je Seite Adresse, Datum der Aufnahme, Titel, Veröffentlichungsdatum, Text

Gefragt wird zuerst die CDX-Schnittstelle des Internet Archive nach allen HTML-Aufnahmen unter dem Präfix.
Feeds, Kommentarseiten, Anhänge und wp-json bleiben außen vor. Was in ZIEL/roh schon liegt, wird nicht
noch einmal geholt. Zwischen zwei Abrufen wartet das Programm, um das Archiv nicht zu belasten.
Den Text liest es so, wie WordPress ihn auszeichnet (entry-title, entry-content, time datetime);
bei anderen Systemen bleiben Titel und Text leer, die Rohseite ist trotzdem da.
"""

import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

CDX = "https://web.archive.org/cdx/search/cdx"
AUSLASSEN = re.compile(r"/feed/?$|/comment-page-|/wp-json|/wp-content/|/attachment/|\?replytocom=|/xmlrpc|/wp-login")


def hole(url, versuche=4):
    for versuch in range(versuche):
        try:
            anfrage = urllib.request.Request(url, headers={"User-Agent": "wayback.py (persönliches Archiv)"})
            with urllib.request.urlopen(anfrage, timeout=60) as antwort:
                return antwort.read()
        except OSError as fehler:
            if versuch == versuche - 1:
                raise
            print(f"  erneut in {10 * (versuch + 1)} s ({fehler})", file=sys.stderr)
            time.sleep(10 * (versuch + 1))


def aufnahmen(praefix, auch_feeds):
    abfrage = urllib.parse.urlencode({"url": praefix + "/*", "output": "json", "filter": ["statuscode:200"],
                                      "fl": "timestamp,original,mimetype"}, doseq=True)
    zeilen = json.loads(hole(f"{CDX}?{abfrage}"))[1:]
    juengste = {}
    for zeitstempel, original, typ in zeilen:
        if typ != "text/html" and not auch_feeds:
            continue
        pfad = urllib.parse.urlsplit(original).path.rstrip("/") or "/"
        if AUSLASSEN.search(original) and not auch_feeds:
            continue
        if pfad not in juengste or zeitstempel > juengste[pfad][0]:
            juengste[pfad] = (zeitstempel, original)
    return dict(sorted(juengste.items()))


class Beitrag(HTMLParser):
    """Titel, Datum und Text eines WordPress-Beitrags."""

    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "blockquote", "br", "div", "tr"}

    def __init__(self):
        super().__init__()
        self.titel, self.datum, self.teile = [], "", []
        self.im_titel = self.im_text = 0
        self.tiefe = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        klassen = (a.get("class") or "").split()
        if self.im_text:
            self.im_text += 1
            if tag in self.BLOCK:
                self.teile.append("\n")
            if tag == "li":
                self.teile.append("- ")
        elif "entry-content" in klassen:
            self.im_text = 1
        if self.im_titel:
            self.im_titel += 1
        elif "entry-title" in klassen:
            self.im_titel = 1
        if tag == "time" and not self.datum and a.get("datetime"):
            self.datum = a["datetime"]

    def handle_endtag(self, tag):
        if self.im_text:
            self.im_text -= 1
            if tag in self.BLOCK:
                self.teile.append("\n")
        if self.im_titel:
            self.im_titel -= 1

    def handle_data(self, data):
        if self.im_titel:
            self.titel.append(data)
        if self.im_text:
            self.teile.append(data)

    def ergebnis(self):
        text = re.sub(r"[ \t]+", " ", "".join(self.teile))
        text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
        return " ".join("".join(self.titel).split()), self.datum, text


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("praefix")
    ap.add_argument("ziel", type=Path)
    ap.add_argument("--auch-feeds", action="store_true", help="auch Feeds und andere Dateitypen holen")
    ap.add_argument("--pause", type=float, default=1.5, help="Sekunden zwischen zwei Abrufen")
    args = ap.parse_args()
    praefix = re.sub(r"^https?://", "", args.praefix).rstrip("/")
    roh = args.ziel / "roh"
    roh.mkdir(parents=True, exist_ok=True)

    liste = aufnahmen(praefix, args.auch_feeds)
    print(f"{len(liste)} Seiten im Archiv unter {praefix}", flush=True)
    seiten = []
    for nr, (pfad, (zeitstempel, original)) in enumerate(liste.items(), 1):
        datei = roh / ((pfad.strip("/").replace("/", "_") or "start") + ".html")
        if not datei.exists():
            # id_ liefert die Seite ohne die Leiste und ohne umgeschriebene Links der Wayback Machine
            datei.write_bytes(hole(f"https://web.archive.org/web/{zeitstempel}id_/{original}"))
            time.sleep(args.pause)
        b = Beitrag()
        b.feed(datei.read_bytes().decode("utf-8", errors="replace"))
        titel, datum, text = b.ergebnis()
        seiten.append({"pfad": pfad, "adresse": original, "aufnahme": zeitstempel, "titel": titel,
                       "veroeffentlicht": datum, "text": text})
        print(f"{nr:>4}/{len(liste)} {pfad}  {titel[:50]}", flush=True)
    (args.ziel / "seiten.json").write_text(json.dumps(seiten, ensure_ascii=False, indent=1), encoding="utf-8")
    leer = [s["pfad"] for s in seiten if not s["text"]]
    print(f"\n{len(seiten)} Seiten nach {args.ziel / 'seiten.json'}, davon {len(leer)} ohne erkannten Text")


if __name__ == "__main__":
    main()
