"""Bilder der Zettel mit dem lokalen Bildmodell abschreiben oder beschreiben.

Aufruf:
  .venv/bin/python abschreiben.py --hoechstens 20     20 Bilder abschreiben und drei Beispiele zeigen
  .venv/bin/python abschreiben.py --minuten 120       zwei Stunden lang abschreiben
  .venv/bin/python abschreiben.py --stand             nur zählen, was erledigt und was offen ist

Liest DATEN/einheiten.jsonl (aus einlesen.py) und die Bilder direkt aus den Zip-Archiven.
Je Bild entsteht DATEN/abschriften/<bildname>.json mit Abschrift, Beschreibung, Modell und Dauer.
Was schon abgeschrieben ist, wird übersprungen. Ein neuer Aufruf macht dort weiter, wo der letzte aufhörte.

Reihenfolge: nach der Liste der Bereiche in config.toml ([abschrift] reihenfolge), innerhalb eines
Bereichs die ältesten zuerst. Videos und animierte Bilder werden übersprungen.

Anhalten: Datei DATEN/stopp anlegen, dann endet der Lauf nach dem laufenden Bild.
Temperatur: Erreicht eine Grafikkarte temperatur_pause, wartet das Programm zwischen zwei Bildern,
bis alle Karten unter temperatur_weiter liegen.
Läuft gerade der Tagesbetrieb des Lesesaals, startet das Programm nicht, weil beide die Grafikkarten brauchen.
"""

import argparse
import base64
import fcntl
import io
import json
import subprocess
import sys
import time
import tomllib
import zipfile
from collections import Counter
from pathlib import Path

import requests
from PIL import Image

PROJEKT = Path(__file__).resolve().parent
LESESAAL_SPERRE = Path("/mnt/daten/lesesaal/tagesbetrieb.lock")
BILDTYPEN = ("image/jpeg", "image/png", "image/webp")

ANWEISUNG = (
    "Das Bild stammt aus einem persönlichen Zettelkasten: Screenshots, Folien, Tafelbilder, Buchseiten, "
    "Fotos.\n"
    "1. abschrift: Schreibe allen lesbaren Text auf dem Bild wörtlich ab, in der Reihenfolge, in der man "
    "ihn liest. Zeilenumbrüche und Aufzählungen beibehalten, Tabellen als Zeilen mit | zwischen den Spalten. "
    "Nichts ergänzen, nichts übersetzen, nichts verbessern. Ist ein Wort nicht sicher lesbar, schreibe, was "
    "dasteht. Steht kein Text auf dem Bild, bleibt das Feld leer.\n"
    "2. beschreibung: Ein Satz auf Deutsch, was das Bild zeigt, etwa „Folie zum Cashflow“, „Tafelbild mit "
    "einem Schema zu Kommunikation“, „Foto eines Waldwegs“."
)
SCHEMA = {
    "type": "object",
    "properties": {"abschrift": {"type": "string"}, "beschreibung": {"type": "string"}},
    "required": ["abschrift", "beschreibung"],
}


def lade_konfiguration():
    with open(PROJEKT / "config.toml", "rb") as datei:
        return tomllib.load(datei)


def bilder_der_reihe_nach(daten, reihenfolge):
    """Alle Bilder aus den Einheiten, jedes nur einmal: [(bildname, archiv, datei, bereich, zeit)]."""
    bilder, gesehen = [], set()
    with open(daten / "einheiten.jsonl", encoding="utf-8") as f:
        for zeile in f:
            einheit = json.loads(zeile)
            for b in einheit["beitraege"]:
                for bild in b["bilder"]:
                    name = Path(bild["datei"]).name
                    if name in gesehen or bild["typ"] not in BILDTYPEN:
                        continue
                    gesehen.add(name)
                    bilder.append((name, einheit["archiv"], bild["datei"], einheit["bereich"], b["zeit"]))
    rang = {b: i for i, b in enumerate(reihenfolge)}
    bilder.sort(key=lambda e: (rang.get(e[3], len(rang)), e[4]))
    return bilder


def verkleinert(rohdaten, kante):
    bild = Image.open(io.BytesIO(rohdaten))
    if getattr(bild, "is_animated", False):
        return None
    bild = bild.convert("RGB")
    bild.thumbnail((kante, kante))
    puffer = io.BytesIO()
    bild.save(puffer, format="JPEG", quality=90)
    return base64.b64encode(puffer.getvalue()).decode()


def frage_bildmodell(konf, bild_b64):
    ollama = konf["ollama"]
    beginn = time.monotonic()
    antwort = requests.post(
        f"{ollama['adresse']}/api/chat",
        json={
            "model": ollama["bildmodell"],
            "messages": [{"role": "user", "content": ANWEISUNG, "images": [bild_b64]}],
            "stream": False,
            "think": False,
            "format": SCHEMA,
            "options": {"temperature": 0},
            "keep_alive": "10m",
        },
        timeout=600,
    )
    if not antwort.ok:
        raise RuntimeError(f"Ollama meldet {antwort.status_code}: {antwort.text[:300]}")
    inhalt = antwort.json()["message"].get("content", "")
    try:
        ergebnis = json.loads(inhalt)
    except json.JSONDecodeError:
        ergebnis = {"abschrift": inhalt, "beschreibung": ""}
    ergebnis["sekunden"] = round(time.monotonic() - beginn, 1)
    return ergebnis


def hoechste_temperatur():
    try:
        ausgabe = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=20).stdout
        return max(int(z) for z in ausgabe.split())
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def abkuehlen(einst):
    grad = hoechste_temperatur()
    if grad < einst["temperatur_pause"]:
        return
    print(f"  {grad} °C, Pause bis unter {einst['temperatur_weiter']} °C", flush=True)
    while hoechste_temperatur() >= einst["temperatur_weiter"]:
        time.sleep(15)


def main():
    parser = argparse.ArgumentParser(description="Bilder der Zettel abschreiben")
    parser.add_argument("--hoechstens", type=int, help="höchstens so viele Bilder")
    parser.add_argument("--minuten", type=float, help="höchstens so lange")
    parser.add_argument("--stand", action="store_true", help="nur zählen")
    args = parser.parse_args()

    konf = lade_konfiguration()
    einst = {"kante": 1500, "temperatur_pause": 83, "temperatur_weiter": 70, "reihenfolge": [],
             **konf.get("abschrift", {})}
    daten = Path(konf["pfade"]["daten"])
    ziel = daten / "abschriften"
    ziel.mkdir(parents=True, exist_ok=True)
    bilder = bilder_der_reihe_nach(daten, einst["reihenfolge"])
    fehler_pfad = daten / "abschrift-fehler.json"
    fehler = json.loads(fehler_pfad.read_text(encoding="utf-8")) if fehler_pfad.exists() else {}
    offen = [b for b in bilder if not (ziel / f"{b[0]}.json").exists()
             and fehler.get(b[0], {}).get("versuche", 0) < 2]
    if fehler:
        print(f"Bilder mit Fehlern: {len(fehler)}, davon nach zwei Versuchen ausgelassen: "
              f"{sum(1 for f in fehler.values() if f['versuche'] >= 2)} (Liste in {fehler_pfad})")

    stand = Counter(b[3] for b in offen)
    fertig = sum(1 for b in bilder if (ziel / f"{b[0]}.json").exists())
    print(f"{len(bilder)} Bilder, {fertig} abgeschrieben, {len(offen)} offen: "
          + ", ".join(f"{bereich} {n}" for bereich, n in stand.most_common()))
    if args.stand or not offen:
        return

    sperre = open(LESESAAL_SPERRE, "a") if LESESAAL_SPERRE.parent.exists() else None  # noqa: SIM115
    if sperre:
        try:
            fcntl.flock(sperre, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Der Tagesbetrieb des Lesesaals läuft, die Grafikkarten sind belegt.") from None

    stoppdatei = daten / "stopp"
    stoppdatei.unlink(missing_ok=True)
    ende = time.monotonic() + args.minuten * 60 if args.minuten else None
    erledigt, sekunden, beispiele, hintereinander = 0, 0.0, [], 0
    archive = {}
    try:
        for name, archiv, datei, bereich, _ in offen:
            if args.hoechstens and erledigt >= args.hoechstens:
                break
            if ende and time.monotonic() > ende:
                print("Zeit erreicht.")
                break
            if stoppdatei.exists():
                print("Stoppsignal erkannt.")
                stoppdatei.unlink(missing_ok=True)
                break
            abkuehlen(einst)
            if archiv not in archive:
                archive[archiv] = zipfile.ZipFile(archiv)
            bild_b64 = verkleinert(archive[archiv].read(datei), einst["kante"])
            if bild_b64 is None:
                (ziel / f"{name}.json").write_text(json.dumps({"uebersprungen": "animiert"}), encoding="utf-8")
                continue
            try:
                ergebnis = frage_bildmodell(konf, bild_b64)
            except (RuntimeError, requests.RequestException) as e1:
                # Zweiter Versuch mit kleinerem Bild; scheitert auch der, wird das Bild vermerkt und übersprungen.
                print(f"  Fehler bei {name}: {e1}; neuer Versuch mit 1000 Pixeln", flush=True)
                try:
                    ergebnis = frage_bildmodell(konf, verkleinert(archive[archiv].read(datei), 1000))
                except (RuntimeError, requests.RequestException) as e2:
                    eintrag = fehler.setdefault(name, {"versuche": 0, "datei": datei, "bereich": bereich})
                    eintrag.update(versuche=eintrag["versuche"] + 1, meldung=str(e2)[:300])
                    fehler_pfad.write_text(json.dumps(fehler, ensure_ascii=False, indent=1), encoding="utf-8")
                    hintereinander += 1
                    if hintereinander >= 5:
                        print("Fünf Fehler hintereinander, Lauf beendet. Läuft Ollama noch?")
                        break
                    continue
            hintereinander = 0
            ergebnis.update(modell=konf["ollama"]["bildmodell"], bereich=bereich, datei=datei)
            (ziel / f"{name}.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1), encoding="utf-8")
            erledigt += 1
            sekunden += ergebnis["sekunden"]
            if len(beispiele) < 3 and ergebnis["abschrift"].strip():
                beispiele.append((name, bereich, ergebnis))
            print(f"  {erledigt}: {bereich} {name} {ergebnis['sekunden']:.0f} s, "
                  f"{len(ergebnis['abschrift'])} Zeichen: {ergebnis['beschreibung'][:70]}", flush=True)
    finally:
        for z in archive.values():
            z.close()

    if erledigt:
        print(f"\n{erledigt} Bilder in {sekunden / 60:.1f} Minuten, im Mittel {sekunden / erledigt:.1f} s")
    for name, bereich, ergebnis in beispiele:
        print(f"\n=== {bereich} {name}: {ergebnis['beschreibung']}\n{ergebnis['abschrift'][:800]}")


if __name__ == "__main__":
    main()
