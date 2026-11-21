# Zettelkasten

Werkzeug, das einen auf mehrere Mastodon-Konten verteilten Zettelkasten aus den Konto-Exporten in einen gemeinsamen, durchsuchbaren Obsidian-Vault überführt. Bilder werden lokal abgeschrieben, Hashtags und Querverweise ergänzt ein lokales Sprachmodell. Später schickt das Werkzeug alte Zettel als überraschende Fundstücke zurück.

Alles läuft auf einem eigenen Rechner. Kein Text und kein Bild geht an einen externen KI-Dienst, mit einer bewussten Ausnahme: handschriftliche Karteikarten (siehe „Physische Karten“). Der Code ist mit Hilfe eines KI-Assistenten entstanden und wird von Hand getestet.

## Stand

Gebaut sind alle Stufen bis zum Vault:

1. `bestand.py` zählt, was in den Exporten steckt.
2. `einlesen.py` gruppiert die Beiträge zu Einheiten, aus denen je eine Notiz wird, und bereinigt den Text.
3. `abschreiben.py` schreibt die Bilder mit dem Bildmodell ab.
4. `anreichern.py` lässt das Sprachmodell Titel, Bereich, zusätzliche Hashtags und eine Lesefassung vorschlagen und prüft sie.
5. `schreiben.py` schreibt fertige Einheiten als Notizen in den Vault.

Dazu kommen `twitter.py` für die Twitter-Archive und `karten.py` für Fotos physischer Karteikarten.

Noch nicht gebaut: Querverweise, Colloquium-Notizen, Zufallsfunde.

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

Die Exporte aus Mastodon (Einstellungen, Import und Export, Daten-Export) liegen als Zip-Archive in dem Ordner, den `[pfade] exporte` in `config.toml` nennt. Namen und Unterordner sind frei. `exporte.py` erkennt einen Export an `outbox.json` und `actor.json`, liest das Konto aus `actor.json` und nimmt je Konto den jüngsten Export. Andere Zip-Dateien im selben Ordner stören nicht.

Ein neuer Export ersetzt den alten. Vorher zeigt `exporte_pruefen.py`, ob im alten Export Beiträge oder Bilder stehen, die im neuen fehlen, etwa weil sie inzwischen gelöscht sind:

```
python3 exporte_pruefen.py ORDNER [ORDNER ...]          ältere gegen den neuesten Export je Konto
python3 exporte_pruefen.py ALT.zip NEU.zip --liste      alle Beiträge, die nur im alten stehen
```

## Twitter

Die Twitter-Archive von 2020 liegen als Zip-Dateien in dem Ordner, den `[pfade] twitter` nennt, je Konto zählt das jüngste. `twitter.py` macht daraus Einheiten nach demselben Muster wie bei Mastodon, mit diesen Besonderheiten:

- Antworten an andere enthalten nur die eigene Seite. Die Tweets der anderen stehen nicht im Archiv.
- Direktnachrichten und Gruppen enthalten beide Seiten, je Gespräch und Monat eine Einheit. Die Namen der Beteiligten kommen aus allen Archiven, sonst steht die Kontonummer da.
- Reine Retweets werden je Konto und Monat in einer Notiz „Geteilt im …“ gesammelt. Folgt auf einen Retweet innerhalb von 15 Minuten ein eigener Tweet, steht der Retweet als „Kurz davor geteilt“ in dessen Notiz.
- t.co-Links werden aufgelöst. Links auf Twitter selbst gibt es nicht mehr, weil die Konten gelöscht sind.
- Bilder gehen durch die Abschrift, Videos und GIFs kommen als Datei in den Vault.
- Bei den Konten aus `[twitter] zettelkonten` wird alles Eigene ein Zettel, auch ohne Hashtag.

Eigene Tweets ohne Hashtag (beitrag) bekommen den Bereich „offen“. Das Modell ordnet sie einem Bereich zu und darf dabei zusätzlich „Gespräch“ wählen, für Alltägliches ohne Zettelcharakter.

Direktnachrichten nennen nur Kontonummern. Namen, die in keinem Archiv stehen, kommen aus `DATEN/twitter_namen.toml`, eine Zeile je Konto wie `"1234567890" = "Vorname"`. Die Datei liegt bei den Daten und nicht im Repository. Welche Nummern noch fehlen, zeigt `.venv/bin/python twitter.py --unbekannt`.

`twitter_struktur.py ORDNER` zeigt den Aufbau der Archive, ohne Inhalte auszugeben.

## Physische Karten

Ein Teil des Zettelkastens existiert nur auf Papier: handschriftliche Karteikarten, nummeriert nach Luhmanns Art (etwa `2/15a`). Die längeren Texte dazu lagen früher bei TwitLonger und sind dort verloren. Die Karten werden einzeln auf grüner Unterlage fotografiert, Vorder- und Rückseite direkt nacheinander.

`karten.py` bereitet die Fotos auf. Aus CR2-Dateien nimmt es das eingebettete JPG, die Rohdatei bleibt unverändert. Zugeschnitten wird über die grüne Unterlage: Zeilen und Spalten mit viel Nicht-Grün gehören zur Karte.

```
.venv/bin/python karten.py QUELLE ZIEL               ZIEL/karte/ volle Auflösung, ZIEL/klein/ längste Kante 1600 Pixel
.venv/bin/python karten.py QUELLE ZIEL --kante 2000  andere Kantenlänge für die kleine Fassung
```

Die Abschriften stehen in einer JSON-Datei, je Karte Nummer, Titel, Fotos der Seiten, Text je Seite und die Nummern aus den Vgl.-Zeilen. Ist `[karten]` in `config.toml` gesetzt, liest `kartei.py` sie beim Einlesen mit ein:

- Jede Karte wird ein Zettel, mit der Abschrift als Text und den Fotos als Bilder. Die Fotos gelten als abgeschrieben, das Bildmodell lässt sie aus.
- Tweets, die nur Kartennummer, Titel und Link enthalten, werden keine eigenen Notizen. Ihr Datum steht als „Getwittert“ in der Karte. Das gilt auch für Karten, die schon als Zettel auf einem Mastodon-Konto stehen (`konten_mit_karten`).
- Zugeordnet wird zuerst über den Titel, dann über die Nummer, weil sich Nummern beim Umsortieren geändert haben.
- Karten ohne Tweet heißen in der Notiz „undatiert“.
- Den Titel der Notiz gibt die Karte vor, nicht das Modell.

Handschrift liest das lokale Bildmodell nicht zuverlässig genug. Die Karten werden deshalb mit Claude abgeschrieben. Es sind Exzerpte und eigene Gedanken zu Fachtexten, nichts Persönliches. Das ist die einzige Stelle, an der Inhalte des Zettelkastens einen externen Dienst sehen.

## Einheiten

| Art | Was | Bereich |
|---|---|---|
| zettel | eigener Beitrag oder Thread mit Hashtags | vom Konto, beim Hauptkonto vergibt ihn das Modell |
| notiz | Direktnachricht ohne Erwähnung, also eine Notiz an mich selbst | wie zettel |
| beitrag | eigener öffentlicher Beitrag oder Thread ohne Hashtags | Gespräch |
| antwort | meine Antworten an andere in einem Gespräch | Gespräch |
| direkt | Gespräch per Direktnachricht | Gespräch/Direkt |
| geteilt | Retweets eines Monats (nur Twitter) | Gespräch/Geteilt |

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
.venv/bin/python anreichern.py --stand            zählen, was angereichert, bereit und wartend ist
.venv/bin/python anreichern.py --hoechstens 10    10 Einheiten anreichern und die Ergebnisse zeigen
.venv/bin/python anreichern.py --minuten 120      zwei Stunden lang anreichern
.venv/bin/python anreichern.py --bereich offen --hoechstens 10   nur Einheiten aus diesem Bereich
.venv/bin/python schreiben.py --probe 3           je Bereich 3 Notizen in einen Probe-Vault
.venv/bin/python schreiben.py                     alle fertigen Einheiten in den Vault schreiben
```

Das Modell sieht keine Zeilen, die in sehr vielen Abschriften gleich vorkommen, etwa Folienköpfe. Vorgeschlagene Hashtags bleiben nur, wenn sie im Text oder in einer Abschrift vorkommen. Eine Lesefassung mit Zahlen, die im Zettel nicht stehen, wird verworfen.

Die Abschrift schreibt je Bild eine JSON-Datei nach `DATEN/abschriften/` und macht beim nächsten Aufruf dort weiter. Anhalten mit der Datei `DATEN/stopp`, nach dem laufenden Bild. Zwischen zwei Bildern wartet sie, wenn eine Grafikkarte zu heiß wird.

Pfade und die Bereiche der thematischen Konten stehen in `config.toml`.

## Alte Blogs aus dem Webarchiv

`wayback.py` holt die Seiten eines verschwundenen Blogs aus der Wayback Machine, je Seite die jüngste Aufnahme. `blogtexte.py` liest daraus die Beiträge samt Kommentaren und schreibt je Beitrag eine Notiz für Obsidian.

```
.venv/bin/python wayback.py socioeconomics.info/blog DATEN/wayback/socioeconomics --bis 2014
.venv/bin/python blogtexte.py DATEN/wayback/socioeconomics --name "SocioEconomics Blog"
```

Erkannt werden drei Bauarten von WordPress-Themes (Twenty Ten und neuere mit `entry-content`, das MH-Theme mit `post-title`, das Theme von Perun mit `storycontent`). Einzelseiten gehen vor Monatsarchiven und Übersichten. Gibt es einen Beitrag nur in einer Übersicht, wird sein Anfang übernommen und als Anriss gekennzeichnet. Seiten anderer Bauart, etwa eine ältere statische Homepage unter derselben Adresse, bleiben als Rohseite liegen. Mit `--bis` lassen sich Aufnahmen aus der Zeit nach dem Ende des Blogs ausschließen, etwa geparkte Domains.

## Aufräumen eines Kontos

`aufraeumen.py` löscht freistehende Beiträge ohne Hashtag und ohne Erwähnung aus einem Mastodon-Konto, etwa um ein gemischt genutztes Konto auszudünnen. Die Auswahl kommt aus den eingelesenen Einheiten, die Beiträge bleiben also im Export und im Zettelkasten erhalten.

```
.venv/bin/python aufraeumen.py liste --konto KONTO --seit 2024-11-21   Auswahl nach DATEN/aufraeumen/KONTO/, ändert nichts
.venv/bin/python aufraeumen.py loeschen --konto KONTO                  Liste abarbeiten, 30 Löschungen je 30 Minuten
.venv/bin/python aufraeumen.py --stand --konto KONTO                   zählen
```

Beiträge, auf die andere geantwortet haben, bleiben stehen. Das Token braucht nur `read:statuses` und `write:statuses` und liegt in `.env.aufraeumen`.

## Lizenz

GPL-3.0, siehe `LICENSE`.
