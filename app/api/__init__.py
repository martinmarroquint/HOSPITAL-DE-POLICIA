# app/api/__init__.py
# VERSION ACTUALIZADA - CON BIOMETRIA + CLIENTES, EMPRESAS, SESIONES, CARTERA, CONFIGURACION DINAMICA, PRE-REGISTROS, GEOLOCALIZACION, INVENTARIO
# OCR ELIMINADO - Ahora funciona independientemente en el frontend con Google Sheets

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
    cartera,
    pre_registros,
    geolocalizacion,
    inventario,
)

api_router = APIRouter()

# Autenticacion y Usuarios
api_router.include_router(auth.router, prefix="/auth", tags=["Autenticacion"])

# Biometria - Huella digital / Face ID
api_router.include_router(biometric.router, prefix="/auth", tags=["Biometria"])

# Personal
api_router.include_router(personal.router, prefix="/personal", tags=["Personal"])

# Planificacion
api_router.include_router(planificacion.router, prefix="/planificacion", tags=["Planificacion"])

# Asistencia
api_router.include_router(asistencia.router, prefix="/asistencia", tags=["Asistencia"])

# Descansos Medicos
api_router.include_router(descansos_medicos.router, prefix="/dm", tags=["Descansos Medicos"])

# Solicitudes
api_router.include_router(solicitudes_cambio.router, prefix="/solicitudes", tags=["Solicitudes de Cambio"])

# QR
api_router.include_router(qr.router, prefix="/qr", tags=["QR"])

# Publicaciones
api_router.include_router(publicaciones.router, prefix="/publicaciones", tags=["Publicaciones"])

# Notificaciones
api_router.include_router(notificaciones.router, prefix="/notificaciones", tags=["Notificaciones"])

# Configuracion dinamica
api_router.include_router(configuracion.router, prefix="/config", tags=["Configuracion"])

# Gestion de Clientes (Panel Super Admin)
api_router.include_router(clientes.router, prefix="/clientes", tags=["Clientes"])

# Gestion de Empresas (Panel Super Admin + Admin Cliente)
api_router.include_router(empresas.router, prefix="/empresas", tags=["Empresas"])

# Sesiones y Clases (Check-in de visitantes)
api_router.include_router(sesiones.router, prefix="/sesiones", tags=["Sesiones"])

# Cartera de Servicios Medicos (Portal Publico + Carga Excel)
api_router.include_router(cartera.router, prefix="/cartera", tags=["Cartera de Servicios"])

# Pre-Registros de Personal (Formulario publico + Admin)
api_router.include_router(pre_registros.router, prefix="/pre-registro", tags=["Pre-Registros"])

# Geolocalizacion GPS
api_router.include_router(geolocalizacion.router, tags=["Geolocalizacion"])

# Inventario Logistico
api_router.include_router(inventario.router, prefix="/inventario", tags=["Inventario"])

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