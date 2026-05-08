"""
MODELO DE EMPRESA
Tabla principal del sistema multi-empresa con soporte para clientes
Jerarquía: super_admin → admin_cliente (cliente) → admin_empresa (empresa)
VERSIÓN CORREGIDA - TIPOS DE DATO COINCIDEN CON BD REAL
"""

from sqlalchemy import Column, String, Boolean, Integer, DateTime, Text, ForeignKey, Date
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database import Base


class Empresa(Base):
    __tablename__ = "empresas"
    
    # Identificación
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(Text, nullable=False)
    nombre_corto = Column(Text)
    ruc = Column(Text)
    
    # Subdominio y emails
    subdominio = Column(Text, unique=True, nullable=False, index=True)
    dominio_email = Column(Text)
    email_contacto = Column(Text)
    telefono = Column(Text)
    direccion = Column(Text)
    
    # Configuración visual
    logo_url = Column(Text)
    color_primario = Column(Text, default="#1a365d")
    color_secundario = Column(Text, default="#2b6cb0")
    color_fondo = Column(Text, default="#f7fafc")
    color_texto = Column(Text, default="#1a202c")
    
    # Control y plan
    activo = Column(Boolean, default=True)
    plan = Column(Text, default="basico")
    max_usuarios = Column(Integer, default=50)
    fecha_vencimiento = Column(DateTime(timezone=True))
    
    # Relaciones con cliente y admin
    cliente_id = Column(UUID(as_uuid=True), ForeignKey("clientes.id"), nullable=True)
    admin_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    
    # Metadata y auditoría
    configuracion = Column(JSONB, default={})
    pie_pagina = Column(String(255))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relaciones
    cliente = relationship("Cliente", backref="empresas", lazy="joined")
    admin = relationship("Usuario", foreign_keys=[admin_id], lazy="joined")
    
    def __repr__(self):
        return f"<Empresa {self.nombre} ({self.subdominio})>"
    
    def to_dict(self):
        return {
            "id": str(self.id),
            "nombre": self.nombre,
            "nombre_corto": self.nombre_corto,
            "subdominio": self.subdominio,
            "dominio_email": self.dominio_email,
            "email_contacto": self.email_contacto,
            "telefono": self.telefono,
            "direccion": self.direccion,
            "activo": self.activo,
            "plan": self.plan,
            "max_usuarios": self.max_usuarios,
            "fecha_vencimiento": self.fecha_vencimiento.isoformat() if self.fecha_vencimiento else None,
            "cliente_id": str(self.cliente_id) if self.cliente_id else None,
            "admin_id": str(self.admin_id) if self.admin_id else None,
            "logo_url": self.logo_url,
            "color_primario": self.color_primario,
            "color_secundario": self.color_secundario,
            "color_fondo": self.color_fondo,
            "color_texto": self.color_texto,
            "pie_pagina": self.pie_pagina,
            "configuracion": self.configuracion,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }