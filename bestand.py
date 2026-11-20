"""Bestand aller Mastodon-Exporte zählen, direkt aus den Zip-Archiven.

Aufruf:
  python3 bestand.py                       den jeweils neuesten Export jedes Kontos unter [pfade] exporte
  python3 bestand.py ARCHIV.zip [...]      nur diese Archive
  python3 bestand.py --jahre               zusätzlich die Tabelle nach Jahren je Konto

Die Exporte dürfen beliebig heißen und in Unterordnern liegen (siehe exporte.py).
Liest nur, ändert nichts, packt nichts aus.

Gezählt wird je Konto:
  Beiträge        eigene Beiträge (Create), ohne Boosts
  Zettel          eigene Beiträge mit Hashtag, die keine Antwort an andere sind
  ohne Hashtag    eigene Beiträge ohne Hashtag, die keine Antwort an andere sind
  an andere       Antworten auf Beiträge anderer Konten
  direkt          Direktnachrichten, davon ohne Erwähnung (Notizen an mich selbst)
  Threads         Ketten aus zwei und mehr eigenen Beiträgen, nicht direkt, ohne Antworten an andere
  Bilder          Anhänge mit Datei im Archiv; Anhänge ohne Datei sind meist Linkvorschauen
"""

import json
import sys
import tomllib
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from exporte import neueste_exporte

PROJEKT = Path(__file__).resolve().parent
OEFFENTLICH = "https://www.w3.org/ns/activitystreams#Public"
SPALTEN = ["Beiträge", "Zettel", "ohne Hashtag", "an andere", "direkt", "Bilder"]


def sichtbarkeit(obj):
    an, kopie = obj.get("to", []), obj.get("cc", [])
    if OEFFENTLICH in an:
        return "öffentlich"
    if OEFFENTLICH in kopie:
        return "nicht gelistet"
    if any(str(x).endswith("/followers") for x in an + kopie):
        return "nur Follower"
    return "direkt"


def neueste_archive():
    with open(PROJEKT / "config.toml", "rb") as datei:
        wurzel = tomllib.load(datei)["pfade"]["exporte"]
    return neueste_exporte(wurzel)


def zaehle(archiv):
    with zipfile.ZipFile(archiv) as z:
        dateien = set(z.namelist())
        with z.open("outbox.json") as f:
            daten = json.load(f)
        konto = ""
        if "actor.json" in dateien:
            with z.open("actor.json") as f:
                konto = json.load(f).get("preferredUsername", "")
    summe, jahre, sicht = Counter(), defaultdict(Counter), Counter()
    gespraeche = defaultdict(list)
    for eintrag in daten.get("orderedItems", []):
        if eintrag.get("type") == "Announce":
            summe["Boosts"] += 1
            continue
        obj = eintrag.get("object")
        if eintrag.get("type") != "Create" or not isinstance(obj, dict):
            continue
        ich = eintrag.get("actor", "")
        jahr = str(obj.get("published", "????"))[:4]
        z = Counter()
        z["Beiträge"] += 1
        art = sichtbarkeit(obj)
        sicht[art] += 1
        antwort = obj.get("inReplyTo")
        an_andere = bool(antwort) and not str(antwort).startswith(ich)
        hashtags = [t for t in obj.get("tag", []) if t.get("type") == "Hashtag"]
        if art == "direkt":
            z["direkt"] += 1
            if not any(t.get("type") == "Mention" for t in obj.get("tag", [])):
                z["direkt ohne Erwähnung"] += 1
        elif an_andere:
            z["an andere"] += 1
        elif hashtags:
            z["Zettel"] += 1
        else:
            z["ohne Hashtag"] += 1
        for anhang in obj.get("attachment", []) or []:
            url = str(anhang.get("url", ""))
            if not url.startswith("http") and url.lstrip("/") in dateien:
                z["Bilder"] += 1
            else:
                z["Anhänge ohne Datei"] += 1
        summe.update(z)
        jahre[jahr].update(z)
        gespraeche[obj.get("conversation") or obj.get("id")].append((ich, obj, art, an_andere))
    summe["Threads"] = sum(
        1 for teile in gespraeche.values()
        if len(teile) >= 2 and not any(art == "direkt" or andere for _, _, art, andere in teile)
    )
    summe["Gespräche direkt"] = sum(1 for teile in gespraeche.values() if any(a == "direkt" for _, _, a, _ in teile))
    return konto or archiv.parent.parent.name, summe, jahre, sicht


def main():
    argumente = [a for a in sys.argv[1:] if not a.startswith("--")]
    archive = [Path(a) for a in argumente] or neueste_archive()
    gesamt = Counter()
    zeilen = []
    for archiv in archive:
        print(f"lese {archiv} …", file=sys.stderr, flush=True)
        konto, summe, jahre, sicht = zaehle(archiv)
        gesamt.update(summe)
        zeilen.append((konto, summe, jahre, sicht, archiv))

    breite = max([len(k) for k, *_ in zeilen] + [6])
    kopf = f"{'Konto':<{breite}}" + "".join(f"{s:>14}" for s in SPALTEN + ["Threads"])
    print(kopf)
    for konto, summe, *_ in zeilen:
        print(f"{konto:<{breite}}" + "".join(f"{summe[s]:>14,}".replace(",", ".") for s in SPALTEN + ["Threads"]))
    print(f"{'Summe':<{breite}}" + "".join(f"{gesamt[s]:>14,}".replace(",", ".") for s in SPALTEN + ["Threads"]))
    print()
    for konto, summe, _, sicht, archiv in zeilen:
        print(f"{konto}: {archiv.stat().st_size / 1e9:.2f} GB, Boosts {summe['Boosts']}, "
              f"direkt ohne Erwähnung {summe['direkt ohne Erwähnung']}, Gespräche direkt {summe['Gespräche direkt']}, "
              f"Anhänge ohne Datei {summe['Anhänge ohne Datei']}; "
              + ", ".join(f"{k} {v}" for k, v in sicht.most_common()))

    if "--jahre" in sys.argv:
        for konto, _, jahre, _, _ in zeilen:
            print(f"\n{konto}\n{'Jahr':<6}" + "".join(f"{s:>14}" for s in SPALTEN))
            for jahr in sorted(jahre):
                print(f"{jahr:<6}" + "".join(f"{jahre[jahr][s]:>14}" for s in SPALTEN))


if __name__ == "__main__":
    main()
