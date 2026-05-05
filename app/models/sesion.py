"""
MODELOS DE SESIONES
Para clases, terapias, entrenamientos y eventos programados
"""

from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, Time, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base


class Sesion(Base):
    """Sesión programada (clase, terapia, entrenamiento)"""
    __tablename__ = "sesiones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    nombre = Column(String(200), nullable=False)
    descripcion = Column(Text)
    fecha = Column(DateTime(timezone=True), nullable=False)
    hora_inicio = Column(Time, nullable=False)
    hora_fin = Column(Time, nullable=False)
    turno_codigo = Column(String(10), nullable=True)
    instructor_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=True)
    max_participantes = Column(Integer, default=20)
    color = Column(String(7), default="#8B5CF6")
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "nombre": self.nombre,
            "descripcion": self.descripcion,
            "fecha": self.fecha.isoformat() if self.fecha else None,
            "hora_inicio": self.hora_inicio.strftime("%H:%M") if self.hora_inicio else None,
            "hora_fin": self.hora_fin.strftime("%H:%M") if self.hora_fin else None,
            "turno_codigo": self.turno_codigo,
            "instructor_id": str(self.instructor_id) if self.instructor_id else None,
            "max_participantes": self.max_participantes,
            "color": self.color,
            "activo": self.activo,
        }

    def __repr__(self):
        return f"<Sesion {self.nombre} - {self.fecha}>"


class SesionAsistente(Base):
    """Asistente a una sesión con registro de check-in"""
    __tablename__ = "sesiones_asistentes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sesion_id = Column(UUID(as_uuid=True), ForeignKey("sesiones.id", ondelete="CASCADE"), nullable=False)
    personal_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=False)
    asistio = Column(Boolean, default=False)
    hora_llegada = Column(DateTime(timezone=True))
    minutos_tardanza = Column(Integer, default=0)
    minutos_temprano = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "sesion_id": str(self.sesion_id),
            "personal_id": str(self.personal_id),
            "asistio": self.asistio,
            "hora_llegada": self.hora_llegada.isoformat() if self.hora_llegada else None,
            "minutos_tardanza": self.minutos_tardanza,
            "minutos_temprano": self.minutos_temprano,
        }

    def __repr__(self):
        return f"<SesionAsistente sesion={self.sesion_id} personal={self.personal_id}>"