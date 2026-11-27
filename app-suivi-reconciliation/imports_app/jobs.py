"""Runners JSONL : staging PostgreSQL durable et compatibilité locale SQLite."""

import contextlib
import os
import subprocess
import sys
import threading
import time
import traceback
import uuid
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import DatabaseError, close_old_connections, connection, models, transaction
from django.utils import timezone

from reconciliation.models import Campaign
from reconciliation.review_import import import_bundle

from .models import MatchingJob
from .progress import ImportProgress, read_progress_file

_worker_state = threading.local()


def job_directory(job):
    return Path(settings.MATCHING_JOB_ROOT) / str(job.pk)


def read_progress(job):
    """Lit les compteurs durables ; les anciens jobs gardent le suivi sur disque."""
    if job.protocol_version:
        return {"phase": job.phase, "completed": sum(job.checkpoint.get("counts", {}).values()),
                "durable": True}
    return read_progress_file(job_directory(job))


def launch(job):
    """Le serveur ne conserve aucun thread de calcul ; le processus lui survit."""
    if settings.MATCHING_JOB_RUNNER == "supervised":
        return  # Le worker consomme PostgreSQL ; aucun processus dans Gunicorn.
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
    if connection.vendor == "postgresql":
        stamp = job.heartbeat_at or job.created_at
        return (timezone.now() - stamp).total_seconds() > settings.MATCHING_HEARTBEAT_TIMEOUT
    heartbeat = job_directory(job) / "heartbeat"
    stamp = heartbeat.stat().st_mtime if heartbeat.exists() else job.created_at.timestamp()
    return time.time() - stamp > 120


@contextlib.contextmanager
def worker_lock():
    """Verrou système libéré aussi en cas d'arrêt brutal ; une seule exécution."""
    if connection.vendor == "postgresql":
        # Verrou de session : partagé entre pods, libéré si le worker meurt.
        # PostgreSQL autorise une reprise du même verrou par sa propre session.
        if getattr(_worker_state, "active", False):
            raise BlockingIOError("Un import est déjà actif dans cette session.")
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_try_advisory_lock(%s)", [734129826])
            acquired = cursor.fetchone()[0]
        if not acquired:
            raise BlockingIOError("Un autre import est déjà en cours.")
        _worker_state.active = True
        _worker_state.session = connection.connection
        try:
            yield
        finally:
            try:
                if connection.connection is _worker_state.session:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s)", [734129826])
            finally:
                _worker_state.active = False
                _worker_state.session = None
        return
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


def assert_worker_session():
    if connection.vendor != "postgresql":
        return
    if not getattr(_worker_state, "active", False) or connection.connection is not _worker_state.session:
        raise RuntimeError("Session du verrou perdue : arrêt du worker avant toute écriture.")
    with connection.cursor() as cursor:
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                       "AND pid=pg_backend_pid() AND classid=0 AND objid=734129826 AND granted)")
        if not cursor.fetchone()[0]:
            raise RuntimeError("Verrou du worker perdu.")


def run_job(job_id=None, resume=False, stop=None):
    """Exécute au plus un job éligible ; retourne son UUID ou None si file vide."""
    from .resumable import InterruptedImport, IncompatibleImport, staged_postgres_import, verify_source

    stop = stop if stop is not None else threading.Event()
    automatic = job_id is None
    with worker_lock():
        if job_id is None:
            resume = True
            eligible = MatchingJob.objects.filter(active=True, state__in=["QUEUED", "MATCHING", "IMPORTING", "INTERRUPTED", "RETRYABLE"])
            eligible = eligible.filter(models.Q(next_attempt_at__isnull=True) | models.Q(next_attempt_at__lte=timezone.now()))
            job_id = eligible.order_by("created_at").values_list("pk", flat=True).first()
            if job_id is None:
                return None
        job = MatchingJob.objects.get(pk=job_id)
        assert_worker_session()
        if automatic and job.attempts >= settings.MATCHING_MAX_ATTEMPTS and job.state != "QUEUED":
            MatchingJob.objects.filter(pk=job.pk).update(state="RETRYABLE", active=False,
                error="Nombre maximal de tentatives atteint ; reprise manuelle nécessaire.")
            return job.pk
        directory = job_directory(job)
        if not job.bundle_name:
            raise RuntimeError("Ancien traitement : importer un fichier de propositions JSONL.")
        if job.state != "QUEUED" and not (resume and job.state in {"IMPORTING", "MATCHING", "INTERRUPTED", "RETRYABLE"}):
            raise RuntimeError("Ce traitement n'est pas en attente ou reprenable.")
        if not job.active:
            # La contrainte one_active_matching_job refuse une reprise si un
            # autre import occupe déjà la file. Le verrou seul ne réserve pas la file.
            assert_worker_session()
            job.active = True
            job.next_attempt_at = None
            job.save(update_fields=["active", "next_attempt_at"])
        pulse_stop = threading.Event()

        def pulse():
            close_old_connections()
            try:
                while not pulse_stop.is_set():
                    if connection.vendor == "postgresql":
                        updated = MatchingJob.objects.filter(pk=job.pk, generation=job.generation).update(heartbeat_at=timezone.now())
                        if not updated:
                            stop.set()
                            return
                    else:
                        (directory / "heartbeat").touch()
                    pulse_stop.wait(10)
            except Exception:
                stop.set()  # Une télémétrie perdue interdit de continuer sans contrôle.
            finally:
                close_old_connections()

        job.generation = uuid.uuid4()
        job.attempts += 1
        job.resumed_at = timezone.now() if job.attempts > 1 else None
        job.heartbeat_at = timezone.now()
        assert_worker_session()
        job.save(update_fields=["generation", "attempts", "resumed_at", "heartbeat_at"])
        thread = threading.Thread(target=pulse, daemon=True)
        thread.start()
        progress = ImportProgress(directory)
        try:
            job.state = "IMPORTING"
            job.error = ""
            job.phase = "Vérification du fichier"
            assert_worker_session()
            job.save(update_fields=["state", "error", "phase"])
            progress("Vérification du fichier")
            path = directory / "propositions.jsonl"
            header, ending, size, digest, seconds = verify_source(path, job, stop)
            job.file_hash, job.source_size = digest, size
            job.checkpoint = {**job.checkpoint, "last_validation_seconds": round(seconds, 3)}
            assert_worker_session()
            job.save(update_fields=["file_hash", "source_size", "checkpoint"])
            progress("Source vérifiée", validation_seconds=round(seconds, 3))
            from .sqlite_staging import is_file_sqlite, staged_import

            duplicate = (
                MatchingJob.objects.filter(state="SUCCESS", file_hash=job.file_hash)
                .exclude(pk=job.pk)
                .exists()
            ) or Campaign.objects.filter(file_hash=job.file_hash).exists()
            if not duplicate and connection.vendor == "postgresql" and header.get("type") == "campaign":
                staged_postgres_import(path, job, header, progress, stop)
                job.refresh_from_db()
            elif not duplicate and is_file_sqlite():
                staged_import(
                    directory / "propositions.jsonl",
                    job=job,
                    directory=directory,
                    progress=progress,
                )
                job.refresh_from_db()  # La publication a enregistré SUCCESS atomiquement.
            else:
                # Compatibilité PostgreSQL et bases mémoire des tests.
                with transaction.atomic():
                    assert_worker_session()
                    if duplicate:
                        job.state = "DUPLICATE"
                    else:
                        job.groups_imported = import_bundle(
                            directory / "propositions.jsonl", job=job, progress=progress
                        )
                        job.state = "SUCCESS"
                    job.active = False
                    job.finished_at = timezone.now()
                    assert_worker_session()
                    job.save()
        except Exception as exc:
            try:
                with (directory / "worker.log").open("a", encoding="utf-8") as log:
                    traceback.print_exc(file=log)
            except OSError:
                pass
            # Une erreur de journal après COMMIT ne transforme pas un succès en échec.
            # Un zombie ne doit surtout pas relire le nouveau jeton puis écraser
            # l'état du worker qui a repris après sa perte de session.
            assert_worker_session()
            generation = job.generation
            job.refresh_from_db()
            assert_worker_session()
            if job.generation != generation:
                raise RuntimeError("Un autre worker détient ce traitement ; diagnostic non écrasé.") from exc
            if job.state != "SUCCESS":
                resumable = connection.vendor == "postgresql"
                transient = isinstance(exc, (InterruptedImport, OSError, DatabaseError)) and not isinstance(exc, FileNotFoundError)
                job.state = ("INTERRUPTED" if isinstance(exc, InterruptedImport) else "RETRYABLE") if resumable and transient else "FAILED"
                if resumable and job.protocol_version and not isinstance(exc, (ValueError, ValidationError, TypeError, KeyError)):
                    job.state = "INTERRUPTED" if isinstance(exc, InterruptedImport) else "RETRYABLE"
                # La source manquante et les versions incompatibles attendent une
                # correction explicite ; aucun retry automatique en boucle.
                if resumable and isinstance(exc, (FileNotFoundError, IncompatibleImport)):
                    job.state = "RETRYABLE"
                can_retry = (job.state in {"INTERRUPTED", "RETRYABLE"} and transient
                             and job.attempts < settings.MATCHING_MAX_ATTEMPTS)
                job.error = str(exc)
                job.active = can_retry
                job.next_attempt_at = timezone.now() + timedelta(seconds=min(300, 10 * 2 ** min(job.attempts, 5))) if can_retry else None
                job.finished_at = None if job.state in {"INTERRUPTED", "RETRYABLE"} else timezone.now()
                job.save()
        finally:
            try:
                with (directory / "import.log").open("a", encoding="utf-8") as log:
                    log.write(f"{job.state} : {job.groups_imported} groupes. {job.error}\n")
            except OSError:
                pass  # Le bilan en base reste la référence, même si le disque est plein.
            pulse_stop.set()
            thread.join(timeout=2)
    close_old_connections()
    return job.pk
