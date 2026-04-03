# app/api/asistencia.py - VERSIÓN ACTUALIZADA CON SOPORTE QR V2
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text, cast, String
from typing import List, Optional
from datetime import datetime, date, timedelta, timezone as tz
from uuid import UUID
import json
import base64
import logging
import pytz

from app.database import get_db, SessionLocal
from app.core.dependencies import require_roles
from app.models.asistencia import Asistencia
from app.models.personal import Personal
from app.models.planificacion import Planificacion
from app.models.qr import QRRegistro
from app.models.usuario import Usuario
from app.schemas.asistencia import (
    AsistenciaCreate, AsistenciaResponse, AsistenciaQR,
    JustificacionCreate, EstadisticasAsistencia, IncidenciaAsistencia
)

# Configurar logging
logger = logging.getLogger(__name__)

# Configurar zona horaria de Perú
PERU_TZ = pytz.timezone('America/Lima')

router = APIRouter()

# =====================================================
# FUNCIÓN AUXILIAR PARA OBTENER HORA LOCAL DE PERÚ
# =====================================================

def get_peru_time() -> datetime:
    """Retorna la fecha y hora actual en la zona horaria de Perú (UTC-5)"""
    return datetime.now(PERU_TZ)

def convertir_a_decimal(dt: datetime) -> float:
    """Convierte un datetime a horas decimales (ej: 07:30 → 7.5)"""
    return dt.hour + dt.minute / 60.0

def generar_id_corto(uuid_str: str, longitud: int = 8) -> str:
    """Genera un ID corto a partir de un UUID (últimos N caracteres)"""
    return uuid_str.replace('-', '')[-longitud:]

# =====================================================
# FUNCIÓN AUXILIAR PARA CALCULAR INCIDENCIAS
# =====================================================

def calcular_incidencias(tipo: str, hora_registro: datetime, turno_codigo: str, fecha: date):
    """
    Calcula tardanza (para ENTRADA) o salida temprana (para SALIDA)
    Retorna dict con incidencias encontradas
    
    HORARIOS:
    - MAN: 07:30 - 13:30 (7.5 - 13.5)
    - TAR: 13:30 - 19:30 (13.5 - 19.5)
    - 12M: 07:30 - 19:30 (7.5 - 19.5)
    - 12N: 19:30 - 07:30 (19.5 - 7.5)
    - ADM: 07:30 - 16:30 (7.5 - 16.5)
    - 24X48: 08:00 - 08:00 (8 - 8)
    """
    incidencias = {}
    
    horarios_turno = {
        "MAN": {"entrada": 7.5, "salida": 13.5, "tolerancia": 15},
        "TAR": {"entrada": 13.5, "salida": 19.5, "tolerancia": 15},
        "12M": {"entrada": 7.5, "salida": 19.5, "tolerancia": 15},
        "12N": {"entrada": 19.5, "salida": 7.5, "tolerancia": 15},
        "ADM": {"entrada": 7.5, "salida": 16.5, "tolerancia": 15},
        "24X48": {"entrada": 8.0, "salida": 8.0, "tolerancia": 30},
        "FR": {"entrada": None, "salida": None, "tolerancia": 0},
        "VAC": {"entrada": None, "salida": None, "tolerancia": 0},
        "DM": {"entrada": None, "salida": None, "tolerancia": 0},
    }
    
    horario = horarios_turno.get(turno_codigo, {"entrada": None, "salida": None, "tolerancia": 15})
    
    hora_decimal = convertir_a_decimal(hora_registro)
    
    if tipo == "ENTRADA" and horario["entrada"] is not None:
        hora_esperada = horario["entrada"]
        diferencia_minutos = int((hora_decimal - hora_esperada) * 60)
        
        if diferencia_minutos > horario["tolerancia"]:
            incidencias["tardanza"] = {
                "minutos": diferencia_minutos,
                "horas": round(diferencia_minutos / 60, 1),
                "tipo": "tardanza",
                "mensaje": f"Llegó {diferencia_minutos} minutos tarde"
            }
        elif diferencia_minutos < -horario["tolerancia"]:
            incidencias["entrada_temprana"] = {
                "minutos": abs(diferencia_minutos),
                "horas": round(abs(diferencia_minutos) / 60, 1),
                "tipo": "entrada_temprana",
                "mensaje": f"Llegó {abs(diferencia_minutos)} minutos temprano"
            }
        else:
            incidencias["puntual"] = {
                "minutos": 0,
                "tipo": "puntual",
                "mensaje": "Llegó puntual"
            }
    
    elif tipo == "SALIDA" and horario["salida"] is not None:
        hora_esperada = horario["salida"]
        
        if turno_codigo == "12N" and hora_esperada < 12:
            minutos_esperados = (24 + hora_esperada) * 60
            hora_decimal_ajustada = hora_decimal if hora_decimal >= 12 else hora_decimal + 24
            minutos_reales = hora_decimal_ajustada * 60
        else:
            minutos_esperados = hora_esperada * 60
            minutos_reales = hora_decimal * 60
        
        diferencia_minutos = int(minutos_esperados - minutos_reales)
        
        if diferencia_minutos > horario["tolerancia"]:
            incidencias["salida_temprana"] = {
                "minutos": diferencia_minutos,
                "horas": round(diferencia_minutos / 60, 1),
                "tipo": "salida_temprana",
                "mensaje": f"Salió {diferencia_minutos} minutos antes"
            }
        elif diferencia_minutos < -horario["tolerancia"]:
            incidencias["salida_tardia"] = {
                "minutos": abs(diferencia_minutos),
                "horas": round(abs(diferencia_minutos) / 60, 1),
                "tipo": "salida_tardia",
                "mensaje": f"Salió {abs(diferencia_minutos)} minutos después"
            }
        else:
            incidencias["puntual"] = {
                "minutos": 0,
                "tipo": "puntual",
                "mensaje": "Salió puntual"
            }
    
    return incidencias


def generar_mensaje_incidencia(incidencias: dict, tipo: str) -> str:
    """Genera mensaje legible para el usuario"""
    if not incidencias:
        return f"Asistencia {tipo} registrada correctamente"
    
    if "tardanza" in incidencias:
        return f"⚠️ {incidencias['tardanza']['mensaje']}"
    if "entrada_temprana" in incidencias:
        return f"✅ {incidencias['entrada_temprana']['mensaje']}"
    if "salida_temprana" in incidencias:
        return f"⚠️ {incidencias['salida_temprana']['mensaje']}"
    if "salida_tardia" in incidencias:
        return f"✅ {incidencias['salida_tardia']['mensaje']}"
    if "puntual" in incidencias:
        return f"✅ {incidencias['puntual']['mensaje']}"
    
    return f"Asistencia {tipo} registrada"


# =====================================================
# MANEJADOR OPTIONS GLOBAL PARA CORS
# =====================================================

@router.options("/{path:path}")
async def options_handler():
    return Response(
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "http://localhost:5173",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type, Authorization",
            "Access-Control-Allow-Credentials": "true",
            "Access-Control-Max-Age": "3600",
        }
    )


# =====================================================
# HEALTH CHECK
# =====================================================

@router.get("/health")
async def health_check():
    """Health check endpoint para monitoreo del sistema"""
    try:
        db_status = "connected"
        try:
            db = SessionLocal()
            db.execute(text("SELECT 1"))
            db.close()
        except Exception as e:
            db_status = f"error: {str(e)}"
            logger.error(f"Database health check failed: {str(e)}")
        
        return JSONResponse(
            status_code=200,
            content={
                "status": "healthy",
                "timestamp": get_peru_time().isoformat(),
                "service": "asistencia",
                "database": db_status
            }
        )
    except Exception as e:
        logger.error(f"Health check error: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "unhealthy",
                "error": str(e),
                "timestamp": get_peru_time().isoformat()
            }
        )


# =====================================================
# ENDPOINT SIMPLE PARA REGISTROS DE HOY
# =====================================================

@router.get("/registros-hoy")
async def registros_hoy(
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia", "jefe_area"]))
):
    """Endpoint SIMPLE para obtener registros de hoy"""
    try:
        inicio = datetime.combine(fecha, datetime.min.time())
        fin = datetime.combine(fecha, datetime.max.time())
        
        registros = db.query(Asistencia).filter(
            Asistencia.timestamp >= inicio,
            Asistencia.timestamp <= fin
        ).order_by(Asistencia.timestamp.desc()).all()
        
        resultado = []
        for r in registros:
            personal = db.query(Personal).filter(Personal.id == r.personal_id).first()
            
            controlador_nombre = "Sistema"
            if r.created_by:
                controlador = db.query(Usuario).filter(Usuario.id == r.created_by).first()
                if controlador:
                    if controlador.personal_id:
                        controlador_personal = db.query(Personal).filter(Personal.id == controlador.personal_id).first()
                        if controlador_personal:
                            controlador_nombre = controlador_personal.nombre
                        else:
                            controlador_nombre = controlador.email
                    else:
                        controlador_nombre = controlador.email
            
            resultado.append({
                "id": str(r.id),
                "personal_id": str(r.personal_id),
                "nombre": personal.nombre if personal else "Desconocido",
                "grado": personal.grado if personal else "",
                "timestamp": r.timestamp.isoformat(),
                "tipo": r.tipo,
                "tipo_registro": r.tipo_registro,
                "turno_codigo": r.turno_codigo,
                "controlador": controlador_nombre
            })
        
        return resultado
        
    except Exception as e:
        logger.error(f"Error en registros_hoy: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener registros: {str(e)}")


# =====================================================
# ENDPOINT ESTADÍSTICAS DE ASISTENCIA
# =====================================================

@router.get("/estadisticas")
async def get_estadisticas(
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """Obtener estadísticas de asistencia para una fecha específica"""
    try:
        inicio = datetime.combine(fecha, datetime.min.time())
        fin = datetime.combine(fecha, datetime.max.time())
        
        registros = db.query(Asistencia).filter(
            Asistencia.timestamp >= inicio,
            Asistencia.timestamp <= fin
        ).all()
        
        entradas = len([r for r in registros if r.tipo == "ENTRADA"])
        salidas = len([r for r in registros if r.tipo == "SALIDA"])
        
        personal_con_turno = db.query(Planificacion).filter(
            Planificacion.fecha == fecha
        ).count()
        
        personal_registrado = len(set([r.personal_id for r in registros]))
        
        turnos_stats = {}
        for registro in registros:
            turno = registro.turno_codigo or "SIN_TURNO"
            if turno not in turnos_stats:
                turnos_stats[turno] = {"entradas": 0, "salidas": 0}
            if registro.tipo == "ENTRADA":
                turnos_stats[turno]["entradas"] += 1
            else:
                turnos_stats[turno]["salidas"] += 1
        
        return {
            "fecha": fecha.isoformat(),
            "total_registros": len(registros),
            "entradas": entradas,
            "salidas": salidas,
            "personal_con_turno": personal_con_turno,
            "personal_registrado": personal_registrado,
            "porcentaje_asistencia": round(
                (personal_registrado / personal_con_turno * 100), 2
            ) if personal_con_turno > 0 else 0,
            "detalle_por_turno": turnos_stats
        }
        
    except Exception as e:
        logger.error(f"Error en estadisticas: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener estadísticas: {str(e)}")


# =====================================================
# ENDPOINT PERSONAL ACTIVO EN EL HOSPITAL
# =====================================================

@router.get("/activos")
async def get_personal_activo(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """Obtener personal actualmente en el hospital"""
    try:
        hoy = date.today()
        ahora_peru = get_peru_time()
        
        inicio_dia = datetime.combine(hoy, datetime.min.time())
        fin_dia = datetime.combine(hoy, datetime.max.time())
        
        entradas_hoy = db.query(Asistencia).filter(
            Asistencia.tipo == "ENTRADA",
            Asistencia.timestamp >= inicio_dia,
            Asistencia.timestamp <= fin_dia
        ).all()
        
        activos = []
        for entrada in entradas_hoy:
            entrada_timestamp = entrada.timestamp
            
            salida_despues = db.query(Asistencia).filter(
                Asistencia.personal_id == entrada.personal_id,
                Asistencia.tipo == "SALIDA",
                Asistencia.timestamp > entrada_timestamp
            ).first()
            
            if not salida_despues:
                personal = db.query(Personal).filter(
                    Personal.id == entrada.personal_id
                ).first()
                
                if personal:
                    diferencia = ahora_peru - entrada_timestamp
                    horas = diferencia.seconds // 3600
                    minutos = (diferencia.seconds % 3600) // 60
                    
                    activos.append({
                        "personal_id": str(personal.id),
                        "nombre": personal.nombre,
                        "grado": personal.grado or "",
                        "hora_entrada": entrada_timestamp.isoformat(),
                        "turno": entrada.turno_codigo or "",
                        "tiempo_en_hospital": f"{horas}h {minutos}m",
                        "tipo_registro": entrada.tipo_registro or "QR"
                    })
        
        return {
            "total_activos": len(activos),
            "personal": activos,
            "fecha": hoy.isoformat(),
            "hora_consulta": ahora_peru.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error en /activos: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener personal activo: {str(e)}")


# =====================================================
# FUNCIÓN AUXILIAR PARA EXTRAER EMPLEADO_ID (SOPORTA V1 Y V2)
# =====================================================

def extraer_empleado_id_qr(payload: dict, db: Session) -> Optional[str]:
    """
    Extrae el empleado_id soportando formato antiguo y nuevo
    Retorna el UUID completo del empleado
    """
    # Formato antiguo (v1)
    if "empleado_id" in payload:
        return payload["empleado_id"]
    
    if "personal_id" in payload:
        return payload["personal_id"]
    
    # Formato nuevo (v2) - {i, n, d, t, v}
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
    
    return None


# =====================================================
# ENDPOINT QR DE ASISTENCIA (ACTUALIZADO - SOPORTA V1 Y V2)
# =====================================================

@router.post("/qr-validar")
async def validar_qr_asistencia(
    qr_data: str = Body(...),
    tipo: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "oficial_permanencia", "control_qr"]))
):
    """
    Valida QR de asistencia - SOPORTA FORMATO V1 (legacy) Y V2 (optimizado)
    
    Formato V1: { empleado_id, expira_en, qr_id, ... }
    Formato V2: { i, n, d, t, v }
    """
    try:
        decoded_str = base64.b64decode(qr_data).decode('utf-8')
        payload = json.loads(decoded_str)
        
        logger.info(f"📦 QR recibido para validación: {payload}")
        
        # =====================================================
        # DETECTAR VERSIÓN DEL FORMATO
        # =====================================================
        version = payload.get("v", "1")
        logger.info(f"📌 Versión QR detectada: {version}")
        
        # =====================================================
        # EXTRAER EMPLEADO_ID (soporta ambos formatos)
        # =====================================================
        empleado_id = extraer_empleado_id_qr(payload, db)
        
        if not empleado_id:
            logger.warning("❌ No se pudo extraer empleado_id del QR")
            raise HTTPException(
                status_code=400, 
                detail="QR_INVALIDO - No se pudo identificar al empleado"
            )
        
        logger.info(f"✅ Empleado ID extraído: {empleado_id}")
        
        # =====================================================
        # BUSCAR QR EN BASE DE DATOS (si existe)
        # =====================================================
        qr_registro = None
        qr_id = None
        expira_en = None
        
        # Para formato v1, buscar por qr_id
        if version == "1" and "qr_id" in payload:
            qr_id = payload["qr_id"]
            qr_registro = db.query(QRRegistro).filter(
                QRRegistro.qr_id == qr_id
            ).first()
            if qr_registro:
                expira_en = qr_registro.expira_en
        
        # Para formato v2, buscar por empleado_id y estado activo
        elif version == "2":
            ahora_peru = get_peru_time()
            qr_registro = db.query(QRRegistro).filter(
                QRRegistro.empleado_id == empleado_id,
                QRRegistro.expira_en > ahora_peru,
                QRRegistro.usado == False,
                QRRegistro.tipo == "asistencia"
            ).order_by(QRRegistro.generado_en.desc()).first()
            
            if qr_registro:
                qr_id = qr_registro.qr_id
                expira_en = qr_registro.expira_en
                logger.info(f"✅ QR encontrado en BD: {qr_id}")
        
        # =====================================================
        # VERIFICAR EXPIRACIÓN
        # =====================================================
        ahora_peru = get_peru_time()
        
        if expira_en:
            if expira_en.tzinfo is None:
                expira_en = PERU_TZ.localize(expira_en)
            
            if ahora_peru > expira_en:
                logger.warning(f"❌ QR expirado - Expira: {expira_en}, Ahora: {ahora_peru}")
                raise HTTPException(
                    status_code=400, 
                    detail="QR_EXPIRADO - El código QR ha expirado (máximo 10 segundos)"
                )
        
        # =====================================================
        # VERIFICAR SI YA FUE USADO
        # =====================================================
        if qr_registro and qr_registro.usado:
            logger.warning(f"❌ QR ya usado: {qr_id}")
            raise HTTPException(
                status_code=400, 
                detail="QR_YA_USADO - Este código QR ya fue utilizado"
            )
        
        # =====================================================
        # VERIFICAR EMPLEADO
        # =====================================================
        personal = db.query(Personal).filter(Personal.id == empleado_id).first()
        if not personal:
            logger.warning(f"❌ Empleado no encontrado: {empleado_id}")
            raise HTTPException(
                status_code=404, 
                detail="EMPLEADO_NO_ENCONTRADO - Personal no encontrado"
            )
        
        if not personal.activo:
            logger.warning(f"❌ Empleado inactivo: {personal.nombre}")
            raise HTTPException(
                status_code=400, 
                detail="EMPLEADO_INACTIVO - El personal está inactivo"
            )
        
        # =====================================================
        # VERIFICAR TURNO DEL DÍA
        # =====================================================
        hoy = ahora_peru.date()
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == empleado_id,
            Planificacion.fecha == hoy
        ).first()
        
        if not planificacion:
            logger.warning(f"❌ Empleado sin turno: {personal.nombre} - {hoy}")
            raise HTTPException(
                status_code=400, 
                detail="SIN_TURNO - No tiene turno asignado para hoy"
            )
        
        # =====================================================
        # VERIFICAR ORDEN DE REGISTRO (ENTRADA -> SALIDA)
        # =====================================================
        inicio_dia = datetime.combine(hoy, datetime.min.time())
        ultimo_registro = db.query(Asistencia).filter(
            Asistencia.personal_id == empleado_id,
            Asistencia.timestamp >= inicio_dia
        ).order_by(Asistencia.timestamp.desc()).first()
        
        tipo_permitido = "ENTRADA"
        if ultimo_registro and ultimo_registro.tipo == "ENTRADA":
            tipo_permitido = "SALIDA"
        
        if tipo != tipo_permitido:
            logger.warning(f"❌ Orden incorrecto: se esperaba {tipo_permitido}, se recibió {tipo}")
            raise HTTPException(
                status_code=400,
                detail=f"Debe registrar {tipo_permitido} primero"
            )
        
        # =====================================================
        # CALCULAR INCIDENCIAS (solo para mensaje)
        # =====================================================
        incidencias = calcular_incidencias(tipo, ahora_peru, planificacion.turno_codigo, hoy)
        
        # =====================================================
        # CREAR REGISTRO DE ASISTENCIA
        # =====================================================
        asistencia = Asistencia(
            personal_id=empleado_id,
            timestamp=ahora_peru,
            tipo=tipo,
            tipo_registro="QR",
            turno_codigo=planificacion.turno_codigo,
            created_by=current_user.id
        )
        
        db.add(asistencia)
        db.commit()
        db.refresh(asistencia)
        
        # =====================================================
        # MARCAR QR COMO USADO
        # =====================================================
        if qr_registro:
            qr_registro.usado = True
            qr_registro.usado_en = ahora_peru
            qr_registro.usado_por = current_user.id
            db.commit()
            logger.info(f"✅ QR marcado como usado: {qr_id}")
        
        logger.info(f"✅ Asistencia registrada: {personal.nombre} - {tipo}")
        
        # =====================================================
        # RESPUESTA
        # =====================================================
        return {
            "valido": True,
            "empleado_id": str(empleado_id),
            "empleado_nombre": personal.nombre,
            "tipo": tipo,
            "timestamp": asistencia.timestamp.isoformat(),
            "turno": planificacion.turno_codigo,
            "formato": version,
            "incidencias": incidencias,
            "mensaje": generar_mensaje_incidencia(incidencias, tipo)
        }
        
    except HTTPException:
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Error decodificando JSON del QR: {e}")
        raise HTTPException(status_code=400, detail="QR_INVALIDO - Formato JSON inválido")
    except Exception as e:
        logger.error(f"Error en qr-validar: {str(e)}")
        raise HTTPException(status_code=400, detail=f"Error al validar QR: {str(e)}")


# =====================================================
# ENDPOINT DIRECTO PARA PRUEBAS (CORREGIDO)
# =====================================================

@router.post("/registro-directo")
async def registro_directo(
    personal_id: UUID = Body(...),
    tipo: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """Registro directo de asistencia - SIN QR (con cálculo de incidencias)"""
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        if tipo not in ["ENTRADA", "SALIDA"]:
            raise HTTPException(status_code=400, detail="Tipo debe ser ENTRADA o SALIDA")
        
        hoy = date.today()
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha == hoy
        ).first()
        
        if not planificacion:
            raise HTTPException(status_code=400, detail="SIN_TURNO - No tiene turno asignado para hoy")
        
        inicio_dia = datetime.combine(hoy, datetime.min.time())
        ultimo = db.query(Asistencia).filter(
            Asistencia.personal_id == personal_id,
            Asistencia.timestamp >= inicio_dia
        ).order_by(Asistencia.timestamp.desc()).first()
        
        if ultimo and ultimo.tipo == "ENTRADA" and tipo != "SALIDA":
            raise HTTPException(status_code=400, detail="Debe registrar SALIDA primero")
        
        if not ultimo and tipo != "ENTRADA":
            raise HTTPException(status_code=400, detail="Debe registrar ENTRADA primero")
        
        ahora_peru = get_peru_time()
        
        # Calcular incidencias solo para mensaje
        incidencias = calcular_incidencias(tipo, ahora_peru, planificacion.turno_codigo, hoy)
        
        # Crear asistencia
        asistencia = Asistencia(
            personal_id=personal_id,
            timestamp=ahora_peru,
            tipo=tipo,
            tipo_registro="MANUAL",
            turno_codigo=planificacion.turno_codigo,
            created_by=current_user.id
        )
        
        db.add(asistencia)
        db.commit()
        db.refresh(asistencia)
        
        return {
            "success": True,
            "mensaje": generar_mensaje_incidencia(incidencias, tipo),
            "fecha": asistencia.timestamp.isoformat(),
            "tipo": tipo,
            "personal_id": str(personal_id),
            "personal_nombre": personal.nombre,
            "turno": planificacion.turno_codigo,
            "incidencias": incidencias
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en registro-directo: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al registrar asistencia: {str(e)}")


# =====================================================
# ENDPOINT PARA REGISTRO MANUAL DE ASISTENCIA
# =====================================================

@router.post("/registro-manual")
async def registro_manual(
    personal_id: UUID = Body(...),
    tipo: str = Body(...),
    justificacion: Optional[str] = Body(None),
    fecha_registro: Optional[datetime] = Body(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """Registro manual de asistencia con justificación"""
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        if tipo not in ["ENTRADA", "SALIDA"]:
            raise HTTPException(status_code=400, detail="Tipo debe ser ENTRADA o SALIDA")
        
        if fecha_registro:
            timestamp = fecha_registro
            if timestamp.tzinfo is None:
                timestamp = PERU_TZ.localize(timestamp)
        else:
            timestamp = get_peru_time()
        
        fecha_registro_date = timestamp.date()
        
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha == fecha_registro_date
        ).first()
        
        if not planificacion:
            raise HTTPException(
                status_code=400, 
                detail=f"SIN_TURNO - No tiene turno asignado para {fecha_registro_date}"
            )
        
        # Calcular incidencias solo para mensaje
        incidencias = calcular_incidencias(tipo, timestamp, planificacion.turno_codigo, fecha_registro_date)
        
        # Crear asistencia
        asistencia = Asistencia(
            personal_id=personal_id,
            timestamp=timestamp,
            tipo=tipo,
            tipo_registro="MANUAL",
            turno_codigo=planificacion.turno_codigo,
            created_by=current_user.id
        )
        
        if hasattr(asistencia, 'justificacion') and justificacion:
            asistencia.justificacion = justificacion
        
        db.add(asistencia)
        db.commit()
        db.refresh(asistencia)
        
        return {
            "success": True,
            "mensaje": generar_mensaje_incidencia(incidencias, tipo),
            "fecha": asistencia.timestamp.isoformat(),
            "tipo": tipo,
            "personal_id": str(personal_id),
            "personal_nombre": personal.nombre,
            "turno": planificacion.turno_codigo,
            "incidencias": incidencias,
            "justificacion": justificacion
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en registro-manual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al registrar asistencia manual: {str(e)}")


# =====================================================
# ENDPOINT PARA OBTENER ASISTENCIA POR PERSONAL
# =====================================================

@router.get("/personal/{personal_id}")
async def get_asistencia_personal(
    personal_id: UUID,
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia", "jefe_area"]))
):
    """Obtener historial de asistencia de un empleado específico"""
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        if not fecha_fin:
            fecha_fin = date.today()
        if not fecha_inicio:
            fecha_inicio = fecha_fin - timedelta(days=30)
        
        inicio = datetime.combine(fecha_inicio, datetime.min.time())
        fin = datetime.combine(fecha_fin, datetime.max.time())
        
        registros = db.query(Asistencia).filter(
            Asistencia.personal_id == personal_id,
            Asistencia.timestamp >= inicio,
            Asistencia.timestamp <= fin
        ).order_by(Asistencia.timestamp.desc()).all()
        
        resultado = []
        for r in registros:
            resultado.append({
                "id": str(r.id),
                "fecha": r.timestamp.date().isoformat(),
                "hora": r.timestamp.time().isoformat(),
                "tipo": r.tipo,
                "tipo_registro": r.tipo_registro,
                "turno": r.turno_codigo
            })
        
        return {
            "personal_id": str(personal_id),
            "personal_nombre": personal.nombre,
            "periodo": {
                "inicio": fecha_inicio.isoformat(),
                "fin": fecha_fin.isoformat()
            },
            "total_registros": len(resultado),
            "registros": resultado
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_asistencia_personal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener historial: {str(e)}")


# =====================================================
# ENDPOINT PARA REPORTE DE ASISTENCIA POR FECHA
# =====================================================

@router.get("/reporte")
async def reporte_asistencia(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    area_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """Generar reporte de asistencia por rango de fechas"""
    try:
        inicio = datetime.combine(fecha_inicio, datetime.min.time())
        fin = datetime.combine(fecha_fin, datetime.max.time())
        
        query = db.query(Asistencia).filter(
            Asistencia.timestamp >= inicio,
            Asistencia.timestamp <= fin
        )
        
        registros = query.all()
        
        estadisticas_por_dia = {}
        for registro in registros:
            fecha_str = registro.timestamp.date().isoformat()
            if fecha_str not in estadisticas_por_dia:
                estadisticas_por_dia[fecha_str] = {
                    "entradas": 0,
                    "salidas": 0,
                    "total": 0
                }
            
            if registro.tipo == "ENTRADA":
                estadisticas_por_dia[fecha_str]["entradas"] += 1
            else:
                estadisticas_por_dia[fecha_str]["salidas"] += 1
            
            estadisticas_por_dia[fecha_str]["total"] += 1
        
        return {
            "periodo": {
                "inicio": fecha_inicio.isoformat(),
                "fin": fecha_fin.isoformat()
            },
            "total_registros": len(registros),
            "estadisticas_por_dia": estadisticas_por_dia
        }
        
    except Exception as e:
        logger.error(f"Error en reporte_asistencia: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al generar reporte: {str(e)}")