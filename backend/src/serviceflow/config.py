import os

from serviceflow.infrastructure.otel import Telemetry
from serviceflow.infrastructure.policy_ingestion import build_default_policy_retriever
from serviceflow.infrastructure.qdrant_policy_store import PolicyRetriever
from serviceflow.infrastructure.redis_store import RedisStore

DEFAULT_DATABASE_URL = "sqlite+aiosqlite:///serviceflow.db"


def get_database_url() -> str:
    return os.getenv("SERVICEFLOW_DATABASE_URL", DEFAULT_DATABASE_URL)


def get_redis_store() -> RedisStore | None:
    url = os.getenv("SERVICEFLOW_REDIS_URL")
    if not url:
        return None
    return RedisStore.from_url(url)


def get_policy_retriever(telemetry: Telemetry | None = None) -> PolicyRetriever:
    return build_default_policy_retriever(telemetry=telemetry)
