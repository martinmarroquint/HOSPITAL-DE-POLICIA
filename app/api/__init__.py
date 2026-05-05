# app/api/__init__.py
# VERSIÓN ACTUALIZADA - CON ROUTER DE SESIONES, EMPRESAS Y CONFIGURACIÓN DINÁMICA

from fastapi import APIRouter
from app.api import (
    auth, 
    personal, 
    planificacion, 
    asistencia, 
    descansos_medicos, 
    solicitudes_cambio, 
    qr, 
    configuracion_mensual, 
    publicaciones, 
    notificaciones,
    configuracion,  # Configuración dinámica
    empresas,        # Gestión de empresas (Panel Super Admin)
    sesiones,        # 🆕 Gestión de sesiones, clases y eventos
)

api_router = APIRouter()

# Autenticación y Usuarios
api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])

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

# Gestión de Empresas (Panel Super Admin)
api_router.include_router(empresas.router, prefix="/empresas", tags=["Empresas"])

# 🆕 Sesiones y Clases (Check-in de visitantes)
api_router.include_router(sesiones.router, prefix="/sesiones", tags=["Sesiones"])

# ⚠️ configuracion_mensual se incluye directamente en main.py

__all__ = [
    'auth',
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
    'empresas',
    'sesiones',  # 🆕 NUEVO
    'api_router'
]