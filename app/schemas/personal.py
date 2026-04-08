# schemas/personal.py
# VERSIÓN COMPLETA - CON SOPORTE PARA MÚLTIPLES TIPOS DE JEFATURA
# Compatible con formato legacy (array) y nuevo (objeto)

from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from uuid import UUID

# =====================================================
# SCHEMAS BASE
# =====================================================

class PersonalBase(BaseModel):
    # =====================================================
    # CAMPOS DE IDENTIFICACIÓN
    # =====================================================
    dni: str = Field(..., min_length=1, max_length=8)
    cip: str
    
    # =====================================================
    # CAMPOS PERSONALES
    # =====================================================
    grado: str
    nombre: str
    sexo: Optional[str] = Field(None, description="Sexo del personal (M, F, No especificado)")
    fecha_nacimiento: Optional[date] = None
    
    # =====================================================
    # CAMPOS DE CONTACTO
    # =====================================================
    email: EmailStr
    telefono: Optional[str] = None
    
    # =====================================================
    # CAMPOS LABORALES
    # =====================================================
    area: str
    especialidad: Optional[str] = None
    numero_colegiatura: Optional[str] = None
    condicion: Optional[str] = None
    observaciones: Optional[str] = None
    
    # =====================================================
    # CAMPOS DE JEFATURA (COMPATIBILIDAD DUAL)
    # =====================================================
    
    # FORMATO LEGACY (ACTUAL - SIGUE FUNCIONANDO)
    # Array plano de áreas que jefatura
    areas_que_jefatura: Optional[List[str]] = Field(default=[])
    
    # FORMATO NUEVO (ESTRUCTURADO POR TIPO DE JEFATURA)
    # Objeto con arrays por tipo de jefatura
    areas_jefatura: Optional[Dict[str, List[str]]] = Field(default={})

    # =====================================================
    # VALIDADORES
    # =====================================================
    
    @validator('dni')
    def validar_dni(cls, v):
        """Validar que el DNI tenga 8 dígitos, si no, marcar como pendiente"""
        dni = str(v).strip()
        if not dni:
            return "PENDIENTE"
        
        if not dni.isdigit() or len(dni) != 8:
            return "PENDIENTE"
        
        return dni

    @validator('sexo')
    def validar_sexo(cls, v):
        """Validar que el sexo sea uno de los valores permitidos"""
        if v is None:
            return "No especificado"
        
        valores_permitidos = ['M', 'F', 'No especificado']
        if v not in valores_permitidos:
            return "No especificado"
        
        return v
    
    @validator('areas_jefatura')
    def validar_areas_jefatura(cls, v):
        """Validar que areas_jefatura tenga la estructura correcta"""
        if v is None:
            return {}
        
        # Asegurar que las claves esperadas existan
        claves_esperadas = ['grupo', 'area', 'departamento', 'direccion']
        resultado = {}
        
        for clave in claves_esperadas:
            if clave in v and isinstance(v[clave], list):
                resultado[clave] = v[clave]
            else:
                resultado[clave] = []
        
        return resultado


class PersonalCreate(PersonalBase):
    fecha_ingreso: Optional[date] = None
    roles: List[str] = ["usuario"]
    activo: bool = True
    
    @validator('roles')
    def validar_roles(cls, v):
        """Validar que los roles sean válidos"""
        roles_validos = [
            'admin', 'jefe_grupo', 'jefe_area', 'jefe_departamento', 
            'jefe_direccion', 'recursos_humanos', 'oficina_central',
            'oficial_permanencia', 'control_qr', 'usuario'
        ]
        for rol in v:
            if rol not in roles_validos:
                raise ValueError(f"Rol inválido: {rol}")
        return v
    
    @validator('areas_que_jefatura')
    def validar_areas_jefatura_creacion(cls, v, values):
        """Validar que jefe_area tenga al menos un área asignada"""
        roles = values.get('roles', [])
        
        if 'jefe_area' in roles:
            # Verificar formato legacy
            areas_legacy = v or []
            # Verificar formato nuevo
            areas_nuevo = values.get('areas_jefatura', {})
            areas_area = areas_nuevo.get('area', []) if areas_nuevo else []
            
            # También verificar áreas con prefijo en el legacy
            areas_con_prefijo = [a for a in areas_legacy if a.startswith('area:')]
            areas_sin_prefijo = [a for a in areas_legacy if ':' not in a]
            
            total_areas = len(areas_area) + len(areas_con_prefijo) + len(areas_sin_prefijo)
            
            if total_areas == 0:
                raise ValueError("Los jefes de área deben tener al menos un área asignada")
        
        return v


class PersonalUpdate(BaseModel):
    # =====================================================
    # CAMPOS DE IDENTIFICACIÓN
    # =====================================================
    dni: Optional[str] = Field(None, min_length=1, max_length=8)
    cip: Optional[str] = None
    
    # =====================================================
    # CAMPOS PERSONALES
    # =====================================================
    grado: Optional[str] = None
    nombre: Optional[str] = None
    sexo: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    
    # =====================================================
    # CAMPOS DE CONTACTO
    # =====================================================
    email: Optional[EmailStr] = None
    telefono: Optional[str] = None
    
    # =====================================================
    # CAMPOS LABORALES
    # =====================================================
    area: Optional[str] = None
    especialidad: Optional[str] = None
    numero_colegiatura: Optional[str] = None
    condicion: Optional[str] = None
    observaciones: Optional[str] = None
    fecha_ingreso: Optional[date] = None
    
    # =====================================================
    # ESTADO Y ROLES
    # =====================================================
    activo: Optional[bool] = None
    roles: Optional[List[str]] = None
    
    # =====================================================
    # CAMPOS DE JEFATURA (COMPATIBILIDAD DUAL)
    # =====================================================
    areas_que_jefatura: Optional[List[str]] = Field(default=[])
    areas_jefatura: Optional[Dict[str, List[str]]] = Field(default={})

    # =====================================================
    # VALIDADORES
    # =====================================================
    
    @validator('dni')
    def validar_dni_actualizacion(cls, v):
        """Validar DNI en actualizaciones"""
        if v is None:
            return v
        dni = str(v).strip()
        if not dni:
            return "PENDIENTE"
        if not dni.isdigit() or len(dni) != 8:
            return "PENDIENTE"
        return dni

    @validator('sexo')
    def validar_sexo_actualizacion(cls, v):
        """Validar sexo en actualizaciones"""
        if v is None:
            return v
        
        valores_permitidos = ['M', 'F', 'No especificado']
        if v not in valores_permitidos:
            return "No especificado"
        
        return v
    
    @validator('areas_jefatura')
    def validar_areas_jefatura_update(cls, v):
        """Validar que areas_jefatura tenga la estructura correcta"""
        if v is None:
            return {}
        
        claves_esperadas = ['grupo', 'area', 'departamento', 'direccion']
        resultado = {}
        
        for clave in claves_esperadas:
            if clave in v and isinstance(v[clave], list):
                resultado[clave] = v[clave]
            else:
                resultado[clave] = []
        
        return resultado
    
    class Config:
        from_attributes = True


class PersonalResponse(PersonalBase):
    id: UUID
    fecha_ingreso: Optional[date]
    roles: List[str]
    activo: bool
    sexo: Optional[str] = "No especificado"
    created_at: datetime
    updated_at: Optional[datetime]
    
    # Campos de jefatura ya están en PersonalBase
    # areas_que_jefatura y areas_jefatura se heredan

    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA CARGA MASIVA
# =====================================================

class CargaMasivaItem(BaseModel):
    """
    Schema para un item de carga masiva desde Excel
    Los nombres de los campos coinciden con los encabezados del Excel
    """
    CIP: str
    DNI: str
    GRADO: str
    NOMBRE_COMPLETO: str
    SEXO: Optional[str] = None
    EMAIL: EmailStr
    TELÉFONO: Optional[str] = None
    FECHA_NACIMIENTO: Optional[str] = None
    ÁREA: str
    ESPECIALIDAD: Optional[str] = None
    FECHA_INGRESO: Optional[str] = None
    ROLES: str
    NÚMERO_COLEGIATURA: Optional[str] = None
    OBSERVACIONES: Optional[str] = None
    
    # Campo para áreas que jefatura (múltiples separadas por comas)
    # Ejemplo: "FARMACIA, RECURSOS HUMANOS, ADMINISTRACION"
    ÁREAS_JEFATURA: Optional[str] = None
    
    # Campo interno para tracking de fila
    _fila: Optional[int] = None
    
    @validator('DNI')
    def validar_dni(cls, v):
        """Validar DNI - si no tiene 8 dígitos, marcar como pendiente"""
        if not v:
            return "PENDIENTE"
        
        dni = str(v).strip()
        if not dni.isdigit() or len(dni) != 8:
            return "PENDIENTE"
        
        return dni
    
    @validator('SEXO')
    def validar_sexo(cls, v):
        """Validar sexo en carga masiva"""
        if not v:
            return "No especificado"
        
        sexo = str(v).strip().upper()
        if sexo in ['M', 'F']:
            return sexo
        if 'MASCULINO' in sexo:
            return 'M'
        if 'FEMENINO' in sexo:
            return 'F'
        
        return "No especificado"
    
    @validator('TELÉFONO')
    def validar_telefono(cls, v):
        """Validar teléfono si existe"""
        if v:
            telefono = str(v).strip()
            telefono = ''.join(c for c in telefono if c.isdigit())
            if telefono and len(telefono) not in [7, 8, 9, 10, 11, 12]:
                return v
            return telefono
        return v
    
    @validator('FECHA_NACIMIENTO', 'FECHA_INGRESO')
    def validar_fecha(cls, v):
        """Validar formato de fecha - si es inválida, devolver None"""
        if v:
            try:
                fecha_str = str(v).strip()
                if fecha_str:
                    datetime.strptime(fecha_str, '%Y-%m-%d')
                    return fecha_str
            except:
                pass
        return None
    
    @validator('ROLES')
    def validar_roles(cls, v):
        """Validar que los roles sean válidos"""
        if not v:
            return "usuario"
        
        roles_validos = [
            'admin', 'jefe_grupo', 'jefe_area', 'jefe_departamento',
            'jefe_direccion', 'recursos_humanos', 'oficina_central',
            'oficial_permanencia', 'control_qr', 'usuario'
        ]
        
        roles = [r.strip().lower() for r in v.split(',') if r.strip()]
        roles_validados = [r for r in roles if r in roles_validos]
        
        if not roles_validados:
            return "usuario"
        
        return ','.join(roles_validados)
    
    def get_areas_jefatura_list(self) -> List[str]:
        """
        Convierte el string de áreas jefatura en una lista
        Ejemplo: "FARMACIA, RRHH" -> ["FARMACIA", "RRHH"]
        """
        if not self.ÁREAS_JEFATURA:
            return []
        
        areas = [
            area.strip().upper() 
            for area in self.ÁREAS_JEFATURA.split(',') 
            if area.strip()
        ]
        return areas
    
    def get_roles_list(self) -> List[str]:
        """
        Convierte el string de roles en una lista
        """
        if not self.ROLES:
            return ["usuario"]
        
        return [r.strip().lower() for r in self.ROLES.split(',') if r.strip()]
    
    class Config:
        from_attributes = True
        alias_generator = None
        populate_by_name = True


class CargaMasivaResponse(BaseModel):
    """
    Schema para la respuesta de carga masiva
    """
    exitosos: int
    fallidos: int
    detalles: List[Dict[str, Any]]
    errores: List[Dict[str, Any]]

    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA VERIFICACIÓN DE RELACIONES
# =====================================================

class VerificarRelacionesResponse(BaseModel):
    """
    Schema para verificar relaciones de un personal
    """
    tiene_relaciones: bool
    detalles: Dict[str, bool]

    class Config:
        from_attributes = True


class VerificarDNIResponse(BaseModel):
    """
    Schema para verificar disponibilidad de DNI
    """
    disponible: bool
    existe: bool
    activo: bool
    id: Optional[UUID] = None
    nombre: Optional[str] = None
    email: Optional[EmailStr] = None

    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA ELIMINACIÓN
# =====================================================

class EliminarResponse(BaseModel):
    """
    Schema para respuesta de eliminación
    """
    success: bool
    message: str
    id: UUID
    soft_delete: Optional[bool] = None

    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA ESTADÍSTICAS (OPCIONAL)
# =====================================================

class PersonalEstadisticas(BaseModel):
    """
    Estadísticas de un personal
    """
    total_turnos: int
    horas_trabajadas: float
    puntualidad: float
    llegadas_tarde: int
    ausencias: int

    class Config:
        from_attributes = True


class PersonalConEstadisticas(PersonalResponse):
    """
    Personal con estadísticas incluidas
    """
    estadisticas: Optional[PersonalEstadisticas] = None

    class Config:
        from_attributes = True


# =====================================================
# SCHEMA PARA INFORMACIÓN DE JEFATURA (RESUMEN)
# =====================================================

class JefaturaResumen(BaseModel):
    """
    Resumen de jefaturas de un usuario
    """
    tiene_acceso_global: bool = False
    roles_jefatura: List[str] = []
    areas_por_tipo: Dict[str, List[str]] = Field(default_factory=dict)
    todas_las_areas: List[str] = []
    
    class Config:
        from_attributes = True