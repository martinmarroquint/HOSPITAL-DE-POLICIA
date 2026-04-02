from pydantic import BaseModel, EmailStr, Field, validator
from typing import Optional, List, Dict, Any
from datetime import date, datetime
from uuid import UUID

# =====================================================
# SCHEMAS BASE
# =====================================================

class PersonalBase(BaseModel):
    dni: str = Field(..., min_length=1, max_length=8)  # Permitir valores temporales
    cip: str
    grado: str
    nombre: str
    sexo: Optional[str] = Field(None, description="Sexo del personal (M, F, No especificado)")
    email: EmailStr
    telefono: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    area: str
    especialidad: Optional[str] = None
    numero_colegiatura: Optional[str] = None
    condicion: Optional[str] = None
    observaciones: Optional[str] = None
    # ✅ CAMPO ACTUALIZADO: Ahora es una lista de áreas que jefatura
    areas_que_jefatura: Optional[List[str]] = Field(default=[])

    @validator('dni')
    def validar_dni(cls, v):
        """Validar que el DNI tenga 8 dígitos, si no, marcar como pendiente"""
        dni = str(v).strip()
        if not dni:
            return "PENDIENTE"
        
        # Si tiene menos de 8 dígitos o no son dígitos, marcar como pendiente
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

class PersonalCreate(PersonalBase):
    fecha_ingreso: Optional[date] = None
    roles: List[str] = ["usuario"]
    activo: bool = True

class PersonalUpdate(BaseModel):
    dni: Optional[str] = Field(None, min_length=1, max_length=8)
    cip: Optional[str] = None
    grado: Optional[str] = None
    nombre: Optional[str] = None
    sexo: Optional[str] = None
    email: Optional[EmailStr] = None
    telefono: Optional[str] = None
    fecha_nacimiento: Optional[date] = None
    area: Optional[str] = None
    especialidad: Optional[str] = None
    numero_colegiatura: Optional[str] = None
    condicion: Optional[str] = None
    observaciones: Optional[str] = None
    activo: Optional[bool] = None
    roles: Optional[List[str]] = None
    # ✅ CAMPO ACTUALIZADO: Ahora es una lista de áreas que jefatura
    areas_que_jefatura: Optional[List[str]] = Field(default=[])

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

class PersonalResponse(PersonalBase):
    id: UUID
    fecha_ingreso: Optional[date]
    roles: List[str]
    activo: bool
    sexo: Optional[str] = "No especificado"
    created_at: datetime
    updated_at: Optional[datetime]
    # ✅ CAMPO ACTUALIZADO: Ahora es una lista de áreas que jefatura
    areas_que_jefatura: Optional[List[str]] = Field(default=[])

    class Config:
        from_attributes = True


# =====================================================
# SCHEMAS PARA CARGA MASIVA (ACTUALIZADO CON SEXO Y AREAS_JEFATURA)
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
    # ✅ CAMPO ACTUALIZADO: Puede ser múltiples áreas separadas por comas
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
        # Si tiene menos de 8 dígitos o no son dígitos, marcar como pendiente
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
            # Limpiar el teléfono (quitar espacios, guiones, etc.)
            telefono = ''.join(c for c in telefono if c.isdigit())
            if telefono and len(telefono) not in [7, 8, 9, 10, 11, 12]:
                # Si no tiene el formato correcto, devolver como está pero marcar en advertencias
                return v
            return telefono
        return v
    
    @validator('FECHA_NACIMIENTO', 'FECHA_INGRESO')
    def validar_fecha(cls, v):
        """Validar formato de fecha - si es inválida, devolver None"""
        if v:
            try:
                # Intentar parsear la fecha
                fecha_str = str(v).strip()
                if fecha_str:
                    datetime.strptime(fecha_str, '%Y-%m-%d')
                    return fecha_str
            except:
                pass
        return None
    
    def get_areas_jefatura_list(self) -> List[str]:
        """
        Convierte el string de áreas jefatura en una lista
        Ejemplo: "FARMACIA, RRHH" -> ["FARMACIA", "RRHH"]
        """
        if not self.ÁREAS_JEFATURA:
            return []
        
        # Separar por comas, limpiar espacios y convertir a mayúsculas
        areas = [
            area.strip().upper() 
            for area in self.ÁREAS_JEFATURA.split(',') 
            if area.strip()
        ]
        return areas
    
    class Config:
        from_attributes = True
        # Permitir nombres de campos con espacios y tildes
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