#!/usr/bin/env python3
"""Beiträge alter Blogs aus den Rohseiten lesen, die wayback.py gesichert hat.

Aufruf:
  .venv/bin/python blogtexte.py ZIEL [--name "SocioEconomics Blog"]

Gelesen wird ZIEL/roh/*.html. Erkannt werden drei Bauarten von WordPress-Themes:
  entry     neuere Themes mit entry-title und entry-content (etwa schedulae.ifwo.eu)
  mh        Theme mit post-title, post-meta und entry (socioeconomics.info/blog, 2011 bis 2013)
  perun     Theme von Perun mit h2 id="post-…", storycontent und unterseite (michael-karbacher.de)
Aus Einzelseiten kommen Beiträge samt Kommentaren. Monatsarchive und Übersichten liefern nur die
Beiträge, für die es keine eigene Seite gibt. Seiten ohne erkannte Bauart (etwa eine ältere,
statische Homepage unter derselben Adresse) bleiben außen vor und werden am Ende aufgezählt.

Ergebnis:
  ZIEL/beitraege.json     je Beitrag Adresse, Titel, Datum, Kategorien, Schlagworte, Text, Kommentare
  ZIEL/texte/<Datum> <Titel>.md   eine Notiz je Beitrag für Obsidian, ohne YAML-Kopf
Bilder werden nicht geholt; sie stehen als Verweis auf ihre frühere Adresse im Text.
"""

import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag

MONATE = {m: i for i, m in enumerate(["januar", "februar", "märz", "april", "mai", "juni", "juli", "august",
                                       "september", "oktober", "november", "dezember"], 1)}
DATUM = re.compile(r"(\d{1,2})\.\s*(Januar|Februar|März|April|Mai|Juni|Juli|August|September|Oktober|"
                   r"November|Dezember)\s+(\d{4})(?:\s+um\s+(\d{1,2}):(\d{2}))?", re.I)
WEG = ("script", "style", "noscript", "form", "iframe")
WEG_KLASSEN = re.compile(r"share|flattr|related|SPOSTARBUST|sharedaddy|addtoany|wp-socializer|fb-like|"
                         r"tags-wrap|nach-oben|feedback", re.I)


def datum(text):
    """'17. April 2012 um 19:35' wird zu '2012-04-17 19:35', ohne Uhrzeit zu '2012-04-17'."""
    m = DATUM.search(text or "")
    if not m:
        return ""
    tag, monat, jahr, std, minute = m.groups()
    d = f"{jahr}-{MONATE[monat.lower()]:02d}-{int(tag):02d}"
    return f"{d} {int(std):02d}:{minute}" if std else d


def adresse_normal(url):
    url = re.sub(r"^https?://(www\.)?", "", (url or "").strip()).split("#")[0].split("?")[0]
    return url.rstrip("/")


# HTML zu Markdown, genug für Blogtexte

def markdown(el):
    return aufraeumen(_md(el))


def aufraeumen(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _inline(el):
    return re.sub(r"\s+", " ", _md(el)).strip()


def _md(el):
    if isinstance(el, NavigableString):
        if el.__class__.__name__ in ("Comment", "Doctype", "Declaration", "ProcessingInstruction"):
            return ""
        return re.sub(r"\s+", " ", str(el))
    if not isinstance(el, Tag):
        return ""
    name = el.name
    if name in WEG or WEG_KLASSEN.search(" ".join(el.get("class") or [])):
        return ""
    innen = "".join(_md(k) for k in el.children)
    if name in ("p", "div", "section", "article", "center", "table", "tbody", "thead"):
        return f"\n\n{innen.strip()}\n\n" if innen.strip() else ""
    if name == "br":
        return "  \n"
    if name in ("h1", "h2", "h3", "h4", "h5", "h6"):
        stufe = max(2, int(name[1]) + 1)  # die Überschrift der Notiz ist die einzige erster Stufe
        return f"\n\n{'#' * min(stufe, 6)} {re.sub(r'\s+', ' ', innen).strip()}\n\n"
    if name in ("strong", "b", "em", "i"):
        # Leerraum gehört vor und hinter die Sternchen, sonst erkennt Markdown die Auszeichnung nicht
        t = innen.strip()
        if not t:
            return innen
        stern = "**" if name in ("strong", "b") else "*"
        vorn = " " if innen[:1].isspace() else ""
        hinten = " " if innen[-1:].isspace() else ""
        return f"{vorn}{stern}{t}{stern}{hinten}"
    if name == "a":
        ziel = el.get("href", "")
        t = innen.strip()
        if not ziel or ziel.startswith("#") or ziel.startswith("javascript"):
            return t
        if not t:
            return ""
        return f"[{t}]({ziel})" if t != ziel else f"<{ziel}>"
    if name == "img":
        quelle = el.get("src", "")
        alt = (el.get("alt") or el.get("title") or "Bild").strip()
        return f" [Bild: {alt}]({quelle}) " if quelle else ""
    if name == "blockquote":
        zeilen = aufraeumen(innen).splitlines()
        return "\n\n" + "\n".join(f"> {z}" if z else ">" for z in zeilen) + "\n\n"
    if name in ("ul", "ol"):
        punkte = []
        for nr, li in enumerate(el.find_all("li", recursive=False), 1):
            zeichen = f"{nr}." if name == "ol" else "-"
            inhalt = markdown(li).replace("\n", "\n   ")
            punkte.append(f"{zeichen} {inhalt}")
        return "\n\n" + "\n".join(punkte) + "\n\n"
    if name == "tr":
        zellen = [_inline(z) for z in el.find_all(["td", "th"], recursive=False)]
        return "\n" + " | ".join(zellen) + "\n"
    if name == "sup":
        return f"^{innen.strip()}" if innen.strip() else ""
    if name in ("pre", "code"):
        return f"`{el.get_text().strip()}`"
    if name == "hr":
        return "\n\n---\n\n"
    return innen


# Bauarten

def bauart(seite):
    if seite.select_one(".entry-title") and seite.select_one(".entry-content, .entry-summary"):
        return "entry"
    if seite.select_one("div.entry") and (seite.select_one("h1.post-title, h2.post-title")
                                          or seite.select_one("body.page")):
        return "mh"
    if seite.select_one("div#text-inhalt h2[id^=post-]"):
        return "perun"
    return ""


def kanonisch(seite):
    link = seite.find("link", rel="canonical")
    return link.get("href", "") if link else ""


def lies_entry(seite):
    einzeln = bool(seite.select_one("body.single, body.page"))
    rahmen_liste = seite.select(".hentry") or [seite]
    beitraege = []
    for rahmen in rahmen_liste:
        titel = rahmen.select_one(".entry-title")
        inhalt = rahmen.select_one(".entry-content")
        anriss = inhalt is None
        inhalt = inhalt or rahmen.select_one(".entry-summary")
        if not titel or not inhalt:
            continue
        for weiter in inhalt.find_all("a"):
            if re.match(r"\s*(Weiterlesen|Continue reading)", weiter.get_text()):
                weiter.decompose()
        link = titel.find("a")
        zeit = rahmen.find("time", datetime=True)
        if zeit:
            d = zeit["datetime"][:16].replace("T", " ")
        else:
            # Twenty Ten: Datum als Text, Uhrzeit im title des Permalinks
            tag = rahmen.select_one(".entry-date")
            d = datum(tag.get_text() if tag else "")
            uhr = tag.find_parent("a").get("title", "") if tag and tag.find_parent("a") else ""
            if d and re.fullmatch(r"\d{1,2}:\d{2}", uhr):
                d += f" {int(uhr.split(':')[0]):02d}:{uhr.split(':')[1]}"
        beitraege.append({
            "adresse": (link.get("href") if link else "") or kanonisch(seite),
            "titel": titel.get_text(" ", strip=True), "datum": d,
            "kategorien": [a.get_text(strip=True) for a in rahmen.select("a[rel~=category]")],
            "schlagworte": [a.get_text(strip=True) for a in rahmen.select("a[rel=tag]")],
            "text": markdown(inhalt), "anriss": anriss,
            "kommentare": kommentare_wp(seite) if einzeln else [],
        })
    return beitraege, einzeln


def lies_mh(seite):
    beitraege = []
    einzeln = bool(seite.select_one("body.single, body.page"))
    titel_liste = seite.select("h1.post-title, h2.post-title")
    if not titel_liste and seite.select_one("body.page"):
        # statische Seite: kein Titel im Beitrag, er steht nur im Kopf des Dokuments
        kopf = BeautifulSoup(f"<h1>{(seite.title.get_text() if seite.title else '').split('|')[0].strip()}</h1>",
                             "html.parser").h1
        rahmen = seite.select_one("div.entry").parent
        rahmen.insert(0, kopf)
        titel_liste = [kopf]
    for titel in titel_liste:
        rahmen = titel.find_parent("article") or titel.find_parent("div")
        meta = rahmen.select_one("p.post-meta")
        inhalt = rahmen.select_one("div.entry")
        if not inhalt:
            continue
        link = titel.find("a")
        beitraege.append({
            "adresse": (link.get("href") if link else "") or kanonisch(seite),
            "titel": titel.get_text(" ", strip=True),
            "datum": datum(meta.get_text(" ") if meta else ""),
            "kategorien": [a.get_text(strip=True) for a in (meta.select("a[rel~=category]") if meta else [])],
            "schlagworte": [a.get_text(strip=True) for a in rahmen.select("ul.tags a")],
            "text": markdown(inhalt), "anriss": False,
            "kommentare": kommentare_wp(seite) if einzeln else [],
        })
    return beitraege, einzeln


def lies_perun(seite):
    rahmen = seite.find("div", id="text-inhalt")
    beitraege = []
    titel_liste = rahmen.find_all("h2", id=re.compile(r"^post-"))
    # Einzelseiten tragen die Angaben zum Beitrag (… ist Beitrag Nr. …) oder die Kommentarliste
    einzeln = len(titel_liste) == 1 and bool(seite.find(string=re.compile(r"ist Beitrag Nr\.|Comments? vom"))
                                         or seite.select_one("ol#commentlist, div.unterseite"))
    for titel in titel_liste:
        inhalt = titel.find_next_sibling("div", class_=["storycontent", "unterseite"])
        if not inhalt:
            continue
        vorher = titel.find_previous_sibling("div", class_="datum")
        meta = rahmen.get_text(" ") if einzeln else ""
        autor = re.search(r"Karbacher am ([^\n]*?\d{4}(?: um \d{1,2}:\d{2})?)", meta)
        d = datum(autor.group(1)) if autor else datum(vorher.get_text() if vorher else "")
        link = titel.find("a")
        beitraege.append({
            "adresse": (link.get("href") if link else "") or kanonisch(seite),
            "titel": titel.get_text(" ", strip=True),
            "datum": d,
            "kategorien": [a.get_text(strip=True) for a in seite.select("a[rel~=category]")] if einzeln else [],
            "schlagworte": [a.get_text(strip=True) for a in seite.select("a[rel=tag]")] if einzeln else [],
            "text": markdown(inhalt), "anriss": False,
            "kommentare": kommentare_perun(seite) if einzeln else [],
        })
    return beitraege, einzeln


def kommentare_wp(seite):
    liste = []
    for k in seite.select("li.comment"):
        text = k.select_one(".comment-text, .comment-content")
        if not text and k.select_one(".comment-body"):
            # Twenty Ten: Kopf, Datum und Antworten-Knopf stehen mit im Kommentar
            text = BeautifulSoup(str(k.select_one(".comment-body")), "html.parser")
            for weg in text.select(".comment-author, .comment-meta, .reply, .comment-awaiting-moderation"):
                weg.decompose()
        if not text:
            continue
        meta = k.select_one(".vcard, .comment-meta, .comment-author")
        autor = ""
        if meta:
            autor = k.select_one(".fn").get_text(strip=True) if k.select_one(".fn") else \
                meta.get_text(" ", strip=True).split("//")[0].strip()
        liste.append({"autor": autor, "datum": datum(meta.get_text(" ") if meta else ""),
                      "antwort": "depth-1" not in (k.get("class") or []), "text": markdown(text)})
    return liste


def kommentare_perun(seite):
    liste = []
    for k in seite.select("ol#commentlist > li"):
        kopf = k.find("h4")
        info = k.select_one("p.kommentar-info")
        teile = [p for p in k.find_all("p", recursive=False) if p is not info]
        liste.append({"autor": kopf.get_text(" ", strip=True) if kopf else "",
                      "datum": datum(info.get_text(" ") if info else ""), "antwort": False,
                      "text": "\n\n".join(markdown(p) for p in teile)})
    return liste


LESER = {"entry": lies_entry, "mh": lies_mh, "perun": lies_perun}


def deutsch(d):
    """'2012-04-17 19:35' wird zu '17.04.2012 19:35'."""
    if not d:
        return ""
    j, m, t = d[:10].split("-")
    return f"{t}.{m}.{j}" + d[10:]


def dateiname(beitrag):
    titel = re.sub(r'[\\/:*?"<>|#^\[\]]', "", beitrag["titel"]).strip()
    titel = re.sub(r"\s+", " ", titel)[:90].rstrip(" .")
    return f"{beitrag['datum'][:10] or 'undatiert'} {titel or 'ohne Titel'}.md"


def notiz(beitrag, name):
    zeilen = [f"# {beitrag['titel']}", ""]
    kopf = f"Veröffentlicht am {deutsch(beitrag['datum']) or 'unbekannten Datum'}" + (f" im {name}" if name else "")
    zeilen.append(kopf)
    if beitrag["kategorien"]:
        zeilen.append("Kategorien: " + ", ".join(beitrag["kategorien"]))
    if beitrag["schlagworte"]:
        zeilen.append("Schlagworte: " + ", ".join(beitrag["schlagworte"]))
    zeilen.append(f"Frühere Adresse: <{beitrag['adresse']}>")
    if beitrag["anriss"]:
        zeilen.append("Erhalten ist nur der Anfang, aus einer Übersichtsseite des Blogs.")
    zeilen += ["", beitrag["text"]]
    if beitrag["kommentare"]:
        zeilen += ["", f"## Kommentare ({len(beitrag['kommentare'])})"]
        for k in beitrag["kommentare"]:
            einzug = "> " if k["antwort"] else ""
            zeilen += ["", f"{einzug}**{k['autor'] or 'Unbekannt'}**, {deutsch(k['datum'])}", einzug.rstrip()]
            zeilen += [f"{einzug}{z}" if z else einzug.rstrip() for z in k["text"].splitlines()]
    return "\n".join(zeilen).rstrip() + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("ziel", type=Path, help="Ordner mit roh/, wie wayback.py ihn anlegt")
    ap.add_argument("--name", default="", help="Name des Blogs für die Kopfzeile, etwa \"SocioEconomics Blog\"")
    args = ap.parse_args()

    gefunden = {}   # Adresse -> (Beitrag, aus Einzelseite)
    unbekannt = []
    for datei in sorted((args.ziel / "roh").glob("*.html")):
        seite = BeautifulSoup(datei.read_bytes(), "html.parser")
        art = bauart(seite)
        if not art:
            unbekannt.append(datei.name)
            continue
        beitraege, einzeln = LESER[art](seite)
        for b in beitraege:
            schluessel = adresse_normal(b["adresse"]) or datei.stem
            alt = gefunden.get(schluessel)
            # Einzelseiten gehen vor; bei zwei Übersichten gilt der längere Text
            besser = (einzeln, len(b["kommentare"]), len(b["text"]))
            if alt is None or besser > (alt[1], len(alt[0]["kommentare"]), len(alt[0]["text"])):
                b["rohseite"] = datei.name
                gefunden[schluessel] = (b, einzeln)

    beitraege = sorted((b for b, _ in gefunden.values() if b["text"] and b["titel"] != "Impressum"), key=lambda b: (b["datum"] or "9", b["titel"]))
    (args.ziel / "beitraege.json").write_text(json.dumps(beitraege, ensure_ascii=False, indent=1), encoding="utf-8")
    texte = args.ziel / "texte"
    texte.mkdir(exist_ok=True)
    for alt in texte.glob("*.md"):
        alt.unlink()
    for b in beitraege:
        (texte / dateiname(b)).write_text(notiz(b, args.name), encoding="utf-8")

    kommentare = sum(len(b["kommentare"]) for b in beitraege)
    print(f"{len(beitraege)} Beiträge mit {kommentare} Kommentaren nach {texte}/")
    for b in beitraege:
        print(f"  {b['datum'][:10] or 'undatiert':10}  {len(b['text']):>6} Zeichen  {len(b['kommentare']):>3} K."
              f"  {'Anriss ' if b['anriss'] else ''}{b['titel'][:60]}")
    if unbekannt:
        print(f"\n{len(unbekannt)} Seiten ohne erkannte Bauart, nicht übernommen:")
        print("  " + " ".join(unbekannt))


if __name__ == "__main__":
    main()
