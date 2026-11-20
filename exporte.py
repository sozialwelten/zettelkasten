"""Mastodon-Exporte finden, egal wie sie heißen oder liegen.

Durchsucht einen Ordner samt Unterordnern nach Zip-Dateien mit outbox.json und actor.json.
Das Konto steht in actor.json, der Zeitpunkt des Exports im Zeitstempel von outbox.json
innerhalb der Zip. Je Konto gilt der jüngste Export.
"""

import json
import zipfile
from datetime import datetime
from pathlib import Path


def lies_kopf(pfad):
    """(konto, zeitpunkt) eines Mastodon-Exports oder None, wenn die Zip keiner ist."""
    try:
        with zipfile.ZipFile(pfad) as z:
            try:
                outbox = z.getinfo("outbox.json")
                actor = json.loads(z.read("actor.json"))
            except KeyError:
                return None
    except (zipfile.BadZipFile, OSError):
        return None
    konto = actor.get("preferredUsername") or pfad.stem
    return konto, datetime(*outbox.date_time)


def neueste_exporte(wurzel):
    """Je Konto der jüngste Export unter wurzel, sortiert nach Konto: [Path, ...]."""
    wurzel = Path(wurzel)
    if wurzel.is_file():
        return [wurzel]
    bester = {}
    for pfad in sorted(wurzel.rglob("*.zip")):
        kopf = lies_kopf(pfad)
        if kopf is None:
            continue
        konto, zeitpunkt = kopf
        if konto not in bester or zeitpunkt > bester[konto][0]:
            bester[konto] = (zeitpunkt, pfad)
    return [bester[k][1] for k in sorted(bester)]
