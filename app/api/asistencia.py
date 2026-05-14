# api/asistencia.py - VERSIÓN ACTUALIZADA CON NUEVOS ROLES SIMPLIFICADOS

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, cast, String, or_
from typing import List, Optional
from datetime import datetime, date, timedelta, timezone as tz
from uuid import UUID
import json
import base64
import logging
import pytz

from app.database import get_db, SessionLocal
from app.core.dependencies import require_roles, get_current_user
from app.models.asistencia import Asistencia
from app.models.personal import Personal
from app.models.planificacion import Planificacion
from app.models.qr import QRRegistro
from app.models.usuario import Usuario
from app.schemas.asistencia import (
    AsistenciaCreate, AsistenciaResponse, AsistenciaQR,
    JustificacionCreate, EstadisticasAsistencia, IncidenciaAsistencia
)

logger = logging.getLogger(__name__)
PERU_TZ = pytz.timezone('America/Lima')
router = APIRouter()

# =====================================================
# ROLES UNIFICADOS - ALINEADOS CON roles.py
# =====================================================

ROLES_VER_ASISTENCIA = ["admin_empresa", "jefe", "usuario", "visitante", "escaner"]

ROLES_REGISTRAR_ASISTENCIA = ["admin_empresa", "jefe", "escaner"]

ROLES_ESTADISTICAS = ["admin_empresa", "jefe"]

ROLES_PERSONAL_ACTIVO = ["admin_empresa", "jefe", "escaner"]

# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def get_peru_time() -> datetime:
    return datetime.now(PERU_TZ)

def convertir_a_decimal(dt: datetime) -> float:
    return dt.hour + dt.minute / 60.0

def generar_id_corto(uuid_str: str, longitud: int = 8) -> str:
    return uuid_str.replace('-', '')[-longitud:]

def verificar_permiso_empresa(current_user, personal, operacion: str = "ver"):
    if current_user.rol_global in ["super_admin"]:
        return True
    if current_user.empresa_id and personal.empresa_id:
        if str(current_user.empresa_id) != str(personal.empresa_id):
            raise HTTPException(
                status_code=403,
                detail=f"Este personal no pertenece a su empresa. No puede {operacion}."
            )
    return True

def aplicar_filtro_empresa(query, current_user, modelo):
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if hasattr(modelo, 'empresa_id'):
            query = query.filter(modelo.empresa_id == current_user.empresa_id)
    return query

def extraer_empleado_id_qr(payload: dict, db: Session) -> Optional[str]:
    if "empleado_id" in payload: return payload["empleado_id"]
    if "personal_id" in payload: return payload["personal_id"]
    if "i" in payload:
        id_corto = payload["i"]
        empleado = db.query(Personal).filter(cast(Personal.id, String).endswith(id_corto)).first()
        if empleado: return str(empleado.id)
        nombre_corto = payload.get("n", "")
        if nombre_corto:
            empleado = db.query(Personal).filter(Personal.nombre.ilike(f"%{nombre_corto}%")).first()
            if empleado: return str(empleado.id)
    return None

# =====================================================
# CALCULAR INCIDENCIAS (USANDO HORARIOS DE TURNOS CONFIGURADOS)
# =====================================================

def calcular_incidencias(tipo: str, hora_registro: datetime, turno_codigo: str, fecha: date):
    """Calcula tardanza usando los horarios de los turnos configurados dinámicamente"""
    incidencias = {}
    
    # Los horarios ahora vienen de la configuración de turnos, no hardcodeados
    # Si el turno es VISITANTE o no tiene restricción, no hay incidencias
    if turno_codigo in ["VISITANTE", None]:
        return {"puntual": {"minutos": 0, "tipo": "puntual", "mensaje": "Registro exitoso"}}
    
    # Para otros turnos, buscar en la configuración
    from app.models.config_turno import ConfigTurno
    turno_config = db.query(ConfigTurno).filter(
        ConfigTurno.codigo == turno_codigo,
        ConfigTurno.activo == True
    ).first()
    
    if not turno_config or not turno_config.hora_inicio:
        return {"puntual": {"minutos": 0, "tipo": "puntual", "mensaje": "Registro exitoso"}}
    
    hora_esperada = convertir_a_decimal(turno_config.hora_inicio)
    hora_decimal = convertir_a_decimal(hora_registro)
    tolerancia = 15  # 15 minutos de tolerancia
    
    if tipo == "ENTRADA":
        diferencia_minutos = int((hora_decimal - hora_esperada) * 60)
        if diferencia_minutos > tolerancia:
            incidencias["tardanza"] = {"minutos": diferencia_minutos, "horas": round(diferencia_minutos / 60, 1), "tipo": "tardanza", "mensaje": f"Llego {diferencia_minutos} minutos tarde"}
        elif diferencia_minutos < -tolerancia:
            incidencias["entrada_temprana"] = {"minutos": abs(diferencia_minutos), "horas": round(abs(diferencia_minutos) / 60, 1), "tipo": "entrada_temprana", "mensaje": f"Llego {abs(diferencia_minutos)} minutos temprano"}
        else:
            incidencias["puntual"] = {"minutos": 0, "tipo": "puntual", "mensaje": "Llego puntual"}
    
    if not incidencias:
        incidencias["puntual"] = {"minutos": 0, "tipo": "puntual", "mensaje": "Registro exitoso"}
    
    return incidencias


def generar_mensaje_incidencia(incidencias: dict, tipo: str) -> str:
    if not incidencias: return f"Asistencia {tipo} registrada correctamente"
    if "tardanza" in incidencias: return incidencias['tardanza']['mensaje']
    if "entrada_temprana" in incidencias: return incidencias['entrada_temprana']['mensaje']
    if "puntual" in incidencias: return incidencias['puntual']['mensaje']
    return f"Asistencia {tipo} registrada"

# =====================================================
# CORS OPTIONS
# =====================================================

@router.options("/{path:path}")
async def options_handler():
    return Response(status_code=200, headers={
        "Access-Control-Allow-Origin": "http://localhost:5173",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Allow-Credentials": "true", "Access-Control-Max-Age": "3600",
    })

# =====================================================
# HEALTH CHECK
# =====================================================

@router.get("/health")
async def health_check():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return JSONResponse(status_code=200, content={"status": "healthy", "timestamp": get_peru_time().isoformat(), "service": "asistencia", "database": "connected"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"status": "unhealthy", "error": str(e)})

# =====================================================
# ENDPOINTS
# =====================================================

@router.get("/registros-hoy")
async def registros_hoy(
    fecha: date = Query(default_factory=date.today),
    empresa_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_VER_ASISTENCIA))
):
    try:
        inicio = datetime.combine(fecha, datetime.min.time())
        fin = datetime.combine(fecha, datetime.max.time())
        query = db.query(Asistencia).filter(Asistencia.timestamp >= inicio, Asistencia.timestamp <= fin)
        if empresa_id:
            query = query.filter(Asistencia.empresa_id == empresa_id)
        else:
            query = aplicar_filtro_empresa(query, current_user, Asistencia)
        
        registros = query.order_by(Asistencia.timestamp.desc()).all()
        resultado = []
        for r in registros:
            personal = db.query(Personal).filter(Personal.id == r.personal_id).first()
            controlador_nombre = "Sistema"
            if r.created_by:
                controlador = db.query(Usuario).filter(Usuario.id == r.created_by).first()
                if controlador:
                    if controlador.personal_id:
                        cp = db.query(Personal).filter(Personal.id == controlador.personal_id).first()
                        controlador_nombre = cp.nombre if cp else controlador.email
                    else:
                        controlador_nombre = controlador.email
            resultado.append({
                "id": str(r.id), "personal_id": str(r.personal_id),
                "nombre": personal.nombre if personal else "Desconocido",
                "grado": personal.grado if personal else "",
                "timestamp": r.timestamp.isoformat(),
                "fecha": r.timestamp.strftime("%Y-%m-%d") if r.timestamp else "",
                "hora": r.timestamp.strftime("%H:%M:%S") if r.timestamp else "",
                "tipo": r.tipo, "tipo_registro": r.tipo_registro,
                "turno_codigo": r.turno_codigo, "controlador": controlador_nombre
            })
        return resultado
    except Exception as e:
        logger.error(f"Error en registros_hoy: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener registros: {str(e)}")

@router.get("/registros")
async def get_registros_por_rango(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    empresa_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_VER_ASISTENCIA))
):
    try:
        inicio = datetime.combine(fecha_inicio, datetime.min.time())
        fin = datetime.combine(fecha_fin, datetime.max.time())
        query = db.query(Asistencia).filter(Asistencia.timestamp >= inicio, Asistencia.timestamp <= fin)
        if empresa_id:
            query = query.filter(Asistencia.empresa_id == empresa_id)
        else:
            query = aplicar_filtro_empresa(query, current_user, Asistencia)
        
        registros = query.order_by(Asistencia.timestamp.desc()).all()
        resultado = []
        personal_cache = {}
        for r in registros:
            if r.personal_id not in personal_cache:
                personal_cache[r.personal_id] = db.query(Personal).filter(Personal.id == r.personal_id).first()
            personal = personal_cache[r.personal_id]
            resultado.append({
                "id": str(r.id), "personal_id": str(r.personal_id),
                "nombre": personal.nombre if personal else "Desconocido",
                "grado": personal.grado if personal else "",
                "cip": personal.cip if personal else "",
                "dni": personal.dni if personal else "",
                "area": personal.area if personal else "",
                "timestamp": r.timestamp.isoformat(),
                "tipo": r.tipo, "tipo_registro": r.tipo_registro,
                "turno_codigo": r.turno_codigo
            })
        return resultado
    except Exception as e:
        logger.error(f"Error en get_registros_por_rango: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener registros: {str(e)}")

@router.post("/registro-directo")
async def registro_directo(
    personal_id: UUID = Body(...),
    tipo: str = Body(...),
    empresa_id: Optional[UUID] = Body(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_REGISTRAR_ASISTENCIA))
):
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        verificar_permiso_empresa(current_user, personal, "registrar asistencia")
        
        if tipo not in ["ENTRADA", "SALIDA"]:
            raise HTTPException(status_code=400, detail="Tipo debe ser ENTRADA o SALIDA")
        
        ahora_peru = get_peru_time()
        hoy = ahora_peru.date()
        
        es_visitante = "visitante" in (personal.roles or [])
        turno_codigo = "VISITANTE" if es_visitante else None
        
        if not es_visitante:
            planificacion = db.query(Planificacion).filter(
                Planificacion.personal_id == personal_id,
                Planificacion.fecha == hoy
            ).first()
            if not planificacion:
                raise HTTPException(status_code=400, detail="SIN_TURNO")
            turno_codigo = planificacion.turno_codigo
        
        inicio_dia = datetime.combine(hoy, datetime.min.time())
        ultimo = db.query(Asistencia).filter(
            Asistencia.personal_id == personal_id,
            Asistencia.timestamp >= inicio_dia
        ).order_by(Asistencia.timestamp.desc()).first()
        
        if ultimo and ultimo.tipo == "ENTRADA" and tipo != "SALIDA":
            raise HTTPException(status_code=400, detail="Debe registrar SALIDA primero")
        if not ultimo and tipo != "ENTRADA":
            raise HTTPException(status_code=400, detail="Debe registrar ENTRADA primero")
        
        asistencia = Asistencia(
            personal_id=personal_id, timestamp=ahora_peru, tipo=tipo,
            tipo_registro="MANUAL", turno_codigo=turno_codigo,
            created_by=current_user.id,
            empresa_id=current_user.empresa_id if current_user.empresa_id else None
        )
        db.add(asistencia)
        db.commit()
        db.refresh(asistencia)
        
        tipo_persona = "Visitante" if es_visitante else "Trabajador"
        logger.info(f"Registro directo ({tipo_persona}): {personal.nombre} - {tipo}")
        
        return {
            "success": True, "fecha": asistencia.timestamp.isoformat(),
            "tipo": tipo, "tipo_persona": tipo_persona,
            "personal_id": str(personal_id), "personal_nombre": personal.nombre,
            "turno": turno_codigo
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en registro-directo: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al registrar asistencia: {str(e)}")

@router.get("/personal/{personal_id}")
async def get_asistencia_personal(
    personal_id: UUID,
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_VER_ASISTENCIA))
):
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        roles_usuario = current_user.roles or []
        es_visitante = "visitante" in [r.lower() for r in roles_usuario if isinstance(r, str)]
        es_admin = "admin_empresa" in [r.lower() for r in roles_usuario if isinstance(r, str)]
        
        if es_visitante and not es_admin and str(current_user.personal_id) != str(personal_id):
            raise HTTPException(status_code=403, detail="Solo puede ver su propia asistencia")
        
        verificar_permiso_empresa(current_user, personal, "ver asistencia")
        
        if not fecha_fin: fecha_fin = date.today()
        if not fecha_inicio: fecha_inicio = fecha_fin - timedelta(days=30)
        
        inicio = datetime.combine(fecha_inicio, datetime.min.time())
        fin = datetime.combine(fecha_fin, datetime.max.time())
        
        query = db.query(Asistencia).filter(
            Asistencia.personal_id == personal_id,
            Asistencia.timestamp >= inicio, Asistencia.timestamp <= fin
        )
        query = aplicar_filtro_empresa(query, current_user, Asistencia)
        registros = query.order_by(Asistencia.timestamp.desc()).all()
        
        resultado = []
        for r in registros:
            timestamp_peru = r.timestamp
            if timestamp_peru.tzinfo is None:
                timestamp_peru = pytz.UTC.localize(timestamp_peru).astimezone(PERU_TZ)
            else:
                timestamp_peru = timestamp_peru.astimezone(PERU_TZ)
            resultado.append({
                "id": str(r.id), "fecha": timestamp_peru.date().isoformat(),
                "hora": timestamp_peru.time().isoformat(), "timestamp": timestamp_peru.isoformat(),
                "tipo": r.tipo, "tipo_registro": r.tipo_registro, "turno": r.turno_codigo
            })
        
        return {
            "personal_id": str(personal_id), "personal_nombre": personal.nombre,
            "periodo": {"inicio": fecha_inicio.isoformat(), "fin": fecha_fin.isoformat()},
            "total_registros": len(resultado), "registros": resultado
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_asistencia_personal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener historial: {str(e)}")