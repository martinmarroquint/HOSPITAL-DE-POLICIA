"""
MODELO DE CLIENTE
Organización que agrupa múltiples empresas
Jerarquía: super_admin → admin_cliente (cliente) → admin_empresa (empresa)
"""

from sqlalchemy import Column, String, Boolean, Date, DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database import Base


class Cliente(Base):
    __tablename__ = "clientes"
    
    # Identificación
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(255), nullable=False)
    razon_social = Column(String(255), nullable=True)
    ruc = Column(String(20), nullable=True)
    
    # Contacto
    email_contacto = Column(String(255), nullable=True)
    telefono = Column(String(50), nullable=True)
    direccion = Column(Text, nullable=True)
    
    # Plan y control
    plan = Column(String(50), default='basico')  # basico, profesional, enterprise
    fecha_vencimiento = Column(Date, nullable=True)
    activo = Column(Boolean, default=True)
    
    # Metadata
    configuracion = Column(Text, nullable=True)  # JSON string para config adicional
    
    # Auditoría
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Relaciones
    # Nota: La relación con Empresa se define en Empresa (backref="empresas")
    
    def __repr__(self):
        return f"<Cliente {self.nombre}>"
    
    def to_dict(self, include_empresas: bool = False):
        """
        Convierte el cliente a diccionario para respuestas API
        
        Args:
            include_empresas: Si es True, incluye las empresas asociadas
        """
        data = {
            "id": str(self.id),
            "nombre": self.nombre,
            "razon_social": self.razon_social,
            "ruc": self.ruc,
            "email_contacto": self.email_contacto,
            "telefono": self.telefono,
            "direccion": self.direccion,
            "plan": self.plan,
            "fecha_vencimiento": self.fecha_vencimiento.isoformat() if self.fecha_vencimiento else None,
            "activo": self.activo,
            "configuracion": self.configuracion,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
        
        if include_empresas and hasattr(self, 'empresas'):
            data["empresas"] = [
                {
                    "id": str(e.id),
                    "nombre": e.nombre,
                    "subdominio": e.subdominio,
                    "activo": e.activo,
                    "plan": e.plan,
                }
                for e in self.empresas
            ]
            data["total_empresas"] = len(self.empresas)
        
        return data