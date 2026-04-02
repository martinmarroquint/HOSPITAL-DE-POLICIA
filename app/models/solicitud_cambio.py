from sqlalchemy import Column, String, DateTime, JSON, Date, ForeignKey, Text, Integer
from sqlalchemy.dialects.postgresql import UUID, JSONB  # ← Importar JSONB
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
from app.database import Base

class SolicitudCambio(Base):
    __tablename__ = "solicitudes_cambio"

    # =====================================================
    # COLUMNAS PRINCIPALES
    # =====================================================
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Tipo y estado
    tipo = Column(String(30), nullable=False)  # propio, intercambio, planificacion_mensual, vacaciones
    estado = Column(String(20), nullable=False, default="pendiente")  # borrador, pendiente, aprobada, rechazada
    
    # Fechas
    fecha_solicitud = Column(DateTime(timezone=True), server_default=func.now())
    fecha_cambio = Column(Date, nullable=False)
    
    # Motivo y observaciones
    motivo = Column(String(50), nullable=False)
    observaciones = Column(Text)
    
    # Involucrados
    empleado_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=False)
    empleado2_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"))  # para intercambio
    
    # =====================================================
    # 🆕 CAMPOS PARA VACACIONES (NUEVOS)
    # =====================================================
    fecha_inicio = Column(Date, nullable=True)  # Fecha de inicio de vacaciones
    fecha_fin = Column(Date, nullable=True)    # Fecha de fin de vacaciones
    dias_solicitados = Column(Integer, nullable=True)  # Días solicitados
    tipo_vacaciones = Column(String(30), nullable=True)  # 'programacion' o 'adelanto'
    
    # =====================================================
    # TURNOS (guardados como JSON)
    # =====================================================
    
    # Para cambio propio
    turno_original = Column(JSON)  # Puede seguir siendo JSON si no necesitas mutabilidad
    turno_solicitado = Column(JSON)
    
    # Para intercambio
    turno_original_solicitante = Column(JSON)
    turno_original_colega = Column(JSON)
    turno_solicitante_recibe = Column(JSON)
    turno_colega_recibe = Column(JSON)
    
    # =====================================================
    # 🆕 CAMPOS DE JERARQUÍA
    # =====================================================
    nivel_actual = Column(String(30), default="usuario")
    proximo_nivel = Column(String(30), nullable=True)
    
    # ✅ CAMBIAR ESTOS A JSONB para detectar cambios
    niveles_pendientes = Column(JSONB, default=[])  # ← JSONB
    niveles_aprobados = Column(JSONB, default=[])  # ← JSONB
    
    # =====================================================
    # VALIDACIONES Y DOCUMENTOS
    # =====================================================
    validacion_dias_libres = Column(JSON)
    documentos = Column(JSON, default=[])
    
    # ✅ CAMBIAR historial a JSONB para detectar .append()
    historial = Column(JSONB, default=[])  # ← JSONB (MUY IMPORTANTE)
    
    # =====================================================
    # AUDITORÍA
    # =====================================================
    created_by = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    
    fecha_revision = Column(DateTime(timezone=True))
    revisado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"))
    comentario_revision = Column(Text)

    # =====================================================
    # RELACIONES
    # =====================================================
    empleado_rel = relationship("Personal", foreign_keys=[empleado_id])
    empleado2_rel = relationship("Personal", foreign_keys=[empleado2_id])

    def __repr__(self):
        return f"<SolicitudCambio {self.id} - {self.estado}>"