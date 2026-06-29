# app/api/__init__.py
# VERSIÓN ACTUALIZADA - CON BIOMETRÍA + CLIENTES, EMPRESAS, SESIONES, CARTERA, CONFIGURACIÓN DINÁMICA, PRE-REGISTROS, GEOLOCALIZACIÓN E INVENTARIO

from fastapi import APIRouter
from app.api import (
    auth, 
    biometric,
    personal, 
    planificacion, 
    asistencia, 
    descansos_medicos, 
    solicitudes_cambio, 
    qr, 
    configuracion_mensual, 
    publicaciones, 
    notificaciones,
    configuracion,
    empresas,
    clientes,
    sesiones,
    cartera,           # Cartera de Servicios Médicos
    pre_registros,     # Pre-Registros de Personal
    geolocalizacion,   # Geolocalización GPS
    inventario,        # Inventario Logístico
)

api_router = APIRouter()

# Autenticación y Usuarios
api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])

# Biometría - Huella digital / Face ID
api_router.include_router(biometric.router, prefix="/auth", tags=["Biometría"])

# Personal
api_router.include_router(personal.router, prefix="/personal", tags=["Personal"])

# Planificación
api_router.include_router(planificacion.router, prefix="/planificacion", tags=["Planificación"])

# Asistencia
api_router.include_router(asistencia.router, prefix="/asistencia", tags=["Asistencia"])

# Descansos Médicos
api_router.include_router(descansos_medicos.router, prefix="/dm", tags=["Descansos Médicos"])

# Solicitudes
api_router.include_router(solicitudes_cambio.router, prefix="/solicitudes", tags=["Solicitudes de Cambio"])

# QR
api_router.include_router(qr.router, prefix="/qr", tags=["QR"])

# Publicaciones
api_router.include_router(publicaciones.router, prefix="/publicaciones", tags=["Publicaciones"])

# Notificaciones
api_router.include_router(notificaciones.router, prefix="/notificaciones", tags=["Notificaciones"])

# Configuración dinámica
api_router.include_router(configuracion.router, prefix="/config", tags=["Configuración"])

# Gestión de Clientes (Panel Super Admin)
api_router.include_router(clientes.router, prefix="/clientes", tags=["Clientes"])

# Gestión de Empresas (Panel Super Admin + Admin Cliente)
api_router.include_router(empresas.router, prefix="/empresas", tags=["Empresas"])

# Sesiones y Clases (Check-in de visitantes)
api_router.include_router(sesiones.router, prefix="/sesiones", tags=["Sesiones"])

# Cartera de Servicios Médicos (Portal Público + Carga Excel)
api_router.include_router(cartera.router, prefix="/cartera", tags=["Cartera de Servicios"])

# Pre-Registros de Personal (Formulario público + Admin)
api_router.include_router(pre_registros.router, prefix="/pre-registro", tags=["Pre-Registros"])

# CORREGIDO: Geolocalización GPS - SIN prefijo adicional
api_router.include_router(geolocalizacion.router, tags=["Geolocalización"])

# 🆕 Inventario Logístico
api_router.include_router(inventario.router, prefix="/inventario", tags=["Inventario"])

# ⚠️ configuracion_mensual se incluye directamente en main.py

__all__ = [
    'auth',
    'biometric',
    'personal',
    'planificacion',
    'asistencia',
    'descansos_medicos',
    'solicitudes_cambio',
    'qr',
    'configuracion_mensual',
    'publicaciones',
    'notificaciones',
    'configuracion',
    'clientes',
    'empresas',
    'sesiones',
    'cartera',
    'pre_registros',
    'geolocalizacion',
    'inventario',
    'api_router'
]