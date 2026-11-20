# Zettelkasten

Werkzeug, das einen auf mehrere Mastodon-Konten verteilten Zettelkasten aus den Konto-Exporten in einen gemeinsamen, durchsuchbaren Obsidian-Vault überführt. Bilder werden lokal abgeschrieben, Hashtags und Querverweise ergänzt ein lokales Sprachmodell. Später schickt das Werkzeug alte Zettel als überraschende Fundstücke zurück.

Alles läuft auf einem eigenen Rechner. Kein Text und kein Bild geht an einen externen KI-Dienst. Der Code ist mit Hilfe eines KI-Assistenten entstanden und wird von Hand getestet.

## Stand

Bisher gibt es nur die Bestandsaufnahme. Das Überführen in den Vault folgt.

## Grundsätze

- **Eigener Text bleibt unverändert.** Das Modell ergänzt nur Hashtags aus Begriffen, die im Text oder in der Abschrift eines Bildes vorkommen, und schlägt Querverweise vor.
- **Ein Zettel je Beitrag, ein Zettel je Thread, ein Zettel je Gespräch per Direktnachricht.**
- **Ein gemeinsamer Vault mit Bereichen** statt getrennter Vaults je Thema, damit Verbindungen zwischen den Bereichen sichtbar bleiben.
- **Das Programm legt nur neue Zettel an** und lässt vorhandene in Ruhe. Was von Hand korrigiert ist, bleibt korrigiert.
- **Hashtags kommen aus dem Text**, nicht aus den Hashtag-Feldern des Exports. Mastodon speichert sie dort ohne Umlaute.
- **Gelesen wird direkt aus den Zip-Archiven.** Ausgepackt wird nichts.

## Voraussetzungen

- Python 3.12 oder neuer. Die Bestandsaufnahme braucht nur die Standardbibliothek.
- Für die späteren Schritte: [Ollama](https://ollama.com) mit einem Sprachmodell (getestet qwen3:32b) und einem Bildmodell (qwen3-vl:30b).

## Ablage der Exporte

Die Exporte aus Mastodon (Einstellungen, Import und Export, Daten-Export) liegen als Zip-Archive unter

```
/mnt/daten/mastodon/<konto>/<datum>/<archiv>.zip
```

## Aufrufe

```
python3 bestand.py                    neuester Export jedes Kontos: Beiträge, Zettel, Gespräche, Threads, Bilder
python3 bestand.py --jahre            zusätzlich je Konto nach Jahren
python3 bestand.py ARCHIV.zip [...]   nur diese Archive
```

## Lizenz

GPL-3.0, siehe `LICENSE`.
