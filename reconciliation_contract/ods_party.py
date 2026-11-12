"""Politique versionnée des seuls tiers absents dans les clés ODS/ODG."""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
from inspect import isgeneratorfunction, signature

POLICY = "missing-equivalent-v1"
ABSENT = "<TIERS_ABSENT_ODS>"
_enabled = ContextVar("ods_absent_party_keys", default=False)


def party_key(value):
    """Retourne la clé technique du tiers déjà normalisé ; ne change jamais une valeur source."""
    return ABSENT if _enabled.get() and value in ("", "NA") else value


@contextmanager
def party_scope(enabled):
    """Active la politique dans le contexte courant puis le restaure, même en cas d'exception."""
    token = _enabled.set(enabled)
    try:
        yield
    finally:
        _enabled.reset(token)


def policy_enabled(owner):
    """Lit la politique d'un en-tête, d'une campagne ou d'une ligne sans modifier cet objet."""
    if isinstance(owner, dict):
        metadata = owner
    else:
        campaign = owner if hasattr(owner, "metadata") else owner.campaign
        metadata = campaign.metadata if campaign is not None else {}
    return metadata.get("ods_party_policy") == POLICY


def party_context(*, new=False):
    """Décore une opération synchrone selon sa campagne, ou force la politique du nouvel export.

    Pour un générateur, le contexte est restauré avant chaque yield : consommer
    partiellement un itérateur ne contamine pas un autre calcul ou une ancienne campagne.
    """
    def decorate(function):
        """Retourne l'enveloppe adaptée au type de la fonction en conservant ses métadonnées."""
        first_parameter = next(iter(signature(function).parameters))
        if isgeneratorfunction(function):
            @wraps(function)
            def generate(*args, **kwargs):
                """Avance l'itérateur sous sa politique, puis restaure le contexte avant de rendre une valeur."""
                owner = args[0] if args else kwargs.get(first_parameter)
                enabled = new or owner is not None and policy_enabled(owner)
                iterator = function(*args, **kwargs)
                try:
                    while True:
                        with party_scope(enabled):
                            try:
                                value = next(iterator)
                            except StopIteration:
                                return
                        yield value
                finally:
                    with party_scope(enabled):
                        iterator.close()
            return generate

        @wraps(function)
        def run(*args, **kwargs):
            """Exécute une opération sous sa politique ; propage erreurs et résultat sans laisser d'état global."""
            owner = args[0] if args else kwargs.get(first_parameter)
            with party_scope(new or owner is not None and policy_enabled(owner)):
                return function(*args, **kwargs)
        return run
    return decorate
