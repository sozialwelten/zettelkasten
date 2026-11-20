# Zettelkasten

Werkzeug, das einen auf mehrere Mastodon-Konten verteilten Zettelkasten aus den Konto-Exporten in einen gemeinsamen, durchsuchbaren Obsidian-Vault überführt. Bilder werden lokal abgeschrieben, Hashtags und Querverweise ergänzt ein lokales Sprachmodell. Später schickt das Werkzeug alte Zettel als überraschende Fundstücke zurück.

Alles läuft auf einem eigenen Rechner. Kein Text und kein Bild geht an einen externen KI-Dienst. Der Code ist mit Hilfe eines KI-Assistenten entstanden und wird von Hand getestet.

## Stand

Bestandsaufnahme, Einlesen und die Abschrift der Bilder sind gebaut. Das Einlesen gruppiert die Beiträge zu Einheiten, aus denen später je eine Notiz wird, und schreibt auf Wunsch Beispielnotizen zur Ansicht. Abschrift der Bilder, Zuordnung der Bereiche, Hashtags und das Schreiben in den Vault folgen.

Der Vault bekommt nur fertige Notizen. Erst wenn eine Einheit abgeschrieben, zugeordnet und verschlagwortet ist, wird sie geschrieben, und danach rührt das Programm sie nicht mehr an.

## Grundsätze

- **Eigener Text bleibt unverändert.** Das Modell ergänzt nur Hashtags aus Begriffen, die im Text oder in der Abschrift eines Bildes vorkommen, und schlägt Querverweise vor.
- **Ein Zettel je Beitrag, ein Zettel je Thread, ein Zettel je Gespräch per Direktnachricht.**
- **Ein gemeinsamer Vault mit Bereichen** statt getrennter Vaults je Thema, damit Verbindungen zwischen den Bereichen sichtbar bleiben.
- **Das Programm legt nur neue Zettel an** und lässt vorhandene in Ruhe. Was von Hand korrigiert ist, bleibt korrigiert.
- **Hashtags kommen aus dem Text**, nicht aus den Hashtag-Feldern des Exports. Mastodon speichert sie dort ohne Umlaute.
- **Gelesen wird direkt aus den Zip-Archiven.** Ausgepackt wird nichts.

## Voraussetzungen

- Python 3.12 oder neuer. Bestandsaufnahme und Einlesen brauchen nur die Standardbibliothek, die Abschrift Pillow und requests:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

- [Ollama](https://ollama.com) mit einem Sprachmodell (getestet qwen3:32b) und einem Bildmodell (qwen3-vl:30b ohne Nachdenken, hier unter dem Namen `bild30`).

## Ablage der Exporte

Die Exporte aus Mastodon (Einstellungen, Import und Export, Daten-Export) liegen als Zip-Archive unter

```
/mnt/daten/mastodon/<konto>/<datum>/<archiv>.zip
```

## Einheiten

| Art | Was | Bereich |
|---|---|---|
| zettel | eigener Beitrag oder Thread mit Hashtags | vom Konto, beim Hauptkonto vergibt ihn das Modell |
| notiz | Direktnachricht ohne Erwähnung, also eine Notiz an mich selbst | wie zettel |
| beitrag | eigener öffentlicher Beitrag oder Thread ohne Hashtags | Gespräch |
| antwort | meine Antworten an andere in einem Gespräch | Gespräch |
| direkt | Gespräch per Direktnachricht | Gespräch/Direkt |

Ein Thread ist eine Einheit, ebenso ein Gespräch. Beiträge, deren Kette auf einen fremden Beitrag zurückgeht, gehören zu den Antworten, auch wenn sie im selben Gespräch stehen wie ein eigener Thread.

## Aufrufe

```
python3 bestand.py                    neuester Export jedes Kontos: Beiträge, Zettel, Gespräche, Threads, Bilder
python3 bestand.py --jahre            zusätzlich je Konto nach Jahren
python3 bestand.py ARCHIV.zip [...]   nur diese Archive
python3 einlesen.py                   alle Konten einlesen, Einheiten nach DATEN/einheiten.jsonl
python3 einlesen.py --probe 3         zusätzlich je Bereich und Art 3 Beispielnotizen nach DATEN/probe/
.venv/bin/python abschreiben.py --stand           zählen, was abgeschrieben und was offen ist
.venv/bin/python abschreiben.py --hoechstens 20   20 Bilder abschreiben, drei Beispiele zeigen
.venv/bin/python abschreiben.py --minuten 120     zwei Stunden lang abschreiben
```

Die Abschrift schreibt je Bild eine JSON-Datei nach `DATEN/abschriften/` und macht beim nächsten Aufruf dort weiter. Anhalten mit der Datei `DATEN/stopp`, nach dem laufenden Bild. Zwischen zwei Bildern wartet sie, wenn eine Grafikkarte zu heiß wird.

Pfade und die Bereiche der thematischen Konten stehen in `config.toml`.

## Lizenz

GPL-3.0, siehe `LICENSE`.
