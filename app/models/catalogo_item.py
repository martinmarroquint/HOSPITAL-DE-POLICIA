from sqlalchemy import Column, String, Integer, Numeric, Boolean, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
import uuid
from datetime import datetime


class CatalogoItem(Base):
    __tablename__ = "catalogo_items"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nombre = Column(String(255), nullable=False)
    icono = Column(String(100), default="mdi:package-variant-closed")
    categoria = Column(String(100))
    precio_unitario = Column(Numeric(10, 2), default=0)
    stock_minimo = Column(Integer, default=5)
    detalles = Column(JSONB, default=[])
    activo = Column(Boolean, default=True)
    creado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)