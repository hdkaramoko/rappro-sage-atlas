"""Empreinte calculée pendant la réception, sans seconde lecture dans HTTP."""

import hashlib

from django.core.files.uploadhandler import TemporaryFileUploadHandler


class HashedTemporaryFileUploadHandler(TemporaryFileUploadHandler):
    def new_file(self, *args, **kwargs):
        super().new_file(*args, **kwargs)
        self.digest = hashlib.sha256()

    def receive_data_chunk(self, raw_data, start):
        self.digest.update(raw_data)
        return super().receive_data_chunk(raw_data, start)

    def file_complete(self, file_size):
        uploaded = super().file_complete(file_size)
        uploaded.sha256 = self.digest.hexdigest()
        return uploaded
