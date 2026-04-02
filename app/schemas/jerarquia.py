# app/schemas/jerarquia.py
from pydantic import BaseModel, Field, validator, UUID4
from typing import Optional, List, Dict, Any
from datetime import datetime
import enum

# =====================================================
# ENUMS (igual que en models/jerarquia.py)
# =====================================================
class NivelJerarquico(int, enum.Enum):
    NIVEL_1 = 1
    NIVEL_2 = 2
    NIVEL_3 = 3
    NIVEL_4 = 4
    NIVEL_5 = 5

class TipoArea(str, enum.Enum):
    DEPARTAMENTO = "departamento"
    SECCION = "seccion"
    SERVICIO = "servicio"
    UNIDAD = "unidad"
    OTRO = "otro"

# =====================================================
# SCHEMAS BASE
# =====================================================
class JerarquiaBase(BaseModel):
    """Campos base para crear/actualizar jerarquía"""
    codigo_area: str = Field(..., min_length=2, max_length=50)
    nombre_area: str = Field(..., min_length=3, max_length=100)
    tipo_area: TipoArea = TipoArea.DEPARTAMENTO
    nivel: NivelJerarquico
    rol_requerido: str = Field(..., min_length=3, max_length=50)
    usuario_id: Optional[UUID4] = None
    jefe_id: Optional[UUID4] = None
    puede_aprobar_misma_area: bool = True
    puede_aprobar_areas_hijas: bool = True
    limite_aprobacion: Dict[str, Any] = Field(default_factory=dict)
    personal_ids: List[UUID4] = Field(default_factory=list)
    subareas_ids: List[UUID4] = Field(default_factory=list)
    config: Dict[str, Any] = Field(default_factory=dict)
    
    @validator('codigo_area')
    def codigo_area_mayusculas(cls, v):
        return v.upper().strip()
    
    @validator('rol_requerido')
    def rol_requerido_formato(cls, v):
        # Convertir a minúsculas y sin espacios
        return v.lower().strip().replace(' ', '_')

class JerarquiaCreate(JerarquiaBase):
    """Para crear una nueva posición jerárquica"""
    pass

class JerarquiaUpdate(BaseModel):
    """Para actualizar una posición jerárquica"""
    nombre_area: Optional[str] = Field(None, min_length=3, max_length=100)
    tipo_area: Optional[TipoArea] = None
    usuario_id: Optional[UUID4] = None
    jefe_id: Optional[UUID4] = None
    puede_aprobar_misma_area: Optional[bool] = None
    puede_aprobar_areas_hijas: Optional[bool] = None
    limite_aprobacion: Optional[Dict[str, Any]] = None
    personal_ids: Optional[List[UUID4]] = None
    subareas_ids: Optional[List[UUID4]] = None
    config: Optional[Dict[str, Any]] = None
    activo: Optional[bool] = None

# =====================================================
# SCHEMAS DE RESPUESTA
# =====================================================
class JerarquiaResponse(JerarquiaBase):
    """Respuesta completa de una posición jerárquica"""
    id: UUID4
    activo: bool
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by: Optional[UUID4] = None
    
    # Nombres para mostrar
    usuario_nombre: Optional[str] = None
    usuario_email: Optional[str] = None
    jefe_nombre: Optional[str] = None
    creado_por_nombre: Optional[str] = None
    
    class Config:
        from_attributes = True

class JerarquiaListResponse(BaseModel):
    """Versión resumida para listados"""
    id: UUID4
    codigo_area: str
    nombre_area: str
    nivel: int
    rol_requerido: str
    usuario_id: Optional[UUID4]
    usuario_nombre: Optional[str]
    activo: bool
    total_personal: int = Field(0, description="Cantidad de personal en esta área")
    
    class Config:
        from_attributes = True

# =====================================================
# SCHEMAS PARA ÁREAS
# =====================================================
class AreaBase(BaseModel):
    """Información básica de un área"""
    codigo: str
    nombre: str
    tipo: TipoArea

class AreaCompleta(AreaBase):
    """Área con toda su jerarquía"""
    niveles: Dict[int, Dict[str, Any]] = Field(default_factory=dict)
    jefes: Dict[int, Dict[str, Any]] = Field(default_factory=dict)
    personal: List[Dict[str, Any]] = Field(default_factory=list)
    subareas: List['AreaCompleta'] = Field(default_factory=list)

class AreaResponse(BaseModel):
    """Respuesta de un área con su estructura"""
    codigo_area: str
    nombre_area: str
    tipo_area: TipoArea
    niveles_disponibles: List[int]
    jefes_asignados: Dict[int, Dict[str, Any]]
    total_personal: int
    subareas: List[Dict[str, Any]]
    
    class Config:
        from_attributes = True

# =====================================================
# SCHEMAS PARA APROBACIONES
# =====================================================
class VerificacionAprobacionRequest(BaseModel):
    """Verificar si un usuario puede aprobar una solicitud"""
    solicitud_id: UUID4
    usuario_id: Optional[UUID4] = None  # Si no se envía, usa el actual

class VerificacionAprobacionResponse(BaseModel):
    """Resultado de la verificación de aprobación"""
    puede_aprobar: bool
    nivel_requerido: int
    nivel_usuario: Optional[int]
    motivo: Optional[str] = None
    siguiente_aprobador: Optional[Dict[str, Any]] = None
    jerarquia_completa: Optional[List[Dict[str, Any]]] = None

class SiguienteAprobadorResponse(BaseModel):
    """Información del siguiente aprobador en la cadena"""
    nivel: int
    usuario_id: UUID4
    usuario_nombre: str
    usuario_email: str
    rol_requerido: str
    area: str
    limite_aprobacion: Dict[str, Any] = Field(default_factory=dict)

# =====================================================
# SCHEMAS PARA ASIGNACIÓN DE PERSONAL
# =====================================================
class AsignarPersonalRequest(BaseModel):
    """Asignar personal a un área"""
    personal_ids: List[UUID4]
    accion: str = "asignar"  # asignar, remover
    
    @validator('accion')
    def validar_accion(cls, v):
        if v not in ['asignar', 'remover']:
            raise ValueError('Acción debe ser "asignar" o "remover"')
        return v

class AsignarJefeRequest(BaseModel):
    """Asignar un jefe a un nivel jerárquico"""
    usuario_id: UUID4
    nivel: NivelJerarquico
    
    @validator('usuario_id')
    def validar_usuario(cls, v):
        if not v:
            raise ValueError('Debe especificar un usuario')
        return v

# =====================================================
# SCHEMAS PARA CONFIGURACIÓN
# =====================================================
class ConfiguracionJerarquia(BaseModel):
    """Configuración global de jerarquías"""
    niveles_maximos: int = Field(5, ge=1, le=10)
    requiere_jefe_en_todos_niveles: bool = False
    permitir_area_vacia: bool = False
    flujo_automatico: bool = True  # Pasar al siguiente nivel automáticamente
    notificar_siguiente_aprobador: bool = True
    
class LimiteAprobacionUpdate(BaseModel):
    """Actualizar límites de aprobación"""
    tipo: str  # monto, dias, etc
    valor: Any
    moneda: Optional[str] = "PEN"
    
    @validator('tipo')
    def validar_tipo(cls, v):
        tipos_permitidos = ['monto', 'dias', 'horas', 'personal']
        if v not in tipos_permitidos:
            raise ValueError(f'Tipo debe ser uno de: {tipos_permitidos}')
        return v

# =====================================================
# SCHEMAS DE FILTROS
# =====================================================
class JerarquiaFiltros(BaseModel):
    """Para filtrar posiciones jerárquicas"""
    codigo_area: Optional[str] = None
    nivel: Optional[int] = None
    rol_requerido: Optional[str] = None
    usuario_id: Optional[UUID4] = None
    activo: Optional[bool] = True
    tiene_jefe: Optional[bool] = None
    sin_asignar: Optional[bool] = None  # Usuario_id is None
    
    class Config:
        extra = "forbid"

# =====================================================
# SCHEMAS ESTADÍSTICOS
# =====================================================
class EstadisticasJerarquia(BaseModel):
    """Estadísticas del sistema jerárquico"""
    total_areas: int
    total_posiciones: int
    posiciones_ocupadas: int
    posiciones_vacantes: int
    niveles_por_area: Dict[str, List[int]]
    areas_sin_jefe: List[str]
    personal_sin_area: int

# =====================================================
# EJEMPLOS DE USO
# =====================================================
"""
# Crear jerarquía para Emergencia
jerarquia = JerarquiaCreate(
    codigo_area="EMERGENCIA",
    nombre_area="Servicio de Emergencia",
    tipo_area=TipoArea.SERVICIO,
    nivel=NivelJerarquico.NIVEL_1,
    rol_requerido="supervisor_emergencia",
    limite_aprobacion={"monto_maximo": 5000, "dias_maximo": 3}
)

# Verificar si puede aprobar
verificacion = VerificacionAprobacionResponse(
    puede_aprobar=True,
    nivel_requerido=2,
    nivel_usuario=2,
    siguiente_aprobador={
        "nivel": 3,
        "usuario_nombre": "Dr. Pérez",
        "rol": "jefe_emergencia"
    }
)
"""