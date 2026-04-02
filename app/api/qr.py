# app/api/qr.py
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
from app.utils.constants import TOKEN_CONFIG, TOKEN_MENSAJES, ERROR_CODES

# Configurar logger
logger = logging.getLogger(__name__)

# =====================================================
# 🟢 ROUTER CON PREFIX CORRECTO
# =====================================================
router = APIRouter(prefix="/qr", tags=["QR"])

# =====================================================
# 🆕 MANEJADOR OPTIONS PARA CORS (preflight)
# =====================================================

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
# ENDPOINTS QR DE ASISTENCIA
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
    if not current_user.personal_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario no tiene personal asociado"
        )
    
    qr_id = f"qr-{datetime.utcnow().timestamp()}-{secrets.token_hex(8)}"
    expira_en = datetime.utcnow() + timedelta(seconds=10)
    
    payload = {
        "qr_id": qr_id,
        "empleado_id": str(current_user.personal_id),
        "generado_en": datetime.utcnow().isoformat(),
        "expira_en": expira_en.isoformat(),
        "tipo": "asistencia"
    }
    
    firma = hmac.new(
        key=settings.JWT_SECRET_KEY.encode(),
        msg=json.dumps(payload, sort_keys=True).encode(),
        digestmod=hashlib.sha256
    ).hexdigest()
    payload["firma"] = firma
    
    qr_registro = QRRegistro(
        qr_id=qr_id,
        empleado_id=current_user.personal_id,
        expira_en=expira_en,
        usado=False,
        tipo="asistencia",
        codigo=json.dumps(payload)
    )
    db.add(qr_registro)
    db.commit()
    
    qr_data = base64.b64encode(json.dumps(payload).encode()).decode()
    
    return {
        "qr_data": qr_data,
        "qr_id": qr_id,
        "expira_en": expira_en.isoformat(),
        "tipo": "asistencia"
    }

@router.post("/validar")
async def validar_qr(
    qr_data: str = Body(...),
    tipo: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["oficial_permanencia", "control_qr", "admin"]))
):
    """Valida QR de asistencia"""
    try:
        # Decodificar QR
        payload = json.loads(base64.b64decode(qr_data).decode())
        
        if payload.get("tipo") != "asistencia":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="QR_INVALIDO"
            )
        
        qr_id = payload.get("qr_id")
        empleado_id = payload.get("empleado_id")
        expira_en = datetime.fromisoformat(payload.get("expira_en"))
        firma_recibida = payload.get("firma")
        
        # Verificar firma
        firma_esperada = hmac.new(
            key=settings.JWT_SECRET_KEY.encode(),
            msg=json.dumps({k: v for k, v in payload.items() if k != "firma"}, sort_keys=True).encode(),
            digestmod=hashlib.sha256
        ).hexdigest()
        
        if firma_recibida != firma_esperada:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="QR_INVALIDO"
            )
        
    except Exception as e:
        logger.error(f"Error decodificando QR: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="QR_INVALIDO"
        )
    
    # Verificar en base de datos
    qr_registro = db.query(QRRegistro).filter(
        QRRegistro.qr_id == qr_id
    ).first()
    
    if not qr_registro:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="QR no encontrado"
        )
    
    if datetime.utcnow() > qr_registro.expira_en:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="QR_EXPIRADO"
        )
    
    if qr_registro.usado:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="QR_YA_USADO"
        )
    
    # Verificar empleado
    empleado = db.query(Personal).filter(Personal.id == empleado_id).first()
    if not empleado:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empleado no encontrado"
        )
    
    # Verificar turno
    hoy = datetime.utcnow().date()
    planificacion = db.query(Planificacion).filter(
        Planificacion.personal_id == empleado_id,
        Planificacion.fecha == hoy
    ).first()
    
    if not planificacion:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SIN_TURNO - El empleado no tiene turno asignado para hoy"
        )
    
    # Verificar tipo de registro (ENTRADA/SALIDA)
    ultimo_registro = db.query(Asistencia).filter(
        Asistencia.personal_id == empleado_id,
        Asistencia.timestamp >= datetime.combine(hoy, datetime.min.time())
    ).order_by(Asistencia.timestamp.desc()).first()
    
    tipo_permitido = "ENTRADA"
    if ultimo_registro and ultimo_registro.tipo == "ENTRADA":
        tipo_permitido = "SALIDA"
    
    if tipo != tipo_permitido:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Debe registrar {tipo_permitido} primero"
        )
    
    # Marcar QR como usado
    qr_registro.usado = True
    qr_registro.usado_en = datetime.utcnow()
    qr_registro.usado_por = current_user.id
    
    # Registrar asistencia
    asistencia = Asistencia(
        personal_id=empleado_id,
        timestamp=datetime.utcnow(),
        tipo=tipo,
        tipo_registro="QR",
        turno_codigo=planificacion.turno_codigo,
        verificado=True,
        created_by=current_user.id
    )
    db.add(asistencia)
    db.commit()
    
    return {
        "valido": True,
        "empleado_id": str(empleado_id),
        "empleado_nombre": empleado.nombre,
        "tipo": tipo,
        "timestamp": datetime.utcnow().isoformat()
    }

@router.get("/empleado/{empleado_id}/activo")
async def obtener_qr_activo(
    empleado_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtiene QR activo de un empleado"""
    if str(current_user.personal_id) != str(empleado_id) and "admin" not in current_user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permiso para ver este QR"
        )
    
    ahora = datetime.utcnow()
    qr_activo = db.query(QRRegistro).filter(
        QRRegistro.empleado_id == empleado_id,
        QRRegistro.expira_en > ahora,
        QRRegistro.usado == False,
        QRRegistro.tipo == "asistencia"
    ).order_by(QRRegistro.generado_en.desc()).first()
    
    if not qr_activo:
        return {"activo": False}
    
    return {
        "activo": True,
        "qr_id": qr_activo.qr_id,
        "generado_en": qr_activo.generado_en.isoformat(),
        "expira_en": qr_activo.expira_en.isoformat()
    }

# =====================================================
# ENDPOINTS DE TOKEN DE EMERGENCIA (para trámites)
# =====================================================

@router.post("/generar-token/{solicitud_id}")
async def generar_token_emergencia(
    solicitud_id: UUID,
    duracion: int = Query(TOKEN_CONFIG["DURACION_DEFAULT"], ge=TOKEN_CONFIG["DURACION_MINIMA"], le=TOKEN_CONFIG["DURACION_MAXIMA"]),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Genera token de emergencia para validación sin QR"""
    # Placeholder - implementar según necesidad
    return {
        "token": f"TOKEN-{secrets.token_hex(4)}",
        "expira_en": (datetime.utcnow() + timedelta(minutes=duracion)).isoformat()
    }

@router.post("/validar-token")
async def validar_token_emergencia(
    solicitud_id: UUID = Body(...),
    token: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["control_qr", "admin", "oficial_permanencia"]))
):
    """Valida token de emergencia"""
    # Placeholder - implementar según necesidad
    return {
        "valido": True,
        "mensaje": "Token válido"
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
    # Placeholder - implementar según necesidad
    return {
        "qr_data": base64.b64encode(f"TRAMITE:{solicitud_id}".encode()).decode(),
        "qr_id": f"tramite-{secrets.token_hex(8)}",
        "expira_en": (datetime.utcnow() + timedelta(minutes=30)).isoformat(),
        "tipo": "tramite"
    }

@router.post("/validar-tramite")
async def validar_qr_tramite(
    qr_data: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Valida QR de trámite"""
    # Placeholder - implementar según necesidad
    return {
        "valido": True,
        "mensaje": "Trámite válido"
    }

@router.get("/tramite/{solicitud_id}/activo")
async def obtener_qr_tramite_activo(
    solicitud_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Obtiene QR activo de un trámite"""
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
    """Valida cualquier método de autenticación"""
    
    if qr_data:
        # Detectar tipo de QR
        if qr_data.startswith("TRAMITE:"):
            return {"metodo": "qr_tramite", "valido": True}
        else:
            try:
                payload = json.loads(base64.b64decode(qr_data).decode())
                if payload.get("tipo") == "asistencia":
                    return {
                        "metodo": "qr_asistencia",
                        "valido": True,
                        "empleado_id": payload.get("empleado_id")
                    }
            except:
                pass
            return {"metodo": "qr_desconocido", "valido": False}
    
    elif token and solicitud_id:
        return {"metodo": "token_emergencia", "valido": True}
    
    else:
        raise HTTPException(
            status_code=400, 
            detail="Debe proporcionar QR data o (token + solicitud_id)"
        )