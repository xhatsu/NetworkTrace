from backend.app.repositories.user_repository import UserRepository


def build_principal_graph(principal=None, service=None, start_ms=None, end_ms=None):
    return UserRepository().graph(principal, service, start_ms, end_ms)
