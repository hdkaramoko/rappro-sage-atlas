"""Lancement et suivi des rapprochements réservés aux administrateurs."""

import errno
import hashlib
import os
import shutil
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, connection, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import MatchingUploadForm
from .jobs import job_directory, launch, log_tail, read_progress, stalled, worker_lock
from .models import MatchingJob


def administrator(view):
    @login_required
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_global_admin:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


@administrator
def index(request):
    form = MatchingUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        storage_error = ""
        try:
            settings.MATCHING_JOB_ROOT.mkdir(parents=True, exist_ok=True)
            available = shutil.disk_usage(settings.MATCHING_JOB_ROOT).free
        except OSError as exc:
            available = 0
            storage_error = f"Stockage des imports inaccessible : {exc}"
        if storage_error:
            form.add_error(None, storage_error)
        elif MatchingJob.objects.filter(active=True).exists():
            form.add_error(None, "Un traitement est déjà en cours. Consultez son suivi ci-dessous.")
        elif available < (
            form.cleaned_data["bundle"].size + 1024**3
        ):
            form.add_error(None, "Espace disque insuffisant pour conserver les extractions.")
        else:
            try:
                with transaction.atomic():
                    job = MatchingJob.objects.create(
                        created_by=request.user,
                        bundle_name=form.cleaned_data["bundle"].name,
                    )
            except IntegrityError:
                form.add_error(None, "Un autre traitement vient de démarrer. Actualisez la page.")
            else:
                try:
                    directory = job_directory(job)
                    directory.mkdir(parents=True)
                    uploaded = form.cleaned_data["bundle"]
                    target = directory / "propositions.jsonl"
                    temporary = directory / "propositions.uploading"
                    job.file_hash = getattr(uploaded, "sha256", "")
                    if os.name != "nt" and hasattr(uploaded, "temporary_file_path"):
                        # Même volume : pas de seconde copie de centaines de Mo dans HTTP.
                        try:
                            os.replace(uploaded.temporary_file_path(), temporary)
                        except OSError as exc:
                            if exc.errno != errno.EXDEV:
                                raise
                            shutil.copyfile(uploaded.temporary_file_path(), temporary)
                        # Le worker revérifie l'empreinte hors de la requête web.
                    else:
                        digest = hashlib.sha256()
                        with temporary.open("wb") as destination:
                            for chunk in uploaded.chunks():
                                destination.write(chunk)
                                digest.update(chunk)
                        job.file_hash = digest.hexdigest()
                    # Même le chemin rename doit synchroniser les données avant QUEUED.
                    with temporary.open("rb+") as source:
                        if not job.file_hash:
                            job.file_hash = hashlib.file_digest(source, "sha256").hexdigest()
                        os.fsync(source.fileno())
                    job.source_size = temporary.stat().st_size
                    os.replace(temporary, target)
                    if os.name != "nt":
                        for synced_directory in (directory, directory.parent):
                            directory_fd = os.open(synced_directory, os.O_RDONLY)
                            try:
                                os.fsync(directory_fd)
                            finally:
                                os.close(directory_fd)
                    job.state = "QUEUED"
                    job.save(update_fields=["state", "file_hash", "source_size"])
                    launch(job)
                except Exception as exc:
                    durable = job.state == "QUEUED" and connection.vendor == "postgresql"
                    job.state, job.active, job.error = "RETRYABLE" if durable else "FAILED", False, str(exc)
                    job.finished_at = None if durable else timezone.now()
                    job.save()
                return redirect("imports:detail", pk=job.pk)
    page = Paginator(MatchingJob.objects.select_related("created_by"), 20).get_page(
        request.GET.get("page")
    )
    return render(
        request,
        "imports/index.html",
        {
            "form": form,
            "page": page,
            "page_range": page.paginator.get_elided_page_range(page.number, on_each_side=2),
        },
    )


@administrator
def detail(request, pk):
    job = get_object_or_404(MatchingJob.objects.select_related("created_by"), pk=pk)
    return render(
        request,
        "imports/detail.html",
        {
            "job": job,
            "campaign": job.campaign
            if hasattr(job, "campaign") and job.campaign.published
            else None,
            "progress": read_progress(job),
            "log": log_tail(job),
            "stalled": stalled(job),
            "has_log": (job_directory(job) / "import.log").is_file(),
            "has_trace": (job_directory(job) / "tentatives.jsonl").is_file(),
            "can_resume": job.state in {"RETRYABLE", "INTERRUPTED"} or stalled(job) and job.state == "IMPORTING",
            "can_abandon": job.state not in {"SUCCESS", "DUPLICATE", "ABANDONED"},
        },
    )


@administrator
@require_POST
def resume(request, pk):
    try:
        # Le heartbeat ne suffit jamais : seul le verrou autorise la transition.
        with worker_lock(), transaction.atomic():
            job = get_object_or_404(MatchingJob.objects.select_for_update(), pk=pk)
            if job.state not in {"RETRYABLE", "INTERRUPTED", "IMPORTING", "MATCHING"}:
                raise ValueError("Ce traitement n'est pas reprenable.")
            from .resumable import PROTOCOL
            if job.protocol_version not in (0, PROTOCOL):
                raise ValueError("Version incompatible ; restaurez une version applicative compatible.")
            if not (job_directory(job) / "propositions.jsonl").is_file():
                raise ValueError("Source introuvable : restaurez le fichier original sur le volume d'import.")
            job.state, job.active, job.error = "QUEUED", True, ""
            job.next_attempt_at, job.finished_at = None, None
            job.save(update_fields=["state", "active", "error", "next_attempt_at", "finished_at"])
        launch(job)
    except (OSError, ValueError, IntegrityError) as exc:
        messages.error(request, str(exc))
    return redirect("imports:detail", pk=pk)


@administrator
@require_POST
def abandon(request, pk):
    if request.POST.get("confirm") != "yes":
        messages.error(request, "Confirmez explicitement l'abandon de l'import.")
        return redirect("imports:detail", pk=pk)
    try:
        with worker_lock(), transaction.atomic():
            job = get_object_or_404(MatchingJob.objects.select_for_update(), pk=pk)
            if job.state in {"SUCCESS", "DUPLICATE", "ABANDONED"}:
                raise ValueError("Ce traitement est déjà terminé.")
            job.state, job.active, job.finished_at = "ABANDONED", False, timezone.now()
            job.save(update_fields=["state", "active", "finished_at"])
    except (OSError, ValueError) as exc:
        messages.error(request, str(exc))
    return redirect("imports:detail", pk=pk)


@administrator
def download(request, pk, artifact):
    job = get_object_or_404(MatchingJob, pk=pk)
    names = {
        "journal": "import.log",
        "tentatives": "tentatives.jsonl",
        "propositions": "propositions.jsonl",
    }
    from django.http import Http404

    if artifact not in names or (job.active and artifact != "journal"):
        raise Http404
    path = job_directory(job) / names[artifact]
    if not path.is_file():
        raise Http404
    return FileResponse(path.open("rb"), as_attachment=True, filename=names[artifact])
