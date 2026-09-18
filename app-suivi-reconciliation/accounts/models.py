from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Compte rattaché à une géographie ou administrateur global."""

    geography = models.CharField("géographie", max_length=100, blank=True)

    @property
    def is_global_admin(self) -> bool:
        """Indique si le compte peut consulter toutes les géographies."""
        return self.is_superuser or self.is_staff
