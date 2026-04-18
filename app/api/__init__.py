# app/api/__init__.py
# VERSIÓN ACTUALIZADA - CON ROUTER DE PUBLICACIONES Y NOTIFICACIONES

from fastapi import APIRouter
from app.api import auth, personal, planificacion, asistencia, descansos_medicos, solicitudes_cambio, qr, configuracion_mensual, publicaciones, notificaciones

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Autenticación"])
api_router.include_router(personal.router, prefix="/personal", tags=["Personal"])
api_router.include_router(planificacion.router, prefix="/planificacion", tags=["Planificación"])
api_router.include_router(asistencia.router, prefix="/asistencia", tags=["Asistencia"])
api_router.include_router(descansos_medicos.router, prefix="/dm", tags=["Descansos Médicos"])
api_router.include_router(solicitudes_cambio.router, prefix="/solicitudes", tags=["Solicitudes de Cambio"])
api_router.include_router(qr.router, prefix="/qr", tags=["QR"])
api_router.include_router(publicaciones.router, prefix="/publicaciones", tags=["Publicaciones"])
api_router.include_router(notificaciones.router, prefix="/notificaciones", tags=["Notificaciones"])
# ⚠️ ELIMINADO: configuracion_mensual.router se incluye directamente en main.py

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
    'api_router'
]