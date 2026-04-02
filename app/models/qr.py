# app/models/qr.py
from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class QRRegistro(Base):
    __tablename__ = "qr_registros"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    qr_id = Column(String(100), unique=True, nullable=False, index=True)
    codigo = Column(String(500), nullable=True)  # ← NUEVO: para guardar el string completo del QR
    empleado_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=False)
    solicitud_id = Column(UUID(as_uuid=True), ForeignKey("solicitudes.id"), nullable=True)  # ← NUEVO: relación con solicitud
    tipo = Column(String(20), nullable=False, default="asistencia")  # ← NUEVO: 'asistencia' o 'tramite'
    generado_en = Column(DateTime(timezone=True), server_default=func.now())
    expira_en = Column(DateTime(timezone=True), nullable=False)
    usado = Column(Boolean, default=False)
    usado_en = Column(DateTime(timezone=True))
    usado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self):
        return f"<QRRegistro {self.qr_id} ({self.tipo})>"