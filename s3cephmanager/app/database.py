from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
from app.config import DB_PATH
import logging

log = logging.getLogger("cephs3mgr.db")

engine = create_async_engine(
    f"sqlite+aiosqlite:///{DB_PATH}",
    echo=False,
    connect_args={"check_same_thread": False},
)


class Base(DeclarativeBase):
    pass


AsyncSessionLocal = async_sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# Columns added after initial release that need ALTER TABLE migrations.
# Each entry: (column_name, column_ddl_fragment)
# SQLite has no "ADD COLUMN IF NOT EXISTS", so we try/except each one.
_MIGRATIONS = [
    ("admin_endpoint",  "ALTER TABLE connections ADD COLUMN admin_endpoint  VARCHAR(500)"),
    ("admin_mode",      "ALTER TABLE connections ADD COLUMN admin_mode      BOOLEAN DEFAULT 0"),
    ("public_endpoint", "ALTER TABLE connections ADD COLUMN public_endpoint VARCHAR(500)"),
]


async def init_db() -> None:
    async with engine.begin() as conn:
        # Create any brand-new tables (no-op for tables that already exist)
        await conn.run_sync(Base.metadata.create_all)

        # Apply incremental column migrations for the connections table.
        # SQLite does not support ALTER TABLE … ADD COLUMN IF NOT EXISTS,
        # so we attempt each ALTER and silently ignore "duplicate column" errors.
        for col_name, ddl in _MIGRATIONS:
            try:
                await conn.execute(text(ddl))
                log.info("DB migration applied: added column '%s' to connections", col_name)
            except Exception:
                # Column already present — this is the normal case after first run
                pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
