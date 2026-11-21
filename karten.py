#!/usr/bin/env python3
"""Fotos physischer Zettel aufbereiten: Vorschau aus der Rohdatei holen, auf die Karte zuschneiden, verkleinern.

Aufruf:
  .venv/bin/python karten.py QUELLE ZIEL [--kante 1600]

QUELLE  Ordner mit Fotos (CR2 oder JPG), je Foto eine Karte auf grüner Unterlage
ZIEL    Ordner für die Ergebnisse:
          ZIEL/karte/<name>.jpg    auf die Karte zugeschnitten, volle Auflösung (für den Vault)
          ZIEL/klein/<name>.jpg    dasselbe, längste Kante --kante Pixel (zum Abschreiben)

Aus CR2-Dateien wird das eingebettete JPG genommen (exiftool -PreviewImage); die Rohdatei bleibt
unverändert. Zugeschnitten wird über die grüne Unterlage: Zeilen und Spalten, in denen viel Nicht-Grün
liegt, gehören zur Karte. Klappt das nicht, bleibt das Bild ungeschnitten und das Skript sagt es.
Was im Ziel schon liegt, wird übersprungen.
"""

import argparse
import io
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageChops, ImageFilter, ImageOps

GRUEN = (70, 120)       # Farbton der Unterlage im HSV-Raum von Pillow (0 bis 255)
SAETTIGUNG_AB = 50      # darunter gilt ein Bildpunkt nicht als grün (Weiß, Grau, Schatten)
ANTEIL = 0.30           # so viel Nicht-Grün braucht eine Zeile oder Spalte, um zur Karte zu zählen
RAND = 0.015            # zusätzlicher Rand um die Karte, Anteil der Bildgröße


def lade(pfad):
    if pfad.suffix.lower() == ".cr2":
        roh = subprocess.run(["exiftool", "-b", "-PreviewImage", str(pfad)], capture_output=True, check=True).stdout
        if not roh:
            raise RuntimeError("keine eingebettete Vorschau")
        bild = Image.open(io.BytesIO(roh))
    else:
        bild = Image.open(pfad)
    return ImageOps.exif_transpose(bild).convert("RGB")


def laengster_lauf(werte):
    """Anfang und Ende des längsten zusammenhängenden Laufs von True."""
    best, start = (0, 0), None
    for i, w in enumerate(list(werte) + [False]):
        if w and start is None:
            start = i
        elif not w and start is not None:
            if i - start > best[1] - best[0]:
                best = (start, i)
            start = None
    return best


def zuschnitt(bild):
    klein = bild.copy()
    klein.thumbnail((600, 600))
    h, s, _ = klein.convert("HSV").split()
    farbton = h.point(lambda x: 255 if GRUEN[0] <= x <= GRUEN[1] else 0)
    satt = s.point(lambda x: 255 if x >= SAETTIGUNG_AB else 0)
    gruen = ImageChops.multiply(farbton, satt)          # grün nur, wenn Farbton passt UND gesättigt
    maske = ImageChops.invert(gruen).filter(ImageFilter.MedianFilter(5))   # 255 = Karte
    breite, hoehe = maske.size
    daten = maske.load()
    zeilen = [sum(1 for x in range(breite) if daten[x, y]) / breite >= ANTEIL for y in range(hoehe)]
    spalten = [sum(1 for y in range(hoehe) if daten[x, y]) / hoehe >= ANTEIL for x in range(breite)]
    oben, unten = laengster_lauf(zeilen)
    links, rechts = laengster_lauf(spalten)
    if (unten - oben) < hoehe * 0.2 or (rechts - links) < breite * 0.2:
        return None
    fx, fy = bild.width / breite, bild.height / hoehe
    rx, ry = bild.width * RAND, bild.height * RAND
    return (max(0, int(links * fx - rx)), max(0, int(oben * fy - ry)),
            min(bild.width, int(rechts * fx + rx)), min(bild.height, int(unten * fy + ry)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("quelle", type=Path)
    ap.add_argument("ziel", type=Path)
    ap.add_argument("--kante", type=int, default=1600)
    args = ap.parse_args()
    voll, klein = args.ziel / "karte", args.ziel / "klein"
    voll.mkdir(parents=True, exist_ok=True)
    klein.mkdir(parents=True, exist_ok=True)
    fotos = sorted(p for p in args.quelle.iterdir() if p.suffix.lower() in (".cr2", ".jpg", ".jpeg"))
    ohne_schnitt = []
    for nr, pfad in enumerate(fotos, 1):
        ziel_voll, ziel_klein = voll / f"{pfad.stem}.jpg", klein / f"{pfad.stem}.jpg"
        if ziel_voll.exists() and ziel_klein.exists():
            continue
        try:
            bild = lade(pfad)
        except (RuntimeError, OSError, subprocess.CalledProcessError) as fehler:
            print(f"{pfad.name}: nicht lesbar ({fehler})", file=sys.stderr)
            continue
        kasten = zuschnitt(bild)
        if kasten:
            bild = bild.crop(kasten)
        else:
            ohne_schnitt.append(pfad.name)
        bild.save(ziel_voll, quality=92)
        bild.thumbnail((args.kante, args.kante))
        bild.save(ziel_klein, quality=85)
        print(f"{nr:>4}/{len(fotos)} {pfad.name} {'zugeschnitten' if kasten else 'NICHT zugeschnitten'}", flush=True)
    if ohne_schnitt:
        print(f"\nOhne Zuschnitt: {', '.join(ohne_schnitt)}")


if __name__ == "__main__":
    main()
