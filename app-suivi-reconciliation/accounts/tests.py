"""Non-régression de l'authentification et de l'expiration des sessions."""

from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.contrib.sessions.models import Session
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import User


class SessionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username="session-user", password="test-password")

    def setUp(self):
        self.response = self.client.post(
            reverse("login"),
            {"username": "session-user", "password": "test-password"},
        )

    def test_login_uses_browser_session_cookie(self):
        self.assertRedirects(self.response, reverse("dashboard:index"))
        self.assertEqual(settings.SESSION_COOKIE_AGE, 600)
        self.assertIs(settings.SESSION_SAVE_EVERY_REQUEST, True)
        self.assertIs(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE, True)
        cookie = self.response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertEqual(cookie["expires"], "")
        self.assertEqual(cookie["max-age"], "")

    def test_requests_renew_session_and_inactivity_redirects_to_login(self):
        session_key = self.client.session.session_key
        initial_expiry = Session.objects.get(session_key=session_key).expire_date
        renewed_at = initial_expiry - timedelta(seconds=1)
        protected_url = reverse("dashboard:index")

        with patch("django.utils.timezone.now", return_value=renewed_at):
            response = self.client.get(protected_url)
        self.assertEqual(response.status_code, 200)
        renewed_expiry = Session.objects.get(session_key=session_key).expire_date
        self.assertEqual(renewed_expiry, renewed_at + timedelta(seconds=600))

        with patch("django.utils.timezone.now", return_value=initial_expiry + timedelta(seconds=1)):
            response = self.client.get(protected_url)
        self.assertEqual(response.status_code, 200)
        final_expiry = Session.objects.get(session_key=session_key).expire_date

        with patch("django.utils.timezone.now", return_value=final_expiry + timedelta(seconds=1)):
            response = self.client.get(protected_url)
        self.assertRedirects(
            response, f"{reverse('login')}?next={protected_url}", fetch_redirect_response=False
        )

    def test_logout_invalidates_session(self):
        session_key = self.client.session.session_key
        response = self.client.post(reverse("logout"))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Session.objects.filter(session_key=session_key).exists())
        protected_url = reverse("dashboard:index")
        self.assertRedirects(
            self.client.get(protected_url),
            f"{reverse('login')}?next={protected_url}",
            fetch_redirect_response=False,
        )
