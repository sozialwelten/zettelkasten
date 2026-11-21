"""Twitter-Archive (Format von 2020) in Einheiten für den Zettelkasten umwandeln.

Wird von einlesen.py aufgerufen, wenn in config.toml [pfade] twitter gesetzt ist. Je Konto zählt das
jüngste Archiv. Erkannt wird ein Archiv an data/tweet.js und data/account.js.

Was daraus wird:
  zettel / beitrag  eigener Tweet oder Thread an mich selbst; zettel mit Hashtags, sonst beitrag.
                    Bei den Konten aus [twitter] zettelkonten wird alles Eigene zum Zettel.
                    Beide bekommen den Bereich „offen“; beim beitrag darf das Modell auch „Gespräch“ wählen.
  antwort           meine Antworten an andere, je Tweet, auf den ich geantwortet habe; nur meine Seite,
                    weil das Archiv die Tweets der anderen nicht enthält
  direkt            Direktnachrichten und Gruppen mit beiden Seiten, je Gespräch und Monat
  geteilt           reine Retweets, je Konto und Monat gesammelt
Folgt auf einen Retweet innerhalb von KONTEXT_MINUTEN ein eigener Tweet, der keine Antwort ist,
steht der Retweet als Kontext in dessen Einheit („Kurz davor geteilt“).

Links: t.co wird zur echten Adresse aufgelöst. Links auf Twitter selbst gibt es nicht, weil die Konten
und die Plattform in dieser Form nicht mehr bestehen. Erwähnungen bleiben als @name im Text.
Direktnachrichten nennen nur Kontonummern; die Namen kommen aus allen eingelesenen Archiven und aus
DATEN/twitter_namen.toml (eine Zeile je Konto: "1234567890" = "Vorname"). Welche Nummern noch ohne Namen sind, zeigt:

  .venv/bin/python twitter.py --unbekannt            Nummer, Zahl der Nachrichten, Zeitraum, Gruppen
"""

import html
import json
import re
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from einlesen import BERLIN, MARKE_AUF, MARKE_ZU, bereinige

KONTEXT_MINUTEN = 15
MONATE = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
          "November", "Dezember"]
TYPEN = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
         ".gif": "image/gif", ".mp4": "video/mp4", ".mov": "video/quicktime"}


def lies_ytd(z, name):
    """Inhalt einer data/*.js-Datei: window.YTD.xyz.part0 = [ ... ]"""
    if name not in z.namelist():
        return []
    roh = z.read(name).decode("utf-8", errors="replace")
    return json.loads(roh[roh.index("=") + 1:])


def ist_twitter_archiv(pfad):
    try:
        with zipfile.ZipFile(pfad) as z:
            namen = set(z.namelist())
    except (zipfile.BadZipFile, OSError):
        return False
    return "data/tweet.js" in namen and "data/account.js" in namen


def konto_von(pfad):
    with zipfile.ZipFile(pfad) as z:
        konto = lies_ytd(z, "data/account.js")[0]["account"]
        zeitpunkt = datetime(*z.getinfo("data/tweet.js").date_time)
    return konto["username"], konto["accountId"], zeitpunkt


def neueste_twitter_archive(wurzel):
    """Je Konto das jüngste Twitter-Archiv unter wurzel: [Path, ...]."""
    bester = {}
    for pfad in sorted(Path(wurzel).expanduser().rglob("*.zip")):
        if not ist_twitter_archiv(pfad):
            continue
        konto, _, zeitpunkt = konto_von(pfad)
        if konto not in bester or zeitpunkt > bester[konto][0]:
            bester[konto] = (zeitpunkt, pfad)
    return [bester[k][1] for k in sorted(bester)]


def tweets_von(z):
    return [e.get("tweet", e) for e in lies_ytd(z, "data/tweet.js")]


def namensliste(archive, bekannt=None):
    """Kontonummer → Name aus allen Archiven: eigene Konten, Erwähnungen, Antworten.
    Einträge aus DATEN/twitter_namen.toml gehen vor; sie dürfen auch Klarnamen sein."""
    namen = {}
    for pfad in archive:
        with zipfile.ZipFile(pfad) as z:
            konto = lies_ytd(z, "data/account.js")[0]["account"]
            namen[konto["accountId"]] = konto["username"]
            for t in tweets_von(z):
                for m in t.get("entities", {}).get("user_mentions", []):
                    if m.get("id_str") and m.get("screen_name"):
                        namen.setdefault(m["id_str"], m["screen_name"])
                if t.get("in_reply_to_user_id_str") and t.get("in_reply_to_screen_name"):
                    namen.setdefault(t["in_reply_to_user_id_str"], t["in_reply_to_screen_name"])
    namen.update({str(k): v for k, v in (bekannt or {}).items()})
    return namen


def namen_aus_datei(konf):
    """Eigene Zuordnung Kontonummer → Name aus DATEN/twitter_namen.toml (liegt nicht im Repository)."""
    import tomllib
    pfad = Path(konf["pfade"]["daten"]) / "twitter_namen.toml"
    if not pfad.exists():
        return {}
    with open(pfad, "rb") as f:
        return {str(k): str(v) for k, v in tomllib.load(f).items()}


def zeit_tweet(text):
    return datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y").astimezone(BERLIN)


def zeit_dm(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(BERLIN)


def medien_index(namen, ordner):
    """Dateien eines Medienordners nach der Kennung vor dem ersten Bindestrich."""
    index = defaultdict(list)
    for n in namen:
        if n.startswith(f"data/{ordner}/") and not n.endswith("/"):
            index[Path(n).name.split("-", 1)[0]].append(n)
    return index


def als_bild(datei):
    return {"datei": datei, "typ": TYPEN.get(Path(datei).suffix.lower(), "application/octet-stream"),
            "beschreibung": ""}


def tweet_text(t):
    """Text eines Tweets: t.co aufgelöst, Medienlinks entfernt, Antwort-Präfix weg, Hashtags markiert."""
    text = t.get("full_text") or t.get("text") or ""
    entities = t.get("entities", {})
    for u in entities.get("urls", []):
        if u.get("url"):
            text = text.replace(u["url"], u.get("expanded_url") or u["url"])
    for m in entities.get("media", []) + t.get("extended_entities", {}).get("media", []):
        if m.get("url"):
            text = text.replace(m["url"], "")
    if t.get("in_reply_to_status_id_str"):
        text = re.sub(r"^(?:@\w+\s+)+", "", text)
    for h in sorted({h["text"] for h in entities.get("hashtags", [])}, key=len, reverse=True):
        text = re.sub(rf"(?<![\w#]){re.escape('#' + h)}(?!\w)", MARKE_AUF + h + MARKE_ZU, text)
    text = html.unescape(text)
    return bereinige(text.strip()), [h["text"] for h in entities.get("hashtags", [])]


def lies_twitter(archiv, namen, konf):
    """Einheiten eines Twitter-Archivs. Gibt (konto, einheiten) zurück."""
    zettelkonten = set(konf.get("twitter", {}).get("zettelkonten", []))
    bereiche = konf.get("bereiche", {})
    with zipfile.ZipFile(archiv) as z:
        alle_namen = z.namelist()
        konto_daten = lies_ytd(z, "data/account.js")[0]["account"]
        tweets = tweets_von(z)
        dms = lies_ytd(z, "data/direct-messages.js")
        gruppen_dms = lies_ytd(z, "data/direct-messages-group.js")
    konto, ich = konto_daten["username"], konto_daten["accountId"]
    eigene_namen = set(namen_aus_datei(konf))  # Klarnamen aus der eigenen Liste, ohne @
    tweet_medien = medien_index(alle_namen, "tweet_media")
    dm_medien = medien_index(alle_namen, "direct_messages_media")
    gruppe_medien = medien_index(alle_namen, "direct_messages_group_media")

    def bereich_fuer(art):
        if konto in bereiche:
            return bereiche[konto]
        if art == "beitrag":
            return "offen"  # das Modell wählt, Gespräch ist eine der Möglichkeiten
        if art == "antwort":
            return "Gespräch"
        if art == "direkt":
            return "Gespräch/Direkt"
        if art == "geteilt":
            return "Gespräch/Geteilt"
        return "offen"

    def einheit(kennung, art, teile, hashtags=(), partner=(), kontext=()):
        teile.sort(key=lambda b: b["zeit"])
        return {
            "kennung": f"twitter-{konto}-{kennung}", "konto": konto, "plattform": "twitter", "archiv": str(archiv),
            "art": art, "bereich": bereich_fuer(art), "von": teile[0]["zeit"], "bis": teile[-1]["zeit"],
            "hashtags": list(dict.fromkeys(hashtags)), "partner": list(partner), "kontext": list(kontext),
            "beitraege": teile,
        }

    def beitrag(kennung, zeit, text, hashtags=(), bilder=(), absender="", partner=()):
        return {"id": kennung, "url": "", "zeit": zeit.isoformat(), "sichtbarkeit": "", "antwort_auf": None,
                "an_andere": False, "gespraech": "", "text": text, "hashtags": list(hashtags), "links": [],
                "partner": list(partner), "empfaenger": False, "inhaltswarnung": "", "bilder": list(bilder),
                "vorschauen": 0, "absender": absender}

    # Tweets
    eigene, retweets = {}, []
    for t in tweets:
        tid = t["id_str"]
        zeit = zeit_tweet(t["created_at"])
        roh = t.get("full_text") or ""
        if roh.startswith("RT @"):
            autor = re.match(r"RT @(\w+):?", roh)
            text, _ = tweet_text(t)
            text = re.sub(r"^RT @\w+:?\s*", "", text)
            retweets.append({"zeit": zeit, "autor": autor.group(1) if autor else "", "text": text})
            continue
        text, hashtags = tweet_text(t)
        partner = [{"name": "@" + m["screen_name"], "href": ""} for m in t.get("entities", {}).get("user_mentions", [])
                   if m.get("id_str") != ich]
        eigene[tid] = {"t": t, "zeit": zeit, "text": text, "hashtags": hashtags, "partner": partner,
                       "eltern": t.get("in_reply_to_status_id_str"),
                       "an_andere": bool(t.get("in_reply_to_status_id_str")) and t.get("in_reply_to_user_id_str") != ich,
                       "bilder": [als_bild(d) for d in sorted(tweet_medien.get(tid, []))]}

    def wurzel(tid):
        gesehen = set()
        while eigene[tid]["eltern"] in eigene and tid not in gesehen:
            gesehen.add(tid)
            tid = eigene[tid]["eltern"]
        return tid

    gruppen = defaultdict(list)
    for tid, e in eigene.items():
        w = wurzel(tid)
        if eigene[w]["an_andere"]:
            gruppen[("antwort", eigene[w]["eltern"])].append(tid)
        else:
            gruppen[("eigen", w)].append(tid)

    retweets.sort(key=lambda r: r["zeit"])
    einheiten = []
    for (art, schluessel), ids in gruppen.items():
        teile = [beitrag(i, eigene[i]["zeit"], eigene[i]["text"], eigene[i]["hashtags"], eigene[i]["bilder"],
                         partner=eigene[i]["partner"]) for i in ids]
        hashtags = [h for i in ids for h in eigene[i]["hashtags"]]
        partner = list({p["name"]: p for i in ids for p in eigene[i]["partner"]}.values())
        kontext = []
        if art == "antwort":
            erster = min(ids, key=lambda i: eigene[i]["zeit"])
            name = eigene[erster]["t"].get("in_reply_to_screen_name")
            if name and name not in [p["name"].lstrip("@") for p in partner]:
                partner.insert(0, {"name": "@" + name, "href": ""})
        else:
            art = "zettel" if hashtags or konto in zettelkonten else "beitrag"
            beginn = min(eigene[i]["zeit"] for i in ids)
            kontext = [{"zeit": r["zeit"].isoformat(), "autor": r["autor"], "text": r["text"]} for r in retweets
                       if timedelta(0) <= beginn - r["zeit"] <= timedelta(minutes=KONTEXT_MINUTEN)]
        einheiten.append(einheit(min(ids, key=int) if art != "antwort" else f"antwort-{schluessel or min(ids)}",
                                 art, teile, hashtags, partner, kontext))

    # Retweets je Monat
    monate = defaultdict(list)
    for r in retweets:
        monate[f"{r['zeit']:%Y-%m}"].append(r)
    for monat, liste in monate.items():
        teile = [beitrag(f"rt-{monat}-{nr}", r["zeit"], r["text"], absender="@" + r["autor"] if r["autor"] else "")
                 for nr, r in enumerate(liste)]
        jahr, m = monat.split("-")
        e = einheit(f"geteilt-{monat}", "geteilt", teile)
        e["titel"] = f"Geteilt im {MONATE[int(m) - 1]} {jahr} (@{konto})"
        einheiten.append(e)

    # Direktnachrichten je Gespräch und Monat
    for quelle, medien in ((dms, dm_medien), (gruppen_dms, gruppe_medien)):
        for eintrag in quelle:
            g = eintrag.get("dmConversation", eintrag)
            titel = ""
            je_monat = defaultdict(list)
            beteiligte = set()
            for m in g.get("messages", []):
                if "conversationNameUpdate" in m:
                    titel = m["conversationNameUpdate"].get("name", titel)
                    continue
                n = m.get("messageCreate")
                if not n:
                    continue
                zeit = zeit_dm(n["createdAt"])
                text = n.get("text", "")
                for u in n.get("urls", []):
                    if u.get("url"):
                        text = text.replace(u["url"], u.get("expanded") or u.get("expanded_url") or u["url"])
                for u in n.get("mediaUrls", []):
                    text = text.replace(u, "")
                text = html.unescape(text).strip()
                absender = namen.get(n.get("senderId"), "") or f"Konto {n.get('senderId', '?')}"
                klar = n.get("senderId") in eigene_namen
                beteiligte.update(x for x in (n.get("senderId"), n.get("recipientId")) if x and x != ich)
                bilder = [als_bild(d) for d in sorted(medien.get(n["id"], []))]
                if n.get("senderId") == ich:
                    absender = "@" + konto
                elif not absender.startswith("Konto") and not klar:
                    absender = "@" + absender
                je_monat[f"{zeit:%Y-%m}"].append(beitrag(n["id"], zeit, text, bilder=bilder, absender=absender))
            partner = [{"name": (namen[b] if b in eigene_namen else "@" + namen[b]) if b in namen else f"Konto {b}",
                        "href": ""} for b in sorted(beteiligte)]
            for monat, teile in je_monat.items():
                e = einheit(f"dm-{g.get('conversationId', '?')}-{monat}", "direkt", teile, partner=partner)
                if titel:
                    e["gruppenname"] = titel
                einheiten.append(e)
    return konto, einheiten


def unbekannte(archive, namen):
    """Kontonummern aus Direktnachrichten, zu denen es keinen Namen gibt: {nummer: Angaben}."""
    offen = {}
    for pfad in archive:
        with zipfile.ZipFile(pfad) as z:
            konto = lies_ytd(z, "data/account.js")[0]["account"]["username"]
            quellen = lies_ytd(z, "data/direct-messages.js") + lies_ytd(z, "data/direct-messages-group.js")
        for eintrag in quellen:
            g = eintrag.get("dmConversation", eintrag)
            titel = ""
            for m in g.get("messages", []):
                if "conversationNameUpdate" in m:
                    titel = m["conversationNameUpdate"].get("name", titel)
                n = m.get("messageCreate")
                if not n or n.get("senderId") in namen:
                    continue
                a = offen.setdefault(n["senderId"], {"anzahl": 0, "von": n["createdAt"], "bis": n["createdAt"],
                                                     "konten": set(), "gruppen": set(), "mit": set()})
                a["anzahl"] += 1
                a["von"], a["bis"] = min(a["von"], n["createdAt"]), max(a["bis"], n["createdAt"])
                a["konten"].add(konto)
                if titel:
                    a["gruppen"].add(titel)
                for p in g.get("participants", []) or []:
                    pid = p.get("userId") if isinstance(p, dict) else p
                    if pid in namen:
                        a["mit"].add(namen[pid])
    return offen


if __name__ == "__main__":
    import argparse
    import tomllib
    ap = argparse.ArgumentParser(description="Hilfen zu den Twitter-Archiven")
    ap.add_argument("--unbekannt", action="store_true", help="Kontonummern ohne Namen auflisten")
    args = ap.parse_args()
    with open(Path(__file__).resolve().parent / "config.toml", "rb") as f:
        konf = tomllib.load(f)
    archive = neueste_twitter_archive(konf["pfade"]["twitter"])
    namen = namensliste(archive, namen_aus_datei(konf))
    if args.unbekannt:
        liste = unbekannte(archive, namen)
        print(f"{len(liste)} Kontonummern ohne Namen, nach Zahl der Nachrichten:\n")
        for nummer, a in sorted(liste.items(), key=lambda x: -x[1]["anzahl"]):
            zusatz = ""
            if a["gruppen"]:
                zusatz += " · Gruppe: " + ", ".join(sorted(a["gruppen"]))[:60]
            print(f"{nummer:>20}  {a['anzahl']:>4} Nachr.  {a['von'][:7]} bis {a['bis'][:7]}  "
                  f"an {', '.join(sorted(a['konten']))}{zusatz}")
