# app/models/__init__.py
# VERSION ACTUALIZADA - CON BIOMETRÍA + METAS + ROTACIONES + CARTERA + PRE-REGISTROS + GEOLOCALIZACIÓN + INVENTARIO + EXÁMENES + GRUPOS

from app.models.usuario import Usuario
from app.models.personal import Personal
from app.models.empresa import Empresa
from app.models.cliente import Cliente
from app.models.planificacion import Planificacion
from app.models.planificacion_borrador import PlanificacionBorrador
from app.models.asistencia import Asistencia
from app.models.justificacion_asistencia import JustificacionAsistencia
from app.models.descanso_medico import DescansoMedico
from app.models.solicitud_cambio import SolicitudCambio
from app.models.solicitud import Solicitud, TipoSolicitud, EstadoSolicitud
from app.models.trazabilidad import Trazabilidad, AccionTrazabilidad
from app.models.jerarquia import Jerarquia, NivelJerarquico, TipoArea
from app.models.qr import QRRegistro
from app.models.configuracion_mensual import ConfiguracionMensual
from app.models.publicacion import Publicacion, PublicacionVista
from app.models.notificacion import Notificacion
from app.models.meta_cumplimiento import MetaCumplimiento
from app.models.rotacion import Rotacion
from app.models.biometric import BiometricCredential
from app.models.pre_registro import PreRegistro

# Cartera de Servicios Médicos
from app.models.cartera import Especialidad, Programacion, CargaExcel

# Geolocalización GPS
from app.models.geolocalizacion import Sede, ConfigGeolocalizacion, RegistroGeolocalizacion

# Inventario Logístico
from app.models.catalogo_item import CatalogoItem
from app.models.inventario_unidad import InventarioUnidad

# Exámenes Online
from app.models.examen import Examen
from app.models.pregunta import Pregunta
from app.models.resultado_examen import ResultadoExamen
from app.models.alumno_examen import AlumnoExamen

# Grupos (Clases/Grupos de docentes)
from app.models.grupo import Grupo

# Configuracion dinamica
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
    # MULTI-TENANCY Y JERARQUIA
    "Empresa",
    "Cliente",
    
    # USUARIOS Y PERSONAL
    "Usuario",
    "Personal",
    "PreRegistro",
    
    # PLANIFICACION
    "Planificacion",
    "PlanificacionBorrador",
    "ConfiguracionMensual",
    
    # METAS DE CUMPLIMIENTO
    "MetaCumplimiento",
    
    # ROTACIONES
    "Rotacion",
    
    # ASISTENCIA Y JUSTIFICACIONES
    "Asistencia",
    "JustificacionAsistencia",
    "QRRegistro",
    
    # GEOLOCALIZACIÓN GPS
    "Sede",
    "ConfigGeolocalizacion",
    "RegistroGeolocalizacion",
    
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
    
    # JERARQUIA
    "Jerarquia",
    "NivelJerarquico",
    "TipoArea",
    
    # COMUNICACIONES
    "Publicacion",
    "PublicacionVista",
    "Notificacion",
    
    # BIOMETRÍA
    "BiometricCredential",
    
    # CARTERA DE SERVICIOS MÉDICOS
    "Especialidad",
    "Programacion",
    "CargaExcel",
    
    # INVENTARIO LOGÍSTICO
    "CatalogoItem",
    "InventarioUnidad",
    
    # EXÁMENES ONLINE
    "Examen",
    "Pregunta",
    "ResultadoExamen",
    "AlumnoExamen",
    
    # GRUPOS (CLASES/GRUPOS DE DOCENTES)
    "Grupo",
    
    # CONFIGURACION DINAMICA
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