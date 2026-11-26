#!/usr/bin/env python3
"""Aufbau eines Facebook-Exports (HTML-Format) zeigen, ohne Inhalte preiszugeben.

Aufruf:
  .venv/bin/python facebook_struktur.py EXPORT.zip [--bereiche posts comments photos_and_videos]

Zeigt je Bereich die Dateien und für einige Beispiele den HTML-Baum mit Tags und Klassen.
Texte erscheinen nur als Länge, ausgenommen Datumsangaben und Dateipfade von Bildern,
die für das Einlesen gebraucht werden. Nachrichten (messages/) werden nie geöffnet.
"""

import argparse
import re
import zipfile
from collections import Counter

from bs4 import BeautifulSoup, NavigableString, Tag

DATUM = re.compile(r"^\s*\d{1,2}\.?\s+\w+\.?\s+\d{4}.*\d{1,2}:\d{2}|^\s*\w{3} \d{1,2}, \d{4}|\d{4}-\d{2}-\d{2}")
GEHEIM = ("messages/",)


def zeige(knoten, tiefe=0, max_tiefe=12, ausgabe=None):
    if ausgabe is None:
        ausgabe = []
    if tiefe > max_tiefe or len(ausgabe) > 120:
        return ausgabe
    for kind in knoten.children:
        if isinstance(kind, NavigableString):
            text = str(kind).strip()
            if not text or kind.__class__.__name__ in ("Comment", "Doctype"):
                continue
            zeigbar = text if DATUM.search(text) else f"[Text {len(text)} Zeichen]"
            ausgabe.append("  " * tiefe + zeigbar)
        elif isinstance(kind, Tag):
            if kind.name in ("script", "style", "head"):
                continue
            merkmale = ""
            if kind.get("class"):
                merkmale += "." + ".".join(kind["class"])
            for attr in ("src", "href"):
                wert = kind.get(attr)
                if wert:
                    wert = wert if not wert.startswith("http") else re.sub(r"(https?://[^/]+).*", r"\1/…", wert)
                    merkmale += f" {attr}={wert[:70]}"
            ausgabe.append("  " * tiefe + f"<{kind.name}{merkmale}>")
            zeige(kind, tiefe + 1, max_tiefe, ausgabe)
    return ausgabe


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("zip")
    ap.add_argument("--bereiche", nargs="+", default=["posts", "comments", "photos_and_videos"])
    ap.add_argument("--beispiele", type=int, default=2, help="HTML-Bäume je Bereich")
    args = ap.parse_args()

    with zipfile.ZipFile(args.zip) as z:
        namen = [n for n in z.namelist() if not n.startswith(GEHEIM)]
        for bereich in args.bereiche:
            html = sorted(n for n in namen if n.startswith(bereich + "/") and n.endswith(".html"))
            bilder = [n for n in namen if n.startswith(bereich + "/") and not n.endswith((".html", "/"))]
            print(f"\n######## {bereich}: {len(html)} HTML-Dateien, {len(bilder)} andere Dateien")
            print("  Dateiarten:", dict(Counter(n.rsplit(".", 1)[-1].lower() for n in bilder).most_common(6)))
            for n in html[:40]:
                print(f"  {n}  ({z.getinfo(n).file_size} Bytes)")
            if len(html) > 40:
                print(f"  … und {len(html) - 40} weitere")
            # große Dateien zuerst, dort steckt der Inhalt
            for n in sorted(html, key=lambda n: -z.getinfo(n).file_size)[:args.beispiele]:
                seite = BeautifulSoup(z.read(n), "html.parser")
                koerper = seite.body or seite
                print(f"\n==== Aufbau von {n}")
                zeilen = zeige(koerper)
                print("\n".join(zeilen[:120]))
                klassen = Counter(c for t in koerper.find_all(True) for c in (t.get("class") or []))
                print("  häufigste Klassen:", klassen.most_common(12))


if __name__ == "__main__":
    main()
