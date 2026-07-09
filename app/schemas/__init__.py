# app/schemas/__init__.py
# VERSIÓN ACTUALIZADA - CON CARTERA DE SERVICIOS MÉDICOS + GEOLOCALIZACIÓN + INVENTARIO + EXÁMENES

from app.schemas.auth import *
from app.schemas.personal import *
from app.schemas.planificacion import *
from app.schemas.asistencia import *
from app.schemas.descanso_medico import *
from app.schemas.solicitud_cambio import *
from app.schemas.publicacion import *
from app.schemas.notificacion import *
from app.schemas.empresa import *
from app.schemas.cliente import *
from app.schemas.cartera import *          # Cartera de Servicios Médicos
from app.schemas.geolocalizacion import *   # Geolocalización GPS
from app.schemas.inventario import *        # Inventario Logístico
from app.schemas.examenes import *          # Exámenes Online

__all__ = [
    # AUTH
    "Token", "TokenData", "LoginRequest", "UserProfile", "PasswordChange",
    "UsuarioCreate", "UsuarioUpdate", "UsuarioResetPassword",
    
    # PERSONAL
    "PersonalBase", "PersonalCreate", "PersonalUpdate", "PersonalResponse",
    "CargaMasivaItem", "CargaMasivaResponse",
    "VerificarRelacionesResponse", "VerificarDNIResponse",
    "EliminarResponse", "JefaturaResumen",
    
    # PLANIFICACIÓN
    "Turno", "PlanificacionBase", "PlanificacionCreate", 
    "PlanificacionResponse", "PlanificacionMasiva",
    "ObservacionCreate", "EstadoPlanificacion",
    
    # ASISTENCIA
    "AsistenciaBase", "AsistenciaCreate", "AsistenciaResponse", 
    "AsistenciaQR", "JustificacionCreate",
    "EstadisticasAsistencia", "IncidenciaAsistencia",
    
    # DESCANSOS MÉDICOS
    "DescansoMedicoBase", "DescansoMedicoCreate", 
    "DescansoMedicoResponse", "DescansoMedicoUpdate",
    
    # SOLICITUDES DE CAMBIO
    "SolicitudCambioBase", "SolicitudCambioCreate", 
    "SolicitudCambioResponse", "SolicitudCambioUpdate",
    
    # PUBLICACIONES
    "PublicacionBase", "PublicacionCreate", "PublicacionUpdate", 
    "PublicacionResponse",
    "PublicacionVistaCreate", "PublicacionVistaResponse", 
    "PublicacionEstadisticas", "EstadisticasGlobales",
    
    # NOTIFICACIONES
    "NotificacionBase", "NotificacionCreate", "NotificacionResponse",
    "NotificacionesCountResponse", "MarcarLeidaResponse", 
    "MarcarTodasLeidasResponse",
    "PreferenciasNotificacionesBase", "PreferenciasNotificacionesResponse",
    
    # EMPRESAS
    "EmpresaCreate", "EmpresaUpdate", "EmpresaResponse", 
    "EmpresaDetailResponse", "EmpresaStatsResponse", "MisEmpresasResponse",
    
    # CLIENTES
    "ClienteCreate", "ClienteUpdate", "ClienteResponse",
    "ClienteDetailResponse", "ClienteStatsResponse",
    
    # CARTERA DE SERVICIOS MÉDICOS
    "ResultadoValidacion", "EspecialidadResponse", "MedicoResponse",
    "CargaResponse", "HorarioResponse",
    
    # GEOLOCALIZACIÓN GPS
    "GeolocalizacionRequest",
    "GeolocalizacionResponse",
    "EstadoGeolocalizacionResponse",
    "SedeCreate",
    "SedeUpdate",
    "SedeResponse",
    "ConfigGeolocalizacionUpdate",
    
    # INVENTARIO LOGÍSTICO
    "CatalogoItemCreate",
    "CatalogoItemUpdate",
    "CatalogoItemResponse",
    "InventarioUnidadCreate",
    "InventarioUnidadUpdate",
    "InventarioUnidadResponse",

    # EXÁMENES ONLINE
    "AfirmacionVF",
    "SegmentoCompletar",
    "PreguntaBase",
    "PreguntaCreate",
    "PreguntaResponse",
    "ConfiguracionExamen",
    "ExamenCreate",
    "ExamenUpdate",
    "ExamenResponse",
    "ExamenDetailResponse",
    "ResultadoCreate",
    "ResultadoResponse",
    "MensajeResponse",
]