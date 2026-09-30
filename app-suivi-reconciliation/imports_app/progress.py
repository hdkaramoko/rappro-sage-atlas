"""Progression sur disque : aucun écrivain SQLite supplémentaire pendant l'import."""

import json
import os
import time
from datetime import UTC, datetime


class ImportProgress:
    """Journalise phases, compteurs et durées indépendamment du signal de vie."""

    def __init__(self, directory):
        """Initialise les chronomètres sans ouvrir une transaction applicative."""
        self.directory = directory
        self.start = self.phase_start = time.monotonic()
        self.phase = ""
        self.completed = 0

    def __call__(self, phase, completed=None, **details):
        """Publie un compteur atomiquement et ajoute une ligne horodatée au journal."""
        now = time.monotonic()
        if phase != self.phase:
            self.phase_start, self.phase = now, phase
            self.completed = 0
        if completed is not None:
            self.completed = completed
        data = {
            "phase": phase,
            "completed": self.completed,
            "elapsed": round(now - self.start, 2),
            "phase_elapsed": round(now - self.phase_start, 2),
            "updated_at": datetime.now(UTC).isoformat(),
            **details,
        }
        target = self.directory / "progress.json"
        temporary = self.directory / "progress.tmp"
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            # Windows peut refuser le remplacement pendant une lecture HTTP ou
            # antivirus. Attente bornée ; le suivi ne doit jamais annuler l'import.
            for attempt in range(3):
                try:
                    os.replace(temporary, target)
                    break
                except PermissionError:
                    if attempt == 2:
                        raise
                    time.sleep(0.05)
        except OSError as exc:
            # Garder le dernier JSON complet ; la prochaine mesure réessaiera.
            data["progress_warning"] = str(exc)
        try:
            with (self.directory / "import.log").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(data, ensure_ascii=False) + "\n")
        except OSError:
            # Les écritures métier conservent leur propre traitement des erreurs.
            # Seule la télémétrie est facultative, même si le disque est plein.
            pass


def read_progress_file(directory):
    """Retourne le dernier progrès connu ; un heartbeat seul n'indique aucun avancement."""
    try:
        return json.loads((directory / "progress.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
