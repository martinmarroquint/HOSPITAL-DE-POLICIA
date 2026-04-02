# D:\Centro de control Hospital PNP\back\app\schemas\configuracion_mensual.py

from pydantic import BaseModel, Field
from datetime import datetime
from typing import Optional, List, Dict, Any

# Schema base
class ConfiguracionMensualBase(BaseModel):
    año: int = Field(..., ge=2020, le=2100)
    mes: int = Field(..., ge=1, le=12)
    turnos_base: int = Field(23, ge=20, le=30)
    motivo: Optional[str] = None
    observacion: Optional[str] = None

# Schema para crear/actualizar
class ConfiguracionMensualCreate(ConfiguracionMensualBase):
    validado: bool = False

class ConfiguracionMensualUpdate(BaseModel):
    turnos_base: Optional[int] = Field(None, ge=20, le=30)
    motivo: Optional[str] = None
    observacion: Optional[str] = None
    validado: Optional[bool] = None

# Schema para validar (acción específica)
class ConfiguracionMensualValidar(BaseModel):
    turnos_base: int = Field(..., ge=20, le=30)
    motivo: Optional[str] = None
    observacion: Optional[str] = None

# Schema para respuesta
class ConfiguracionMensualResponse(ConfiguracionMensualBase):
    id: int
    validado: bool
    fecha_validacion: Optional[datetime] = None
    validado_por: Optional[int] = None
    creado_en: datetime
    actualizado_en: Optional[datetime] = None
    historial: List[Dict[str, Any]] = []
    
    class Config:
        from_attributes = True

# Schema para respuesta con nombre de validador
class ConfiguracionMensualDetailResponse(ConfiguracionMensualResponse):
    validado_por_nombre: Optional[str] = None

# Schema para respuesta de rango
class ConfiguracionMensualRangoResponse(BaseModel):
    configuraciones: Dict[str, ConfiguracionMensualResponse]  # key: "YYYY-MM"
    total: int
    validados: int
    pendientes: int