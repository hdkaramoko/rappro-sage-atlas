"""Verrou partagé et empreinte du flux de transfert."""

import hashlib
from unittest import skipUnless
from unittest.mock import MagicMock, patch

from django.db import connection
from django.test import SimpleTestCase, TransactionTestCase

from .jobs import worker_lock
from .upload_handlers import HashedTemporaryFileUploadHandler


class ImportInfrastructureTests(SimpleTestCase):
    def test_upload_digest_tracks_received_chunks(self):
        handler = HashedTemporaryFileUploadHandler()
        handler.new_file("bundle", "campaign.jsonl", "application/json", 6)
        handler.receive_data_chunk(b"abc", 0)
        handler.receive_data_chunk(b"def", 3)
        uploaded = handler.file_complete(6)
        try:
            self.assertEqual(uploaded.sha256, hashlib.sha256(b"abcdef").hexdigest())
            self.assertEqual(uploaded.read(), b"abcdef")
        finally:
            uploaded.close()

    def test_postgres_lock_released_on_failure(self):
        db = MagicMock(vendor="postgresql")
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (True,)
        with patch("imports_app.jobs.connection", db):
            with self.assertRaisesRegex(ValueError, "failure"), worker_lock():
                raise ValueError("failure")
        self.assertEqual(
            cursor.execute.call_args_list[0].args[0], "SELECT pg_try_advisory_lock(%s)"
        )
        self.assertEqual(cursor.execute.call_args_list[-1].args[0], "SELECT pg_advisory_unlock(%s)")

    def test_postgres_busy_lock_rejects_import(self):
        db = MagicMock(vendor="postgresql")
        cursor = db.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (False,)
        with (
            patch("imports_app.jobs.connection", db),
            self.assertRaises(BlockingIOError),
            worker_lock(),
        ):
            self.fail("Concurrent importer entered the critical section")
        cursor.execute.assert_called_once()

    def test_postgres_lock_cannot_be_reentered_by_same_session(self):
        db = MagicMock(vendor="postgresql")
        db.cursor.return_value.__enter__.return_value.fetchone.return_value = (True,)
        with patch("imports_app.jobs.connection", db), worker_lock():
            with self.assertRaises(BlockingIOError), worker_lock():
                self.fail("Reentrant importer entered the critical section")


@skipUnless(connection.vendor == "postgresql", "Requires a PostgreSQL test database")
class PostgreSQLLockTests(TransactionTestCase):
    def test_independent_session_cannot_import_until_lock_is_released(self):
        other = connection.copy()
        try:
            with worker_lock():
                with other.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s)", [734129826])
                    self.assertFalse(cursor.fetchone()[0])
            with other.cursor() as cursor:
                cursor.execute("SELECT pg_try_advisory_lock(%s)", [734129826])
                self.assertTrue(cursor.fetchone()[0])
                cursor.execute("SELECT pg_advisory_unlock(%s)", [734129826])
        finally:
            other.close()
