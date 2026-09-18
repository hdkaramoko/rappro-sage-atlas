"""Lancement et suivi des rapprochements réservés aux administrateurs."""

import hashlib
import shutil
from functools import wraps

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import FileResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import MatchingUploadForm
from .jobs import job_directory, launch, log_tail, stalled
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
        if MatchingJob.objects.filter(active=True).exists():
            form.add_error(None, "Un traitement est déjà en cours. Consultez son suivi ci-dessous.")
        elif shutil.disk_usage(settings.BASE_DIR).free < (
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
                    digest = hashlib.sha256()
                    with (directory / "propositions.jsonl").open("wb") as destination:
                        for chunk in form.cleaned_data["bundle"].chunks():
                            destination.write(chunk)
                            digest.update(chunk)
                    job.file_hash = digest.hexdigest()
                    job.state = "QUEUED"
                    job.save(update_fields=["state", "file_hash"])
                    launch(job)
                except Exception as exc:
                    job.state, job.active, job.error = "FAILED", False, str(exc)
                    job.finished_at = timezone.now()
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
            "log": log_tail(job),
            "stalled": stalled(job),
            "has_log": (job_directory(job) / "import.log").is_file(),
            "has_trace": (job_directory(job) / "tentatives.jsonl").is_file(),
        },
    )


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
