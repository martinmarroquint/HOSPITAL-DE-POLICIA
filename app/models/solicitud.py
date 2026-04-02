# app/models/solicitud.py
from sqlalchemy import Column, String, DateTime, Boolean, JSON, ForeignKey, Integer, Enum, Text, Date
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum
from app.database import Base

# ✅ ENUMERACIÓN DE TIPOS (basado en tus tipos reales)
class TipoSolicitud(str, enum.Enum):
    PROPIO = "propio"  # cambio propio
    INTERCAMBIO = "intercambio"  # intercambio con colega
    PLANIFICACION_MENSUAL = "planificacion_mensual"  # solicitud de cambio de planificación
    VACACIONES = "vacaciones"
    PERMISO = "permiso"
    DESCANSO_MEDICO = "descanso_medico"
    LICENCIA = "licencia"
    CAPACITACION = "capacitacion"
    OTRO = "otro"

# ✅ ENUMERACIÓN DE ESTADOS (basado en tus estados)
class EstadoSolicitud(str, enum.Enum):
    BORRADOR = "borrador"
    PENDIENTE = "pendiente"
    EN_APROBACION = "en_aprobacion"
    APROBADA = "aprobada"
    RECHAZADA = "rechazada"
    OBSERVADA = "observada"
    CANCELADA = "cancelada"

class Solicitud(Base):
    __tablename__ = "solicitudes"

    # =====================================================
    # COLUMNAS PRINCIPALES
    # =====================================================
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Tipado (usando Enum para validación)
    tipo = Column(Enum(TipoSolicitud), nullable=False, index=True)
    estado = Column(Enum(EstadoSolicitud), default=EstadoSolicitud.BORRADOR, index=True)
    
    # Fechas
    fecha_solicitud = Column(DateTime(timezone=True), server_default=func.now())
    fecha_cambio = Column(Date, nullable=False)  # Fecha en que aplica el cambio
    
    # Motivo y observaciones
    motivo = Column(String(50), nullable=False)
    observaciones = Column(Text)
    
    # Involucrados (siempre el empleado principal, opcional el segundo)
    empleado_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=False, index=True)
    empleado2_id = Column(UUID(as_uuid=True), ForeignKey("personal.id"), nullable=True)
    
    # =====================================================
    # 🆕 CAMPOS PARA VACACIONES (NUEVOS)
    # =====================================================
    fecha_inicio = Column(Date, nullable=True)  # Fecha de inicio de vacaciones
    fecha_fin = Column(Date, nullable=True)    # Fecha de fin de vacaciones
    dias_solicitados = Column(Integer, nullable=True)  # Días solicitados
    tipo_vacaciones = Column(String(30), nullable=True)  # 'programacion' o 'adelanto'
    
    # =====================================================
    # DATOS FLEXIBLES (JSON - Corazón del modelo)
    # =====================================================
    # Aquí va TODO lo específico de cada tipo de solicitud
    datos = Column(JSON, nullable=False, default={})
    
    # =====================================================
    # CONTROL JERÁRQUICO
    # =====================================================
    nivel_actual = Column(Integer, default=1)  # Nivel en el que está actualmente
    nivel_maximo = Column(Integer, nullable=False, default=1)  # Cuántos niveles debe pasar
    
    # =====================================================
    # VALIDACIONES Y DOCUMENTOS
    # =====================================================
    validacion_dias_libres = Column(JSON)  # Validación automática de disponibilidad
    documentos = Column(JSON, default=[])  # URLs de documentos adjuntos
    
    # =====================================================
    # METADATA (corregido - ya no se llama 'metadata')
    # =====================================================
    meta_datos = Column(JSON, default={})  # QR generado, información extra, etc.
    
    # =====================================================
    # 🆕 TOKEN DE EMERGENCIA (NUEVO)
    # =====================================================
    token_emergencia = Column(JSON, default={})  # {token_hash, generado_en, expira_en, intentos, usado}
    
    # =====================================================
    # AUDITORÍA
    # =====================================================
    created_by = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    
    # Revisión
    fecha_revision = Column(DateTime(timezone=True), nullable=True)
    revisado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    comentario_revision = Column(Text, nullable=True)
    
    # Aprobación final
    fecha_aprobacion = Column(DateTime(timezone=True), nullable=True)
    aprobado_por = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)

    # =====================================================
    # RELACIONES
    # =====================================================
    # Relación con personal
    empleado_rel = relationship("Personal", foreign_keys=[empleado_id])
    empleado2_rel = relationship("Personal", foreign_keys=[empleado2_id])
    
    # Relación con usuarios (auditoría)
    creador_rel = relationship("Usuario", foreign_keys=[created_by])
    revisor_rel = relationship("Usuario", foreign_keys=[revisado_por])
    aprobador_rel = relationship("Usuario", foreign_keys=[aprobado_por])

    def __repr__(self):
        return f"<Solicitud {self.id} - {self.tipo.value if self.tipo else 'sin_tipo'} - {self.estado.value if self.estado else 'sin_estado'}>"
    
    # =====================================================
    # MÉTODOS DE AYUDA PARA TOKEN
    # =====================================================
    def tiene_token_activo(self) -> bool:
        """Verifica si hay un token activo no expirado"""
        if not self.token_emergencia:
            return False
        
        token_data = self.token_emergencia
        if token_data.get("usado", False):
            return False
        
        if "expira_en" in token_data:
            from datetime import datetime
            expira_en = datetime.fromisoformat(token_data["expira_en"])
            if datetime.now() > expira_en:
                return False
        
        return True
    
    def token_intentos_restantes(self) -> int:
        """Devuelve intentos restantes para el token actual"""
        if not self.token_emergencia:
            return 0
        max_intentos = self.token_emergencia.get("max_intentos", 3)
        intentos = self.token_emergencia.get("intentos", 0)
        return max_intentos - intentos