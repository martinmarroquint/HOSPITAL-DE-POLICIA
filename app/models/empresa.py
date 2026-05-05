"""
MODELO DE EMPRESA
Tabla principal del sistema multi-empresa
"""

from sqlalchemy import Column, String, Boolean, Integer, DateTime, Text, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
import uuid
from app.database import Base


class Empresa(Base):
    __tablename__ = "empresas"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(200), nullable=False)
    nombre_corto = Column(String(50))
    ruc = Column(String(20))
    subdominio = Column(String(50), unique=True, nullable=False, index=True)
    dominio_email = Column(String(255), nullable=True)
    email_contacto = Column(String(255))
    telefono = Column(String(20))
    direccion = Column(Text)
    
    # Configuración visual
    logo_url = Column(Text)
    color_primario = Column(String(20), default="#1a365d")
    color_secundario = Column(String(20), default="#2b6cb0")
    color_fondo = Column(String(20), default="#f7fafc")
    color_texto = Column(String(20), default="#1a202c")
    
    # Control
    activo = Column(Boolean, default=True)
    plan = Column(String(20), default="basico")
    max_usuarios = Column(Integer, default=50)
    fecha_vencimiento = Column(DateTime(timezone=True))
    admin_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    
    # Metadata
    configuracion = Column(JSONB, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    def __repr__(self):
        return f"<Empresa {self.nombre} ({self.subdominio})>"