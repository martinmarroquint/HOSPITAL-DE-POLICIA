# D:\Centro de control Hospital PNP\back\app\models\configuracion_mensual.py

from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, JSON, UniqueConstraint  # ✅ AGREGAR UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base
import uuid

class ConfiguracionMensual(Base):
    __tablename__ = "configuraciones_mensuales"
    
    id = Column(Integer, primary_key=True, index=True)
    año = Column(Integer, nullable=False, index=True)
    mes = Column(Integer, nullable=False, index=True)  # 1-12
    
    # Configuración
    turnos_base = Column(Integer, nullable=False, default=25)  # 23,24,25 (por defecto 25)
    motivo = Column(String, nullable=True)
    observacion = Column(String, nullable=True)
    validado = Column(Boolean, default=False)
    
    # Metadatos
    fecha_validacion = Column(DateTime(timezone=True), nullable=True)
    validado_por = Column(UUID(as_uuid=True), ForeignKey('usuarios.id'), nullable=True)
    
    # Auditoría
    creado_en = Column(DateTime(timezone=True), server_default=func.now())
    actualizado_en = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Historial de cambios
    historial = Column(JSON, default=[])  # Lista de cambios anteriores
    
    __table_args__ = (
        UniqueConstraint('año', 'mes', name='uq_configuracion_mes_año'),  # ✅ AHORA SÍ FUNCIONA
    )