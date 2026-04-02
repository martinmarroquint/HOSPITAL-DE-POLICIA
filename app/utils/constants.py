# app/utils/constants.py
"""
Constantes globales para toda la aplicación
Centraliza todos los valores fijos para facilitar mantenimiento
"""

from enum import Enum
from typing import Dict, List, Any

# =====================================================
# TIPOS DE SOLICITUD (debe coincidir con models/solicitud.py)
# =====================================================
TIPOS_SOLICITUD = {
    "PROPIO": "propio",
    "INTERCAMBIO": "intercambio",
    "PLANIFICACION_MENSUAL": "planificacion_mensual",
    "VACACIONES": "vacaciones",
    "PERMISO": "permiso",
    "DESCANSO_MEDICO": "descanso_medico",
    "LICENCIA": "licencia",
    "CAPACITACION": "capacitacion",
    "OTRO": "otro"
}

TIPOS_SOLICITUD_LISTA = list(TIPOS_SOLICITUD.values())

# Tipos que requieren aprobación multinivel
TIPOS_MULTINIVEL = [
    TIPOS_SOLICITUD["VACACIONES"],
    TIPOS_SOLICITUD["LICENCIA"],
    TIPOS_SOLICITUD["PLANIFICACION_MENSUAL"]
]

# Tipos que pueden tener documentos adjuntos
TIPOS_CON_DOCUMENTOS = [
    TIPOS_SOLICITUD["DESCANSO_MEDICO"],
    TIPOS_SOLICITUD["LICENCIA"],
    TIPOS_SOLICITUD["CAPACITACION"]
]

# =====================================================
# ESTADOS DE SOLICITUD
# =====================================================
ESTADOS_SOLICITUD = {
    "BORRADOR": "borrador",
    "PENDIENTE": "pendiente",
    "EN_APROBACION": "en_aprobacion",
    "APROBADA": "aprobada",
    "RECHAZADA": "rechazada",
    "OBSERVADA": "observada",
    "CANCELADA": "cancelada"
}

ESTADOS_SOLICITUD_LISTA = list(ESTADOS_SOLICITUD.values())

# Estados en los que se puede editar
ESTADOS_EDITABLES = [
    ESTADOS_SOLICITUD["BORRADOR"],
    ESTADOS_SOLICITUD["OBSERVADA"]
]

# Estados finales (no se pueden modificar)
ESTADOS_FINALES = [
    ESTADOS_SOLICITUD["APROBADA"],
    ESTADOS_SOLICITUD["RECHAZADA"],
    ESTADOS_SOLICITUD["CANCELADA"]
]

# =====================================================
# ACCIONES DE TRAZABILIDAD
# =====================================================
ACCIONES_TRAZABILIDAD = {
    "CREACION": "creacion",
    "ENVIO": "envio",
    "APROBACION": "aprobacion",
    "RECHAZO": "rechazo",
    "OBSERVACION": "observacion",
    "CANCELACION": "cancelacion",
    "MODIFICACION": "modificacion",
    "VISUALIZACION": "visualizacion",
    "DESCARGA_QR": "descarga_qr",
    "VALIDACION_QR": "validacion_qr",
    "SUBIDA_DOCUMENTO": "subida_documento",
    "NOTIFICACION": "notificacion",
    "GENERACION_TOKEN": "generacion_token",  # 🆕 NUEVO
    "VALIDACION_TOKEN": "validacion_token"   # 🆕 NUEVO
}

ACCIONES_TRAZABILIDAD_LISTA = list(ACCIONES_TRAZABILIDAD.values())

# =====================================================
# 🆕 CONFIGURACIÓN DE TOKEN DE EMERGENCIA (NUEVO)
# =====================================================
TOKEN_CONFIG = {
    "DURACION_DEFAULT": 5,           # minutos
    "DURACION_MINIMA": 1,            # mínimo 1 minuto
    "DURACION_MAXIMA": 15,           # máximo 15 minutos
    "INTENTOS_MAXIMOS": 3,           # intentos permitidos
    "LONGITUD_TOKEN": 8,             # caracteres
    "CARACTERES_SEGUROS": "ABCDEFGHJKLMNPQRSTUVWXYZ23456789",  # Sin 0,O,I,1
    "FORMATO": "XXXX-XXXX",          # formato para mostrar
    "TOKEN_PREFIX": "TKN",            # prefijo para identificación
    "BLOQUEAR_DESPUES_INTENTOS": True # bloquear después de intentos fallidos
}

# Mensajes para token
TOKEN_MENSAJES = {
    "generado": "Token de emergencia generado exitosamente",
    "expirado": "El token ha expirado. Genere uno nuevo.",
    "usado": "Este token ya fue utilizado",
    "incorrecto": "Token incorrecto. Le quedan {intentos} intentos.",
    "bloqueado": "Demasiados intentos fallidos. Genere un nuevo token.",
    "no_activo": "No hay token activo para esta solicitud",
    "instrucciones": "Ingrese el token de 8 caracteres (formato XXXX-XXXX)"
}

# =====================================================
# NIVELES JERÁRQUICOS
# =====================================================
NIVELES_JERARQUICOS = {
    "NIVEL_1": 1,  # Jefe inmediato
    "NIVEL_2": 2,  # Jefe de departamento
    "NIVEL_3": 3,  # Subdirector
    "NIVEL_4": 4,  # Director
    "NIVEL_5": 5   # Director General
}

NIVELES_JERARQUICOS_LISTA = [1, 2, 3, 4, 5]

# Descripción de cada nivel
NIVELES_DESCRIPCION = {
    1: "Jefe inmediato (supervisor, coordinador)",
    2: "Jefe de departamento",
    3: "Subdirector",
    4: "Director",
    5: "Director General / Comandante"
}

# =====================================================
# TIPOS DE ÁREA
# =====================================================
TIPOS_AREA = {
    "DEPARTAMENTO": "departamento",
    "SECCION": "seccion",
    "SERVICIO": "servicio",
    "UNIDAD": "unidad",
    "OTRO": "otro"
}

TIPOS_AREA_LISTA = list(TIPOS_AREA.values())

# Áreas críticas que requieren más niveles de aprobación
AREAS_CRITICAS = [
    "EMERGENCIA",
    "UCI",
    "QUIROFANO",
    "NEONATOLOGIA",
    "CARDIOLOGIA"
]

# =====================================================
# ROLES DE USUARIO
# =====================================================
ROLES = {
    "ADMIN": "admin",
    "JEFE_AREA": "jefe_area",
    "OFICIAL_PERMANENCIA": "oficial_permanencia",
    "CONTROL_QR": "control_qr",
    "USUARIO": "usuario",
    "MEDICO": "medico",
    "ENFERMERO": "enfermero",
    "TECNICO": "tecnico"
}

ROLES_LISTA = list(ROLES.values())

# Roles que pueden aprobar solicitudes
ROLES_APROBADORES = [
    ROLES["ADMIN"],
    ROLES["JEFE_AREA"]
]

# Roles para control de asistencia
ROLES_CONTROL_ASISTENCIA = [
    ROLES["OFICIAL_PERMANENCIA"],
    ROLES["CONTROL_QR"],
    ROLES["ADMIN"]
]

# =====================================================
# TIPOS DE TURNO
# =====================================================
TIPOS_TURNO = {
    "MANANA": "MAN",
    "TARDE": "TAR",
    "NOCHE": "NOC",
    "FRANCO": "FRA",
    "VACACIONES": "VAC",
    "DESCANSO_MEDICO": "DM",
    "LIBRE": "LIB",
    "DIA24": "DIA24"
}

TIPOS_TURNO_LISTA = list(TIPOS_TURNO.values())

# Mapeo de códigos cortos a códigos largos
MAPA_TURNOS = {
    'M': 'MAN',
    'T': 'TAR',
    'N': 'NOC',
    'F': 'FRA',
    'V': 'VAC',
    'D': 'DM',
    'L': 'LIB',
    '24': 'DIA24',
    'D24': 'DIA24'
}

# =====================================================
# TIPOS DE REGISTRO DE ASISTENCIA
# =====================================================
TIPOS_REGISTRO_ASISTENCIA = {
    "ENTRADA": "ENTRADA",
    "SALIDA": "SALIDA"
}

TIPOS_REGISTRO_ASISTENCIA_LISTA = ["ENTRADA", "SALIDA"]

# =====================================================
# TIPOS DE QR
# =====================================================
TIPOS_QR = {
    "ASISTENCIA": "asistencia",
    "TRAMITE": "tramite"
}

# Duración por defecto de QR de asistencia (segundos)
QR_ASISTENCIA_DURACION = 10

# =====================================================
# VALIDACIONES Y LÍMITES
# =====================================================
LIMITES = {
    "VACACIONES_MAX_DIAS": 30,
    "VACACIONES_AVISO_DIAS": 15,  # Días a partir de los cuales avisar
    "DESCANSO_MEDICO_MAX_DIAS": 30,
    "DESCANSO_MEDICO_AVISO_DIAS": 3,
    "PERMISO_MAX_HORAS": 8,
    "DOCUMENTO_MAX_SIZE_MB": 10,
    "SOLICITUD_MOTIVO_MIN_LENGTH": 5,
    "SOLICITUD_MOTIVO_MAX_LENGTH": 50,
    "OBSERVACION_MAX_LENGTH": 500
}

# =====================================================
# PAGINACIÓN
# =====================================================
PAGINACION = {
    "PAGINA_DEFAULT": 1,
    "TAMANO_DEFAULT": 20,
    "TAMANO_MAXIMO": 100
}

# =====================================================
# CÓDIGOS DE ERROR COMUNES
# =====================================================
ERROR_CODES = {
    "NOT_FOUND": "RECURSO_NO_ENCONTRADO",
    "UNAUTHORIZED": "NO_AUTORIZADO",
    "FORBIDDEN": "PROHIBIDO",
    "VALIDATION_ERROR": "ERROR_VALIDACION",
    "DUPLICATE": "REGISTRO_DUPLICADO",
    "INVALID_STATE": "ESTADO_INVALIDO",
    "QR_INVALID": "QR_INVALIDO",
    "QR_EXPIRED": "QR_EXPIRADO",
    "QR_USED": "QR_YA_USADO",
    "TOKEN_INVALIDO": "TOKEN_INVALIDO",        # 🆕 NUEVO
    "TOKEN_EXPIRADO": "TOKEN_EXPIRADO",        # 🆕 NUEVO
    "TOKEN_USADO": "TOKEN_YA_USADO",            # 🆕 NUEVO
    "TOKEN_BLOQUEADO": "TOKEN_BLOQUEADO"        # 🆕 NUEVO
}

# =====================================================
# MENSAJES DE ÉXITO
# =====================================================
SUCCESS_MESSAGES = {
    "CREADO": "Registro creado exitosamente",
    "ACTUALIZADO": "Registro actualizado exitosamente",
    "ELIMINADO": "Registro eliminado exitosamente",
    "APROBADO": "Solicitud aprobada exitosamente",
    "RECHAZADO": "Solicitud rechazada exitosamente",
    "ENVIADO": "Solicitud enviada a aprobación",
    "QR_GENERADO": "QR generado exitosamente",
    "TOKEN_GENERADO": "Token de emergencia generado exitosamente",  # 🆕 NUEVO
    "TOKEN_VALIDADO": "Token validado exitosamente"                  # 🆕 NUEVO
}

# =====================================================
# CONFIGURACIÓN DE CACHÉ
# =====================================================
CACHE_CONFIG = {
    "PLANIFICACION_TTL": 300,  # 5 minutos
    "PERSONAL_TTL": 3600,       # 1 hora
    "ASISTENCIA_TTL": 60        # 1 minuto
}

# =====================================================
# FUNCIÓN DE AYUDA PARA VALIDACIÓN
# =====================================================
def get_constants_info() -> Dict[str, Any]:
    """Retorna información resumida de todas las constantes"""
    return {
        "tipos_solicitud": len(TIPOS_SOLICITUD),
        "estados_solicitud": len(ESTADOS_SOLICITUD),
        "acciones_trazabilidad": len(ACCIONES_TRAZABILIDAD),
        "niveles_jerarquicos": len(NIVELES_JERARQUICOS),
        "roles": len(ROLES),
        "tipos_turno": len(TIPOS_TURNO),
        "areas_criticas": len(AREAS_CRITICAS),
        "limites": LIMITES,
        "token_config": TOKEN_CONFIG  # 🆕 NUEVO
    }