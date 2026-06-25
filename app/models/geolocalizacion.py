# app/models/geolocalizacion.py

from sqlalchemy import Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.database import Base


class Sede(Base):
    """
    Sedes autorizadas para registro de asistencia por geolocalización.
    Cada empresa puede tener múltiples sedes con diferentes radios de tolerancia.
    """
    __tablename__ = "sedes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False)
    nombre = Column(String(255), nullable=False)
    descripcion = Column(Text, nullable=True)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    radio_permitido = Column(Integer, default=50)  # metros
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ConfigGeolocalizacion(Base):
    """
    Configuración de geolocalización por empresa.
    Define si el módulo está activo y los parámetros de validación.
    """
    __tablename__ = "config_geolocalizacion"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id", ondelete="CASCADE"), nullable=False, unique=True)
    activo = Column(Boolean, default=False)
    radio_tolerancia_default = Column(Integer, default=50)  # metros
    precision_minima = Column(Integer, default=100)  # metros
    exigir_alta_precision = Column(Boolean, default=False)
    permitir_sin_gps = Column(Boolean, default=False)
    mostrar_distancia = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class RegistroGeolocalizacion(Base):
    """
    Registro de asistencias realizadas por geolocalización.
    Almacena las coordenadas GPS y los resultados de la validación.
    """
    __tablename__ = "registros_geolocalizacion"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    asistencia_id = Column(UUID(as_uuid=True), ForeignKey("asistencias.id", ondelete="CASCADE"), nullable=False)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id", ondelete="CASCADE"), nullable=False)
    sede_id = Column(UUID(as_uuid=True), ForeignKey("sedes.id", ondelete="SET NULL"), nullable=True)
    latitud = Column(Float, nullable=False)
    longitud = Column(Float, nullable=False)
    precision_gps = Column(Float, nullable=True)  # metros
    distancia_calculada = Column(Float, nullable=True)  # metros
    dentro_del_radio = Column(Boolean, default=False)
    ip_origen = Column(String(45), nullable=True)
    navegador = Column(Text, nullable=True)
    dispositivo = Column(String(50), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)