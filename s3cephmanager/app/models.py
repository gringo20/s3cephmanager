from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy import select, update
from app.database import Base, AsyncSessionLocal
from datetime import datetime
from typing import Optional


class Connection(Base):
    __tablename__ = "connections"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    name           = Column(String(100), unique=True, nullable=False)
    endpoint       = Column(String(500), nullable=False)
    access_key     = Column(String(200), nullable=False)
    secret_key     = Column(String(200), nullable=False)
    region         = Column(String(100), default="us-east-1")
    admin_endpoint = Column(String(500), nullable=True)
    admin_mode     = Column(Boolean, default=False)   # enables RGW Admin API / user tab
    verify_ssl     = Column(Boolean, default=True)
    is_last_used   = Column(Boolean, default=False)
    created_at     = Column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        return {
            "id":             self.id,
            "name":           self.name,
            "endpoint":       self.endpoint,
            "access_key":     self.access_key,
            "secret_key":     self.secret_key,
            "region":         self.region,
            "admin_endpoint": self.admin_endpoint,
            "admin_mode":     bool(self.admin_mode),
            "verify_ssl":     bool(self.verify_ssl),
            "is_last_used":   bool(self.is_last_used),
        }


# ── CRUD helpers ──────────────────────────────────────────────────────────────

async def list_connections() -> list[dict]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Connection).order_by(
                Connection.is_last_used.desc(), Connection.created_at
            )
        )
        return [c.to_dict() for c in result.scalars().all()]


async def get_connection(conn_id: int) -> Optional[dict]:
    async with AsyncSessionLocal() as db:
        c = await db.get(Connection, conn_id)
        return c.to_dict() if c else None


async def save_connection(data: dict) -> dict:
    async with AsyncSessionLocal() as db:
        safe = {k: v for k, v in data.items() if k != "id"}
        conn = Connection(**safe)
        db.add(conn)
        await db.commit()
        await db.refresh(conn)
        return conn.to_dict()


async def update_connection(conn_id: int, data: dict) -> Optional[dict]:
    _allowed = {"name", "endpoint", "access_key", "secret_key",
                "region", "admin_endpoint", "admin_mode", "verify_ssl"}
    async with AsyncSessionLocal() as db:
        c = await db.get(Connection, conn_id)
        if not c:
            return None
        for k, v in data.items():
            if k in _allowed:
                setattr(c, k, v)
        await db.commit()
        await db.refresh(c)
        return c.to_dict()


async def delete_connection(conn_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        c = await db.get(Connection, conn_id)
        if not c:
            return False
        await db.delete(c)
        await db.commit()
        return True


async def set_last_used(conn_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(Connection).values(is_last_used=False))
        await db.execute(
            update(Connection)
            .where(Connection.id == conn_id)
            .values(is_last_used=True)
        )
        await db.commit()
