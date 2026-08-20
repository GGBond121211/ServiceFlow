import os

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///serviceflow.db"


def get_database_url() -> str:
    return os.getenv("SERVICEFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)
