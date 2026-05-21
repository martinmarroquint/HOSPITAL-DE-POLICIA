# app/models/rotacion.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base


class Rotacion(Base):
    __tablename__ = "rotaciones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="CASCADE"), nullable=True)
    nombre = Column(String(100), nullable=False)
    descripcion = Column(Text, nullable=True)
    patron = Column(JSONB, nullable=False, default=list)
    duracion_ciclo = Column(Integer, nullable=False, default=1)
    color = Column(String(7), default='#6366F1')
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    empresa = relationship("Empresa", backref="rotaciones")

    def __repr__(self):
        return f"<Rotacion {self.nombre} ciclo={self.duracion_ciclo}>"