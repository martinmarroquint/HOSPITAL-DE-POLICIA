# app/models/meta_cumplimiento.py

from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from app.database import Base


class MetaCumplimiento(Base):
    __tablename__ = "metas_cumplimiento"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    personal_id = Column(UUID(as_uuid=True), ForeignKey("personal.id", ondelete="CASCADE"), nullable=False)
    mes = Column(Integer, nullable=False)
    anio = Column(Integer, nullable=False)
    meta_turnos = Column(Integer, nullable=False)
    ajustada_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    fecha_ajuste = Column(DateTime(timezone=True), server_default=func.now())
    justificacion = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # Relaciones
    personal = relationship("Personal", backref="metas_cumplimiento")
    ajustador = relationship("Usuario", foreign_keys=[ajustada_por])

    def __repr__(self):
        return f"<MetaCumplimiento personal={self.personal_id} mes={self.mes}/{self.anio} meta={self.meta_turnos}>"