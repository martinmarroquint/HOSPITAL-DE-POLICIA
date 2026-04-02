# app/models/trazabilidad.py
from sqlalchemy import Column, String, DateTime, JSON, ForeignKey, Integer, Text, Enum  # ← AGREGAR 'Enum'
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum  # ← Este es para el enum de Python, no el de SQLAlchemy
from app.database import Base

# ✅ ENUMERACIÓN DE ACCIONES (para saber qué pasó)
class AccionTrazabilidad(str, enum.Enum):
    CREACION = "creacion"
    ENVIO = "envio"  # cuando pasa de borrador a pendiente
    APROBACION = "aprobacion"
    RECHAZO = "rechazo"
    OBSERVACION = "observacion"
    CANCELACION = "cancelacion"
    MODIFICACION = "modificacion"
    VISUALIZACION = "visualizacion"
    DESCARGA_QR = "descarga_qr"
    VALIDACION_QR = "validacion_qr"
    SUBIDA_DOCUMENTO = "subida_documento"
    NOTIFICACION = "notificacion"

class Trazabilidad(Base):
    __tablename__ = "trazabilidad"

    # =====================================================
    # COLUMNAS PRINCIPALES
    # =====================================================
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Solicitud asociada
    solicitud_id = Column(UUID(as_uuid=True), ForeignKey("solicitudes.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Acción realizada
    accion = Column(Enum(AccionTrazabilidad), nullable=False, index=True)
    
    # Usuario que realizó la acción
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    
    # =====================================================
    # HASHES (CORAZÓN DE LA SEGURIDAD)
    # =====================================================
    # Hash del estado actual de la solicitud en este momento
    hash_solicitud = Column(String(64), nullable=False)  # SHA256 = 64 caracteres
    
    # Hash del registro anterior (para encadenar)
    hash_anterior = Column(String(64), nullable=True)  # Null para el primer registro
    
    # Hash de este registro (para integridad)
    hash_actual = Column(String(64), nullable=False, unique=True)  # Único para evitar duplicados
    
    # =====================================================
    # DATOS DE LA ACCIÓN
    # =====================================================
    # Detalles específicos de la acción (ej: qué cambió)
    datos = Column(JSON, default={})
    
    # Comentario adicional (ej: motivo de rechazo)
    comentario = Column(Text, nullable=True)
    
    # =====================================================
    # METADATA
    # =====================================================
    # IP desde donde se realizó la acción
    ip_origen = Column(String(45), nullable=True)  # IPv6 puede tener 45 caracteres
    
    # User agent del navegador/cliente
    user_agent = Column(String(255), nullable=True)
    
    # =====================================================
    # TIMESTAMPS
    # =====================================================
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    
    # =====================================================
    # RELACIONES
    # =====================================================
    solicitud_rel = relationship("Solicitud", foreign_keys=[solicitud_id])
    usuario_rel = relationship("Usuario", foreign_keys=[usuario_id])

    def __repr__(self):
        return f"<Trazabilidad {self.id[:8]} - {self.accion.value} - {self.created_at}>"