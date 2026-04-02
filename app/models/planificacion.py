from sqlalchemy import Column, String, DateTime, JSON, Date, ForeignKey, UniqueConstraint, Index
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class Planificacion(Base):
    __tablename__ = "planificacion"
    __table_args__ = (
        UniqueConstraint('personal_id', 'fecha', name='unique_personal_fecha'),
        Index('ix_planificacion_personal_id', 'personal_id'),  # ← NUEVO ÍNDICE
        Index('ix_planificacion_fecha', 'fecha'),              # ← NUEVO ÍNDICE
        Index('ix_planificacion_personal_fecha', 'personal_id', 'fecha'),  # ← ÍNDICE COMPUESTO
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    personal_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=False)
    fecha = Column(Date, nullable=False)
    turno_codigo = Column(String(10), nullable=False)
    observacion = Column(String(500))
    dm_info = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))

    def __repr__(self):
        return f"<Planificacion {self.fecha} - {self.turno_codigo}>"