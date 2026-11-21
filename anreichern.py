"""Einheiten mit dem Sprachmodell anreichern: Titel, Bereich, zusätzliche Hashtags und Lesefassung.

Aufruf:
  .venv/bin/python anreichern.py --hoechstens 10      10 Einheiten anreichern und alle Ergebnisse zeigen
  .venv/bin/python anreichern.py --minuten 120        zwei Stunden lang anreichern
  .venv/bin/python anreichern.py --stand              nur zählen, was erledigt, bereit und wartend ist
  .venv/bin/python anreichern.py --bereich offen --hoechstens 10
                                                     nur Einheiten aus diesem Bereich

Liest DATEN/einheiten.jsonl und die Abschriften aus DATEN/abschriften/. Eine Einheit ist bereit, wenn alle
ihre Bilder abgeschrieben sind. Je Einheit entsteht DATEN/anreicherung/<kennung>.json. Was schon angereichert
ist, wird übersprungen.

Was das Modell liefert und was der Code daraus macht:
  titel        kurz und begrifflich; wird zum Dateinamen der Notiz
  bereich      nur bei Einheiten mit Bereich „offen“, aus der Liste in config.toml [anreicherung] bereiche
  hashtags     höchstens drei zusätzliche Begriffe; der Code behält nur die, die in meinem eigenen Text
               vorkommen, bei Einheiten mit weniger als zehn eigenen Wörtern auch aus den Abschriften
  lesefassung  nur bei Zetteln und Notizen an mich selbst; leer, wenn der Zettel schon gut verständlich ist.
               Keine, wenn der Zettel weniger als 15 eigene Wörter ohne Links hat und kein Bild mit Text.
               Enthält sie Zahlen, die im Zettel nicht vorkommen, verwirft der Code sie.

Zeilen, die in sehr vielen Abschriften wörtlich gleich vorkommen (Folienköpfe, Logos), bekommt das Modell nicht
zu sehen. Die Grenze steht in config.toml als [anreicherung] kopfzeile_ab.

Anhalten, Temperatur und Sperre gegen den Lesesaal wie bei abschreiben.py.
"""

import argparse
import fcntl
import json
import re
import time
from collections import Counter
from pathlib import Path

import requests

from abschreiben import BILDTYPEN, LESESAAL_SPERRE, abkuehlen, lade_konfiguration

WOERTER_HOECHSTENS = 2500        # mehr Text geht nicht ins Modell; der Rest wird abgeschnitten
LESEFASSUNG_BIS_WOERTER = 1200   # längere Einheiten bekommen keine Lesefassung
LESEFASSUNG_AB_WOERTER = 15      # kürzere Zettel ohne Bild mit Text bekommen keine Lesefassung
HASHTAGS_HOECHSTENS = 3          # so viele Hashtags ergänzt das Modell höchstens
EIGENE_HASHTAGS_AB_WOERTER = 10  # ab so vielen eigenen Wörtern kommen neue Hashtags nur aus dem eigenen Text


def vergleichsform(text):
    text = text.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue").replace("ß", "ss")
    return re.sub(r"[^a-z0-9]", "", text)


def lies_abschriften(ordner):
    abschriften = {}
    for pfad in ordner.glob("*.json"):
        daten = json.loads(pfad.read_text(encoding="utf-8"))
        if "uebersprungen" not in daten:
            abschriften[pfad.name.removesuffix(".json")] = daten
    return abschriften


def kopfzeilen(abschriften, ab):
    """Zeilen, die in mindestens `ab` verschiedenen Abschriften wörtlich vorkommen."""
    zaehler = Counter()
    for daten in abschriften.values():
        zaehler.update({z.strip() for z in daten.get("abschrift", "").splitlines() if z.strip()})
    return {z for z, n in zaehler.items() if n >= ab}


def ohne_kopf(abschrift, kopf):
    return "\n".join(z for z in abschrift.splitlines() if z.strip() and z.strip() not in kopf)


def eigener_text(einheit):
    """Meine eigenen Worte der Einheit, ohne Links."""
    text = "\n".join(b["text"] for b in einheit["beitraege"] if b["text"])
    return re.sub(r"\(?https?://\S+", " ", text)


def hat_bildtext(einheit, abschriften, kopf):
    return any(ohne_kopf(abschriften.get(Path(bild["datei"]).name, {}).get("abschrift", ""), kopf)
               for b in einheit["beitraege"] for bild in b["bilder"])


def quelltext(einheit, abschriften, kopf):
    """Alles, was zur Einheit gehört, als Text für das Modell und für die Prüfungen."""
    teile = []
    for k in einheit.get("kontext", []):
        teile.append(f"[Kurz davor geteilt, von @{k['autor']}: {k['text']}]")
    for b in einheit["beitraege"]:
        if b["text"]:
            teile.append(f"{b['absender']}: {b['text']}" if b.get("absender") else b["text"])
        for bild in b["bilder"]:
            name = Path(bild["datei"]).name
            daten = abschriften.get(name, {})
            text = ohne_kopf(daten.get("abschrift", ""), kopf)
            if bild["beschreibung"]:
                teile.append(f"[Bildbeschreibung: {bild['beschreibung']}]")
            if text:
                teile.append(f"[Abschrift eines Bildes]\n{text}")
            elif daten.get("beschreibung"):
                teile.append(f"[Bild: {daten['beschreibung']}]")
    worte = "\n\n".join(teile).split(" ")
    return " ".join(worte[:WOERTER_HOECHSTENS]), len(worte)


def anweisung(einheit, text, einst, mit_lesefassung):
    arten = {
        "zettel": "einen Zettel aus meinem Zettelkasten",
        "notiz": "eine Notiz, die ich mir selbst geschrieben habe",
        "beitrag": "einen öffentlichen Beitrag von mir in sozialen Medien",
        "antwort": "meine Antworten in einem Gespräch mit anderen",
        "direkt": "meine Nachrichten in einem privaten Gespräch",
        "geteilt": "Beiträge anderer, die ich geteilt habe",
    }
    if einheit["art"] == "direkt" and any(b.get("absender") for b in einheit["beitraege"]):
        arten["direkt"] = f"ein privates Gespräch mit beiden Seiten; meine Nachrichten stehen unter @{einheit['konto']}"
    zeilen = [
        f"Du bekommst {arten[einheit['art']]}, vom Konto @{einheit['konto']}, {einheit['von'][:10]}.",
        f"Vorhandene Hashtags: {', '.join(einheit['hashtags']) or 'keine'}",
        "",
        text,
        "",
        "---",
        "Aufgaben:",
        "titel: Ein kurzer, begrifflicher Titel auf Deutsch, höchstens acht Wörter, so dass ich in einer langen "
        "Liste erkenne, worum es geht. Fachbegriffe aus dem Text bevorzugen. Kein Datum, keine Satzzeichen am Ende.",
        "hashtags: Höchstens drei weitere Schlagworte, die genau so in meinem Text vorkommen und das Thema "
        "tragen, die wichtigsten zuerst. Keine allgemeinen Wörter wie Vorstellungen oder Merkmal. Ohne Raute, "
        "mehrere Wörter zusammengeschrieben wie ÖffentlicherSektor. Keine, die schon vorhanden sind. Lieber "
        "keines als ein beliebiges.",
    ]
    if einheit["bereich"] == "offen":
        zeilen.append("bereich: Wähle genau einen Bereich aus dieser Liste. Im Zweifel „ungeordnet“.")
        zeilen += [f"- {name}: {beschreibung}" for name, beschreibung in einst["bereiche"].items()]
    if mit_lesefassung:
        zeilen.append(
            "lesefassung: Ich habe wegen der Zeichengrenze oft stark verkürzt. Formuliere den Zettel in ganzen, "
            "verständlichen Sätzen aus, in meiner Perspektive. Verkürzungen auflösen, soweit sie sich aus dem Zettel "
            "selbst ergeben. Keine Fakten, Zahlen, Namen, Beispiele oder Erklärungen ergänzen, die nicht im Zettel "
            "stehen. Inhalte aus den Abschriften nur so weit einbeziehen, wie der Zettel sie braucht. Abkürzungen nur "
            "ausschreiben, wenn die Langform im Zettel oder in einer Abschrift steht. Keine Namen von Personen, "
            "Organisationen oder Orten ergänzen, die dort nicht stehen. Zeilen, die nur die Quelle oder die "
            "Veranstaltung nennen, nicht als Inhalt wiedergeben. Lass das Feld leer, wenn der Zettel schon gut "
            "verständlich ist oder nur aus Links besteht."
        )
    return "\n".join(zeilen)


def schema(einheit, einst, mit_lesefassung):
    eigenschaften = {"titel": {"type": "string"}, "hashtags": {"type": "array", "items": {"type": "string"}}}
    if einheit["bereich"] == "offen":
        eigenschaften["bereich"] = {"type": "string", "enum": list(einst["bereiche"])}
    if mit_lesefassung:
        eigenschaften["lesefassung"] = {"type": "string"}
    return {"type": "object", "properties": eigenschaften, "required": list(eigenschaften)}


def frage_modell(konf, inhalt, form):
    ollama = konf["ollama"]
    beginn = time.monotonic()
    antwort = requests.post(
        f"{ollama['adresse']}/api/chat",
        json={"model": ollama["modell"], "messages": [{"role": "user", "content": inhalt}], "stream": False,
              "think": False, "format": form, "options": {"temperature": 0.2}, "keep_alive": "10m"},
        timeout=900,
    )
    antwort.raise_for_status()
    daten = antwort.json()
    try:
        ergebnis = json.loads(daten["message"].get("content", ""))
    except json.JSONDecodeError:
        ergebnis = {}
    return ergebnis, round(time.monotonic() - beginn, 1)


def trenne_woerter(titel, einheit=None, text=""):
    """Zusammengeschriebene Wörter im Titel trennen: ÖffentlicherSektor → Öffentlicher Sektor.

    Ein Wort bleibt, wie es ist, wenn es genau so im Text steht und dort kein Hashtag ist,
    etwa YouTube oder PeerTube.
    """
    schutz = text
    for h in (einheit or {}).get("hashtags", []):
        schutz = re.sub(rf"(?<!\w){re.escape(h)}(?!\w)", " ", schutz)

    def teile(treffer):
        wort = treffer.group(0)
        if wort in schutz.split() or re.search(rf"(?<!\w){re.escape(wort)}(?!\w)", schutz):
            return wort
        return re.sub(r"(?<=[a-zäöüß]{2})(?=[A-ZÄÖÜ][a-zäöüß])", " ", wort)

    return re.sub(r"\S+", teile, titel)


def sauberer_hashtag(h):
    return re.sub(r"[^\wÄÖÜäöüß]", "", str(h).lstrip("#").replace(" ", ""))


def pruefe(einheit, roh, text, einst):
    """Ergebnis des Modells prüfen und bereinigen. Gibt (ergebnis, gründe) zurück."""
    gruende = []
    quelle = vergleichsform(text + " " + " ".join(einheit["hashtags"]))
    eigen = eigener_text(einheit)
    tag_quelle = vergleichsform(eigen) if len(eigen.split()) >= EIGENE_HASHTAGS_AB_WOERTER else quelle
    vorhanden = {vergleichsform(h) for h in einheit["hashtags"]}
    neue = []
    for h in roh.get("hashtags", []):
        h = sauberer_hashtag(h)
        v = vergleichsform(h)
        if not h or v in vorhanden or v in {vergleichsform(x) for x in neue}:
            continue
        if v not in tag_quelle:
            gruende.append(f"Hashtag nicht im eigenen Text: {h}" if v in quelle else f"Hashtag nicht im Text: {h}")
            continue
        if len(neue) >= HASHTAGS_HOECHSTENS:
            gruende.append(f"Hashtag über der Höchstzahl: {h}")
            continue
        neue.append(h)
    titel = " ".join(str(roh.get("titel", "")).replace("/", " ").split()).strip(" .:;")
    titel = trenne_woerter(titel, einheit, text) or einheit["art"]
    if einheit.get("plattform") == "karte":
        titel = einheit["titel"]  # Karteikarten tragen ihren Titel selbst
    ergebnis = {"titel": titel[:90], "hashtags_neu": neue}
    if einheit["bereich"] == "offen":
        bereich = roh.get("bereich", "ungeordnet")
        ergebnis["bereich"] = bereich if bereich in einst["bereiche"] else "ungeordnet"
    lesefassung = str(roh.get("lesefassung", "")).strip()
    if lesefassung:
        fremde = [z for z in re.findall(r"\d+(?:[.,]\d+)*", lesefassung) if vergleichsform(z) not in quelle]
        if fremde:
            gruende.append(f"Lesefassung verworfen, Zahlen nicht im Zettel: {', '.join(fremde[:5])}")
            lesefassung = ""
    ergebnis["lesefassung"] = lesefassung
    return ergebnis, gruende


def main():
    parser = argparse.ArgumentParser(description="Einheiten mit dem Sprachmodell anreichern")
    parser.add_argument("--hoechstens", type=int, help="höchstens so viele Einheiten")
    parser.add_argument("--minuten", type=float, help="höchstens so lange")
    parser.add_argument("--stand", action="store_true", help="nur zählen")
    parser.add_argument("--bereich", action="append", metavar="NAME",
                        help="nur Einheiten aus diesem Bereich, etwa offen oder Gespräch; mehrfach möglich")
    args = parser.parse_args()

    konf = lade_konfiguration()
    einst = {"kopfzeile_ab": 25, "temperatur_pause": 83, "temperatur_weiter": 70,
             "reihenfolge": konf.get("abschrift", {}).get("reihenfolge", []), **konf["anreicherung"]}
    daten = Path(konf["pfade"]["daten"])
    ziel = daten / "anreicherung"
    ziel.mkdir(parents=True, exist_ok=True)
    abschriften = lies_abschriften(daten / "abschriften")
    abgeschrieben = {p.name.removesuffix(".json") for p in (daten / "abschriften").glob("*.json")}
    kopf = kopfzeilen(abschriften, einst["kopfzeile_ab"])

    with open(daten / "einheiten.jsonl", encoding="utf-8") as f:
        einheiten = [json.loads(z) for z in f]
    rang = {b: i for i, b in enumerate(einst["reihenfolge"])}
    einheiten.sort(key=lambda e: (rang.get(e["bereich"], len(rang)), e["von"]))
    erledigt = {p.name.removesuffix(".json") for p in ziel.glob("*.json")}
    bereit, wartet = [], 0
    for e in einheiten:
        if e["kennung"] in erledigt:
            continue
        namen = [Path(bild["datei"]).name for b in e["beitraege"] for bild in b["bilder"] if bild["typ"] in BILDTYPEN]
        if all(n in abgeschrieben for n in namen):
            bereit.append(e)
        else:
            wartet += 1
    if args.bereich:
        bereit = [e for e in bereit if e["bereich"] in args.bereich]
        print(f"Nur Bereich {', '.join(args.bereich)}: {len(bereit)} bereit")
    print(f"{len(einheiten)} Einheiten: {len(erledigt)} angereichert, {len(bereit)} bereit, "
          f"{wartet} warten auf Abschriften. Kopfzeilen, die ausgeblendet werden: {len(kopf)}")
    if args.stand or not bereit:
        return

    sperre = open(LESESAAL_SPERRE, "a")  # noqa: SIM115
    try:
        fcntl.flock(sperre, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("Der Tagesbetrieb des Lesesaals oder die Abschrift läuft, die Grafikkarten sind belegt.") from None

    stoppdatei = daten / "stopp"
    stoppdatei.unlink(missing_ok=True)
    ende = time.monotonic() + args.minuten * 60 if args.minuten else None
    anzahl, sekunden, gezeigt = 0, 0.0, []
    for einheit in bereit:
        if args.hoechstens and anzahl >= args.hoechstens:
            break
        if ende and time.monotonic() > ende:
            print("Zeit erreicht.")
            break
        if stoppdatei.exists():
            print("Stoppsignal erkannt.")
            stoppdatei.unlink(missing_ok=True)
            break
        if einheit["art"] == "geteilt":
            ergebnis = {"titel": einheit.get("titel") or "Geteilt", "hashtags_neu": [], "lesefassung": "",
                        "sekunden": 0, "gruende": [], "modell": ""}
            (ziel / f"{einheit['kennung']}.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1),
                                                             encoding="utf-8")
            anzahl += 1
            print(f"  {anzahl}: {einheit['bereich']} ohne Modell „{ergebnis['titel']}“", flush=True)
            continue
        abkuehlen(einst)
        text, worte = quelltext(einheit, abschriften, kopf)
        mit_lesefassung = (einheit["art"] in ("zettel", "notiz") and worte <= LESEFASSUNG_BIS_WOERTER
                           and (len(eigener_text(einheit).split()) >= LESEFASSUNG_AB_WOERTER
                                or hat_bildtext(einheit, abschriften, kopf)))
        roh, dauer = frage_modell(konf, anweisung(einheit, text, einst, mit_lesefassung),
                                  schema(einheit, einst, mit_lesefassung))
        ergebnis, gruende = pruefe(einheit, roh, text, einst)
        ergebnis.update(sekunden=dauer, gruende=gruende, modell=konf["ollama"]["modell"])
        (ziel / f"{einheit['kennung']}.json").write_text(json.dumps(ergebnis, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
        anzahl += 1
        sekunden += dauer
        print(f"  {anzahl}: {einheit['bereich']}→{ergebnis.get('bereich', einheit['bereich'])} {dauer:.0f} s "
              f"„{ergebnis['titel']}“", flush=True)
        if args.hoechstens:
            gezeigt.append((einheit, text, ergebnis))

    if anzahl:
        print(f"\n{anzahl} Einheiten in {sekunden / 60:.1f} Minuten, im Mittel {sekunden / anzahl:.1f} s")
    for einheit, text, ergebnis in gezeigt:
        print(f"\n=== {einheit['kennung']} ({einheit['art']}, {einheit['bereich']})\n{text[:600]}\n---")
        print(f"Titel: {ergebnis['titel']}")
        if "bereich" in ergebnis:
            print(f"Bereich: {ergebnis['bereich']}")
        print(f"Hashtags neu: {', '.join(ergebnis['hashtags_neu']) or 'keine'}")
        if ergebnis["lesefassung"]:
            print(f"Lesefassung: {ergebnis['lesefassung']}")
        for g in ergebnis["gruende"]:
            print(f"Hinweis: {g}")


if __name__ == "__main__":
    main()
