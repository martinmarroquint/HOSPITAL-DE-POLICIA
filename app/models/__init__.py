# app/models/__init__.py
# VERSIÓN ACTUALIZADA - CON MODELOS DE PUBLICACIONES

from app.models.usuario import Usuario
from app.models.personal import Personal
from app.models.planificacion import Planificacion
from app.models.planificacion_borrador import PlanificacionBorrador
from app.models.asistencia import Asistencia
from app.models.descanso_medico import DescansoMedico
from app.models.solicitud_cambio import SolicitudCambio
from app.models.solicitud import Solicitud, TipoSolicitud, EstadoSolicitud
from app.models.trazabilidad import Trazabilidad, AccionTrazabilidad
from app.models.jerarquia import Jerarquia, NivelJerarquico, TipoArea
from app.models.qr import QRRegistro
from app.models.configuracion_mensual import ConfiguracionMensual
from app.models.publicacion import Publicacion, PublicacionVista

__all__ = [
    "Usuario",
    "Personal",
    "Planificacion",
    "PlanificacionBorrador",
    "Asistencia",
    "DescansoMedico",
    "SolicitudCambio",
    "Solicitud",
    "TipoSolicitud",
    "EstadoSolicitud",
    "Trazabilidad",
    "AccionTrazabilidad",
    "Jerarquia",
    "NivelJerarquico",
    "TipoArea",
    "QRRegistro",
    "ConfiguracionMensual",
    "Publicacion",
    "PublicacionVista"
]