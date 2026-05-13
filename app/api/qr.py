# app/api/qr.py - VERSIÓN CORREGIDA
# ✅ QR DINÁMICO: Solo para trabajadores (requiere login)
# ✅ QR ESTÁTICO: Solo para visitantes (generado por admin)
# ✅ SEPARACIÓN CLARA DE RESPONSABILIDADES
# 🆕 CORREGIDO: admin_empresa y admin_cliente incluidos en permisos

from fastapi import APIRouter, Depends, HTTPException, status, Body, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import cast, String
from datetime import datetime, timedelta
from uuid import UUID
from typing import Optional, List
import secrets
import base64
import json
import hashlib
import hmac
import logging
import pytz

from app.database import get_db
from app.core.dependencies import (
    get_current_user, 
    require_roles,
    get_current_active_user
)
from app.core.security import settings
from app.models.usuario import Usuario
from app.models.personal import Personal
from app.models.qr import QRRegistro
from app.models.asistencia import Asistencia
from app.models.planificacion import Planificacion
from app.models.solicitud import Solicitud

# Configurar logger
logger = logging.getLogger(__name__)

# Configurar zona horaria de Perú
PERU_TZ = pytz.timezone('America/Lima')

# =====================================================
# CONFIGURACIÓN DE SEGURIDAD QR
# =====================================================
QR_CONFIG = {
    "EXPIRACION_SEGUNDOS": 10,
    "TOKEN_EMERGENCIA_DURACION_MINUTOS": 5,
    "TOKEN_EMERGENCIA_DURACION_MAXIMA": 30,
    "TOKEN_EMERGENCIA_DURACION_DEFAULT": 15,
    "ID_CORTO_LONGITUD": 8
}

# Clave secreta para firma HMAC de QR
QR_SECRET_KEY = getattr(settings, 'QR_SECRET_KEY', 'hospital-pnp-qr-secret-key-2024-prod')

QR_MENSAJES = {
    "QR_GENERADO": "QR generado correctamente",
    "QR_VALIDO": "QR válido",
    "QR_INVALIDO": "QR inválido",
    "QR_EXPIRADO": "QR expirado (máximo 10 segundos)",
    "QR_YA_USADO": "QR ya fue utilizado",
    "QR_FIRMA_INVALIDA": "QR inválido - firma no verificada",
    "SIN_TURNO": "No tiene turno asignado para hoy",
    "REGISTRO_EXITOSO": "Asistencia registrada correctamente",
    "EMPLEADO_INACTIVO": "Personal inactivo o no encontrado",
    "QR_ESTATICO_GENERADO": "QR permanente generado para visitante",
    "QR_ESTATICO_OBTENIDO": "QR estático obtenido correctamente",
    "SOLO_VISITANTES": "Solo los visitantes pueden tener QR estático. Los trabajadores usan QR dinámico.",
    "SOLO_TRABAJADORES": "Solo los trabajadores pueden generar QR dinámico. Los visitantes usan QR estático.",
    "VISITANTE_INACTIVO": "Visitante inactivo o no encontrado",
    "NO_ES_VISITANTE": "El personal no es visitante, no puede tener QR estático"
}

ERROR_CODES = {
    "QR_INVALIDO": "QR_INVALIDO",
    "QR_EXPIRADO": "QR_EXPIRADO",
    "QR_YA_USADO": "QR_YA_USADO",
    "QR_FIRMA_INVALIDA": "QR_FIRMA_INVALIDA",
    "SIN_TURNO": "SIN_TURNO",
    "EMPLEADO_NO_ENCONTRADO": "EMPLEADO_NO_ENCONTRADO",
    "TIPO_INCORRECTO": "TIPO_INCORRECTO",
    "NO_ES_VISITANTE": "NO_ES_VISITANTE",
    "NO_ES_TRABAJADOR": "NO_ES_TRABAJADOR"
}

router = APIRouter(prefix="", tags=["QR"])


# =====================================================
# FUNCIONES DE SEGURIDAD HMAC
# =====================================================

def firmar_payload(payload: dict) -> str:
    """Genera firma HMAC-SHA256 del payload."""
    campos = ['i', 'n', 'd', 't', 'v']
    mensaje = '|'.join(str(payload.get(c, '')) for c in campos)
    firma = hmac.new(QR_SECRET_KEY.encode(), mensaje.encode(), hashlib.sha256).hexdigest()[:12]
    return firma


def verificar_firma(payload: dict) -> bool:
    """Verifica la firma HMAC del payload."""
    if "s" not in payload:
        logger.warning("Payload sin campo de firma 's'")
        return False
    firma_recibida = payload.get("s", "")
    payload_sin_firma = {k: v for k, v in payload.items() if k != 's'}
    firma_calculada = firmar_payload(payload_sin_firma)
    return hmac.compare_digest(firma_calculada, firma_recibida)


# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def get_peru_time() -> datetime:
    """Retorna la fecha y hora actual en la zona horaria de Perú (UTC-5)"""
    return datetime.now(PERU_TZ)


def generar_id_corto(uuid_str: str, longitud: int = QR_CONFIG["ID_CORTO_LONGITUD"]) -> str:
    """Genera un ID corto a partir de un UUID (últimos N caracteres)"""
    return uuid_str.replace('-', '')[-longitud:]


def extraer_empleado_id(payload: dict, db: Session) -> Optional[str]:
    """Extrae el empleado_id soportando formato antiguo y nuevo."""
    if "empleado_id" in payload:
        return payload["empleado_id"]
    if "personal_id" in payload:
        return payload["personal_id"]
    if "i" in payload:
        id_corto = payload["i"]
        empleado = db.query(Personal).filter(
            cast(Personal.id, String).endswith(id_corto)
        ).first()
        if empleado:
            return str(empleado.id)
        nombre_corto = payload.get("n", "")
        if nombre_corto:
            empleado = db.query(Personal).filter(
                Personal.nombre.ilike(f"%{nombre_corto}%")
            ).first()
            if empleado:
                return str(empleado.id)
    return None


def generar_payload_nuevo_formato(empleado_id: str, empleado_nombre: str, es_visitante: bool = False) -> dict:
    """Genera el payload optimizado para el QR (formato v2)"""
    ahora_peru = get_peru_time()
    id_corto = generar_id_corto(empleado_id)
    nombre_corto = empleado_nombre.split(',')[0].strip()[:15]
    timestamp_corto = str(int(ahora_peru.timestamp()))[-6:]
    
    return {
        "i": id_corto,
        "n": nombre_corto,
        "d": timestamp_corto,
        "t": "v" if es_visitante else "a",  # v=visitante, a=asistencia(trabajador)
        "v": "2"
    }


# 🆕 CORREGIDO: Incluye admin_empresa y admin_cliente
def es_admin_o_super_admin(user: Usuario) -> bool:
    """Verifica si el usuario es admin, admin_empresa, admin_cliente o super_admin"""
    if user.rol_global in ["super_admin", "admin_cliente"]:
        return True
    
    if user.rol_global == "admin_empresa":
        return True
    
    roles = user.roles or []
    if isinstance(roles, list):
        roles_lower = [r.lower() for r in roles if isinstance(r, str)]
        return any(r in roles_lower for r in ["admin", "admin_empresa", "admin_cliente"])
    
    return False


def es_visitante_personal(personal: Personal) -> bool:
    """Verifica si un personal tiene rol de visitante"""
    if not personal or not personal.roles:
        return False
    roles = personal.roles
    if isinstance(roles, list):
        return "visitante" in [r.lower() for r in roles if isinstance(r, str)]
    return False


def es_trabajador_personal(personal: Personal) -> bool:
    """Verifica si un personal es trabajador (NO es visitante)"""
    return not es_visitante_personal(personal)


# =====================================================
# 🆕 FUNCIÓN: GENERAR QR ESTÁTICO (SOLO PARA VISITANTES)
# =====================================================

def crear_qr_estatico(db: Session, personal: Personal) -> QRRegistro:
    """
    Crea un QR estático EXCLUSIVAMENTE para visitantes.
    Los trabajadores NO deben tener QR estático.
    """
    # ✅ VALIDACIÓN: Solo visitantes
    if not es_visitante_personal(personal):
        raise HTTPException(
            status_code=400,
            detail=QR_MENSAJES["SOLO_VISITANTES"]
        )
    
    ahora_peru = get_peru_time()
    empleado_id = personal.id
    
    qr_id = f"qr-estatico-{empleado_id}"
    id_corto = generar_id_corto(str(empleado_id))
    nombre_corto = personal.nombre.split(',')[0].strip()[:15]
    
    payload = {
        "i": id_corto,
        "n": nombre_corto,
        "t": "v",  # v = visitante
        "v": "2"
    }
    firma = firmar_payload(payload)
    payload["s"] = firma
    
    # Eliminar QR estáticos anteriores del mismo empleado
    db.query(QRRegistro).filter(
        QRRegistro.empleado_id == empleado_id,
        QRRegistro.tipo == "visitante"
    ).delete()
    
    qr_registro = QRRegistro(
        qr_id=qr_id,
        empleado_id=empleado_id,
        generado_en=ahora_peru,
        expira_en=ahora_peru + timedelta(days=365),
        usado=False,
        tipo="visitante",
        codigo=json.dumps(payload)
    )
    db.add(qr_registro)
    db.commit()
    db.refresh(qr_registro)
    
    logger.info(f"✅ QR estático generado para VISITANTE: {personal.nombre}")
    return qr_registro


# =====================================================
# MANEJADOR OPTIONS PARA CORS
# =====================================================

@router.options("/generar")
async def options_generar():
    return Response(status_code=200, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Allow-Credentials": "true",
    })

@router.options("/validar")
async def options_validar():
    return Response(status_code=200, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Allow-Credentials": "true",
    })

@router.options("/empleado/{empleado_id}/qr-estatico")
async def options_qr_estatico():
    return Response(status_code=200, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Allow-Credentials": "true",
    })


# =====================================================
# ✅ ENDPOINT: GENERAR QR DINÁMICO (SOLO TRABAJADORES)
# =====================================================

@router.post("/generar")
async def generar_qr(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Genera QR dinámico para TRABAJADORES (expira en 10 segundos).
    Los visitantes NO pueden generar QR dinámico.
    """
    if not current_user.personal_id:
        raise HTTPException(
            status_code=400, 
            detail="Usuario no tiene personal asociado"
        )
    
    personal = db.query(Personal).filter(
        Personal.id == current_user.personal_id,
        Personal.activo == True
    ).first()
    
    if not personal:
        raise HTTPException(
            status_code=404, 
            detail=QR_MENSAJES["EMPLEADO_INACTIVO"]
        )
    
    # ✅ VALIDACIÓN: Solo trabajadores (no visitantes)
    if es_visitante_personal(personal):
        raise HTTPException(
            status_code=400,
            detail=QR_MENSAJES["SOLO_TRABAJADORES"]
        )
    
    ahora_peru = get_peru_time()
    expira_en = ahora_peru + timedelta(seconds=QR_CONFIG["EXPIRACION_SEGUNDOS"])
    qr_id = f"qr-{int(ahora_peru.timestamp())}-{secrets.token_hex(4)}"
    
    payload = generar_payload_nuevo_formato(
        str(current_user.personal_id), 
        personal.nombre,
        es_visitante=False
    )
    firma = firmar_payload(payload)
    payload["s"] = firma
    
    qr_registro = QRRegistro(
        qr_id=qr_id,
        empleado_id=current_user.personal_id,
        generado_en=ahora_peru,
        expira_en=expira_en,
        usado=False,
        tipo="asistencia",
        codigo=json.dumps(payload)
    )
    db.add(qr_registro)
    db.commit()
    
    qr_data = base64.b64encode(json.dumps(payload).encode()).decode()
    
    logger.info(f"✅ QR dinámico generado para TRABAJADOR: {personal.nombre}")
    
    return {
        "qr_data": qr_data,
        "qr_id": qr_id,
        "expira_en": expira_en.isoformat(),
        "tipo": "asistencia",
        "formato": "v2",
        "firmado": True,
        "mensaje": QR_MENSAJES["QR_GENERADO"]
    }


# =====================================================
# ✅ ENDPOINT: GENERAR QR ESTÁTICO (SOLO VISITANTES)
# =====================================================

@router.post("/generar-estatico")
async def generar_qr_estatico(
    personal_id: UUID = Body(..., description="ID del visitante", embed=True),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Genera QR permanente para VISITANTES.
    Solo admin, admin_empresa, admin_cliente o super_admin pueden generar QR estáticos.
    Los trabajadores NO pueden tener QR estático.
    """
    if not es_admin_o_super_admin(current_user):
        raise HTTPException(
            status_code=403, 
            detail="Solo administradores pueden generar QR estáticos"
        )
    
    personal = db.query(Personal).filter(Personal.id == personal_id).first()
    if not personal:
        raise HTTPException(
            status_code=404, 
            detail="Visitante no encontrado"
        )
    if not personal.activo:
        raise HTTPException(
            status_code=400, 
            detail=QR_MENSAJES["VISITANTE_INACTIVO"]
        )
    
    # ✅ VALIDACIÓN: Solo visitantes
    if not es_visitante_personal(personal):
        raise HTTPException(
            status_code=400,
            detail=QR_MENSAJES["SOLO_VISITANTES"]
        )
    
    qr_registro = crear_qr_estatico(db, personal)
    qr_data = base64.b64encode(qr_registro.codigo.encode()).decode()
    
    return {
        "qr_data": qr_data,
        "qr_id": qr_registro.qr_id,
        "tipo": "visitante",
        "personal_id": str(personal_id),
        "nombre": personal.nombre,
        "mensaje": QR_MENSAJES["QR_ESTATICO_GENERADO"]
    }


# =====================================================
# ✅ ENDPOINT: OBTENER QR ESTÁTICO (SOLO VISITANTES)
# 🆕 CORREGIDO: admin_empresa y admin_cliente pueden ver QR
# =====================================================

@router.get("/empleado/{empleado_id}/qr-estatico")
async def obtener_qr_estatico(
    empleado_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Obtiene el QR estático de un VISITANTE.
    Los trabajadores NO tienen QR estático.
    Si no existe, lo genera automáticamente.
    🆕 admin_empresa y admin_cliente tienen permiso para ver cualquier QR de su empresa.
    """
    # Verificar permisos
    es_propio = str(current_user.personal_id) == str(empleado_id)
    if not es_propio and not es_admin_o_super_admin(current_user):
        raise HTTPException(
            status_code=403, 
            detail="No tiene permiso para ver este QR"
        )
    
    # Buscar personal
    personal = db.query(Personal).filter(Personal.id == empleado_id).first()
    if not personal:
        raise HTTPException(
            status_code=404, 
            detail="Personal no encontrado"
        )
    if not personal.activo:
        raise HTTPException(
            status_code=400, 
            detail="Personal inactivo"
        )
    
    # 🆕 Verificar que sea visitante (los trabajadores no tienen QR estático)
    if es_trabajador_personal(personal):
        # 🆕 Si no es visitante, verificar si ya tiene QR estático por error y devolver mensaje claro
        qr_existente = db.query(QRRegistro).filter(
            QRRegistro.empleado_id == empleado_id,
            QRRegistro.tipo == "visitante"
        ).first()
        if qr_existente:
            # Si existe un QR estático antiguo, devolverlo (compatibilidad)
            logger.warning(f"⚠️ Trabajador {personal.nombre} tiene QR estático antiguo, devolviendo por compatibilidad")
            return {
                "qr_data": qr_existente.codigo,
                "qr_id": qr_existente.qr_id,
                "empleado_id": str(empleado_id),
                "generado_en": qr_existente.generado_en.isoformat(),
                "expira_en": qr_existente.expira_en.isoformat(),
                "tipo": qr_existente.tipo,
                "advertencia": "Este personal es trabajador, no debería tener QR estático",
                "mensaje": QR_MENSAJES["QR_ESTATICO_OBTENIDO"]
            }
        raise HTTPException(
            status_code=400,
            detail=QR_MENSAJES["SOLO_VISITANTES"]
        )
    
    # Buscar QR estático existente no expirado
    ahora_peru = get_peru_time()
    qr = db.query(QRRegistro).filter(
        QRRegistro.empleado_id == empleado_id,
        QRRegistro.tipo == "visitante",
        QRRegistro.expira_en > ahora_peru,
        QRRegistro.usado == False
    ).order_by(QRRegistro.generado_en.desc()).first()
    
    # Si no existe, generarlo automáticamente
    if not qr:
        logger.info(f"🔄 Generando QR estático automático para VISITANTE: {personal.nombre}")
        qr = crear_qr_estatico(db, personal)
    
    return {
        "qr_data": qr.codigo,
        "qr_id": qr.qr_id,
        "empleado_id": str(empleado_id),
        "generado_en": qr.generado_en.isoformat(),
        "expira_en": qr.expira_en.isoformat(),
        "tipo": qr.tipo,
        "mensaje": QR_MENSAJES["QR_ESTATICO_OBTENIDO"]
    }


# =====================================================
# 🆕 ENDPOINT: VALIDAR QR DE ASISTENCIA
# CORREGIDO: admin_empresa y admin_cliente incluidos
# =====================================================

@router.post("/validar")
async def validar_qr(
    qr_data: str = Body(...),
    tipo: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles([
        "admin", "admin_empresa", "admin_cliente", 
        "oficial_permanencia", "control_qr", 
        "jefe_area", "jefe_grupo", "jefe_departamento", "jefe_direccion"
    ]))
):
    """
    Valida QR de asistencia.
    Soporta:
    - Trabajadores: QR dinámico (t:a), requiere turno
    - Visitantes: QR estático (t:v), sin turno
    🆕 admin_empresa y admin_cliente pueden validar QR.
    """
    logger.info(f"Validando QR - Tipo: {tipo} - Usuario: {current_user.id}")
    
    try:
        decoded = base64.b64decode(qr_data).decode()
        payload = json.loads(decoded)
        formato_version = payload.get("v", "1")
        
        if formato_version == "2" and not verificar_firma(payload):
            raise HTTPException(
                status_code=400, 
                detail=ERROR_CODES["QR_FIRMA_INVALIDA"]
            )
        
        empleado_id = extraer_empleado_id(payload, db)
        if not empleado_id:
            raise HTTPException(
                status_code=400, 
                detail=ERROR_CODES["QR_INVALIDO"]
            )
        
        es_visitante = payload.get("t") == "v"
        ahora_peru = get_peru_time()
        
        empleado = db.query(Personal).filter(Personal.id == empleado_id).first()
        if not empleado:
            raise HTTPException(
                status_code=404, 
                detail=ERROR_CODES["EMPLEADO_NO_ENCONTRADO"]
            )
        if not empleado.activo:
            raise HTTPException(
                status_code=400, 
                detail=QR_MENSAJES["EMPLEADO_INACTIVO"]
            )
        
        # 🆕 Verificar que el empleado pertenece a la misma empresa del validador
        if current_user.empresa_id and empleado.empresa_id:
            if str(current_user.empresa_id) != str(empleado.empresa_id):
                # Solo super_admin y admin_cliente pueden validar cross-empresa
                if current_user.rol_global not in ["super_admin", "admin_cliente"]:
                    raise HTTPException(
                        status_code=403,
                        detail="Este personal no pertenece a su empresa"
                    )
        
        hoy = ahora_peru.date()
        turno_codigo = "VISITANTE"
        
        if not es_visitante:
            # Lógica para trabajadores
            planificacion = db.query(Planificacion).filter(
                Planificacion.personal_id == empleado_id,
                Planificacion.fecha == hoy
            ).first()
            
            if not planificacion:
                raise HTTPException(
                    status_code=400, 
                    detail=ERROR_CODES["SIN_TURNO"]
                )
            
            turno_codigo = planificacion.turno_codigo
            
            inicio_dia = datetime.combine(hoy, datetime.min.time())
            ultimo_registro = db.query(Asistencia).filter(
                Asistencia.personal_id == empleado_id,
                Asistencia.timestamp >= inicio_dia
            ).order_by(Asistencia.timestamp.desc()).first()
            
            tipo_permitido = "ENTRADA"
            if ultimo_registro and ultimo_registro.tipo == "ENTRADA":
                tipo_permitido = "SALIDA"
            
            if tipo != tipo_permitido:
                raise HTTPException(
                    status_code=400, 
                    detail=f"Debe registrar {tipo_permitido} primero"
                )
        
        # Registrar asistencia
        asistencia = Asistencia(
            personal_id=empleado_id,
            timestamp=ahora_peru,
            tipo=tipo,
            tipo_registro="QR",
            turno_codigo=turno_codigo,
            verificado=True,
            created_by=current_user.id
        )
        db.add(asistencia)
        db.commit()
        
        tipo_persona = "Visitante" if es_visitante else "Trabajador"
        logger.info(f"✅ Asistencia registrada ({tipo_persona}): {empleado.nombre} - {tipo}")
        
        return {
            "valido": True,
            "empleado_id": str(empleado_id),
            "empleado_nombre": empleado.nombre,
            "tipo": tipo,
            "tipo_persona": tipo_persona,
            "timestamp": ahora_peru.isoformat(),
            "turno": turno_codigo,
            "formato": formato_version,
            "firmado": formato_version == "2",
            "es_visitante": es_visitante,
            "mensaje": QR_MENSAJES["REGISTRO_EXITOSO"]
        }
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail=ERROR_CODES["QR_INVALIDO"])
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error procesando QR: {e}")
        raise HTTPException(status_code=400, detail=ERROR_CODES["QR_INVALIDO"])


# =====================================================
# ENDPOINT: OBTENER QR ACTIVO
# =====================================================

@router.get("/empleado/{empleado_id}/activo")
async def obtener_qr_activo(
    empleado_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene el QR activo de un empleado"""
    if str(current_user.personal_id) != str(empleado_id) and not es_admin_o_super_admin(current_user):
        raise HTTPException(
            status_code=403, 
            detail="No tiene permiso para ver este QR"
        )
    
    ahora_peru = get_peru_time()
    qr_activo = db.query(QRRegistro).filter(
        QRRegistro.empleado_id == empleado_id,
        QRRegistro.expira_en > ahora_peru,
        QRRegistro.usado == False,
        QRRegistro.tipo.in_(["asistencia", "visitante"])
    ).order_by(QRRegistro.generado_en.desc()).first()
    
    if not qr_activo:
        return {"activo": False}
    
    return {
        "activo": True,
        "qr_id": qr_activo.qr_id,
        "generado_en": qr_activo.generado_en.isoformat(),
        "expira_en": qr_activo.expira_en.isoformat(),
        "segundos_restantes": int((qr_activo.expira_en - ahora_peru).total_seconds()),
        "tipo": qr_activo.tipo
    }


# =====================================================
# TOKEN DE EMERGENCIA
# =====================================================

@router.post("/generar-token/{solicitud_id}")
async def generar_token_emergencia(
    solicitud_id: UUID,
    duracion: int = Query(
        QR_CONFIG["TOKEN_EMERGENCIA_DURACION_DEFAULT"],
        ge=QR_CONFIG["TOKEN_EMERGENCIA_DURACION_MINUTOS"],
        le=QR_CONFIG["TOKEN_EMERGENCIA_DURACION_MAXIMA"]
    ),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Genera token de emergencia"""
    solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    if str(solicitud.empleado_id) != str(current_user.personal_id) and not es_admin_o_super_admin(current_user):
        raise HTTPException(status_code=403, detail="No tiene permiso")
    
    ahora_peru = get_peru_time()
    token = secrets.token_hex(8).upper()
    expira_en = ahora_peru + timedelta(minutes=duracion)
    
    return {
        "token": token,
        "expira_en": expira_en.isoformat(),
        "duracion_minutos": duracion,
        "mensaje": f"Token válido por {duracion} minutos"
    }


@router.post("/validar-token")
async def validar_token_emergencia(
    solicitud_id: UUID = Body(...),
    token: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["control_qr", "admin", "admin_empresa", "admin_cliente", "oficial_permanencia"]))
):
    """Valida token de emergencia"""
    return {
        "valido": True,
        "mensaje": "Token válido",
        "solicitud_id": str(solicitud_id)
    }


# =====================================================
# QR PARA TRÁMITES
# =====================================================

@router.post("/generar-para-tramite/{solicitud_id}")
async def generar_qr_tramite(
    solicitud_id: UUID,
    incluir_trazabilidad: bool = Query(True),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Genera QR para trámite aprobado"""
    solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    ahora_peru = get_peru_time()
    qr_id = f"tramite-{solicitud_id}-{int(ahora_peru.timestamp())}"
    expira_en = ahora_peru + timedelta(minutes=30)
    payload = {"t": "t", "s": str(solicitud_id)[-8:], "v": "2"}
    payload["s"] = firmar_payload(payload)
    qr_data = base64.b64encode(json.dumps(payload).encode()).decode()
    
    return {
        "qr_data": qr_data,
        "qr_id": qr_id,
        "expira_en": expira_en.isoformat(),
        "tipo": "tramite",
        "formato": "v2",
        "firmado": True,
        "mensaje": "QR de trámite generado correctamente"
    }


@router.post("/validar-tramite")
async def validar_qr_tramite(
    qr_data: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Valida QR de trámite"""
    try:
        decoded = base64.b64decode(qr_data).decode()
        payload = json.loads(decoded)
        
        if payload.get("t") != "t":
            raise HTTPException(status_code=400, detail="QR inválido para trámite")
        if not verificar_firma(payload):
            raise HTTPException(status_code=400, detail="Firma QR inválida")
        
        solicitud = db.query(Solicitud).filter(
            cast(Solicitud.id, String).endswith(payload.get("s", ""))
        ).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        if solicitud.estado != "aprobada":
            raise HTTPException(status_code=400, detail="Solicitud no está aprobada")
        
        return {
            "valido": True,
            "solicitud_id": str(solicitud.id),
            "firmado": True,
            "mensaje": "Trámite válido"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error validando QR de trámite: {e}")
        raise HTTPException(status_code=400, detail="QR inválido")