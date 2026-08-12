from sqlalchemy.pool import AsyncAdaptedQueuePool, NullPool
from synapsekb.config import Settings
from synapsekb.database.session import create_database_engine


def test_api_database_engine_uses_connection_pool() -> None:
    engine = create_database_engine(Settings(database_pool_mode="pooled"))

    assert isinstance(engine.sync_engine.pool, AsyncAdaptedQueuePool)


def test_worker_database_engine_does_not_reuse_connections_between_event_loops() -> None:
    engine = create_database_engine(Settings(database_pool_mode="null"))

    assert isinstance(engine.sync_engine.pool, NullPool)
