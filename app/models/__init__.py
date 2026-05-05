# app/models/__init__.py
# VERSIÓN ACTUALIZADA - CON MODELO DE EMPRESA Y CONFIGURACIÓN DINÁMICA

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
from app.models.notificacion import Notificacion

# 🆕 MODELO DE EMPRESA (MULTI-TENANCY)
from app.models.empresa import Empresa

# 🆕 MODELOS DE CONFIGURACIÓN DINÁMICA
from app.models.configuracion import (
    ConfigTurno,
    ConfigRegla,
    ConfigNivelJerarquico,
    ConfigUnidad,
    ConfigRol,
    ConfigCampoPersonal,
    ConfigCatalogo,
    ConfigCliente,
    TipoTurno,
    UnidadMedida,
    Periodicidad,
    TipoMeta,
    MetodoRedondeo,
    AlcanceRegla,
    TipoCampo,
)

__all__ = [
    # MULTI-TENANCY
    "Empresa",
    
    # USUARIOS Y PERSONAL
    "Usuario",
    "Personal",
    
    # PLANIFICACIÓN
    "Planificacion",
    "PlanificacionBorrador",
    "ConfiguracionMensual",
    
    # ASISTENCIA
    "Asistencia",
    "QRRegistro",
    
    # SALUD
    "DescansoMedico",
    
    # SOLICITUDES
    "SolicitudCambio",
    "Solicitud",
    "TipoSolicitud",
    "EstadoSolicitud",
    
    # TRAZABILIDAD
    "Trazabilidad",
    "AccionTrazabilidad",
    
    # JERARQUÍA
    "Jerarquia",
    "NivelJerarquico",
    "TipoArea",
    
    # COMUNICACIONES
    "Publicacion",
    "PublicacionVista",
    "Notificacion",
    
    # CONFIGURACIÓN DINÁMICA
    "ConfigTurno",
    "ConfigRegla",
    "ConfigNivelJerarquico",
    "ConfigUnidad",
    "ConfigRol",
    "ConfigCampoPersonal",
    "ConfigCatalogo",
    "ConfigCliente",
    "TipoTurno",
    "UnidadMedida",
    "Periodicidad",
    "TipoMeta",
    "MetodoRedondeo",
    "AlcanceRegla",
    "TipoCampo",
]