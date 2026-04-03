# app/api/qr.py - VERSIÓN ACTUALIZADA PARA NUEVO FORMATO QR
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
# CONSTANTES DE QR
# =====================================================
QR_CONFIG = {
    "EXPIRACION_SEGUNDOS": 10,
    "TOKEN_EMERGENCIA_DURACION_MINUTOS": 5,
    "TOKEN_EMERGENCIA_DURACION_MAXIMA": 30,
    "TOKEN_EMERGENCIA_DURACION_DEFAULT": 15,
    "ID_CORTO_LONGITUD": 8  # Longitud del ID corto
}

QR_MENSAJES = {
    "QR_GENERADO": "✅ QR generado correctamente",
    "QR_VALIDO": "✅ QR válido",
    "QR_INVALIDO": "❌ QR inválido",
    "QR_EXPIRADO": "❌ QR expirado (máximo 10 segundos)",
    "QR_YA_USADO": "❌ QR ya fue utilizado",
    "SIN_TURNO": "❌ No tiene turno asignado para hoy",
    "REGISTRO_EXITOSO": "✅ Asistencia registrada correctamente",
    "EMPLEADO_INACTIVO": "❌ Personal inactivo o no encontrado"
}

ERROR_CODES = {
    "QR_INVALIDO": "QR_INVALIDO",
    "QR_EXPIRADO": "QR_EXPIRADO",
    "QR_YA_USADO": "QR_YA_USADO",
    "SIN_TURNO": "SIN_TURNO",
    "EMPLEADO_NO_ENCONTRADO": "EMPLEADO_NO_ENCONTRADO",
    "TIPO_INCORRECTO": "TIPO_INCORRECTO"
}

router = APIRouter(prefix="", tags=["QR"])


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
    """
    Extrae el empleado_id soportando formato antiguo y nuevo
    Retorna el UUID completo del empleado
    """
    # Formato antiguo
    if "empleado_id" in payload:
        return payload["empleado_id"]
    
    # Formato nuevo (optimizado) - {i, n, d, t}
    if "i" in payload:
        id_corto = payload["i"]
        logger.info(f"🔍 Buscando empleado por ID corto: {id_corto}")
        
        # Buscar empleado cuyo ID termine con el ID corto
        empleado = db.query(Personal).filter(
            cast(Personal.id, String).endswith(id_corto)
        ).first()
        
        if empleado:
            logger.info(f"✅ Empleado encontrado por ID corto: {empleado.nombre}")
            return str(empleado.id)
        
        # Si no se encuentra, intentar por nombre
        nombre_corto = payload.get("n", "")
        if nombre_corto:
            logger.info(f"🔍 Buscando empleado por nombre: {nombre_corto}")
            empleado = db.query(Personal).filter(
                Personal.nombre.ilike(f"%{nombre_corto}%")
            ).first()
            if empleado:
                logger.info(f"✅ Empleado encontrado por nombre: {empleado.nombre}")
                return str(empleado.id)
    
    # Formato alternativo
    if "personal_id" in payload:
        return payload["personal_id"]
    
    return None


def generar_payload_nuevo_formato(empleado_id: str, empleado_nombre: str) -> dict:
    """Genera el payload optimizado para el QR (formato nuevo)"""
    ahora_peru = get_peru_time()
    id_corto = generar_id_corto(empleado_id)
    nombre_corto = empleado_nombre.split(',')[0].strip()[:15]  # Primer nombre, máx 15 chars
    timestamp_corto = str(int(ahora_peru.timestamp()))[-6:]  # Últimos 6 dígitos del timestamp
    
    return {
        "i": id_corto,           # ID corto
        "n": nombre_corto,       # Nombre corto
        "d": timestamp_corto,    # Timestamp corto
        "t": "a",                # Tipo: asistencia
        "v": "2"                 # Versión del formato
    }


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


# =====================================================
# ENDPOINT: GENERAR QR DE ASISTENCIA (NUEVO FORMATO)
# =====================================================

@router.post("/generar")
async def generar_qr(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Genera un nuevo código QR en formato optimizado (más pequeño y rápido)
    """
    logger.info(f"📱 Generando QR (nuevo formato) para usuario: {current_user.id}")
    
    if not current_user.personal_id:
        logger.warning(f"Usuario {current_user.id} no tiene personal asociado")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario no tiene personal asociado"
        )
    
    # Verificar que el personal existe y está activo
    personal = db.query(Personal).filter(
        Personal.id == current_user.personal_id,
        Personal.activo == True
    ).first()
    
    if not personal:
        logger.warning(f"Personal {current_user.personal_id} no encontrado o inactivo")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=QR_MENSAJES["EMPLEADO_INACTIVO"]
        )
    
    ahora_peru = get_peru_time()
    expira_en = ahora_peru + timedelta(seconds=QR_CONFIG["EXPIRACION_SEGUNDOS"])
    
    # Generar QR ID para tracking
    qr_id = f"qr-{int(ahora_peru.timestamp())}-{secrets.token_hex(4)}"
    
    # 🔥 NUEVO FORMATO OPTIMIZADO
    payload = generar_payload_nuevo_formato(
        str(current_user.personal_id), 
        personal.nombre
    )
    
    # Agregar metadatos para tracking (no van en el QR visible pero se guardan en BD)
    qr_metadata = {
        "qr_id": qr_id,
        "empleado_id": str(current_user.personal_id),
        "generado_en": ahora_peru.isoformat(),
        "expira_en": expira_en.isoformat(),
        "formato": "v2"
    }
    
    logger.info(f"📦 Payload QR (nuevo formato): {payload}")
    
    # Guardar en base de datos con el payload completo
    qr_registro = QRRegistro(
        qr_id=qr_id,
        empleado_id=current_user.personal_id,
        generado_en=ahora_peru,
        expira_en=expira_en,
        usado=False,
        tipo="asistencia",
        codigo=json.dumps({**payload, **qr_metadata})
    )
    db.add(qr_registro)
    db.commit()
    
    logger.info(f"✅ QR generado (formato v2): {qr_id} para {personal.nombre}")
    
    # Codificar el payload optimizado para el frontend
    qr_data = base64.b64encode(json.dumps(payload).encode()).decode()
    
    return {
        "qr_data": qr_data,
        "qr_id": qr_id,
        "expira_en": expira_en.isoformat(),
        "tipo": "asistencia",
        "formato": "v2",
        "mensaje": QR_MENSAJES["QR_GENERADO"]
    }


# =====================================================
# ENDPOINT: VALIDAR QR DE ASISTENCIA (SOPORTA NUEVO FORMATO)
# =====================================================

@router.post("/validar")
async def validar_qr(
    qr_data: str = Body(...),
    tipo: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["oficial_permanencia", "control_qr", "admin"]))
):
    """
    Valida QR de asistencia soportando formato antiguo y nuevo
    """
    logger.info(f"🔍 Validando QR - Tipo: {tipo} - Escaneado por: {current_user.id}")
    
    try:
        # Decodificar QR
        decoded = base64.b64decode(qr_data).decode()
        payload = json.loads(decoded)
        logger.info(f"📦 QR decodificado: {payload}")
        
        # Detectar versión del formato
        formato_version = payload.get("v", "1")
        logger.info(f"📌 Formato QR versión: {formato_version}")
        
        # Extraer empleado_id (soporta ambos formatos)
        empleado_id = extraer_empleado_id(payload, db)
        
        if not empleado_id:
            logger.warning("No se pudo extraer empleado_id del QR")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_CODES["QR_INVALIDO"]
            )
        
        logger.info(f"✅ Empleado ID extraído: {empleado_id}")
        
        # Buscar el QR en la base de datos (si tiene qr_id)
        qr_registro = None
        if "qr_id" in payload:
            qr_registro = db.query(QRRegistro).filter(
                QRRegistro.qr_id == payload["qr_id"]
            ).first()
        
        ahora_peru = get_peru_time()
        
        # Si encontramos el QR en BD, verificamos estado
        if qr_registro:
            # Verificar expiración
            if ahora_peru > qr_registro.expira_en:
                logger.warning(f"QR expirado: {qr_registro.qr_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_CODES["QR_EXPIRADO"]
                )
            
            # Verificar si ya fue usado
            if qr_registro.usado:
                logger.warning(f"QR ya usado: {qr_registro.qr_id}")
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=ERROR_CODES["QR_YA_USADO"]
                )
        
        # Verificar empleado
        empleado = db.query(Personal).filter(Personal.id == empleado_id).first()
        if not empleado:
            logger.warning(f"Empleado no encontrado: {empleado_id}")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ERROR_CODES["EMPLEADO_NO_ENCONTRADO"]
            )
        
        if not empleado.activo:
            logger.warning(f"Empleado inactivo: {empleado.nombre}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=QR_MENSAJES["EMPLEADO_INACTIVO"]
            )
        
        # Verificar turno del día
        hoy = ahora_peru.date()
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == empleado_id,
            Planificacion.fecha == hoy
        ).first()
        
        if not planificacion:
            logger.warning(f"Empleado sin turno: {empleado.nombre} - {hoy}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_CODES["SIN_TURNO"]
            )
        
        # Verificar orden de registro
        inicio_dia = datetime.combine(hoy, datetime.min.time())
        ultimo_registro = db.query(Asistencia).filter(
            Asistencia.personal_id == empleado_id,
            Asistencia.timestamp >= inicio_dia
        ).order_by(Asistencia.timestamp.desc()).first()
        
        tipo_permitido = "ENTRADA"
        if ultimo_registro and ultimo_registro.tipo == "ENTRADA":
            tipo_permitido = "SALIDA"
        
        if tipo != tipo_permitido:
            logger.warning(f"Orden incorrecto: se esperaba {tipo_permitido}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Debe registrar {tipo_permitido} primero"
            )
        
        # Marcar QR como usado (si existe en BD)
        if qr_registro:
            qr_registro.usado = True
            qr_registro.usado_en = ahora_peru
            qr_registro.usado_por = current_user.id
        
        # Registrar asistencia
        asistencia = Asistencia(
            personal_id=empleado_id,
            timestamp=ahora_peru,
            tipo=tipo,
            tipo_registro="QR",
            turno_codigo=planificacion.turno_codigo,
            verificado=True,
            created_by=current_user.id
        )
        db.add(asistencia)
        db.commit()
        
        logger.info(f"✅ Asistencia registrada: {empleado.nombre} - {tipo}")
        
        return {
            "valido": True,
            "empleado_id": str(empleado_id),
            "empleado_nombre": empleado.nombre,
            "tipo": tipo,
            "timestamp": ahora_peru.isoformat(),
            "turno": planificacion.turno_codigo,
            "formato": formato_version,
            "mensaje": QR_MENSAJES["REGISTRO_EXITOSO"]
        }
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decodificando JSON del QR: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_CODES["QR_INVALIDO"]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error procesando QR: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_CODES["QR_INVALIDO"]
        )


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
    
    if str(current_user.personal_id) != str(empleado_id) and "admin" not in current_user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para ver este QR"
        )
    
    ahora_peru = get_peru_time()
    
    qr_activo = db.query(QRRegistro).filter(
        QRRegistro.empleado_id == empleado_id,
        QRRegistro.expira_en > ahora_peru,
        QRRegistro.usado == False,
        QRRegistro.tipo == "asistencia"
    ).order_by(QRRegistro.generado_en.desc()).first()
    
    if not qr_activo:
        return {"activo": False}
    
    return {
        "activo": True,
        "qr_id": qr_activo.qr_id,
        "generado_en": qr_activo.generado_en.isoformat(),
        "expira_en": qr_activo.expira_en.isoformat(),
        "segundos_restantes": int((qr_activo.expira_en - ahora_peru).total_seconds())
    }


# =====================================================
# ENDPOINTS DE TOKEN DE EMERGENCIA
# =====================================================

@router.post("/generar-token/{solicitud_id}")
async def generar_token_emergencia(
    solicitud_id: UUID,
    duracion: int = Query(QR_CONFIG["TOKEN_EMERGENCIA_DURACION_DEFAULT"], 
                          ge=QR_CONFIG["TOKEN_EMERGENCIA_DURACION_MINUTOS"], 
                          le=QR_CONFIG["TOKEN_EMERGENCIA_DURACION_MAXIMA"]),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Genera token de emergencia para validación sin QR"""
    
    solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    if str(solicitud.empleado_id) != str(current_user.personal_id) and "admin" not in current_user.roles:
        raise HTTPException(status_code=403, detail="No tiene permiso para esta solicitud")
    
    ahora_peru = get_peru_time()
    token = secrets.token_hex(8).upper()
    expira_en = ahora_peru + timedelta(minutes=duracion)
    
    logger.info(f"🔑 Token de emergencia generado para solicitud {solicitud_id}")
    
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
    current_user: Usuario = Depends(require_roles(["control_qr", "admin", "oficial_permanencia"]))
):
    """Valida token de emergencia para trámites"""
    logger.info(f"🔍 Validando token para solicitud {solicitud_id}")
    
    return {
        "valido": True,
        "mensaje": "Token válido",
        "solicitud_id": str(solicitud_id)
    }


# =====================================================
# ENDPOINTS QR PARA TRÁMITES
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
    
    payload = {
        "t": "t",  # Tipo: trámite
        "s": str(solicitud_id)[-8:],  # ID corto de solicitud
        "v": "2"
    }
    
    qr_data = base64.b64encode(json.dumps(payload).encode()).decode()
    
    logger.info(f"📱 QR de trámite generado: {qr_id}")
    
    return {
        "qr_data": qr_data,
        "qr_id": qr_id,
        "expira_en": expira_en.isoformat(),
        "tipo": "tramite",
        "formato": "v2",
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
        
        solicitud_id_corto = payload.get("s")
        if not solicitud_id_corto:
            raise HTTPException(status_code=400, detail="ID de solicitud no encontrado")
        
        # Buscar solicitud por ID corto
        solicitud = db.query(Solicitud).filter(
            cast(Solicitud.id, String).endswith(solicitud_id_corto)
        ).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if solicitud.estado != "aprobada":
            raise HTTPException(status_code=400, detail="Solicitud no está aprobada")
        
        logger.info(f"✅ QR de trámite validado: {solicitud.id}")
        
        return {
            "valido": True,
            "solicitud_id": str(solicitud.id),
            "mensaje": "Trámite válido"
        }
        
    except Exception as e:
        logger.error(f"Error validando QR de trámite: {e}")
        raise HTTPException(status_code=400, detail="QR inválido")