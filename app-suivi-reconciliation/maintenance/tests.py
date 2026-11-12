"""Tests isolés des permissions, du blocage HTTP et de la récupération de maintenance."""

from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser, Permission
from django.contrib.sessions.models import Session
from django.contrib.staticfiles.views import serve
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, OperationalError, transaction
from django.http import JsonResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import path, re_path, reverse
from django.utils import timezone

from config.urls import urlpatterns as application_urls
from reconciliation.models import Campaign, LineReview, ReviewEvent

from .middleware import MaintenanceMiddleware
from .models import MaintenanceEvent, MaintenanceState
from .services import can_manage, current_state, transition


def probe(request):
    """Retourne la méthode reçue pour vérifier que le middleware laisse réellement atteindre la vue."""
    return JsonResponse({"method": request.method})


urlpatterns = [path("api/maintenance-test/", probe, name="maintenance-test-probe"),
               re_path(r"^maintenance-test-static/(?P<path>.*)$", serve), *application_urls]


@override_settings(ROOT_URLCONF="maintenance.tests")
class MaintenanceTests(TestCase):
    """Exerce les routes réelles et une API témoin sur une base de test, sans données locales."""

    @classmethod
    def setUpTestData(cls):
        """Crée des comptes distinguant privilèges métier, staff et permission dédiée."""
        user = get_user_model()
        cls.regular = user.objects.create_user("regular", password="test-password")
        cls.global_user = user.objects.create_user("global", is_staff=True, password="test-password")
        cls.manager = user.objects.create_user("manager", is_staff=True, password="test-password")
        cls.root = user.objects.create_superuser("root", password="test-password")
        cls.nonstaff = user.objects.create_user("nonstaff", password="test-password")
        permission = Permission.objects.get(content_type__app_label="maintenance", codename="change_maintenancestate")
        cls.manager.user_permissions.add(permission)
        cls.nonstaff.user_permissions.add(permission)

    def set_state(self, state, message="Message de maintenance", planned_at=None):
        """Applique une transition autorisée sur la base jetable et retourne le nouvel état."""
        transition(state=state, message=message, planned_at=planned_at, version=current_state().version, actor=self.manager)
        return current_state()

    def test_normal_does_not_change_business_routes_or_login(self):
        """NORMAL conserve connexion, consultation et POST/API ; aucune configuration n'est écrite à la lecture."""
        self.assertEqual(current_state().state, "NORMAL")
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)
        self.client.force_login(self.regular)
        self.assertEqual(self.client.get(reverse("projects:portfolio")).status_code, 200)
        self.assertEqual(self.client.post(reverse("maintenance-test-probe")).json(), {"method": "POST"})
        self.assertEqual(current_state().version, 0)
        self.assertEqual(MaintenanceEvent.objects.count(), 0)

    def test_scheduled_banner_and_past_date_do_not_activate(self):
        """Une programmation passée reste informative ; le bandeau apparaît dans l'application et l'administration."""
        planned = timezone.now() - timezone.timedelta(days=1)
        self.set_state("SCHEDULED", "Travaux ce soir", planned)
        self.client.force_login(self.regular)
        response = self.client.get(reverse("projects:portfolio"))
        self.assertContains(response, "Maintenance programmée")
        self.assertContains(response, "Travaux ce soir")
        self.assertEqual(self.client.post(reverse("maintenance-test-probe")).status_code, 200)
        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse("admin:index")), "Maintenance programmée")
        self.assertEqual(current_state().state, "SCHEDULED")

    def test_active_blocks_all_business_methods_and_roles(self):
        """GET/POST/API et URL alternatives sont bloqués, même pour un administrateur hors pilotage."""
        self.set_state("ACTIVE")
        paths = [reverse("projects:portfolio"), reverse("imports:index"),
                 reverse("reconciliation:review-detail", args=[999]),
                 reverse("reconciliation:inventory-detail", args=[999]),
                 reverse("projects:portfolio-import"), reverse("maintenance-test-probe"),
                 reverse("login"), "/admin/accounts/user/", "/api/unknown/", "/imports//"]
        before = (Campaign.objects.count(), LineReview.objects.count(), ReviewEvent.objects.count())
        for user in (None, self.regular, self.global_user, self.manager, self.root):
            client = Client()
            if user:
                client.force_login(user)
            for target in paths:
                for method in ("get", "post", "put", "delete", "patch", "head", "options"):
                    with self.subTest(user=user, target=target, method=method):
                        response = getattr(client, method)(target)
                        self.assertEqual(response.status_code, 503)
                        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(before, (Campaign.objects.count(), LineReview.objects.count(), ReviewEvent.objects.count()))

    def test_permissions_are_not_business_global_or_staff_alone(self):
        """Seuls staff avec permission dédiée et superutilisateurs staff peuvent piloter."""
        for user, allowed in ((self.regular, False), (self.global_user, False),
                              (self.nonstaff, False), (self.manager, True), (self.root, True)):
            self.assertEqual(can_manage(user), allowed)
            if not allowed:
                with self.assertRaises(PermissionDenied):
                    transition(state="ACTIVE", message="", planned_at=None, version=0, actor=user)
        self.assertTrue(self.global_user.is_global_admin)
        self.client.force_login(self.global_user)
        target = reverse("admin:maintenance-pilot")
        self.assertEqual(self.client.get(target).status_code, 403)
        self.assertEqual(self.client.post(target, {"state": "ACTIVE", "version": 0, "confirm_active": "on"}).status_code, 403)
        self.set_state("ACTIVE")
        self.assertEqual(self.client.post(target, {"state": "NORMAL", "version": 1}).status_code, 503)

    def test_activation_confirmation_csrf_audit_and_reopening(self):
        """Le panneau exige POST, CSRF et confirmation ; chaque changement est immédiatement visible et audité."""
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.manager)
        target = reverse("admin:maintenance-pilot")
        self.assertEqual(client.get(target).status_code, 200)
        payload = {"state": "ACTIVE", "version": 0, "message": "Déploiement"}
        self.assertEqual(client.post(target, payload).status_code, 403)
        token = client.cookies["csrftoken"].value
        response = client.post(target, {**payload, "csrfmiddlewaretoken": token})
        self.assertContains(response, "Confirmez explicitement")
        self.assertEqual(current_state().state, "NORMAL")
        response = client.post(target, {**payload, "confirm_active": "on", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(current_state().state, "ACTIVE")
        self.assertEqual(client.get(reverse("admin:index")).status_code, 200)
        self.assertContains(client.get(target), "Déploiement")
        response = client.post(target, {"state": "NORMAL", "version": 1, "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(current_state().state, "NORMAL")
        events = list(MaintenanceEvent.objects.order_by("pk"))
        self.assertEqual([(event.previous_state, event.next_state) for event in events], [("NORMAL", "ACTIVE"), ("ACTIVE", "NORMAL")])
        self.assertEqual(events[0].actor_id, self.manager.pk)
        self.assertEqual(events[0].message, "Déploiement")

    def test_stale_submission_does_not_overwrite_or_append_audit(self):
        """Un formulaire ancien ne remplace pas une transition concurrente."""
        self.set_state("SCHEDULED")
        self.client.force_login(self.manager)
        response = self.client.post(reverse("admin:maintenance-pilot"), {"state": "NORMAL", "version": 0})
        self.assertContains(response, "état a changé")
        self.assertEqual(current_state().state, "SCHEDULED")
        self.assertEqual(MaintenanceEvent.objects.count(), 1)

    def test_session_survives_active_then_normal(self):
        """Une session encore valide retrouve son accès sans déconnexion ni suppression."""
        self.client.force_login(self.regular)
        key = self.client.session.session_key
        self.set_state("ACTIVE")
        self.assertEqual(self.client.get(reverse("projects:portfolio")).status_code, 503)
        self.assertTrue(Session.objects.filter(session_key=key).exists())
        self.set_state("NORMAL")
        response = self.client.get(reverse("projects:portfolio"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.wsgi_request.user.pk, self.regular.pk)
        self.assertEqual(self.client.session.session_key, key)

    def test_recovery_login_is_restricted_and_csrf_protected(self):
        """La récupération n'ouvre pas de session aux comptes métier et protège aussi son POST."""
        self.set_state("ACTIVE")
        client = Client(enforce_csrf_checks=True)
        target = reverse("maintenance-access")
        self.assertEqual(client.get(target).status_code, 503)
        self.assertEqual(client.post(target, {"username": "manager", "password": "test-password"}).status_code, 403)
        token = client.cookies["csrftoken"].value
        response = client.post(target, {"username": "global", "password": "test-password", "csrfmiddlewaretoken": token})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("_auth_user_id", client.session)
        response = client.post(target, {"username": "manager", "password": "test-password", "csrfmiddlewaretoken": token,
                                        "next": "https://example.org/"})
        self.assertRedirects(response, reverse("admin:maintenance-pilot"))
        self.assertEqual(client.get(reverse("imports:index")).status_code, 503)

    def test_configuration_absent_is_normal_without_creation(self):
        """L'absence de ligne initialise logiquement NORMAL sans écrire à chaque consultation."""
        MaintenanceState.objects.all().delete()
        with self.assertNumQueries(1):
            self.assertEqual(current_state().state, "NORMAL")
        self.assertEqual(MaintenanceState.objects.count(), 0)
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)

    def test_configuration_database_failure_returns_standalone_503(self):
        """Une table absente ou une base indisponible produit un 503 journalisé, sans rendu dépendant de la base."""
        for message in ("no such table", "database unavailable"):
            with patch("maintenance.middleware.current_state", side_effect=OperationalError(message)):
                with self.assertLogs("maintenance.middleware", level="ERROR"):
                    response = self.client.get(reverse("login"))
                self.assertContains(response, "service est temporairement indisponible", status_code=503)
                self.assertNotContains(response, message, status_code=503)
                self.assertNotIn("Retry-After", response)
                self.assertEqual(self.client.get(reverse("maintenance-liveness")).status_code, 200)

    def test_full_database_failure_preserves_existing_session_cookie(self):
        """Une panne totale avec cookie existant ne déclenche pas de lecture de session en sortie du 503."""
        self.client.force_login(self.regular)
        key = self.client.session.session_key
        with patch("django.db.backends.utils.CursorWrapper.execute", side_effect=OperationalError("database unavailable")):
            with self.assertLogs("maintenance.middleware", level="ERROR"):
                response = self.client.get(reverse("projects:portfolio"))
            self.assertEqual(response.status_code, 503)
            self.assertNotIn("sessionid", response.cookies)
            self.assertEqual(self.client.get(reverse("maintenance-liveness")).status_code, 200)
        self.assertEqual(self.client.session.session_key, key)

    def test_singleton_constraint_and_atomic_audit(self):
        """La base interdit plusieurs états et annule une transition dont l'audit échoue."""
        with self.assertRaises(IntegrityError), transaction.atomic():
            MaintenanceState.objects.create(pk=2)
        with patch("maintenance.services.MaintenanceEvent.objects.create", side_effect=IntegrityError("audit")):
            with self.assertRaises(IntegrityError):
                self.set_state("ACTIVE")
        self.assertEqual(current_state().state, "NORMAL")
        self.assertEqual(current_state().version, 0)

    def test_save_failure_is_visible(self):
        """Une sauvegarde refusée affiche une erreur lisible et ne prétend pas avoir activé le mode."""
        self.client.force_login(self.manager)
        with patch("maintenance.admin.transition", side_effect=OperationalError("locked")):
            with self.assertLogs("maintenance.admin", level="ERROR"):
                response = self.client.post(reverse("admin:maintenance-pilot"),
                    {"state": "ACTIVE", "version": 0, "confirm_active": "on"})
        self.assertContains(response, "Enregistrement impossible", status_code=503)
        self.assertEqual(current_state().state, "NORMAL")

    def test_workers_read_fresh_shared_state_without_configuration_writes(self):
        """Deux instances de middleware relisent le même état à chaque appel, sans cache local ni écriture."""
        workers = [MaintenanceMiddleware(probe), MaintenanceMiddleware(probe)]
        factory = RequestFactory()
        request = factory.get(reverse("maintenance-test-probe"))
        request.user = AnonymousUser()
        for worker in workers:
            with self.assertNumQueries(1):
                self.assertEqual(worker(request).status_code, 200)
        self.set_state("ACTIVE")
        for worker in workers:
            with self.assertNumQueries(1):
                self.assertEqual(worker(request).status_code, 503)
        self.set_state("NORMAL")
        self.assertEqual(workers[0](request).status_code, 200)

    def test_page_is_autonomous_escaped_and_liveness_is_not_business_access(self):
        """La page mobile autonome échappe le message et n'ouvre aucun accès métier via la sonde."""
        self.set_state("ACTIVE", "<script>private</script>")
        response = self.client.get(reverse("projects:portfolio"))
        self.assertContains(response, "viewport", status_code=503)
        self.assertContains(response, "&lt;script&gt;private&lt;/script&gt;", status_code=503)
        self.assertNotContains(response, "<script>", status_code=503)
        self.assertNotContains(response, "stylesheet", status_code=503)
        self.assertEqual(self.client.get(reverse("maintenance-liveness")).json(), {"status": "alive"})
        self.assertEqual(self.client.post(reverse("maintenance-liveness")).status_code, 503)
        self.assertEqual(self.client.get(reverse("maintenance-liveness") + "extra/").status_code, 503)

    def test_recovery_command_is_audited_and_requires_reason(self):
        """La commande serveur remet NORMAL avec motif et audit ; aucun accès HTTP n'appelle cette commande."""
        self.set_state("ACTIVE")
        with self.assertRaises(CommandError):
            call_command("maintenance_normal", reason=" ", stdout=StringIO())
        output = StringIO()
        call_command("maintenance_normal", reason="Récupération après incident", stdout=output)
        self.assertEqual(current_state().state, "NORMAL")
        event = MaintenanceEvent.objects.latest("pk")
        self.assertEqual(event.actor_label, "Exploitation serveur")
        self.assertIsNone(event.actor)
        self.assertEqual(event.reason, "Récupération après incident")
        with self.assertRaises(ValidationError):
            transition(state="ACTIVE", message="", planned_at=None, version=current_state().version, recovery_reason="incident")

    def test_static_collection_and_debug_asset_route(self):
        """Vérifie collectstatic en dossier temporaire et le passage des seuls assets GET en mode local."""
        self.set_state("ACTIVE")
        with TemporaryDirectory() as folder:
            with override_settings(STATIC_ROOT=folder, DEBUG=False, STORAGES={
                "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
                "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"}}):
                call_command("collectstatic", interactive=False, verbosity=0, stdout=StringIO())
                self.assertTrue((Path(folder) / "staticfiles.json").is_file())
                self.assertTrue((Path(folder) / "admin/css/base.css").is_file())
                self.assertContains(self.client.get(reverse("projects:portfolio")), "Atlas × Sage X3", status_code=503)
        with override_settings(DEBUG=True):
            with self.assertNumQueries(0):
                response = self.client.get("/maintenance-test-static/css/app.css")
                self.assertEqual(response.status_code, 200)
                response.close()
            self.assertEqual(self.client.post("/maintenance-test-static/css/app.css").status_code, 503)
