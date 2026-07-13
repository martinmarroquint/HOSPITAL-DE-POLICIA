# back/app/models/grupo.py
from sqlalchemy import Column, String, DateTime, JSON
from app.database import Base
from datetime import datetime, timezone


class Grupo(Base):
    __tablename__ = "grupos"

    id = Column(String, primary_key=True)
    nombre = Column(String(200), nullable=False)
    docente_id = Column(String(100), nullable=False, default="default")
    alumnos = Column(JSON, default=[])
    asistencias = Column(JSON, default=[])
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))