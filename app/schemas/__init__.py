# app/schemas/__init__.py
# VERSIÓN ACTUALIZADA - CON SCHEMAS DE PUBLICACIONES Y NOTIFICACIONES

from app.schemas.auth import *
from app.schemas.personal import *
from app.schemas.planificacion import *
from app.schemas.asistencia import *
from app.schemas.descanso_medico import *
from app.schemas.solicitud_cambio import *
from app.schemas.publicacion import *
from app.schemas.notificacion import *

__all__ = [
    "Token", "TokenData", "LoginRequest", "UserProfile", "PasswordChange",
    "PersonalBase", "PersonalCreate", "PersonalUpdate", "PersonalResponse",
    "Turno", "PlanificacionBase", "PlanificacionCreate", "PlanificacionResponse", "PlanificacionMasiva",
    "AsistenciaBase", "AsistenciaCreate", "AsistenciaResponse", "AsistenciaQR", "JustificacionCreate",
    "DescansoMedicoBase", "DescansoMedicoCreate", "DescansoMedicoResponse", "DescansoMedicoUpdate",
    "SolicitudCambioBase", "SolicitudCambioCreate", "SolicitudCambioResponse", "SolicitudCambioUpdate",
    "PublicacionBase", "PublicacionCreate", "PublicacionUpdate", "PublicacionResponse",
    "PublicacionVistaCreate", "PublicacionVistaResponse", "PublicacionEstadisticas", "EstadisticasGlobales",
    "NotificacionBase", "NotificacionCreate", "NotificacionResponse",
    "NotificacionesCountResponse", "MarcarLeidaResponse", "MarcarTodasLeidasResponse",
    "PreferenciasNotificacionesBase", "PreferenciasNotificacionesResponse"
]