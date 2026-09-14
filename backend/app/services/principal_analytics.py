"""Expose a stable analytics façade while ClickHouse query ownership stays in the repository."""

from backend.app.repositories.user_repository import UserRepository


def build_principal_analytics():
    return UserRepository().analytics()
