# D:\Centro de control Hospital PNP\back\app\models\planificacion_borrador.py
from sqlalchemy import Column, String, DateTime, Integer, JSON, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class PlanificacionBorrador(Base):
    __tablename__ = "planificacion_borradores"
    __table_args__ = (
        UniqueConstraint('area', 'mes', 'año', name='unique_area_mes_anio'),
        Index('ix_planificacion_borrador_area', 'area'),
        Index('ix_planificacion_borrador_estado', 'estado'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Identificación
    area = Column(String(100), nullable=False)
    mes = Column(Integer, nullable=False)
    año = Column(Integer, nullable=False)
    estado = Column(String(20), nullable=False, default='borrador')  # borrador, pendiente, aprobado, rechazado
    
    # Datos de planificación (array de objetos)
    datos = Column(JSON, nullable=True)
    
    # Fechas de control
    fecha_creacion = Column(DateTime(timezone=True), server_default=func.now())
    fecha_actualizacion = Column(DateTime(timezone=True), onupdate=func.now())
    fecha_envio = Column(DateTime(timezone=True))
    fecha_aprobacion = Column(DateTime(timezone=True))
    
    # Auditores
    creado_por = Column(UUID(as_uuid=True), ForeignKey("personal.id"))
    enviado_por = Column(UUID(as_uuid=True), ForeignKey("personal.id"))
    aprobado_por = Column(UUID(as_uuid=True), ForeignKey("personal.id"))
    
    # Comentarios
    comentario_rechazo = Column(String(500))
    
    def __repr__(self):
        return f"<PlanificacionBorrador {self.area} {self.mes}/{self.año} - {self.estado}>"