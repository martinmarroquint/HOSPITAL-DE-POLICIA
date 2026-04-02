from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class Asistencia(Base):
    __tablename__ = "asistencia"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    personal_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    tipo = Column(String(20), nullable=False)  # ENTRADA, SALIDA, PAUSA
    tipo_registro = Column(String(10), nullable=False)  # QR, MANUAL
    turno_codigo = Column(String(10))
    justificacion = Column(Text)
    verificado = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))

    def __repr__(self):
        return f"<Asistencia {self.timestamp} - {self.tipo}>"