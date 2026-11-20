#!/usr/bin/env python3
"""Prüft, ob ältere Mastodon-Exporte vollständig in neueren enthalten sind.

Aufruf:
    python3 exporte_pruefen.py PFAD [PFAD ...] [--liste]

PFAD kann ein Ordner (wird rekursiv durchsucht) oder eine einzelne Zip-Datei
sein. Jede Zip mit outbox.json und actor.json gilt als Mastodon-Export. Die
Exporte werden nach Konto gruppiert und nach dem jüngsten Beitrag sortiert.
Für jeden älteren Export wird gezeigt, welche Beiträge, Boosts und Mediendateien
im neuesten Export desselben Kontos fehlen. Gelöscht wird nichts.

--liste gibt alle fehlenden Beiträge mit Datum und Adresse aus, nicht nur fünf.
"""

import argparse
import html
import json
import re
import sys
import zipfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse


def finde_zips(pfade):
    for p in pfade:
        p = Path(p)
        if p.is_file() and p.suffix.lower() == ".zip":
            yield p
        elif p.is_dir():
            yield from sorted(p.rglob("*.zip"))


def textform(inhalt):
    """Vergleichbare Form eines Beitragstexts: ohne HTML, Links, Leerraum, Groß/klein."""
    t = re.sub(r"<[^>]+>", " ", inhalt or "")
    t = html.unescape(t)
    t = re.sub(r"https?://\S+", "", t)
    t = re.sub(r"\W+", " ", t).strip().lower()
    return t


def lies_export(pfad):
    try:
        z = zipfile.ZipFile(pfad)
    except zipfile.BadZipFile:
        return None
    with z:
        namen = set(z.namelist())
        if "outbox.json" not in namen or "actor.json" not in namen:
            return None
        actor = json.loads(z.read("actor.json"))
        outbox = json.loads(z.read("outbox.json"))
        medien = {n for n in namen if n.startswith("media_attachments/") and not n.endswith("/")}

    konto_id = actor.get("id", "")
    host = urlparse(konto_id).hostname or "?"
    konto = f"{actor.get('preferredUsername', '?')}@{host}"

    beitraege, boosts = {}, {}
    juengster = ""
    for a in outbox.get("orderedItems", []):
        typ = a.get("type")
        obj = a.get("object")
        zeit = a.get("published", "")
        if typ == "Create" and isinstance(obj, dict):
            zeit = obj.get("published", zeit)
            beitraege[obj.get("id", a.get("id"))] = (zeit, obj.get("url") or obj.get("id", ""),
                                                     textform(obj.get("content", "")))
        elif typ == "Announce":
            ziel = obj if isinstance(obj, str) else (obj or {}).get("id", "")
            boosts[a.get("id")] = (zeit, ziel)
        if zeit > juengster:
            juengster = zeit

    return {
        "pfad": pfad,
        "konto": konto,
        "juengster": juengster,
        "beitraege": beitraege,
        "boosts": boosts,
        "medien": medien,
        "groesse": pfad.stat().st_size,
    }


def mb(n):
    return f"{n / 1e6:,.0f} MB".replace(",", ".")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pfade", nargs="+")
    ap.add_argument("--liste", action="store_true", help="alle fehlenden Beiträge ausgeben")
    args = ap.parse_args()

    konten = defaultdict(list)
    for z in finde_zips(args.pfade):
        e = lies_export(z)
        if e is None:
            print(f"übersprungen (kein Mastodon-Export): {z}", file=sys.stderr)
            continue
        konten[e["konto"]].append(e)

    if not konten:
        print("Keine Mastodon-Exporte gefunden.")
        return 1

    for konto in sorted(konten):
        exporte = sorted(konten[konto], key=lambda e: (e["juengster"], e["pfad"].stat().st_mtime))
        neu = exporte[-1]
        print(f"\n=== {konto}")
        for e in exporte:
            marke = "  neuester" if e is neu else ""
            print(f"  {e['juengster'][:10]}  {len(e['beitraege']):6d} Beiträge  {len(e['boosts']):6d} Boosts  "
                  f"{len(e['medien']):6d} Medien  {mb(e['groesse']):>9}  {e['pfad']}{marke}")

        neue_texte = {v[2] for v in neu["beitraege"].values() if v[2]}
        for e in exporte[:-1]:
            fehlt_alle = sorted(v for k, v in e["beitraege"].items() if k not in neu["beitraege"])
            neu_entworfen = [v for v in fehlt_alle if v[2] and v[2] in neue_texte]
            fehlt_b = [v for v in fehlt_alle if not (v[2] and v[2] in neue_texte)]
            fehlt_o = [k for k in e["boosts"] if k not in neu["boosts"]]
            fehlt_m = e["medien"] - neu["medien"]
            print(f"\n  {e['pfad'].name} gegen {neu['pfad'].name}:")
            if not (fehlt_b or fehlt_m):
                zusatz = []
                if neu_entworfen:
                    zusatz.append(f"{len(neu_entworfen)} Beiträge mit gleichem Text unter neuer Adresse")
                if fehlt_o:
                    zusatz.append(f"{len(fehlt_o)} zurückgenommene Boosts")
                print("    vollständig enthalten, kann weg" + (f" ({', '.join(zusatz)})" if zusatz else ""))
                continue
            print(f"    nur hier: {len(fehlt_b)} Beiträge, {len(fehlt_m)} Mediendateien")
            print(f"    außerdem: {len(neu_entworfen)} Beiträge mit gleichem Text unter neuer Adresse, "
                  f"{len(fehlt_o)} zurückgenommene Boosts")
            if fehlt_b:
                print(f"    Zeitraum: {fehlt_b[0][0][:10]} bis {fehlt_b[-1][0][:10]}")
                for zeit, url, text in (fehlt_b if args.liste else fehlt_b[:5]):
                    print(f"      {zeit[:10]}  {url}  {text[:60]}")
                if not args.liste and len(fehlt_b) > 5:
                    print(f"      … {len(fehlt_b) - 5} weitere (mit --liste alle)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
