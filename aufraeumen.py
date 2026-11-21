#!/usr/bin/env python3
"""Freistehende Beiträge ohne Hashtag und ohne Erwähnung aus einem Mastodon-Konto löschen.

Aufruf:
  .venv/bin/python aufraeumen.py liste --konto sozialwelten --seit 2024-11-21
      Auswahl aus DATEN/einheiten.jsonl zusammenstellen, nach DATEN/aufraeumen/<konto>/liste.json und
      liste.md zum Durchsehen schreiben. Ändert nichts am Konto.
  .venv/bin/python aufraeumen.py loeschen --konto sozialwelten
      Die Liste abarbeiten. Braucht MASTODON_TOKEN in .env.aufraeumen (siehe unten).
  .venv/bin/python aufraeumen.py --stand --konto sozialwelten
      zählen, was gelöscht, übersprungen und offen ist

Ausgewählt werden eigene Beiträge und Threads ohne Hashtag (im Zettelkasten die Art „beitrag“), in denen
kein Beitrag jemanden erwähnt und keiner älter ist als --seit. Antworten in Gesprächen, Direktnachrichten,
Zettel und Boosts bleiben unberührt. Wer die Beiträge von der Liste nehmen will, löscht ihre Zeilen in
liste.json, bevor das Löschen beginnt.

Vor jedem Löschen fragt das Programm den Beitrag beim Server ab und überspringt ihn, wenn andere darauf
geantwortet haben, weil er dann zu einem Gespräch gehört. Mastodon erlaubt 30 Löschungen in 30 Minuten;
das Programm wartet die Sperre ab und macht weiter. Anhalten mit der Datei DATEN/aufraeumen/<konto>/stopp.
Was erledigt ist, steht in erledigt.json; ein neuer Aufruf macht dort weiter.

Token: In Mastodon unter Einstellungen, Entwicklung, Neue Anwendung, nur die Rechte read:statuses und
write:statuses. Den Zugangsschlüssel in .env.aufraeumen als MASTODON_TOKEN=... ablegen (chmod 600) und
die Anwendung nach dem Löschen wieder entfernen.
"""

import argparse
import json
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

PROJEKT = Path(__file__).resolve().parent


def lade_konfiguration():
    with open(PROJEKT / "config.toml", "rb") as f:
        return tomllib.load(f)


def token():
    pfad = PROJEKT / ".env.aufraeumen"
    if not pfad.exists():
        raise SystemExit(f"{pfad} fehlt. Siehe Hinweis zum Token in: aufraeumen.py --help")
    if pfad.stat().st_mode & 0o077:
        raise SystemExit(f"{pfad} ist für andere lesbar. Bitte: chmod 600 {pfad}")
    for zeile in pfad.read_text().splitlines():
        if zeile.startswith("MASTODON_TOKEN="):
            return zeile.split("=", 1)[1].strip()
    raise SystemExit(f"In {pfad} fehlt die Zeile MASTODON_TOKEN=...")


def anfrage(methode, url, schluessel):
    """Gibt (status, json, kopfzeilen) zurück."""
    req = urllib.request.Request(url, method=methode, headers={"Authorization": f"Bearer {schluessel}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as antwort:
            return antwort.status, json.loads(antwort.read() or b"{}"), antwort.headers
    except urllib.error.HTTPError as fehler:
        try:
            inhalt = json.loads(fehler.read() or b"{}")
        except ValueError:
            inhalt = {}
        return fehler.code, inhalt, fehler.headers


def warte_bis(kopf, mindestens=60):
    zurueck = kopf.get("Retry-After") if kopf else None
    reset = kopf.get("X-RateLimit-Reset") if kopf else None
    sekunden = mindestens
    if zurueck and zurueck.isdigit():
        sekunden = int(zurueck)
    elif reset:
        try:
            sekunden = (datetime.fromisoformat(reset.replace("Z", "+00:00")) - datetime.now().astimezone()).total_seconds()
        except ValueError:
            pass
    sekunden = max(mindestens, int(sekunden) + 5)
    print(f"  Grenze erreicht, warte {sekunden // 60} min {sekunden % 60} s", flush=True)
    return sekunden


def liste(args, daten, ordner):
    treffer = []
    with open(daten / "einheiten.jsonl", encoding="utf-8") as f:
        for zeile in f:
            e = json.loads(zeile)
            if e["konto"] != args.konto or e.get("plattform") or e["art"] != "beitrag":
                continue
            if any(b["zeit"] < args.seit or b["partner"] or b["hashtags"] for b in e["beitraege"]):
                continue
            for b in e["beitraege"]:
                treffer.append({"id": b["id"].rstrip("/").rsplit("/", 1)[-1], "url": b["url"], "zeit": b["zeit"],
                                "text": b["text"][:200]})
    treffer.sort(key=lambda t: t["zeit"])
    ordner.mkdir(parents=True, exist_ok=True)
    (ordner / "liste.json").write_text(json.dumps(treffer, ensure_ascii=False, indent=1), encoding="utf-8")
    zeilen = [f"Auswahl für @{args.konto} seit {args.seit}: {len(treffer)} Beiträge", ""]
    for t in treffer:
        zeilen.append(f"- {t['zeit'][:10]} [{t['id']}]({t['url']}) " + " ".join(t["text"].split())[:120])
    (ordner / "liste.md").write_text("\n".join(zeilen) + "\n", encoding="utf-8")
    print(f"{len(treffer)} Beiträge nach {ordner / 'liste.json'} und {ordner / 'liste.md'}")


def loeschen(args, konf, ordner):
    treffer = json.loads((ordner / "liste.json").read_text(encoding="utf-8"))
    erledigt_pfad = ordner / "erledigt.json"
    erledigt = json.loads(erledigt_pfad.read_text(encoding="utf-8")) if erledigt_pfad.exists() else {}
    offen = [t for t in treffer if t["id"] not in erledigt]
    print(f"{len(treffer)} in der Liste, {len(erledigt)} erledigt, {len(offen)} offen", flush=True)
    if args.stand or not offen:
        arten = {}
        for wert in erledigt.values():
            arten[wert] = arten.get(wert, 0) + 1
        print(", ".join(f"{n} {a}" for a, n in sorted(arten.items())) or "noch nichts erledigt")
        return
    schluessel = token()
    server = konf.get("mastodon", {}).get("server", "https://ifwo.eu").rstrip("/")
    status, ich, _ = anfrage("GET", f"{server}/api/v1/accounts/verify_credentials", schluessel)
    if status != 200 or ich.get("username") != args.konto:
        raise SystemExit(f"Das Token gehört nicht zu @{args.konto} (Antwort {status}: {ich.get('username') or ich})")
    stopp = ordner / "stopp"
    stopp.unlink(missing_ok=True)

    def merke(tid, ergebnis):
        erledigt[tid] = ergebnis
        erledigt_pfad.write_text(json.dumps(erledigt, indent=0), encoding="utf-8")

    for nr, t in enumerate(offen, 1):
        if stopp.exists():
            stopp.unlink(missing_ok=True)
            print("Stoppsignal erkannt.")
            break
        while True:
            status, beitrag, kopf = anfrage("GET", f"{server}/api/v1/statuses/{t['id']}", schluessel)
            if status != 429:
                break
            time.sleep(warte_bis(kopf))
        if status == 404:
            merke(t["id"], "schon weg")
            continue
        if status != 200:
            print(f"  {t['id']}: Abfrage ergab {status}, übersprungen", flush=True)
            continue
        if beitrag.get("replies_count", 0) > 0:
            merke(t["id"], "übersprungen, hat Antworten")
            print(f"{nr:>4}/{len(offen)} {t['zeit'][:10]} bleibt, hat Antworten", flush=True)
            continue
        while True:
            status, _, kopf = anfrage("DELETE", f"{server}/api/v1/statuses/{t['id']}", schluessel)
            if status != 429:
                break
            time.sleep(warte_bis(kopf, 120))
        if status in (200, 404):
            merke(t["id"], "gelöscht")
            print(f"{nr:>4}/{len(offen)} {t['zeit'][:10]} gelöscht", flush=True)
        else:
            print(f"  {t['id']}: Löschen ergab {status}, später erneut", flush=True)
        time.sleep(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("schritt", nargs="?", choices=["liste", "loeschen"], default="loeschen")
    ap.add_argument("--konto", required=True)
    ap.add_argument("--seit", default="2024-11-21", help="Datum im Format JJJJ-MM-TT")
    ap.add_argument("--stand", action="store_true", help="nur zählen")
    args = ap.parse_args()
    konf = lade_konfiguration()
    daten = Path(konf["pfade"]["daten"])
    ordner = daten / "aufraeumen" / args.konto
    if args.schritt == "liste" and not args.stand:
        liste(args, daten, ordner)
    else:
        if not (ordner / "liste.json").exists():
            raise SystemExit("Noch keine Liste. Zuerst: aufraeumen.py liste --konto ...")
        loeschen(args, konf, ordner)


if __name__ == "__main__":
    sys.exit(main())
