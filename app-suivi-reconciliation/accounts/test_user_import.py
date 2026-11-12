"""Recette de l'import Excel de comptes, avec secrets synthétiques exclusivement en mémoire."""

import json
import time
from io import BytesIO
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.admin.models import LogEntry
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, OperationalError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from projects.models import Project, ProjectPortfolio
from projects.portfolio_import import import_portfolios
from reconciliation import test_campaigns as fixtures
from reconciliation.models import Campaign, LineReview
from reconciliation.review import signature
from reconciliation.review_import import import_bundle

from .user_import import HEADERS, create_users, parse_users, preview_token, verify_preview

SECRET = "Synthetic-Only-Pass-000017!"


def workbook_file(rows=None, *, header=HEADERS, sheet="data", name="users_mdp.xlsx"):
    """Retourne un classeur synthétique mémoire au format réel, sans fichier de secrets sur disque."""
    book = Workbook()
    page = book.active
    page.title = sheet
    page.append(header)
    for row in rows if rows is not None else [("Dupont", "Alice", "alice-import", SECRET)]:
        page.append(row)
    stream = BytesIO()
    book.save(stream)
    book.close()
    return SimpleUploadedFile(name, stream.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


class UserImportTests(TestCase):
    """Teste le parcours réel Admin, ses protections et les accès métier après création."""

    @classmethod
    def setUpTestData(cls):
        """Crée administrateur, staff sans permission et opérateur avec permission de création existante."""
        model = get_user_model()
        cls.admin = model.objects.create_superuser("root-import", password="root-test")
        cls.staff = model.objects.create_user("staff-import", is_staff=True)
        cls.regular = model.objects.create_user("regular-import")
        cls.creator = model.objects.create_user("creator-import", is_staff=True)
        cls.creator.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="add_user"))

    def setUp(self):
        """Connecte l'administrateur et prépare l'URL d'import sans modifier les données réelles."""
        self.client.force_login(self.admin)
        self.url = reverse("admin:accounts-user-import")

    def import_one(self, username="alice-import"):
        """Exerce aperçu puis confirmation avec deux téléversements identiques et retourne le compte créé."""
        raw = workbook_file([("Dupont", "Alice", username, SECRET)]).read()
        preview = self.client.post(self.url, {"action": "preview", "workbook": SimpleUploadedFile("users_mdp.xlsx", raw)})
        self.assertEqual(preview.status_code, 200)
        token = preview.context["token"]
        self.assertTrue(token)
        result = self.client.post(self.url, {"action": "confirm", "token": token, "workbook": SimpleUploadedFile("users_mdp.xlsx", raw)})
        self.assertEqual(result.context["result"]["created"], [2])
        return get_user_model().objects.get(username=username)

    def campaign_fixture(self):
        """Charge deux projets fictifs pour tester les accès directs et l'affectation ultérieure."""
        folder = TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = folder
        a, b = fixtures.atlas(), fixtures.atlas("B", **{"Code projet": "Q"})
        path = fixtures.CampaignTests.bundle(self, inventory=[a, b], proposals=[fixtures.proposal([a]), fixtures.proposal([b], key="other", project="Q")])
        import_bundle(path)
        return Campaign.objects.get(is_current=True)

    def test_preview_confirm_hash_and_no_secrets(self):
        """L'aperçu ne crée rien, ne révèle aucun secret ; la confirmation crée deux comptes classiques hachés."""
        rows = [("Dupont", "Alice", "alice-import", SECRET), ("Martin", "Bob", "bob-import", "00000123")]
        raw = workbook_file(rows).read()
        with patch("django.core.files.uploadedfile.TemporaryUploadedFile.__init__", side_effect=AssertionError("Secret sur disque")):
            with self.assertNoLogs("accounts", level="DEBUG"):
                preview = self.client.post(self.url, {"action": "preview", "workbook": SimpleUploadedFile("users_mdp.xlsx", raw)})
                self.assertEqual(preview.context["create_count"], 2)
                self.assertFalse(get_user_model().objects.filter(username="alice-import").exists())
                token = preview.context["token"]
                response = self.client.post(self.url, {"action": "confirm", "token": token,
                    "is_staff": "on", "is_superuser": "on", "geography": "GLOBAL",
                    "workbook": SimpleUploadedFile("users_mdp.xlsx", raw)})
        for secret in (SECRET, "00000123"):
            self.assertNotContains(preview, secret)
            self.assertNotContains(response, secret)
            self.assertNotIn(secret, json.dumps(dict(self.client.session)))
            self.assertNotIn(secret, json.dumps(list(LogEntry.objects.values("object_repr", "change_message"))))
        self.assertEqual(LogEntry.objects.filter(user=self.admin).count(), 2)
        self.assertEqual(response.context["result"]["created"], [2, 3])
        for username, password in (("alice-import", SECRET), ("bob-import", "00000123")):
            user = get_user_model().objects.get(username=username)
            self.assertTrue(user.check_password(password))
            self.assertNotEqual(user.password, password)
            self.assertTrue(user.is_active)
            self.assertFalse(user.is_staff or user.is_superuser or user.is_global_admin)
            self.assertEqual(user.geography, "")
            self.assertFalse(user.portfolio_entries.exists())
            self.assertFalse(user.groups.exists() or user.user_permissions.exists())

    def test_existing_user_and_repeat_never_overwrite(self):
        """Deux confirmations du même fichier ignorent les comptes déjà présents sans toucher leurs mots de passe."""
        raw = workbook_file().read()
        preview = self.client.post(self.url, {"action": "preview", "workbook": SimpleUploadedFile("u.xlsx", raw)})
        payload = {"action": "confirm", "token": preview.context["token"]}
        self.client.post(self.url, {**payload, "workbook": SimpleUploadedFile("u.xlsx", raw)})
        user = get_user_model().objects.get(username="alice-import")
        user.set_password("Changed-locally")
        user.save(update_fields=["password"])
        response = self.client.post(self.url, {**payload, "workbook": SimpleUploadedFile("u.xlsx", raw)})
        self.assertEqual(response.context["result"], {"created": [], "ignored": [2]})
        user.refresh_from_db()
        self.assertTrue(user.check_password("Changed-locally"))
        self.assertEqual(get_user_model().objects.filter(username="alice-import").count(), 1)

    def test_invalid_rows_reject_whole_file(self):
        """Les cellules vides, numériques, formules et doublons interdisent toute création partielle."""
        base = ("Dupont", "Alice", "alice-import", SECRET)
        invalids = [("Martin", "Bob", "alice-import", SECRET), ("Martin", "", "bob", SECRET),
                    ("Martin", "Bob", "bob", 123), ("Martin", "Bob", 123, SECRET),
                    ("Martin", "Bob", "bob", "=1+1"), ("Martin", "Bob", " bob ", SECRET),
                    ("Martin", "Bob", "bad name", SECRET)]
        for invalid in invalids:
            with self.subTest(kind=invalid[2]):
                response = self.client.post(self.url, {"action": "preview", "workbook": workbook_file([base, invalid])})
                self.assertTrue(response.context["errors"])
                self.assertFalse(response.context["token"])
                self.assertFalse(get_user_model().objects.filter(username="alice-import").exists())
                self.assertNotContains(response, SECRET)

    def test_sheet_headers_corruption_and_size(self):
        """Les erreurs de format exact et limites configurables produisent des messages sans compte créé."""
        files = [workbook_file(sheet="Data"), workbook_file(header=("nom", "prenom", "username", "mdp")),
                 workbook_file(header=("nom", "prénom", "username", "password")),
                 SimpleUploadedFile("u.xlsx", b"corrupted"), workbook_file(name="u.xls")]
        for uploaded in files:
            response = self.client.post(self.url, {"action": "preview", "workbook": uploaded})
            self.assertTrue(response.context["errors"])
        with override_settings(USER_IMPORT_MAX_BYTES=1024):
            response = self.client.post(self.url, {"action": "preview", "workbook": workbook_file()})
            self.assertTrue(response.context["errors"])
        with override_settings(USER_IMPORT_MAX_ROWS=1):
            response = self.client.post(self.url, {"action": "preview", "workbook": workbook_file([
                ("Dupont", "Alice", "a", SECRET), ("Martin", "Bob", "b", SECRET)])})
            self.assertTrue(response.context["errors"])
        self.assertFalse(get_user_model().objects.filter(username="alice-import").exists())

    def test_blank_lines_and_preview_escaping(self):
        """Les lignes vides sont ignorées et les noms sont échappés dans l'aperçu."""
        response = self.client.post(self.url, {"action": "preview", "workbook": workbook_file([
            (None, None, None, None), ("<script>name</script>", "Alice", "alice-import", SECRET)])})
        self.assertEqual(response.context["create_count"], 1)
        self.assertContains(response, "&lt;script&gt;name&lt;/script&gt;")
        self.assertNotContains(response, "<script>name</script>")

    def test_permissions_and_csrf_before_processing(self):
        """Un POST direct exige staff avec droit add_user et un jeton CSRF valide."""
        for user in (self.regular, self.staff):
            self.client.force_login(user)
            for method in ("get", "post"):
                response = getattr(self.client, method)(self.url)
                self.assertIn(response.status_code, (302, 403))
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.creator)
        self.assertEqual(client.get(self.url).status_code, 200)
        self.assertEqual(client.post(self.url, {"action": "preview", "workbook": workbook_file()}).status_code, 403)
        token = client.cookies["csrftoken"].value
        response = client.post(self.url, {"action": "preview", "workbook": workbook_file(), "csrfmiddlewaretoken": token})
        self.assertTrue(response.context["token"])
        anonymous = Client()
        self.assertEqual(anonymous.post(self.url).status_code, 302)

    def test_import_button_respects_existing_permissions(self):
        """Le bouton apparaît dans la liste Admin uniquement avec le droit existant de création."""
        response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertContains(response, self.url)
        self.client.force_login(self.creator)
        self.assertContains(self.client.get(reverse("admin:index")), self.url)
        self.staff.user_permissions.add(Permission.objects.get(content_type__app_label="accounts", codename="view_user"))
        self.client.force_login(self.staff)
        response = self.client.get(reverse("admin:accounts_user_changelist"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.url)
        self.assertNotContains(self.client.get(reverse("admin:index")), self.url)

    def test_maintenance_active_blocks_user_import_too(self):
        """L'import de comptes ne contourne pas la suspension des opérations pendant la maintenance active."""
        from maintenance.services import current_state, transition
        transition(state="ACTIVE", message="Maintenance", planned_at=None,
                   version=current_state().version, actor=self.admin)
        self.assertEqual(self.client.get(self.url).status_code, 503)
        self.assertEqual(self.client.post(self.url, {"action": "preview", "workbook": workbook_file()}).status_code, 503)
        self.assertEqual(self.client.get(reverse("admin:maintenance-pilot")).status_code, 200)

    def test_confirmation_requires_same_file_actor_and_recent_token(self):
        """Une confirmation falsifiée, expirée ou portant sur un autre fichier/acteur est refusée."""
        rows, errors, fingerprint = parse_users(workbook_file())
        token = preview_token(fingerprint, self.admin)
        for actor, digest, value in ((self.creator, fingerprint, token), (self.admin, "other", token), (self.admin, fingerprint, "bad")):
            with self.assertRaises(ValidationError):
                verify_preview(value, digest, actor)
        with patch("django.core.signing.time.time", return_value=time.time() + 601):
            with self.assertRaises(ValidationError):
                verify_preview(token, fingerprint, self.admin)
        response = self.client.post(self.url, {"action": "confirm", "token": token,
            "workbook": workbook_file([("Changed", "Alice", "other-user", SECRET)])})
        self.assertTrue(response.context["errors"])
        self.assertFalse(get_user_model().objects.filter(username="other-user").exists())

    def test_atomic_rollback_on_concurrent_collision(self):
        """Une collision au second compte annule également le premier, sans répercuter le secret SQL."""
        rows, _, _ = parse_users(workbook_file([("Dupont", "Alice", "one", SECRET), ("Martin", "Bob", "two", SECRET)]))
        model = get_user_model()
        save = model.save

        def collide(user, *args, **kwargs):
            """Simule une contrainte concurrente au second compte après sauvegarde du premier."""
            if user.username == "two":
                raise IntegrityError(SECRET)
            return save(user, *args, **kwargs)

        with patch.object(model, "save", collide):
            with self.assertRaises(ValidationError) as error:
                create_users(rows, self.admin)
        self.assertNotIn(SECRET, str(error.exception))
        self.assertFalse(model.objects.filter(username__in=["one", "two"]).exists())

    def test_password_validators_do_not_echo_secret(self):
        """La politique Django reste active et son détail n'expose pas la valeur mdp."""
        with override_settings(AUTH_PASSWORD_VALIDATORS=[{"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator", "OPTIONS": {"min_length": 100}}]):
            response = self.client.post(self.url, {"action": "preview", "workbook": workbook_file()})
        self.assertTrue(response.context["errors"])
        self.assertNotContains(response, SECRET)

    def test_database_error_never_leaks_sql_or_claims_success(self):
        """Une erreur de base est expurgée et le bilan ne prétend pas connaître le résultat du commit."""
        raw = workbook_file().read()
        preview = self.client.post(self.url, {"action": "preview", "workbook": SimpleUploadedFile("u.xlsx", raw)})
        with patch("accounts.user_import_views.create_users", side_effect=OperationalError(SECRET)):
            response = self.client.post(self.url, {"action": "confirm", "token": preview.context["token"],
                "workbook": SimpleUploadedFile("u.xlsx", raw)})
        self.assertContains(response, "Résultat non confirmé")
        self.assertNotContains(response, SECRET)
        self.assertNotContains(response, "Import rejeté : aucun compte créé")

    def test_no_portfolio_no_access_then_existing_portfolio_import(self):
        """Sans portefeuille, listes/détails/actions/exports sont fermés ; l'import existant ouvre seulement P."""
        campaign = self.campaign_fixture()
        user = self.import_one()
        self.client.force_login(user)
        project = Project.objects.get(code="P")
        line = LineReview.objects.get(transaction__project=project)
        inventory = campaign.inventory.get(project_code="P")
        self.assertEqual(self.client.get(reverse("reconciliation:reviews")).context["page"].paginator.count, 0)
        protected = [reverse("reconciliation:review-detail", args=[line.pk]),
                     reverse("reconciliation:inventory-detail", args=[inventory.pk]),
                     reverse("reconciliation:campaign-export", args=[campaign.pk]),
                     reverse("reconciliation:conservation-export"),
                     reverse("reconciliation:accounting-detail", args=[project.pk])]
        for target in protected:
            self.assertEqual(self.client.get(target).status_code, 404)
        self.assertEqual(self.client.post(reverse("reconciliation:review-detail", args=[line.pk]), {"action": "validate"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("reconciliation:inventory-detail", args=[inventory.pk]), {"action": "correct"}).status_code, 404)
        self.assertEqual(self.client.post(reverse("projects:portfolio"), {"project_code": "P"}).status_code, 403)
        self.assertFalse(ProjectPortfolio.objects.filter(user=user).exists())
        self.assertEqual(self.client.get(reverse("dashboard:index")).context["total"], 0)
        portfolio = workbook_file([(user.username, "P")], header=("username", "code projet"), sheet="Portefeuilles")
        report = import_portfolios(portfolio, self.admin)
        self.assertEqual(report.created_count, 1)
        self.assertEqual(self.client.get(reverse("reconciliation:reviews")).context["page"].paginator.count, 1)
        self.assertEqual(self.client.get(reverse("reconciliation:review-detail", args=[line.pk])).status_code, 200)
        other = LineReview.objects.get(transaction__project__code="Q")
        self.assertEqual(self.client.get(reverse("reconciliation:review-detail", args=[other.pk])).status_code, 404)
        values = {name: {"mode": "SET", "value": value} for name, value in {
            "status": "Comptabilisé", "amount": "100", "document": "D", "date": "2026-01-01"}.items()}
        from reconciliation.review import decide
        decide(line.pk, user, state="VALIDATED", values=values, comment="Contrôle synthétique",
               expected_version=line.version, expected_group_version=line.group.version,
               expected_source=signature(line), acknowledge=True)
        line.refresh_from_db()
        self.assertEqual(line.state, "VALIDATED")
        from reconciliation.business import correct_inventory
        correct_inventory(inventory.pk, user, reason="AMOUNT", amount="100",
                          expected_version=inventory.business_version, comment="Correction autorisée synthétique")
        self.assertEqual(self.client.get(reverse("reconciliation:campaign-export", args=[campaign.pk])).status_code, 200)
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("reconciliation:review-detail", args=[other.pk])).status_code, 200)
