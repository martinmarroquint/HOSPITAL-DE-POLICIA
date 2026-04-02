# app/api/asistencia.py - VERSIÓN COMPLETA CORREGIDA (ZONA HORARIA CONSISTENTE)
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body
from fastapi.responses import Response, JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, date, timedelta, timezone as tz
from uuid import UUID
import json
import base64
import logging

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

router = APIRouter()

# =====================================================
# 🆕 MANEJADOR OPTIONS GLOBAL PARA CORS (preflight)
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
# 🆕 HEALTH CHECK CORREGIDO
# =====================================================

@router.get("/health")
async def health_check():
    """
    Health check endpoint para monitoreo del sistema
    """
    try:
        # Verificar conexión a base de datos
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
                "timestamp": datetime.utcnow().isoformat(),
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
                "timestamp": datetime.utcnow().isoformat()
            }
        )

# =====================================================
# 🆕 ENDPOINT SIMPLE PARA REGISTROS DE HOY
# =====================================================

@router.get("/registros-hoy")
async def registros_hoy(
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia", "jefe_area"]))
):
    """
    Endpoint SIMPLE para obtener registros de hoy
    """
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
                "controlador": controlador_nombre
            })
        
        return resultado
        
    except Exception as e:
        logger.error(f"Error en registros_hoy: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener registros: {str(e)}")

# =====================================================
# 🆕 ENDPOINT ESTADÍSTICAS DE ASISTENCIA
# =====================================================

@router.get("/estadisticas")
async def get_estadisticas(
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """
    Obtener estadísticas de asistencia para una fecha específica
    """
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
# 🆕 ENDPOINT PERSONAL ACTIVO EN EL HOSPITAL
# =====================================================

@router.get("/activos")
async def get_personal_activo(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """
    Obtener personal actualmente en el hospital
    """
    try:
        hoy = date.today()
        
        inicio_dia = datetime.combine(hoy, datetime.min.time()).replace(tzinfo=tz.utc)
        fin_dia = datetime.combine(hoy, datetime.max.time()).replace(tzinfo=tz.utc)
        ahora_utc = datetime.utcnow().replace(tzinfo=tz.utc)
        
        entradas_hoy = db.query(Asistencia).filter(
            Asistencia.tipo == "ENTRADA",
            Asistencia.timestamp >= inicio_dia,
            Asistencia.timestamp <= fin_dia
        ).all()
        
        activos = []
        for entrada in entradas_hoy:
            if entrada.timestamp.tzinfo is None:
                entrada_timestamp = entrada.timestamp.replace(tzinfo=tz.utc)
            else:
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
                    diferencia = ahora_utc - entrada_timestamp
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
            "hora_consulta": ahora_utc.isoformat()
        }
        
    except Exception as e:
        logger.error(f"Error en /activos: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener personal activo: {str(e)}")

# =====================================================
# 🆕 ENDPOINT QR DE ASISTENCIA - VERSIÓN CORREGIDA
# =====================================================

@router.post("/qr-validar")
async def validar_qr_asistencia(
    qr_data: str = Body(...),
    tipo: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "oficial_permanencia", "control_qr"]))
):
    """
    Valida QR de asistencia generado por /qr/generar
    """
    try:
        decoded_str = base64.b64decode(qr_data).decode('utf-8')
        data = json.loads(decoded_str)
        
        empleado_id = data.get("empleado_id")
        if not empleado_id:
            raise HTTPException(status_code=400, detail="QR no contiene empleado_id")
        
        # Verificar expiración - manejo consistente de zona horaria
        expira_en = datetime.fromisoformat(data.get("expira_en"))
        ahora_utc = datetime.utcnow().replace(tzinfo=tz.utc)
        
        if expira_en.tzinfo is None:
            expira_en = expira_en.replace(tzinfo=tz.utc)
        
        if ahora_utc > expira_en:
            raise HTTPException(status_code=400, detail="QR_EXPIRADO")
        
        personal = db.query(Personal).filter(Personal.id == empleado_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")
        
        hoy = date.today()
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == empleado_id,
            Planificacion.fecha == hoy
        ).first()
        
        if not planificacion:
            raise HTTPException(status_code=400, detail="SIN_TURNO - No tiene turno asignado para hoy")
        
        inicio_dia = datetime.combine(hoy, datetime.min.time()).replace(tzinfo=tz.utc)
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
        
        asistencia = Asistencia(
            personal_id=empleado_id,
            timestamp=datetime.utcnow(),
            tipo=tipo,
            tipo_registro="QR",
            turno_codigo=planificacion.turno_codigo,
            created_by=current_user.id
        )
        
        db.add(asistencia)
        db.commit()
        db.refresh(asistencia)
        
        qr_registro = db.query(QRRegistro).filter(
            QRRegistro.qr_id == data.get("qr_id")
        ).first()
        if qr_registro:
            qr_registro.usado = True
            qr_registro.usado_en = datetime.utcnow()
            qr_registro.usado_por = current_user.id
            db.commit()
        
        return {
            "valido": True,
            "empleado_id": str(empleado_id),
            "empleado_nombre": personal.nombre,
            "tipo": tipo,
            "timestamp": asistencia.timestamp.isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en qr-validar: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))

# =====================================================
# 🆕 ENDPOINT DIRECTO PARA PRUEBAS
# =====================================================

@router.post("/registro-directo")
async def registro_directo(
    personal_id: UUID = Body(...),
    tipo: str = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """
    Registro directo de asistencia - SIN QR
    """
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
        
        inicio_dia = datetime.combine(hoy, datetime.min.time()).replace(tzinfo=tz.utc)
        ultimo = db.query(Asistencia).filter(
            Asistencia.personal_id == personal_id,
            Asistencia.timestamp >= inicio_dia
        ).order_by(Asistencia.timestamp.desc()).first()
        
        if ultimo and ultimo.tipo == "ENTRADA" and tipo != "SALIDA":
            raise HTTPException(status_code=400, detail="Debe registrar SALIDA primero")
        
        if not ultimo and tipo != "ENTRADA":
            raise HTTPException(status_code=400, detail="Debe registrar ENTRADA primero")
        
        asistencia = Asistencia(
            personal_id=personal_id,
            timestamp=datetime.utcnow(),
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
            "mensaje": f"Asistencia {tipo} registrada para {personal.nombre}",
            "fecha": asistencia.timestamp.isoformat(),
            "tipo": tipo,
            "personal_id": str(personal_id)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en registro-directo: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al registrar asistencia: {str(e)}")

# =====================================================
# 🆕 ENDPOINT PARA REGISTRO MANUAL DE ASISTENCIA
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
    """
    Registro manual de asistencia con justificación
    """
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        if tipo not in ["ENTRADA", "SALIDA"]:
            raise HTTPException(status_code=400, detail="Tipo debe ser ENTRADA o SALIDA")
        
        timestamp = fecha_registro or datetime.utcnow()
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=tz.utc)
            
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
            "mensaje": f"Asistencia {tipo} registrada manualmente para {personal.nombre}",
            "fecha": asistencia.timestamp.isoformat(),
            "tipo": tipo,
            "personal_id": str(personal_id),
            "justificacion": justificacion
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en registro-manual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al registrar asistencia manual: {str(e)}")

# =====================================================
# 🆕 ENDPOINT PARA OBTENER ASISTENCIA POR PERSONAL
# =====================================================

@router.get("/personal/{personal_id}")
async def get_asistencia_personal(
    personal_id: UUID,
    fecha_inicio: Optional[date] = Query(None),
    fecha_fin: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia", "jefe_area"]))
):
    """
    Obtener historial de asistencia de un empleado específico
    """
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
# 🆕 ENDPOINT PARA REPORTE DE ASISTENCIA POR FECHA
# =====================================================

@router.get("/reporte")
async def reporte_asistencia(
    fecha_inicio: date = Query(...),
    fecha_fin: date = Query(...),
    area_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "oficial_permanencia"]))
):
    """
    Generar reporte de asistencia por rango de fechas
    """
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