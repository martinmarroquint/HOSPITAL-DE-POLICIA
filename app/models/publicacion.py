# app/models/publicacion.py
# MODELO DE PUBLICACIONES - SIGUIENDO EL PATRÓN EXISTENTE

from sqlalchemy import Column, String, DateTime, Boolean, JSON, Text, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database import Base


class Publicacion(Base):
    __tablename__ = "publicaciones"

    # =====================================================
    # CAMPOS DE IDENTIFICACIÓN
    # =====================================================
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    titulo = Column(String(255), nullable=False)
    
    # =====================================================
    # TIPO Y CONTENIDO
    # =====================================================
    tipo = Column(String(20), nullable=False)  # TEXTO, IMAGEN, PDF
    contenido_texto = Column(Text, nullable=True)
    url_archivo = Column(String(500), nullable=True)
    descripcion = Column(Text, nullable=True)
    
    # =====================================================
    # CATEGORÍA Y METADATOS
    # =====================================================
    categoria = Column(String(50), default="general")
    es_automatica = Column(Boolean, default=False)
    
    # =====================================================
    # RELACIONES
    # =====================================================
    autor_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    
    # =====================================================
    # CONTROL DE PUBLICACIÓN
    # =====================================================
    fecha_publicacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_expiracion = Column(DateTime(timezone=True), nullable=True)
    activo = Column(Boolean, default=True, index=True)
    fijado = Column(Boolean, default=False)
    
    # =====================================================
    # MÉTRICAS CACHEADAS
    # =====================================================
    total_vistas = Column(Integer, default=0)
    
    # =====================================================
    # CAMPOS DE AUDITORÍA
    # =====================================================
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # =====================================================
    # RELACIONES
    # =====================================================
    vistas = relationship("PublicacionVista", back_populates="publicacion", cascade="all, delete-orphan")
    autor = relationship("Usuario", foreign_keys=[autor_id])

    def __repr__(self):
        return f"<Publicacion {self.titulo[:30]}... (ID: {self.id})>"


class PublicacionVista(Base):
    __tablename__ = "publicaciones_vistas"

    # =====================================================
    # CAMPOS DE IDENTIFICACIÓN
    # =====================================================
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    publicacion_id = Column(UUID(as_uuid=True), ForeignKey("publicaciones.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    
    # =====================================================
    # CAMPOS DE REGISTRO
    # =====================================================
    fecha_vista = Column(DateTime(timezone=True), server_default=func.now())
    
    # =====================================================
    # RELACIONES
    # =====================================================
    publicacion = relationship("Publicacion", back_populates="vistas")
    usuario = relationship("Usuario", foreign_keys=[usuario_id])

    def __repr__(self):
        return f"<PublicacionVista publicacion={self.publicacion_id} usuario={self.usuario_id}>"