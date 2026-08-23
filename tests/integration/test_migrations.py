import os

import pytest
from sqlalchemy import create_engine, text
from testcontainers.postgres import PostgresContainer


@pytest.mark.integration
def test_initial_migration_with_pgvector() -> None:
    if os.getenv("RUN_DOCKER_TESTS") != "1":
        pytest.skip("set RUN_DOCKER_TESTS=1 to run Docker integration tests")
    from alembic import command
    from alembic.config import Config
    from synapsekb.config import get_settings

    with PostgresContainer("pgvector/pgvector:0.8.0-pg16") as postgres:
        url = postgres.get_connection_url().replace("postgresql+psycopg2", "postgresql+asyncpg")
        previous = os.environ.get("DATABASE_URL")
        os.environ["DATABASE_URL"] = url
        get_settings.cache_clear()
        try:
            config = Config("alembic.ini")
            command.upgrade(config, "head")
            command.downgrade(config, "0013_agent_tool_tokens")
            command.upgrade(config, "head")
            sync_url = url.replace("+asyncpg", "+psycopg")
            with create_engine(sync_url).connect() as connection:
                assert connection.scalar(text("SELECT count(*) FROM users")) == 0
                assert (
                    connection.scalar(text("SELECT version_num FROM alembic_version"))
                    == "0015_kb_deletion"
                )
                assert (
                    connection.scalar(text("SELECT to_regclass('wiki_document_states')"))
                    == "wiki_document_states"
                )
                assert (
                    connection.scalar(
                        text("SELECT to_regclass('knowledge_base_deletion_jobs')")
                    )
                    == "knowledge_base_deletion_jobs"
                )
        finally:
            if previous is None:
                os.environ.pop("DATABASE_URL", None)
            else:
                os.environ["DATABASE_URL"] = previous
            get_settings.cache_clear()
