import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from .config import config
from .logger import logger


# Convert sync database URL to async
# sqlite:// -> sqlite+aiosqlite://
# postgresql:// -> postgresql+psycopg://
def get_async_database_url(url: str) -> str:
    if url.startswith("sqlite://"):
        return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


connect_args = {}
pool_config = {}

if config.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
elif config.DATABASE_URL.startswith("postgresql"):
    # When using external pooling (PgBouncer/Neon), use NullPool or minimal pooling
    # Check if URL contains "-pooler" (Neon's PgBouncer indicator)
    if "-pooler" in config.DATABASE_URL:
        # Using external pooler - disable SQLAlchemy's internal pooling
        from sqlalchemy.pool import NullPool

        pool_config["poolclass"] = NullPool
        logger.info("Detected external connection pooler, using NullPool")
    else:
        # Direct connection - use SQLAlchemy's pooling with conservative settings
        pool_config["pool_size"] = 5
        pool_config["max_overflow"] = 10
        pool_config["pool_pre_ping"] = True
        logger.info(
            "Using SQLAlchemy connection pooling (pool_size=5, max_overflow=10)"
        )

engine: AsyncEngine = create_async_engine(
    get_async_database_url(config.DATABASE_URL),
    echo=config.DATABASE_ECHO,
    connect_args=connect_args,
    **pool_config,
)


@asynccontextmanager
async def get_session(
    max_retries: int = 3, retry_delay: float = 0.1
) -> AsyncGenerator[AsyncSession, None]:
    """Get an async database session with automatic retry logic for connection errors.

    Retries session creation if it fails due to OperationalError.
    Note: This does not retry operations performed inside the with block -
    the pool_pre_ping setting on the engine handles stale connections.

    Args:
        max_retries: Maximum number of retry attempts for session creation (default: 3)
        retry_delay: Initial delay between retries in seconds (default: 0.1)

    Yields:
        AsyncSession: A SQLAlchemy async database session

    Raises:
        OperationalError: If session creation fails after all retry attempts
    """
    retries = 0

    # Retry session creation
    while retries <= max_retries:
        try:
            session = AsyncSession(engine, expire_on_commit=False)
            # Yield the session and ensure cleanup
            try:
                yield session
            finally:
                await session.close()
            return  # Successfully completed
        except OperationalError as e:
            retries += 1

            if retries > max_retries:
                logger.error(
                    "Database session creation failed after %d retries: %s",
                    max_retries,
                    str(e),
                )
                raise

            # Exponential backoff with async sleep
            delay = retry_delay * (2 ** (retries - 1))
            logger.warning(
                "Database session creation failed (attempt %d/%d), retrying in %.2fs: %s",
                retries,
                max_retries,
                delay,
                str(e),
            )
            await asyncio.sleep(delay)
