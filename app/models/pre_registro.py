# app/models/pre_registro.py
from sqlalchemy import Column, String, DateTime, Integer, Date, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class PreRegistro(Base):
    __tablename__ = "pre_registros"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)
    
    # Datos del empleado
    nombre = Column(String(255), nullable=False)
    documento = Column(String(20), nullable=False)
    sexo = Column(String(20))
    fecha_nacimiento = Column(Date)
    email = Column(String(255))
    telefono = Column(String(20))
    area = Column(String(255))
    cargo = Column(String(255))
    especialidad = Column(String(255))
    cip = Column(String(50))
    fecha_ingreso = Column(Date)
    observaciones = Column(Text)
    
    # Control de estado
    estado = Column(String(20), default="PENDIENTE")  # PENDIENTE, APROBADO, RECHAZADO
    motivo_rechazo = Column(Text)
    
    # Seguridad
    ip_origen = Column(String(45))
    tiempo_llenado_segundos = Column(Integer)
    
    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    aprobado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    aprobado_en = Column(DateTime(timezone=True))
    personal_creado_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"))

    def __repr__(self):
        return f"<PreRegistro {self.nombre} - {self.estado}>"