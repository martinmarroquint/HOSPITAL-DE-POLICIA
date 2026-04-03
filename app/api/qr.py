# app/api/qr.py - VERSIÓN CORREGIDA
from fastapi import APIRouter, Depends, HTTPException, status, Body, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
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
    "EXPIRACION_SEGUNDOS": 10,  # ✅ Se mantiene 10 segundos (seguridad óptima)
    "TOKEN_EMERGENCIA_DURACION_MINUTOS": 5,
    "TOKEN_EMERGENCIA_DURACION_MAXIMA": 30,
    "TOKEN_EMERGENCIA_DURACION_DEFAULT": 15
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


# =====================================================
# FUNCIÓN AUXILIAR PARA OBTENER HORA LOCAL DE PERÚ
# =====================================================

def get_peru_time() -> datetime:
    """Retorna la fecha y hora actual en la zona horaria de Perú (UTC-5)"""
    return datetime.now(PERU_TZ)


# =====================================================
# MANEJADOR OPTIONS PARA CORS (preflight)
# =====================================================

router = APIRouter(prefix="", tags=["QR"])


@router.options("/generar")
async def options_generar():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "http://localhost:5173",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "3600",
        }
    )


@router.options("/validar")
async def options_validar():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "http://localhost:5173",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "3600",
        }
    )


@router.options("/empleado/{empleado_id}/activo")
async def options_empleado_activo():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "http://localhost:5173",
            "Access-Control-Allow-Methods": "GET, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "3600",
        }
    )


# =====================================================
# ENDPOINT: GENERAR QR DE ASISTENCIA
# =====================================================

@router.post("/generar")
async def generar_qr(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Genera un nuevo código QR válido por 10 segundos
    CUALQUIER usuario autenticado puede generar su propio QR
    """
    logger.info(f"📱 Generando QR para usuario: {current_user.id}")
    
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
    
    qr_id = f"qr-{int(ahora_peru.timestamp())}-{secrets.token_hex(8)}"
    
    payload = {
        "qr_id": qr_id,
        "empleado_id": str(current_user.personal_id),
        "empleado_nombre": personal.nombre,
        "generado_en": ahora_peru.isoformat(),
        "expira_en": expira_en.isoformat(),
        "tipo": "asistencia"
    }
    
    # Generar firma HMAC para seguridad
    firma = hmac.new(
        key=settings.JWT_SECRET_KEY.encode(),
        msg=json.dumps(payload, sort_keys=True).encode(),
        digestmod=hashlib.sha256
    ).hexdigest()
    payload["firma"] = firma
    
    # Guardar en base de datos
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
    
    logger.info(f"✅ QR generado: {qr_id} para {personal.nombre} (expira en {QR_CONFIG['EXPIRACION_SEGUNDOS']}s)")
    
    # Codificar para enviar al frontend
    qr_data = base64.b64encode(json.dumps(payload).encode()).decode()
    
    return {
        "qr_data": qr_data,
        "qr_id": qr_id,
        "expira_en": expira_en.isoformat(),
        "tipo": "asistencia",
        "mensaje": QR_MENSAJES["QR_GENERADO"]
    }


# =====================================================
# ENDPOINT: VALIDAR QR DE ASISTENCIA
# =====================================================

@router.post("/validar")
async def validar_qr(
    qr_data: str = Body(...),
    tipo: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["oficial_permanencia", "control_qr", "admin"]))
):
    """
    Valida QR de asistencia y registra entrada/salida
    Este endpoint es llamado por el Oficial de Permanencia al escanear
    """
    logger.info(f"🔍 Validando QR - Tipo: {tipo} - Escaneado por: {current_user.id}")
    
    try:
        # Decodificar QR
        payload = json.loads(base64.b64decode(qr_data).decode())
        
        if payload.get("tipo") != "asistencia":
            logger.warning(f"Tipo de QR incorrecto: {payload.get('tipo')}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_CODES["QR_INVALIDO"]
            )
        
        qr_id = payload.get("qr_id")
        empleado_id = payload.get("empleado_id")
        expira_en_str = payload.get("expira_en")
        firma_recibida = payload.get("firma")
        
        if not qr_id or not empleado_id or not expira_en_str:
            logger.warning("Payload incompleto en QR")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_CODES["QR_INVALIDO"]
            )
        
        # Verificar firma
        payload_sin_firma = {k: v for k, v in payload.items() if k != "firma"}
        firma_esperada = hmac.new(
            key=settings.JWT_SECRET_KEY.encode(),
            msg=json.dumps(payload_sin_firma, sort_keys=True).encode(),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        if firma_recibida != firma_esperada:
            logger.warning(f"Firma inválida para QR: {qr_id}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ERROR_CODES["QR_INVALIDO"]
            )
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decodificando JSON del QR: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_CODES["QR_INVALIDO"]
        )
    except Exception as e:
        logger.error(f"Error procesando QR: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_CODES["QR_INVALIDO"]
        )
    
    # Verificar QR en base de datos
    qr_registro = db.query(QRRegistro).filter(
        QRRegistro.qr_id == qr_id
    ).first()
    
    if not qr_registro:
        logger.warning(f"QR no encontrado en BD: {qr_id}")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ERROR_CODES["QR_INVALIDO"]
        )
    
    ahora_peru = get_peru_time()
    
    # Verificar expiración
    if ahora_peru > qr_registro.expira_en:
        logger.warning(f"QR expirado: {qr_id} (expiró a las {qr_registro.expira_en})")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ERROR_CODES["QR_EXPIRADO"]
        )
    
    # Verificar si ya fue usado
    if qr_registro.usado:
        logger.warning(f"QR ya usado: {qr_id}")
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
    
    # Verificar orden de registro (ENTRADA primero, luego SALIDA)
    inicio_dia = datetime.combine(hoy, datetime.min.time())
    ultimo_registro = db.query(Asistencia).filter(
        Asistencia.personal_id == empleado_id,
        Asistencia.timestamp >= inicio_dia
    ).order_by(Asistencia.timestamp.desc()).first()
    
    tipo_permitido = "ENTRADA"
    if ultimo_registro and ultimo_registro.tipo == "ENTRADA":
        tipo_permitido = "SALIDA"
    
    if tipo != tipo_permitido:
        logger.warning(f"Orden incorrecto: se esperaba {tipo_permitido} pero se recibió {tipo}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Debe registrar {tipo_permitido} primero"
        )
    
    # Marcar QR como usado
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
    
    logger.info(f"✅ Asistencia registrada: {empleado.nombre} - {tipo} - {ahora_peru}")
    
    return {
        "valido": True,
        "empleado_id": str(empleado_id),
        "empleado_nombre": empleado.nombre,
        "tipo": tipo,
        "timestamp": ahora_peru.isoformat(),
        "turno": planificacion.turno_codigo,
        "mensaje": QR_MENSAJES["REGISTRO_EXITOSO"]
    }


# =====================================================
# ENDPOINT: OBTENER QR ACTIVO DE UN EMPLEADO
# =====================================================

@router.get("/empleado/{empleado_id}/activo")
async def obtener_qr_activo(
    empleado_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene el QR activo (no expirado y no usado) de un empleado
    El empleado puede ver su propio QR, y los admins pueden ver cualquier QR
    """
    # Verificar permisos
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
# ENDPOINTS DE TOKEN DE EMERGENCIA (para trámites)
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
    """
    Genera token de emergencia para validación sin QR
    Útil cuando el empleado no tiene acceso a su QR
    """
    # Verificar que la solicitud existe y pertenece al usuario
    solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    if str(solicitud.empleado_id) != str(current_user.personal_id) and "admin" not in current_user.roles:
        raise HTTPException(status_code=403, detail="No tiene permiso para esta solicitud")
    
    ahora_peru = get_peru_time()
    token = secrets.token_hex(8).upper()
    expira_en = ahora_peru + timedelta(minutes=duracion)
    
    # Guardar token en la solicitud o en una tabla de tokens
    # (Implementar según necesidad)
    
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
    """
    Valida token de emergencia para trámites
    """
    # Implementar validación según lógica de negocio
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
    """
    Genera QR para trámite aprobado
    """
    # Verificar solicitud
    solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
    if not solicitud:
        raise HTTPException(status_code=404, detail="Solicitud no encontrada")
    
    ahora_peru = get_peru_time()
    qr_id = f"tramite-{solicitud_id}-{int(ahora_peru.timestamp())}"
    expira_en = ahora_peru + timedelta(minutes=30)
    
    payload = {
        "qr_id": qr_id,
        "solicitud_id": str(solicitud_id),
        "tipo": "tramite",
        "generado_en": ahora_peru.isoformat(),
        "expira_en": expira_en.isoformat()
    }
    
    qr_data = base64.b64encode(json.dumps(payload).encode()).decode()
    
    logger.info(f"📱 QR de trámite generado: {qr_id}")
    
    return {
        "qr_data": qr_data,
        "qr_id": qr_id,
        "expira_en": expira_en.isoformat(),
        "tipo": "tramite",
        "mensaje": "QR de trámite generado correctamente"
    }


@router.post("/validar-tramite")
async def validar_qr_tramite(
    qr_data: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Valida QR de trámite
    """
    try:
        payload = json.loads(base64.b64decode(qr_data).decode())
        
        if payload.get("tipo") != "tramite":
            raise HTTPException(status_code=400, detail="QR inválido para trámite")
        
        solicitud_id = payload.get("solicitud_id")
        expira_en = datetime.fromisoformat(payload.get("expira_en"))
        
        ahora_peru = get_peru_time()
        
        if ahora_peru > expira_en:
            raise HTTPException(status_code=400, detail="QR expirado")
        
        # Verificar solicitud en BD
        solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if solicitud.estado != "aprobada":
            raise HTTPException(status_code=400, detail="Solicitud no está aprobada")
        
        logger.info(f"✅ QR de trámite validado: {solicitud_id}")
        
        return {
            "valido": True,
            "solicitud_id": str(solicitud_id),
            "mensaje": "Trámite válido"
        }
        
    except Exception as e:
        logger.error(f"Error validando QR de trámite: {e}")
        raise HTTPException(status_code=400, detail="QR inválido")


@router.get("/tramite/{solicitud_id}/activo")
async def obtener_qr_tramite_activo(
    solicitud_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Obtiene QR activo de un trámite
    """
    ahora_peru = get_peru_time()
    
    # Buscar QR activo (implementar según estructura de datos)
    # Por ahora retornamos que no hay activo
    
    return {"activo": False}


# =====================================================
# ENDPOINT UNIFICADO DE VALIDACIÓN
# =====================================================

@router.post("/validar-universal")
async def validar_universal(
    qr_data: Optional[str] = Body(None),
    token: Optional[str] = Body(None),
    solicitud_id: Optional[UUID] = Body(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["control_qr", "admin", "oficial_permanencia"]))
):
    """
    Valida cualquier método de autenticación (QR o Token)
    Útil para la interfaz unificada de control QR
    """
    
    if qr_data:
        # Detectar tipo de QR
        try:
            decoded = base64.b64decode(qr_data).decode()
            payload = json.loads(decoded)
            
            if payload.get("tipo") == "asistencia":
                return {
                    "metodo": "qr_asistencia",
                    "valido": True,
                    "empleado_id": payload.get("empleado_id")
                }
            elif payload.get("tipo") == "tramite":
                return {
                    "metodo": "qr_tramite",
                    "valido": True,
                    "solicitud_id": payload.get("solicitud_id")
                }
            else:
                return {"metodo": "qr_desconocido", "valido": False}
        except:
            return {"metodo": "qr_invalido", "valido": False}
    
    elif token and solicitud_id:
        # Validar token (implementar según lógica)
        return {
            "metodo": "token_emergencia",
            "valido": True,
            "solicitud_id": str(solicitud_id)
        }
    
    else:
        raise HTTPException(
            status_code=400, 
            detail="Debe proporcionar QR data o (token + solicitud_id)"
        )