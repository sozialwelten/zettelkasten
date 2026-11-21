#!/usr/bin/env python3
"""Aufbau von Twitter-Archiven zeigen, ohne Inhalte: Dateien, Anzahlen, Feldnamen, Zeiträume.

Aufruf:
  python3 twitter_struktur.py ORDNER_ODER_ZIP [...]

Gibt keine Texte aus, keine Namen und keine Nachrichten, nur den Aufbau. Gedacht als Grundlage
für das Einlesen der Archive in den Zettelkasten.
"""

import json
import re
import sys
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path


def lies_ytd(z, name):
    """Inhalt einer data/*.js-Datei: window.YTD.xyz.part0 = [ ... ]"""
    roh = z.read(name).decode("utf-8", errors="replace")
    variable = re.match(r"\s*window\.(\S+)\s*=", roh)
    daten = json.loads(roh[roh.index("=") + 1:])
    return (variable.group(1) if variable else "?"), daten


def schluessel(obj, tiefe=0, praefix=""):
    """Feldnamen bis zur vierten Ebene, ohne Werte."""
    zeilen = []
    if isinstance(obj, dict) and tiefe < 4:
        for k, v in obj.items():
            art = type(v).__name__
            zeilen.append(f"{praefix}{k}: {art}" + (f"[{len(v)}]" if isinstance(v, list) else ""))
            if isinstance(v, dict):
                zeilen += schluessel(v, tiefe + 1, praefix + "  ")
            elif isinstance(v, list) and v and isinstance(v[0], dict):
                zeilen += schluessel(v[0], tiefe + 1, praefix + "  ")
    return zeilen


def datum(text):
    for form in ("%a %b %d %H:%M:%S %z %Y", "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, form).strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            pass
    return None


def zeige(pfad):
    print(f"\n######## {pfad.name}  ({pfad.stat().st_size / 1e6:.0f} MB)")
    with zipfile.ZipFile(pfad) as z:
        namen = [n for n in z.namelist() if not n.endswith("/")]
        oben = {n.split("/", 1)[0] for n in namen}
        print(f"Oberste Ebene: {', '.join(sorted(oben))[:300]}")
        praefix = ""
        if not any(n.startswith("data/") for n in namen):
            kandidaten = {n.split("/data/")[0] + "/" for n in namen if "/data/" in n}
            praefix = sorted(kandidaten)[0] if kandidaten else ""
        ordner = Counter(n[len(praefix):].split("/")[1] for n in namen
                         if n.startswith(praefix + "data/") and n.count("/") > praefix.count("/") + 1)
        print("Unterordner in data/: " + ", ".join(f"{o} ({n})" for o, n in ordner.most_common()))
        js = sorted(n for n in namen if n.startswith(praefix + "data/") and n.endswith(".js")
                    and n.count("/") == praefix.count("/") + 1)
        print(f"{len(js)} .js-Dateien in data/:")
        for name in js:
            groesse = z.getinfo(name).file_size
            try:
                variable, daten = lies_ytd(z, name)
                anzahl = len(daten) if isinstance(daten, list) else "?"
            except (ValueError, json.JSONDecodeError):
                variable, anzahl = "nicht lesbar", "?"
            print(f"  {name[len(praefix) + 5:]:<45} {groesse / 1e3:>9.0f} kB  {anzahl:>7} Einträge  {variable}")

        for teil in ("tweet.js", "tweets.js", "direct-messages.js", "direct-message.js",
                     "direct-messages-group.js", "direct-message-group.js", "account.js"):
            name = praefix + "data/" + teil
            if name not in namen:
                continue
            _, daten = lies_ytd(z, name)
            if not daten:
                continue
            print(f"\n  Felder in {teil} (erster Eintrag):")
            for zeile in schluessel(daten[0]):
                print(f"    {zeile}")
            if teil.startswith("tweet"):
                tweets = [e.get("tweet", e) for e in daten]
                tage = sorted(d for d in (datum(t.get("created_at")) for t in tweets) if d)
                antworten = sum(1 for t in tweets if t.get("in_reply_to_status_id_str") or t.get("in_reply_to_status_id"))
                rts = sum(1 for t in tweets if str(t.get("full_text", t.get("text", ""))).startswith("RT @"))
                medien = sum(1 for t in tweets if t.get("extended_entities", {}).get("media") or t.get("entities", {}).get("media"))
                tags = sum(1 for t in tweets if t.get("entities", {}).get("hashtags"))
                print(f"  Tweets: {len(tweets)}, Zeitraum {tage[0] if tage else '?'} bis {tage[-1] if tage else '?'}, "
                      f"Antworten {antworten}, Retweets {rts}, mit Medien {medien}, mit Hashtags {tags}")
            if teil.startswith("direct"):
                gespraeche = [e.get("dmConversation", e) for e in daten]
                nachrichten = [m for g in gespraeche for m in g.get("messages", [])]
                arten = Counter(next(iter(m), "?") for m in nachrichten)
                tage = sorted(d for d in (datum(next(iter(m.values()), {}).get("createdAt")) for m in nachrichten) if d)
                print(f"  Gespräche: {len(gespraeche)}, Nachrichten: {len(nachrichten)} "
                      f"({', '.join(f'{a} {n}' for a, n in arten.most_common())}), "
                      f"Zeitraum {tage[0] if tage else '?'} bis {tage[-1] if tage else '?'}")


def main():
    pfade = []
    for a in sys.argv[1:]:
        p = Path(a).expanduser()
        pfade += sorted(p.glob("*.zip")) if p.is_dir() else [p]
    if not pfade:
        raise SystemExit("Aufruf: python3 twitter_struktur.py ORDNER_ODER_ZIP [...]")
    for p in pfade:
        try:
            zeige(p)
        except zipfile.BadZipFile:
            print(f"\n{p.name}: keine Zip-Datei")


if __name__ == "__main__":
    main()
