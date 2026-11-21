"""Mastodon-Exporte einlesen, zu Zetteln, Threads und Gesprächen gruppieren und bereinigen.

Aufruf:
  python3 einlesen.py                  alle Konten einlesen, Ergebnis nach DATEN/einheiten.jsonl
  python3 einlesen.py --probe 3        zusätzlich je Bereich und Art 3 Beispielnotizen nach DATEN/probe/
  python3 einlesen.py ARCHIV.zip       nur dieses Archiv

Liest nur aus den Zip-Archiven, packt nichts aus und schreibt nicht in den Vault.
Welche Archive: je Konto der jüngste Mastodon-Export unter [pfade] exporte, gleich wie die
Dateien heißen oder in welchen Unterordnern sie liegen (siehe exporte.py).
Die Probe kopiert für ihre Beispielnotizen die Bilder mit nach DATEN/probe/Zubehör/.

Eine Einheit ist das, was später eine Notiz wird:
  zettel   eigener Beitrag oder Thread mit Hashtags
  notiz    Direktnachricht ohne Erwähnung, also eine Notiz an mich selbst
  beitrag  eigener Beitrag oder Thread ohne Hashtags, öffentlich (Social Media)
  antwort  meine Antworten an andere in einem Gespräch
  direkt   Gespräch per Direktnachricht mit anderen, nur die Nachrichten mit Empfänger

Twitter: Ist [pfade] twitter gesetzt, kommen die Twitter-Archive dazu (siehe twitter.py).

Bereich: bei den thematischen Konten vom Konto. Bei @sozialwelten gehen antwort und beitrag nach
„Gespräch“, direkt nach „Gespräch/Direkt“. zettel und notiz aus @sozialwelten bekommen den Bereich
„offen“; ihn vergibt später das Modell.
"""

import argparse
import html
import json
import re
import sys
import tomllib
import zipfile
from collections import Counter, defaultdict
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

from exporte import neueste_exporte

PROJEKT = Path(__file__).resolve().parent
ANHAENGE = "Zubehör"  # Ordner für Bilder im Vault; der Name sortiert ihn hinter die Bereiche
BERLIN = ZoneInfo("Europe/Berlin")
OEFFENTLICH = "https://www.w3.org/ns/activitystreams#Public"
NULLBREITE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
MARKE_AUF, MARKE_ZU = "\u0001", "\u0002"  # umschließen Hashtags im Text, bis Hashtag-Zeilen entfernt sind
VERWEIS = re.compile(r"(\b(?:[Vv]gl|[Ss]iehe|[Cc]f)\.?|\b[Ss]\.|→|->|=>)([ \t]*)"
                     + MARKE_AUF + "([^" + MARKE_ZU + "]*)" + MARKE_ZU)
VERWEIS_FOLGE = re.compile(r"(#[\w-]+)([ \t]*(?:,|;|/|und|&)?[ \t]*)" + MARKE_AUF + "([^" + MARKE_ZU + "]*)" + MARKE_ZU)


def lade_konfiguration():
    with open(PROJEKT / "config.toml", "rb") as datei:
        return tomllib.load(datei)


def sichtbarkeit(obj):
    an, kopie = obj.get("to", []), obj.get("cc", [])
    if OEFFENTLICH in an:
        return "öffentlich"
    if OEFFENTLICH in kopie:
        return "nicht gelistet"
    if any(str(x).endswith("/followers") for x in an + kopie):
        return "nur Follower"
    return "direkt"


class Text(HTMLParser):
    """HTML eines Beitrags in Klartext: Absätze, Zeilenumbrüche, Links ausgeschrieben, Hashtags ohne Raute."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.teile, self.hashtags, self.links, self.erwaehnt = [], [], [], []
        self.link = None    # offenes <a>: [art, href, gesammelter Text]
        self.spans = []     # je offenes <span>: unsichtbar ja oder nein

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        klasse = a.get("class") or ""
        if tag == "br":
            self.teile.append("\n")
        elif tag == "p" and self.teile:
            self.teile.append("\n\n")
        elif tag == "span":
            self.spans.append("invisible" in klasse.split())
        elif tag == "a":
            art = "hashtag" if "hashtag" in klasse else "erwaehnung" if "mention" in klasse else "link"
            self.link = [art, a.get("href", ""), []]

    def handle_endtag(self, tag):
        if tag == "span" and self.spans:
            self.spans.pop()
        elif tag == "a" and self.link:
            art, href, text = self.link
            self.link = None
            text = "".join(text)
            if art == "hashtag":
                name = NULLBREITE.sub("", text).lstrip("#").strip()
                if name:
                    self.hashtags.append(name)
                self.teile.append(MARKE_AUF + name + MARKE_ZU)
            elif art == "erwaehnung":
                self.erwaehnt.append(href)
                self.teile.append(f"[{text.strip()}]({href})" if href else text.strip())
            else:
                self.links.append(href)
                self.teile.append(href)

    def handle_data(self, data):
        if self.link:
            self.link[2].append(data)
        elif not any(self.spans):
            self.teile.append(data)

    def ergebnis(self):
        return bereinige(NULLBREITE.sub("", "".join(self.teile)))


def bereinige(text):
    """Text mit markierten Hashtags (MARKE_AUF Name MARKE_ZU) in die Form für den Zettel bringen."""
    # Frühe Schreibweise ohne Nullbreitenzeichen: #Konsum(s) steht für „Konsums“ mit dem Hashtag Konsum.
    text = re.sub(MARKE_ZU + r"\((\w+)\)", MARKE_ZU + r"\1", text)
    # Verweise wie „vgl. #Gefahrenmeldung“ behalten die Raute an ihrer Stelle, damit sie in Obsidian
    # anklickbar bleiben; ebenso weitere Hashtags, die direkt danach aufgezählt sind.
    text = VERWEIS.sub(lambda t: t.group(1) + t.group(2) + "#" + t.group(3), text)
    while True:
        neu = VERWEIS_FOLGE.sub(lambda t: t.group(1) + t.group(2) + "#" + t.group(3), text)
        if neu == text:
            break
        text = neu
    # Zeilen, die nur aus Hashtags bestehen, fallen weg: Die Hashtags stehen ohnehin als Liste unter dem Zettel.
    zeilen = []
    for zeile in text.split("\n"):
        rest = re.sub(MARKE_AUF + "[^" + MARKE_ZU + "]*" + MARKE_ZU + r"\w*", "", zeile)
        if MARKE_AUF in zeile and not re.sub(r"[\W_]", "", rest):
            continue
        zeilen.append(zeile.replace(MARKE_AUF, "").replace(MARKE_ZU, ""))
    text = re.sub(r"[ \t]+\n", "\n", "\n".join(zeilen))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


KLARTEXT_ERWAEHNUNG = re.compile(r"(?<![\[\w/@.])@([A-Za-z0-9_][\w.]*)(?:@([\w-]+(?:\.[\w-]+)+))?(?!\]\()")


def profil(href):
    """Profiladresse in der lesbaren Form https://instanz/@name statt https://instanz/users/name."""
    return re.sub(r"^(https://[^/]+)/users/([^/]+)$", r"\1/@\2", href or "")


def zerlege(inhalt, instanz="ifwo.eu", bekannte=None):
    """Text, Hashtags, Links und Erwähnungen eines Beitrags. Erwähnungen, die Mastodon nicht verlinkt hat,
    etwa @name@instanz als bloßer Text, werden ebenfalls verlinkt: auf das Profil aus den Erwähnungen des
    Beitrags (bekannte: Name ohne @ und Instanz → Adresse), sonst auf die genannte oder die eigene Instanz."""
    bekannte = bekannte or {}
    parser = Text()
    parser.feed(inhalt or "")
    parser.close()
    erwaehnt = list(parser.erwaehnt)
    klartext = []

    def verlinke(treffer):
        name, host = treffer.group(1).rstrip("."), treffer.group(2)
        rest = treffer.group(1)[len(name):]
        href = bekannte.get(name.lower()) if not host else None
        href = href or f"https://{host or instanz}/@{name}"
        klartext.append({"name": f"@{name}@{host}" if host else f"@{name}", "href": href})
        return f"[@{name}{'@' + host if host else ''}]({href}){rest}"

    text = KLARTEXT_ERWAEHNUNG.sub(verlinke, parser.ergebnis())
    return text, parser.hashtags, parser.links, erwaehnt, klartext


def zeit(iso):
    return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(BERLIN)


def lies_archiv(archiv, bereiche):
    with zipfile.ZipFile(archiv) as z:
        dateien = set(z.namelist())
        with z.open("outbox.json") as f:
            daten = json.load(f)
        with z.open("actor.json") as f:
            konto = json.load(f).get("preferredUsername", archiv.parent.parent.name)

    beitraege = {}
    for eintrag in daten.get("orderedItems", []):
        obj = eintrag.get("object")
        if eintrag.get("type") != "Create" or not isinstance(obj, dict):
            continue
        ich = eintrag.get("actor", "")
        instanz = re.sub(r"^https://([^/]+)/.*$", r"\1", ich) or "ifwo.eu"
        partner = [{"name": t.get("name", ""), "href": profil(t.get("href", ""))}
                   for t in obj.get("tag", []) if t.get("type") == "Mention"]
        bekannte = {p["name"].lstrip("@").split("@")[0].lower(): p["href"] for p in partner if p["href"]}
        text, hashtags, links, erwaehnt, klartext = zerlege(obj.get("content", ""), instanz, bekannte)
        empfaenger = bool(partner)  # nur echte Erwähnungen machen eine Direktnachricht zum Gespräch
        bekannt = {p["name"].lstrip("@").split("@")[0].lower() for p in partner}
        partner += [p for p in klartext if p["name"].lstrip("@").split("@")[0].lower() not in bekannt]
        bilder, vorschauen = [], 0
        for anhang in obj.get("attachment", []) or []:
            url = str(anhang.get("url", ""))
            if not url.startswith("http") and url.lstrip("/") in dateien:
                bilder.append({"datei": url.lstrip("/"), "typ": anhang.get("mediaType", ""),
                               "beschreibung": anhang.get("name") or ""})
            else:
                vorschauen += 1
        antwort = obj.get("inReplyTo")
        beitraege[obj["id"]] = {
            "id": obj["id"], "url": obj.get("url") or obj["id"], "zeit": zeit(obj.get("published")).isoformat(),
            "sichtbarkeit": sichtbarkeit(obj), "antwort_auf": antwort,
            "an_andere": bool(antwort) and not str(antwort).startswith(ich),
            "gespraech": obj.get("conversation") or obj["id"],
            "text": text, "hashtags": hashtags, "links": links, "partner": partner,
            "empfaenger": empfaenger, "inhaltswarnung": obj.get("summary") or "", "bilder": bilder, "vorschauen": vorschauen,
        }

    # Wurzel jedes Beitrags innerhalb der eigenen Beiträge: geht die Kette auf einen fremden Beitrag zurück,
    # gehört der Beitrag zu meinen Antworten an andere, sonst zu meinem eigenen Thread.
    def an_andere_kette(b, gesehen=None):
        gesehen = gesehen or set()
        while b["antwort_auf"] in beitraege and b["id"] not in gesehen:
            gesehen.add(b["id"])
            b = beitraege[b["antwort_auf"]]
        return b["an_andere"]

    gruppen = defaultdict(list)
    for b in beitraege.values():
        if b["sichtbarkeit"] == "direkt":
            # Eine Direktnachricht ohne Empfänger erreicht niemanden: Sie ist eine Notiz an mich selbst,
            # auch mitten in einem Gespräch. Erwähnungen ohne Link zählen dabei nicht als Empfänger.
            art = "direkt" if b["empfaenger"] else "notiz"
        elif an_andere_kette(b):
            art = "antwort"
        else:
            art = "eigen"
        gruppen[(b["gespraech"], art)].append(b)

    einheiten = []
    for (gespraech, art), teile in gruppen.items():
        teile.sort(key=lambda b: b["zeit"])
        if art == "eigen":
            art = "zettel" if any(b["hashtags"] for b in teile) else "beitrag"
        hashtags = list(dict.fromkeys(h for b in teile for h in b["hashtags"]))
        partner = list({p["name"]: p for b in teile for p in b["partner"]
                        if p["name"].lstrip("@").split("@")[0] != konto}.values())
        if konto in bereiche:
            bereich = bereiche[konto]
        elif art in ("antwort", "beitrag"):
            bereich = "Gespräch"
        elif art == "direkt":
            bereich = "Gespräch/Direkt"
        else:
            bereich = "offen"
        einheiten.append({
            "kennung": f"{konto}-{teile[0]['id'].rstrip('/').rsplit('/', 1)[-1]}",
            "konto": konto, "archiv": str(archiv), "art": art, "bereich": bereich,
            "von": teile[0]["zeit"], "bis": teile[-1]["zeit"], "hashtags": hashtags, "partner": partner,
            "beitraege": teile,
        })
    return konto, einheiten


# Probe als Markdown

def dateiname(einheit):
    beginn = datetime.fromisoformat(einheit["von"])
    text = next((b["text"] for b in einheit["beitraege"] if b["text"]), "") or einheit["art"]
    worte = re.sub(r"https?://\S+|@\S+", "", text.split("\n", 1)[0])
    worte = re.sub(r"[^\w\säöüÄÖÜß-]", "", worte).split()
    titel = " ".join(worte[:8])[:60].strip() or einheit["art"]
    return f"{beginn:%Y-%m-%d} {titel}"


def als_markdown(einheit):
    beginn, ende = datetime.fromisoformat(einheit["von"]), datetime.fromisoformat(einheit["bis"])
    zeitraum = f"{beginn:%d.%m.%Y}" + (f" bis {ende:%d.%m.%Y}" if ende.date() != beginn.date() else "")
    kopf = [einheit["bereich"], f"@{einheit['konto']}", zeitraum]
    if einheit["beitraege"][0]["url"]:
        kopf.append(f"[Original]({einheit['beitraege'][0]['url']})")
    zeilen = [" · ".join(kopf)]
    if einheit["partner"]:
        zeilen.append("Mit: " + ", ".join(f"[{p['name']}]({p['href']})" if p["href"] else p["name"]
                                          for p in einheit["partner"]))
    mehrere = len(einheit["beitraege"]) > 1
    for b in einheit["beitraege"]:
        zeilen.append("")
        if mehrere:
            zeilen.append(f"**{datetime.fromisoformat(b['zeit']):%d.%m.%Y %H:%M}**")
            zeilen.append("")
        if b["inhaltswarnung"]:
            zeilen += [f"Inhaltswarnung: {b['inhaltswarnung']}", ""]
        if b["text"]:
            zeilen.append(b["text"])
        for bild in b["bilder"]:
            zeilen += ["", f"![[{Path(bild['datei']).name}]]"]
            if bild["beschreibung"]:
                zeilen.append(f"Bildbeschreibung: {bild['beschreibung']}")
    if einheit["hashtags"]:
        zeilen += ["", " ".join("#" + re.sub(r"\s+", "", h) for h in einheit["hashtags"])]
    return "\n".join(zeilen) + "\n"


def schreibe_probe(einheiten, ordner, anzahl):
    anhaenge = ordner / ANHAENGE
    anhaenge.mkdir(parents=True, exist_ok=True)
    gewaehlt = defaultdict(list)
    # je Bereich und Art: zuerst eine Einheit mit Bild, eine mit mehreren Beiträgen, dann die übrigen
    for einheit in sorted(einheiten, key=lambda e: (not any(b["bilder"] for b in e["beitraege"]),
                                                    len(e["beitraege"]) < 2, e["von"])):
        schluessel = (einheit["bereich"], einheit["art"])
        if len(gewaehlt[schluessel]) < anzahl:
            gewaehlt[schluessel].append(einheit)
    namen = Counter()
    for (bereich, art), liste in sorted(gewaehlt.items()):
        ziel = ordner / bereich.replace("/", " - ")
        ziel.mkdir(parents=True, exist_ok=True)
        for einheit in liste:
            name = dateiname(einheit)
            namen[name] += 1
            if namen[name] > 1:
                name += f" {namen[name]}"
            (ziel / f"{name}.md").write_text(als_markdown(einheit), encoding="utf-8")
            with zipfile.ZipFile(einheit["archiv"]) as z:
                for b in einheit["beitraege"]:
                    for bild in b["bilder"]:
                        (anhaenge / Path(bild["datei"]).name).write_bytes(z.read(bild["datei"]))
    return sum(len(v) for v in gewaehlt.values())


def main():
    parser = argparse.ArgumentParser(description="Mastodon-Exporte einlesen und gruppieren")
    parser.add_argument("archive", nargs="*", type=Path, help="nur diese Archive")
    parser.add_argument("--probe", type=int, metavar="N", help="je Bereich und Art N Beispielnotizen schreiben")
    args = parser.parse_args()

    konf = lade_konfiguration()
    daten = Path(konf["pfade"]["daten"])
    daten.mkdir(parents=True, exist_ok=True)
    archive = args.archive or neueste_exporte(konf["pfade"]["exporte"])

    alle = []
    for archiv in archive:
        print(f"lese {archiv.name} …", file=sys.stderr, flush=True)
        konto, einheiten = lies_archiv(archiv, konf["bereiche"])
        alle += einheiten
        arten = Counter(e["art"] for e in einheiten)
        print(f"  {konto}: {len(einheiten)} Einheiten: " + ", ".join(f"{n} {a}" for a, n in arten.most_common()))

    if konf["pfade"].get("twitter") and not args.archive:
        from twitter import lies_twitter, namensliste, neueste_twitter_archive
        twitter_archive = neueste_twitter_archive(konf["pfade"]["twitter"])
        namen = namensliste(twitter_archive)
        for archiv in twitter_archive:
            print(f"lese {archiv.name} …", file=sys.stderr, flush=True)
            konto, einheiten = lies_twitter(archiv, namen, konf)
            alle += einheiten
            arten = Counter(e["art"] for e in einheiten)
            print(f"  {konto} (Twitter): {len(einheiten)} Einheiten: "
                  + ", ".join(f"{n} {a}" for a, n in arten.most_common()))

    with open(daten / "einheiten.jsonl", "w", encoding="utf-8") as f:
        for einheit in alle:
            f.write(json.dumps(einheit, ensure_ascii=False) + "\n")
    print(f"\n{len(alle)} Einheiten nach {daten / 'einheiten.jsonl'}")
    print("Nach Bereich: " + ", ".join(f"{b} {n}" for b, n in Counter(e["bereich"] for e in alle).most_common()))

    if args.probe:
        ordner = daten / "probe"
        anzahl = schreibe_probe(alle, ordner, args.probe)
        print(f"{anzahl} Beispielnotizen nach {ordner}")


if __name__ == "__main__":
    main()
