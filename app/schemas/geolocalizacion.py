# app/schemas/geolocalizacion.py

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
from uuid import UUID


class GeolocalizacionRequest(BaseModel):
    """Request para registrar asistencia por geolocalización"""
    latitud: float = Field(..., ge=-90, le=90, description="Latitud del dispositivo")
    longitud: float = Field(..., ge=-180, le=180, description="Longitud del dispositivo")
    precision: Optional[float] = Field(None, ge=0, description="Precisión del GPS en metros")
    timestamp: Optional[int] = Field(None, description="Timestamp del dispositivo")
    navegador: Optional[str] = Field(None, description="User agent del navegador")
    dispositivo: Optional[str] = Field(None, description="Tipo de dispositivo")


class GeolocalizacionResponse(BaseModel):
    """Response de registro de asistencia por geolocalización"""
    success: bool
    registro: Optional[dict] = None
    distancia: Optional[float] = None
    dentro_del_radio: Optional[bool] = None
    sede_nombre: Optional[str] = None
    mensaje: str


class EstadoGeolocalizacionResponse(BaseModel):
    """Response del último estado de geolocalización"""
    ultimo_registro: Optional[dict] = None
    config: Optional[dict] = None


class SedeCreate(BaseModel):
    """Crear nueva sede"""
    nombre: str = Field(..., min_length=1, max_length=255)
    descripcion: Optional[str] = None
    latitud: float = Field(..., ge=-90, le=90)
    longitud: float = Field(..., ge=-180, le=180)
    radio_permitido: int = Field(50, ge=10, le=1000)


class SedeUpdate(BaseModel):
    """Actualizar sede existente"""
    nombre: Optional[str] = Field(None, min_length=1, max_length=255)
    descripcion: Optional[str] = None
    latitud: Optional[float] = Field(None, ge=-90, le=90)
    longitud: Optional[float] = Field(None, ge=-180, le=180)
    radio_permitido: Optional[int] = Field(None, ge=10, le=1000)
    activo: Optional[bool] = None


class SedeResponse(BaseModel):
    """Response de sede"""
    id: str
    nombre: str
    descripcion: Optional[str] = None
    latitud: float
    longitud: float
    radio_permitido: int
    activo: bool


class ConfigGeolocalizacionUpdate(BaseModel):
    """Actualizar configuración de geolocalización"""
    activo: Optional[bool] = None
    radio_tolerancia_default: Optional[int] = Field(None, ge=10, le=1000)
    precision_minima: Optional[int] = Field(None, ge=10, le=500)
    exigir_alta_precision: Optional[bool] = None
    permitir_sin_gps: Optional[bool] = None
    mostrar_distancia: Optional[bool] = None