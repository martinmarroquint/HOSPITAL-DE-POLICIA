from sqlalchemy import Column, String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, JSONB
from app.database import Base
import uuid
from datetime import datetime


class InventarioUnidad(Base):
    __tablename__ = "inventario_unidades"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    catalogo_item_id = Column(UUID(as_uuid=True), ForeignKey("catalogo_items.id", ondelete="CASCADE"), nullable=False)
    unidad_nombre = Column(String(255), nullable=False)
    cantidades = Column(JSONB, default={})
    movimientos = Column(JSONB, default=[])
    actualizado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"))
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at = Column(DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow)
    
    __table_args__ = (
        UniqueConstraint('catalogo_item_id', 'unidad_nombre', name='uq_item_unidad'),
    )