"""Abgeschriebene Karteikarten als Einheiten einlesen und mit den Tweets verbinden, die auf sie verweisen.

Wird von einlesen.py aufgerufen, wenn config.toml einen Abschnitt [karten] hat:

  [karten]
  ordner = "/mnt/daten/zettelkasten/karten"    # enthält karte/<foto>.jpg und die Abschrift
  abschrift = "schedulae_karten.json"
  konto = "schedulae"                          # Twitter-Konto, auf dem die Karten erschienen sind
  bereich = "Soziologie"
  konten_mit_karten = ["soziologie"]           # Mastodon-Konten, auf denen Karten schon als Zettel stehen

Jede Karte wird eine Einheit der Art zettel. Ihr Text ist die Abschrift, die Fotos hängen als Bilder daran.
Für die Fotos legt das Einlesen in DATEN/abschriften/ eine Datei an, die sie als erledigt markiert,
damit das Bildmodell sie nicht noch einmal abschreibt.

Tweets, die nur aus Kartennummer, Titel und Link bestehen, gehen in der Karte auf: Ihr Datum steht dann
als „Getwittert“ in der Notiz, und der Tweet selbst wird keine eigene Notiz. Das gilt auch für Karten,
die schon als Zettel auf einem Mastodon-Konto stehen. Tweets mit einer Nummer, zu der es weder Karte noch
Zettel gibt, bleiben erhalten; sie sind die einzige Spur dieser Karte.
"""

import json
import re
from datetime import datetime
from pathlib import Path

NUMMER = re.compile(r"\s*(\d+(?:/[0-9][0-9a-z]*)?)\s+([^\n]*)")
# Kartennummer, Titel, wahlweise das Kürzel zkschdl, dann nur noch Links (bit.ly oder „Read: tl.gd/…“)
NUR_VERWEIS = re.compile(r"^\s*\d+(?:/[0-9][0-9a-z]*)?[ \t]+[^\n]*?(?:\s*(?:Read:)?\s*https?://\S+)+\s*$")


def vergleich(titel):
    titel = re.sub(r"\bzkschdl\b|\bRead:", "", titel.split("http")[0])
    return re.sub(r"\W+", "", titel.casefold())


def titel_fuer_datei(titel):
    return re.sub(r"\s*/\s*", ", ", titel).strip()


def dateititel(nummer, titel):
    """Notizname einer Karte: Nummer mit Punkt statt Schrägstrich, dann der Titel, etwa „2.4c1 Semantik“."""
    return f"{nummer.replace('/', '.')} {titel_fuer_datei(titel)}".strip()


def oberkarte(nummer):
    """Nummer der übergeordneten Karte nach Luhmanns Ordnung: 2/4c1a1 → 2/4c1a → … → 2/4 → 2; 0a → 0."""
    if "/" in nummer:
        stamm, rest = nummer.split("/", 1)
        if rest.isdigit():
            return stamm
        return stamm + "/" + re.sub(r"(\d+|[a-z]+)$", "", rest)
    kuerzer = re.sub(r"[a-z]+$", "", nummer)
    return kuerzer if kuerzer != nummer else ""


def lies_karten(konf, daten):
    k = konf["karten"]
    ordner = Path(k["ordner"])
    karten = json.loads((ordner / k["abschrift"]).read_text(encoding="utf-8"))["karten"]
    abschriften = daten / "abschriften"
    abschriften.mkdir(parents=True, exist_ok=True)
    einheiten = []
    for karte in karten:
        bilder = []
        for seite in karte["seiten"]:
            datei = f"karte/{seite}.jpg"
            bilder.append({"datei": datei, "typ": "image/jpeg", "beschreibung": ""})
            marke = abschriften / f"{seite}.jpg.json"
            if not marke.exists():
                marke.write_text(json.dumps({"uebersprungen": "karte, Abschrift steht im Text"}), encoding="utf-8")
        nummer = karte["nummer"]
        einheiten.append({
            "kennung": f"karte-{k['konto']}-{nummer.replace('/', '-')}", "konto": k["konto"], "plattform": "karte",
            "archiv": str(ordner), "art": "zettel", "bereich": k["bereich"], "von": "", "bis": "",
            "hashtags": [], "partner": [], "titel": dateititel(nummer, karte["titel"] or ""),
            "karte": nummer, "verweise": karte.get("verweise", []), "getwittert": [],
            "herkunft": karte.get("herkunft", ""),
            "beitraege": [{"id": nummer, "url": "", "zeit": "", "sichtbarkeit": "", "antwort_auf": None,
                           "an_andere": False, "gespraech": "",
                           # spitze Klammern stehen für Spencer-Browns Haken; Obsidian soll sie nicht als HTML lesen
                           "text": "\n".join(karte["abschrift"]).replace("<", "\\<"),
                           "hashtags": [], "links": [], "partner": [], "empfaenger": False, "inhaltswarnung": "",
                           "bilder": bilder, "vorschauen": 0}],
        })
    return einheiten


def verbinde(alle, karten, konf):
    """Tweets den Karten und Mastodon-Zetteln zuordnen. Gibt die bereinigte Liste aller Einheiten zurück."""
    k = konf["karten"]
    ziele, nach_titel = {}, {}
    for e in karten:
        ziele[e["karte"]] = e
        nach_titel[vergleich(e["titel"])] = e
    for e in alle:
        if e["konto"] in k.get("konten_mit_karten", []) and e["beitraege"]:
            m = NUMMER.match(e["beitraege"][0]["text"])
            if m and ("/" in m.group(1) or len(m.group(2).split()) <= 6):
                # Karte, die schon als Zettel auf Mastodon steht: gehört in dieselbe Ordnung wie die Kartei
                e.setdefault("karte", m.group(1))
                e.setdefault("getwittert", [])
                e["bereich"] = k["bereich"]
                e["titel"] = dateititel(m.group(1), re.sub(r"#", "", m.group(2)).strip())
                text = " ".join(b["text"] for b in e["beitraege"])
                e["verweise"] = [v for v in re.findall(r"[Vv]gl\.?:?\s+(\d+/[0-9][0-9a-z]*)", text)]
                ziele.setdefault(m.group(1), e)
                nach_titel.setdefault(vergleich(m.group(2)), e)

    ergebnis, aufgegangen = [], 0
    for e in alle:
        if e.get("plattform") != "twitter" or e["konto"] != k["konto"] or e["art"] == "geteilt":
            ergebnis.append(e)
            continue
        bleiben = []
        for b in e["beitraege"]:
            m = NUMMER.match(b["text"])
            ziel = None
            if m and NUR_VERWEIS.match(b["text"]):
                ziel = nach_titel.get(vergleich(m.group(2))) or ziele.get(m.group(1))
            if ziel:
                ziel["getwittert"].append(b["zeit"])
                aufgegangen += 1
            else:
                bleiben.append(b)
        if bleiben:
            e["beitraege"] = bleiben
            e["von"], e["bis"] = bleiben[0]["zeit"], bleiben[-1]["zeit"]
            ergebnis.append(e)

    getwittert = [z for e in karten for z in e["getwittert"]]
    frueheste = min(getwittert) if getwittert else datetime(2017, 1, 1).isoformat()
    for e in karten:
        e["getwittert"].sort()
        zeit = e["getwittert"][0] if e["getwittert"] else frueheste
        e["von"] = e["bis"] = e["beitraege"][0]["zeit"] = zeit
        if not e["getwittert"]:
            e["datum_geschaetzt"] = True
    for e in ergebnis:
        if "getwittert" in e:
            e["getwittert"].sort()

    # Links innerhalb der Kartei: Oberkarte nach der Nummer, Verweise aus den Vgl.-Zeilen
    titel = {e["karte"]: e["titel"] for e in ergebnis + karten if e.get("karte") and e.get("titel")}
    for e in ergebnis + karten:
        if not e.get("karte"):
            continue
        oben = oberkarte(e["karte"])
        e["oberkarte"] = titel.get(oben, "")
        e["verweis_titel"] = [titel[v] for v in dict.fromkeys(e.get("verweise", [])) if v in titel]
    return ergebnis + karten, aufgegangen
