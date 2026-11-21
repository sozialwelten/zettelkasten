"""Fertig angereicherte Einheiten als Notizen in den Vault schreiben.

Aufruf:
  .venv/bin/python schreiben.py --probe 3         je Bereich 3 Notizen nach DATEN/probe-vault/, der Vault bleibt unberührt
  .venv/bin/python schreiben.py                   alle fertigen Einheiten in den Vault schreiben
  .venv/bin/python schreiben.py --stand           nur zählen
  .venv/bin/python schreiben.py --probe 3 --roh --plattform twitter
                                                  Probe ohne Anreicherung, Titel aus den ersten Wörtern;
                                                  zeigt den Aufbau, bevor das Modell gelaufen ist

Fertig ist eine Einheit, wenn sie angereichert ist (anreichern.py). Geschrieben wird jede Einheit genau einmal.
Welche Datei zu welcher Einheit gehört, steht in DATEN/geschrieben.json. Eine geschriebene Notiz rührt das
Programm nie wieder an, auch wenn sie inzwischen von Hand geändert ist. Fehlt sie, weil sie gelöscht wurde,
wird sie auch nicht neu angelegt.

Aufbau einer Notiz:
  Kopfzeile: Bereich, Konto, Datum oder Zeitraum, Link zum Original; bei Gesprächen „Mit:“
  meine Beiträge, bei mehreren mit Datum und Uhrzeit; darunter je Bild das Bild und die Abschrift in einem
  zugeklappten Kasten „Abschrift“ (Obsidian-Callout; die Suche findet den Text trotzdem)
  die Lesefassung, abgesetzt durch eine Linie und mit der Zeile „Lesefassung“
  die Hashtags: zuerst meine, dann die vom Modell ergänzten; Doppel, die sich nur in Groß- und
  Kleinschreibung unterscheiden, nur einmal

Dateiname: der Titel aus der Anreicherung. Gibt es ihn im Bereich schon, kommt das Datum dazu.
Das Änderungsdatum jeder Notiz wird auf das Datum des ersten Beitrags gesetzt, damit Obsidian auch
chronologisch sortieren kann. Bilder kommen einmal nach Zubehör/ im Vault.
"""

import argparse
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from abschreiben import lade_konfiguration
from anreichern import kopfzeilen, lies_abschriften, ohne_kopf, trenne_woerter
from einlesen import ANHAENGE

VERBOTEN = re.compile(r'[\\/:*?"<>|#^\[\]]')


def dateiname(titel):
    name = " ".join(VERBOTEN.sub(" ", titel).split()).strip(" .")
    return name[:100] or "Ohne Titel"


def roh_titel(einheit):
    """Titel aus den ersten Wörtern, für Proben ohne Anreicherung."""
    text = next((b["text"] for b in einheit["beitraege"] if b["text"]), "") or einheit["art"]
    worte = re.sub(r"https?://\S+|@\S+", "", text.split("\n", 1)[0])
    worte = re.sub(r"[^\w\säöüÄÖÜß-]", "", worte).split()
    return " ".join(worte[:8])[:60].strip() or einheit["art"]


def als_notiz(einheit, anreicherung, abschriften, kopf):
    bereich = anreicherung.get("bereich", einheit["bereich"])
    beginn, ende = datetime.fromisoformat(einheit["von"]), datetime.fromisoformat(einheit["bis"])
    zeitraum = f"{beginn:%d.%m.%Y}" + (f" bis {ende:%d.%m.%Y}" if ende.date() != beginn.date() else "")
    plattform = {"twitter": " (Twitter)", "karte": " (Karteikarte)"}.get(einheit.get("plattform"), "")
    konto = f"@{einheit['konto']}{plattform}"
    if einheit.get("plattform") == "karte":
        zeitraum = "undatiert" if einheit.get("datum_geschaetzt") else zeitraum
    kopf = [bereich, konto, zeitraum]
    if einheit.get("karte"):
        kopf.insert(1, f"Karte {einheit['karte']}")
    if einheit["beitraege"][0]["url"]:
        kopf.append(f"[Original]({einheit['beitraege'][0]['url']})")
    zeilen = [" · ".join(kopf)]
    if einheit.get("herkunft"):
        zeilen.append(einheit["herkunft"])
    if einheit.get("getwittert"):
        tage = list(dict.fromkeys(f"{datetime.fromisoformat(z):%d.%m.%Y}" for z in einheit["getwittert"]))
        zeilen.append("Getwittert auf @schedulae: " + ", ".join(tage))
    if einheit.get("gruppenname"):
        zeilen.append(f"Gruppe: {einheit['gruppenname']}")
    if einheit["partner"]:
        zeilen.append("Mit: " + ", ".join(f"[{p['name']}]({p['href']})" if p["href"] else p["name"]
                                          for p in einheit["partner"]))
    if einheit.get("kontext"):
        zeilen += ["", "Kurz davor geteilt:"]
        for k in einheit["kontext"]:
            zeilen += [f"> **@{k['autor']}**: " + k["text"].replace("\n", "\n> ")]
    mehrere = len(einheit["beitraege"]) > 1
    for b in einheit["beitraege"]:
        zeilen.append("")
        if mehrere or b.get("absender"):
            zeilen += [f"**{datetime.fromisoformat(b['zeit']):%d.%m.%Y %H:%M}**"
                       + (f" · {b['absender']}" if b.get("absender") else ""), ""]
        if b["inhaltswarnung"]:
            zeilen += [f"Inhaltswarnung: {b['inhaltswarnung']}", ""]
        if b["text"]:
            zeilen.append(b["text"])
        for bild in b["bilder"]:
            name = Path(bild["datei"]).name
            daten = abschriften.get(name, {})
            zeilen += ["", f"![[{name}]]"]
            if bild["beschreibung"]:
                zeilen.append(f"Bildbeschreibung: {bild['beschreibung']}")
            text = ohne_kopf(daten.get("abschrift", ""), kopf)
            if text:
                zeilen += ["", "> [!quote]- Abschrift"] + [f"> {z}" for z in text.splitlines()]
            elif daten.get("beschreibung") and not bild["beschreibung"]:
                zeilen.append(f"Bild: {daten['beschreibung']}")
    if anreicherung.get("lesefassung"):
        zeilen += ["", "---", "", "**Lesefassung**", "", anreicherung["lesefassung"]]
    hashtags, gesehen = [], set()
    for h in einheit["hashtags"] + anreicherung.get("hashtags_neu", []):
        h = re.sub(r"\s+", "", h)
        if h and h.casefold() not in gesehen:
            gesehen.add(h.casefold())
            hashtags.append(h)
    if hashtags:
        zeilen += ["", " ".join("#" + re.sub(r"\s+", "", h) for h in hashtags)]
    return bereich, "\n".join(zeilen) + "\n"


def main():
    parser = argparse.ArgumentParser(description="Angereicherte Einheiten in den Vault schreiben")
    parser.add_argument("--probe", type=int, metavar="N", help="je Bereich N Notizen in einen Probe-Vault")
    parser.add_argument("--stand", action="store_true", help="nur zählen")
    parser.add_argument("--roh", action="store_true", help="mit --probe: auch Einheiten ohne Anreicherung")
    parser.add_argument("--plattform", choices=["mastodon", "twitter", "karte"], help="nur Einheiten dieser Plattform")
    args = parser.parse_args()
    if args.roh and not args.probe:
        raise SystemExit("--roh geht nur zusammen mit --probe.")

    konf = lade_konfiguration()
    daten = Path(konf["pfade"]["daten"])
    vault = daten / "probe-vault" if args.probe else Path(konf["pfade"]["vault"])
    register_pfad = daten / "geschrieben.json"
    register = {} if args.probe else (json.loads(register_pfad.read_text(encoding="utf-8"))
                                      if register_pfad.exists() else {})
    anreicherungen = {p.name.removesuffix(".json"): p for p in (daten / "anreicherung").glob("*.json")}
    with open(daten / "einheiten.jsonl", encoding="utf-8") as f:
        einheiten = [json.loads(z) for z in f]
    if args.plattform:
        einheiten = [e for e in einheiten if e.get("plattform", "mastodon") == args.plattform]
    fertig = [e for e in einheiten if (args.roh or e["kennung"] in anreicherungen) and e["kennung"] not in register]
    print(f"{len(einheiten)} Einheiten: {len(register)} geschrieben, {len(fertig)} fertig zum Schreiben")
    if args.stand or not fertig:
        return

    abschriften = lies_abschriften(daten / "abschriften")
    kopf = kopfzeilen(abschriften, konf["anreicherung"].get("kopfzeile_ab", 25))
    je_bereich = Counter()
    archive = {}
    (vault / ANHAENGE).mkdir(parents=True, exist_ok=True)
    geschrieben = defaultdict(int)
    for einheit in sorted(fertig, key=lambda e: e["von"]):
        if einheit["kennung"] in anreicherungen:
            anreicherung = json.loads(anreicherungen[einheit["kennung"]].read_text(encoding="utf-8"))
        else:
            anreicherung = {"titel": einheit.get("titel") or roh_titel(einheit), "hashtags_neu": [], "lesefassung": ""}
        bereich, inhalt = als_notiz(einheit, anreicherung, abschriften, kopf)
        if args.probe and je_bereich[bereich] >= args.probe:
            continue
        ordner = vault / bereich
        ordner.mkdir(parents=True, exist_ok=True)
        eigen = "\n".join(b["text"] for b in einheit["beitraege"] if b["text"])
        name = dateiname(trenne_woerter(anreicherung["titel"], einheit, eigen))
        pfad = ordner / f"{name}.md"
        if pfad.exists():
            pfad = ordner / f"{name} ({datetime.fromisoformat(einheit['von']):%d.%m.%Y}).md"
        nr = 2
        while pfad.exists():
            pfad = ordner / f"{name} ({datetime.fromisoformat(einheit['von']):%d.%m.%Y}) {nr}.md"
            nr += 1
        for b in einheit["beitraege"]:
            for bild in b["bilder"]:
                ziel = vault / ANHAENGE / Path(bild["datei"]).name
                if not ziel.exists():
                    if Path(einheit["archiv"]).is_dir():
                        ziel.write_bytes((Path(einheit["archiv"]) / bild["datei"]).read_bytes())
                        continue
                    if einheit["archiv"] not in archive:
                        archive[einheit["archiv"]] = zipfile.ZipFile(einheit["archiv"])
                    ziel.write_bytes(archive[einheit["archiv"]].read(bild["datei"]))
        pfad.write_text(inhalt, encoding="utf-8")
        zeit = datetime.fromisoformat(einheit["von"]).timestamp()
        os.utime(pfad, (zeit, zeit))
        je_bereich[bereich] += 1
        geschrieben[bereich] += 1
        if not args.probe:
            register[einheit["kennung"]] = str(pfad.relative_to(vault))
    for z in archive.values():
        z.close()
    if not args.probe:
        register_pfad.write_text(json.dumps(register, ensure_ascii=False, indent=0), encoding="utf-8")
    print(f"{sum(geschrieben.values())} Notizen nach {vault}: "
          + ", ".join(f"{b} {n}" for b, n in sorted(geschrieben.items())))


if __name__ == "__main__":
    main()
