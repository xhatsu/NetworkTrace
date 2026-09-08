from backend.app.repositories.user_repository import UserRepository


def build_principal_analytics():
    return UserRepository().analytics()
