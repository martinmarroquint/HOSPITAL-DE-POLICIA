# app/schemas/__init__.py
# VERSIÓN ACTUALIZADA - CON CARTERA DE SERVICIOS MÉDICOS

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
from app.schemas.cartera import *   # NUEVO - Cartera de Servicios Médicos

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
]