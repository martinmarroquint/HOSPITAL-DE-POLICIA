# app/models/jerarquia.py
from sqlalchemy import Column, String, DateTime, Boolean, JSON, ForeignKey, Integer, Enum, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import uuid
import enum
from app.database import Base

# ✅ ENUMERACIÓN DE NIVELES JERÁRQUICOS
class NivelJerarquico(int, enum.Enum):
    NIVEL_1 = 1  # Jefe inmediato (supervisor, coordinador)
    NIVEL_2 = 2  # Jefe de departamento
    NIVEL_3 = 3  # Subdirector
    NIVEL_4 = 4  # Director
    NIVEL_5 = 5  # Director General / Comandante

class TipoArea(str, enum.Enum):
    DEPARTAMENTO = "departamento"
    SECCION = "seccion"
    SERVICIO = "servicio"
    UNIDAD = "unidad"
    OTRO = "otro"

class Jerarquia(Base):
    __tablename__ = "jerarquia"
    
    # =====================================================
    # COLUMNAS PRINCIPALES
    # =====================================================
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # =====================================================
    # ÁREA
    # =====================================================
    # Código único del área (ej: "EMERGENCIA", "CIRUGIA")
    codigo_area = Column(String(50), nullable=False, index=True)
    
    # Nombre descriptivo
    nombre_area = Column(String(100), nullable=False)
    
    # Tipo de área
    tipo_area = Column(Enum(TipoArea), default=TipoArea.DEPARTAMENTO)
    
    # =====================================================
    # JERARQUÍA
    # =====================================================
    # Nivel en la jerarquía (1-5)
    nivel = Column(Integer, nullable=False)  # 1 = más bajo, 5 = más alto
    
    # Rol requerido en Usuario.roles para aprobar en este nivel
    # Ej: "jefe_departamento", "subdirector", "director"
    rol_requerido = Column(String(50), nullable=False)
    
    # =====================================================
    # RELACIONES CON USUARIOS
    # =====================================================
    # Usuario que ocupa esta posición (puede ser null si está vacante)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    
    # Usuario que es el jefe de esta posición (para escalamiento)
    jefe_id = Column(UUID(as_uuid=True), ForeignKey("jerarquia.id"), nullable=True)
    
    # =====================================================
    # CONFIGURACIÓN DE APROBACIONES
    # =====================================================
    # ¿Puede aprobar solicitudes de su propia área?
    puede_aprobar_misma_area = Column(Boolean, default=True)
    
    # ¿Puede aprobar solicitudes de áreas hijas?
    puede_aprobar_areas_hijas = Column(Boolean, default=True)
    
    # Límite de aprobaciones (ej: monto máximo en soles)
    limite_aprobacion = Column(JSON, default={})  # {"monto_maximo": 5000, "dias_maximo": 15}
    
    # =====================================================
    # METADATA DEL ÁREA
    # =====================================================
    # Personal que pertenece a esta área (IDs)
    personal_ids = Column(JSON, default=[])  # Lista de UUIDs de personal
    
    # Subáreas hijas (IDs de jerarquia)
    subareas_ids = Column(JSON, default=[])  # Lista de UUIDs de jerarquia
    
    # Configuración adicional
    config = Column(JSON, default={})  # Horarios, reglas específicas, etc.
    
    # =====================================================
    # AUDITORÍA
    # =====================================================
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    created_by = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    
    # =====================================================
    # RELACIONES SQLAlchemy
    # =====================================================
    # Usuario que ocupa el cargo
    usuario_rel = relationship("Usuario", foreign_keys=[usuario_id])
    
    # Jefe directo (relación recursiva)
    jefe_rel = relationship("Jerarquia", remote_side=[id], foreign_keys=[jefe_id])
    
    # Creador del registro
    creador_rel = relationship("Usuario", foreign_keys=[created_by])

    # =====================================================
    # CONSTRAINTS
    # =====================================================
    __table_args__ = (
        # Un usuario no puede estar en dos posiciones activas del mismo nivel en la misma área
        UniqueConstraint('codigo_area', 'nivel', 'usuario_id', name='uq_area_nivel_usuario'),
    )

    def __repr__(self):
        return f"<Jerarquia {self.codigo_area} - Nivel {self.nivel} - {self.rol_requerido}>"