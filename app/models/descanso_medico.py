from sqlalchemy import Column, String, DateTime, JSON, Date, Integer, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class DescansoMedico(Base):
    __tablename__ = "descansos_medicos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    paciente_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=False)
    diagnostico_cie = Column(String(10))
    diagnostico_desc = Column(Text, nullable=False)
    fecha_inicio = Column(Date, nullable=False)
    fecha_fin = Column(Date, nullable=False)
    dias = Column(Integer, nullable=False)
    domicilio = Column(JSON, nullable=False)
    profesional = Column(JSON, nullable=False)
    estado = Column(String(20), nullable=False, default="pendiente")  # pendiente, aprobado, rechazado
    observaciones = Column(Text)
    anotaciones = Column(Text)
    imagen_url = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    created_by = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))

    def __repr__(self):
        return f"<DescansoMedico {self.id} - {self.estado}>"