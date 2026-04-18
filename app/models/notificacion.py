# app/models/notificacion.py
# MODELO DE NOTIFICACIONES - SIN COLUMNA DATA

from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database import Base


class Notificacion(Base):
    __tablename__ = "notificaciones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    publicacion_id = Column(UUID(as_uuid=True), ForeignKey("publicaciones.id", ondelete="SET NULL"), nullable=True)
    tipo = Column(String(30), nullable=False)
    titulo = Column(String(100), nullable=False)
    mensaje = Column(String(255), nullable=False)
    leida = Column(Boolean, default=False)
    leida_en = Column(DateTime(timezone=True), nullable=True)
    creada_en = Column(DateTime(timezone=True), server_default=func.now())
    
    usuario = relationship("Usuario", foreign_keys=[usuario_id])
    publicacion = relationship("Publicacion", foreign_keys=[publicacion_id])

    def __repr__(self):
        return f"<Notificacion {self.tipo} - Usuario: {self.usuario_id}>"