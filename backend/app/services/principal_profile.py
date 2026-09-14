"""Keep profile construction at the repository boundary for one consistent user view."""

from backend.app.repositories.user_repository import UserRepository


def build_principal_profile(principal: str, start_ms=None, end_ms=None):
    return UserRepository().profile(principal, start_ms, end_ms)
