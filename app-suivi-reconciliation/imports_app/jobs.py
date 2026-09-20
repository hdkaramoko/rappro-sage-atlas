"""Import atomique de JSONL en processus détaché, sans exécution du moteur."""

import contextlib
import hashlib
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone

from reconciliation.review_import import import_bundle

from .models import MatchingJob


def job_directory(job):
    return Path(settings.MATCHING_JOB_ROOT) / str(job.pk)


def launch(job):
    """Le serveur ne conserve aucun thread de calcul ; le processus lui survit."""
    executable = Path(sys.executable)
    if os.name == "nt":
        # CREATE_NO_WINDOW est ignoré lorsqu'il est combiné à DETACHED_PROCESS.
        windowless = executable.with_name("pythonw.exe")
        if windowless.is_file():
            executable = windowless
        startup = subprocess.STARTUPINFO()
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
        options = {"creationflags": subprocess.CREATE_NO_WINDOW, "startupinfo": startup}
    else:
        options = {"start_new_session": True}
    with (job_directory(job) / "worker.log").open("ab") as log:
        subprocess.Popen(
            [
                str(executable),
                str(settings.BASE_DIR / "manage.py"),
                "run_matching_job",
                str(job.pk),
            ],
            cwd=settings.BASE_DIR,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            close_fds=True,
            **options,
        )


def log_tail(job, limit=24000):
    path = job_directory(job) / "import.log"
    if not path.exists():
        return "Le journal apparaîtra au démarrage de l’import."
    with path.open("rb") as stream:
        stream.seek(max(0, path.stat().st_size - limit))
        return stream.read(limit).decode("utf-8", errors="replace")


def stalled(job):
    if not job.active:
        return False
    heartbeat = job_directory(job) / "heartbeat"
    stamp = heartbeat.stat().st_mtime if heartbeat.exists() else job.created_at.timestamp()
    return time.time() - stamp > 120


@contextlib.contextmanager
def worker_lock():
    """Verrou système libéré aussi en cas d'arrêt brutal ; une seule exécution."""
    root = Path(settings.MATCHING_JOB_ROOT)
    root.mkdir(parents=True, exist_ok=True)
    with (root / "worker.lock").open("a+b") as stream:
        stream.write(b"0")
        stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def run_job(job_id, resume=False):
    with worker_lock():
        job = MatchingJob.objects.get(pk=job_id)
        directory = job_directory(job)
        if not job.bundle_name:
            raise RuntimeError("Ancien traitement : importer un fichier de propositions JSONL.")
        if job.state != "QUEUED" and not (resume and job.active):
            raise RuntimeError("Ce traitement n'est pas en attente ou reprenable.")
        stop = threading.Event()

        def pulse():
            while not stop.is_set():
                (directory / "heartbeat").touch()
                stop.wait(10)

        directory.mkdir(parents=True, exist_ok=True)
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        try:
            job.state = "IMPORTING"
            job.error = ""
            job.save(update_fields=["state", "error"])
            with (directory / "import.log").open("a", encoding="utf-8") as log:
                log.write("Contrôle et chargement des propositions\n")
            with (directory / "propositions.jsonl").open("rb") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != job.file_hash:
                    raise ValueError("Le fichier a changé depuis son transfert. Import annulé.")
            # L'import et son statut final sont validés ensemble : pas de succès partiel.
            with transaction.atomic():
                if (
                    MatchingJob.objects.filter(state="SUCCESS", file_hash=job.file_hash)
                    .exclude(pk=job.pk)
                    .exists()
                ):
                    job.state = "DUPLICATE"
                else:
                    job.groups_imported = import_bundle(directory / "propositions.jsonl", job=job)
                    job.state = "SUCCESS"
                job.active = False
                job.finished_at = timezone.now()
                job.save()
        except Exception as exc:
            job.state = "FAILED"
            job.error = str(exc)
            job.active = False
            job.finished_at = timezone.now()
            job.save()
        finally:
            try:
                with (directory / "import.log").open("a", encoding="utf-8") as log:
                    log.write(f"{job.state} : {job.groups_imported} groupes. {job.error}\n")
            except OSError:
                pass  # Le bilan en base reste la référence, même si le disque est plein.
            stop.set()
            thread.join(timeout=2)
            close_old_connections()
