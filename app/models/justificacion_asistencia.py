# app/models/justificacion_asistencia.py
from sqlalchemy import Column, String, Boolean, Date, Text, ForeignKey, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.database import Base

class JustificacionAsistencia(Base):
    __tablename__ = "justificaciones_asistencia"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    personal_id = Column(UUID(as_uuid=True), ForeignKey("personal.id", ondelete="CASCADE"), nullable=False)
    fecha = Column(Date, nullable=False)
    tipo = Column(String(50), nullable=False)  # LLEGADA_TARDE, INASISTENCIA, SALIDA_TEMPRANA, OTRO
    motivo = Column(Text, nullable=False)
    notificar_padre = Column(Boolean, default=True)
    justificado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relaciones
    personal = relationship("Personal", backref="justificaciones_asistencia")
    justificador = relationship("Usuario", backref="justificaciones_realizadas")

    def __repr__(self):
        return f"<JustificacionAsistencia {self.fecha} - {self.tipo}>"