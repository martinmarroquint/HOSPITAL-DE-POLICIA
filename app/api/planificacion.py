# api/planificacion.py
# VERSIÓN COMPLETA - CON SOPORTE MULTI-EMPRESA, hora_inicio, hora_fin Y CARGA MASIVA RÁPIDA

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func, text, case
from typing import List, Optional, Dict, Any
from datetime import date, datetime, timedelta, time
from uuid import UUID
import json
import logging

from app.database import get_db
from app.core.dependencies import require_roles, get_current_user, get_current_user_id, get_current_personal_id
from app.models.planificacion import Planificacion
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.models.solicitud_cambio import SolicitudCambio
from app.schemas.planificacion import (
    PlanificacionCreate, PlanificacionResponse, PlanificacionMasiva,
    ObservacionCreate, EstadoPlanificacion
)

router = APIRouter()
logger = logging.getLogger(__name__)

# =====================================================
# 🆕 FUNCIÓN AUXILIAR: FILTRO MULTI-EMPRESA
# =====================================================

def aplicar_filtro_empresa(query, current_user, modelo):
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if hasattr(modelo, 'empresa_id'):
            query = query.filter(modelo.empresa_id == current_user.empresa_id)
    return query


def aplicar_filtro_empresa_personal(query, current_user):
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    return query


def parse_hora(hora_str: Optional[str]) -> Optional[time]:
    """Convierte string HH:MM a objeto time"""
    if not hora_str:
        return None
    try:
        parts = hora_str.strip().split(':')
        return time(int(parts[0]), int(parts[1]))
    except:
        return None


# =====================================================
# 🚀 CACHE EN MEMORIA CON EXPIRACIÓN (5 minutos)
# =====================================================

class PlanificacionCache:
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
        self.default_timeout = 300
    
    def get(self, key: str):
        if key in self._cache and key in self._timestamps:
            if datetime.now() - self._timestamps[key] < timedelta(seconds=self.default_timeout):
                return self._cache[key]
            else:
                del self._cache[key]
                del self._timestamps[key]
        return None
    
    def set(self, key: str, value: Any, timeout: int = None):
        self._cache[key] = value
        self._timestamps[key] = datetime.now()
        if timeout:
            self.default_timeout = timeout
    
    def invalidate(self, key_pattern: str = None):
        if key_pattern:
            keys_to_delete = [k for k in self._cache.keys() if key_pattern in k]
            for key in keys_to_delete:
                del self._cache[key]
                del self._timestamps[key]
        else:
            self._cache.clear()
            self._timestamps.clear()
            logger.info("🧹 Caché de planificación limpiado completamente")
    
    def invalidate_for_mes(self, anio: int, mes: int):
        pattern = f"{anio}-{mes:02d}"
        self.invalidate(pattern)

planificacion_cache = PlanificacionCache()

def get_jefe_area(db: Session, user_id: UUID):
    return db.query(Personal).filter(Personal.id == user_id).first()

# =====================================================
# 🔴 RUTAS ESPECÍFICAS PRIMERO (ORDEN CORRECTO)
# =====================================================

@router.get("/health")
async def health_check():
    return {
        "status": "healthy", "service": "planificacion",
        "timestamp": datetime.utcnow().isoformat(),
        "cache_stats": {
            "size": len(planificacion_cache._cache),
            "keys": list(planificacion_cache._cache.keys())[:5]
        }
    }

# ─── PLANIFICACIÓN DEL DÍA ──────────────────────────
@router.get("/dia/{fecha}")
async def obtener_planificacion_dia(
    fecha: date,
    area: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "oficial_permanencia", "usuario", "visitante"]))
):
    try:
        query = db.query(
            Planificacion.id, Planificacion.personal_id, Planificacion.fecha,
            Planificacion.turno_codigo, Planificacion.hora_inicio, Planificacion.hora_fin,
            Planificacion.observacion, Planificacion.dm_info,
            Personal.nombre.label("personal_nombre"), Personal.grado.label("personal_grado"),
            Personal.area.label("personal_area"), Personal.dni, Personal.cip,
            Personal.especialidad, Personal.condicion
        ).join(Personal, Personal.id == Planificacion.personal_id).filter(Planificacion.fecha == fecha)
        
        query = aplicar_filtro_empresa_personal(query, current_user)
        if area: query = query.filter(Personal.area == area)
        
        roles = current_user.roles or []
        if "usuario" in roles and "admin" not in roles and "jefe_area" not in roles and "visitante" in roles:
            if current_user.personal_id:
                query = query.filter(Planificacion.personal_id == current_user.personal_id)
        elif "jefe_area" in roles and "admin" not in roles:
            jefe = get_jefe_area(db, current_user.personal_id)
            if jefe and jefe.area: query = query.filter(Personal.area == jefe.area)
        
        resultados = query.all()
        
        return [
            {
                "id": str(r.id), "personal_id": str(r.personal_id),
                "fecha": r.fecha.isoformat(), "turno_codigo": r.turno_codigo,
                "hora_inicio": str(r.hora_inicio) if r.hora_inicio else None,
                "hora_fin": str(r.hora_fin) if r.hora_fin else None,
                "observacion": r.observacion, "dm_info": r.dm_info,
                "personal_nombre": r.personal_nombre, "personal_grado": r.personal_grado,
                "personal_area": r.personal_area, "dni": r.dni, "cip": r.cip,
                "especialidad": r.especialidad, "condicion": r.condicion
            } for r in resultados
        ]
    except Exception as e:
        logger.error(f"❌ Error en obtener_planificacion_dia: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# ─── PLANIFICACIÓN POR PERSONAL ─────────────────────
@router.get("/personal/{personal_id}")
async def obtener_planificacion_personal(
    personal_id: UUID,
    inicio: date = Query(..., description="Fecha inicio"),
    fin: date = Query(..., description="Fecha fin"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario", "visitante"]))
):
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        if current_user.empresa_id and current_user.rol_global != "super_admin":
            if personal.empresa_id != current_user.empresa_id:
                raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
        
        roles = current_user.roles or []
        es_visitante = "visitante" in roles
        es_usuario = "usuario" in roles
        es_admin = "admin" in roles
        es_jefe = "jefe_area" in roles
        
        if (es_usuario or es_visitante) and not es_admin and not es_jefe:
            if str(current_user.personal_id) != str(personal_id):
                raise HTTPException(status_code=403, detail="No puede ver planificación de otro personal")
        
        if es_jefe and not es_admin:
            jefe = get_jefe_area(db, current_user.personal_id)
            if not personal or not jefe or personal.area != jefe.area:
                raise HTTPException(status_code=403, detail="No puede ver personal de otra área")
        
        query = db.query(
            Planificacion.fecha, Planificacion.turno_codigo,
            Planificacion.hora_inicio, Planificacion.hora_fin,
            Planificacion.observacion, Planificacion.dm_info
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= inicio, Planificacion.fecha <= fin
        )
        
        planificaciones = query.order_by(Planificacion.fecha).all()
        
        resultado = {}
        for p in planificaciones:
            resultado[p.fecha.isoformat()] = {
                "turno_codigo": p.turno_codigo,
                "hora_inicio": str(p.hora_inicio) if p.hora_inicio else None,
                "hora_fin": str(p.hora_fin) if p.hora_fin else None,
                "observacion": p.observacion,
                "dm_info": p.dm_info
            }
        
        return resultado
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en obtener_planificacion_personal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# ─── PLANIFICACIÓN PÚBLICA ──────────────────────────
@router.get("/publico/personal/{personal_id}")
async def obtener_planificacion_publica_personal(
    personal_id: UUID,
    inicio: date = Query(..., description="Fecha inicio"),
    fin: date = Query(..., description="Fecha fin"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
        if current_user.empresa_id and current_user.rol_global != "super_admin":
            if personal.empresa_id != current_user.empresa_id:
                raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
        
        query = db.query(
            Planificacion.fecha, Planificacion.turno_codigo,
            Planificacion.hora_inicio, Planificacion.hora_fin,
            Planificacion.observacion, Planificacion.dm_info
        ).filter(Planificacion.personal_id == personal_id, Planificacion.fecha >= inicio, Planificacion.fecha <= fin)
        planificaciones = query.order_by(Planificacion.fecha).all()
        
        resultado = {}
        for p in planificaciones:
            resultado[p.fecha.isoformat()] = {
                "turno_codigo": p.turno_codigo,
                "hora_inicio": str(p.hora_inicio) if p.hora_inicio else None,
                "hora_fin": str(p.hora_fin) if p.hora_fin else None,
                "observacion": p.observacion, "dm_info": p.dm_info
            }
        return resultado
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Error en obtener_planificacion_publica_personal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# ─── MI HORARIO PERSONAL ────────────────────────────
@router.get("/mi-horario/{anio}/{mes}")
async def get_mi_horario(
    anio: int, mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    try:
        if mes < 1 or mes > 12: raise HTTPException(status_code=400, detail="Mes inválido")
        personal_id = current_user.personal_id
        if not personal_id: raise HTTPException(status_code=404, detail="Usuario no tiene personal asociado")
        
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        query = db.query(
            Planificacion.fecha, Planificacion.turno_codigo,
            Planificacion.hora_inicio, Planificacion.hora_fin, Planificacion.dm_info
        ).filter(Planificacion.personal_id == personal_id, Planificacion.fecha >= fecha_inicio, Planificacion.fecha < fecha_fin)
        planificaciones = query.order_by(Planificacion.fecha).all()
        
        return [{
            "fecha": p.fecha.isoformat(), "turno_codigo": p.turno_codigo,
            "hora_inicio": str(p.hora_inicio) if p.hora_inicio else None,
            "hora_fin": str(p.hora_fin) if p.hora_fin else None,
            "dm_info": p.dm_info
        } for p in planificaciones]
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Error en get_mi_horario: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# ─── MIS ESTADÍSTICAS ───────────────────────────────
@router.get("/mi-horario/{anio}/{mes}/estadisticas")
async def get_mi_estadisticas(
    anio: int, mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    try:
        personal_id = current_user.personal_id
        if not personal_id: raise HTTPException(status_code=404, detail="Usuario no tiene personal asociado")
        
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        stats_query = db.query(Planificacion.turno_codigo, func.count(Planificacion.id).label('cantidad')).filter(
            Planificacion.personal_id == personal_id, Planificacion.fecha >= fecha_inicio, Planificacion.fecha < fecha_fin
        )
        stats = stats_query.group_by(Planificacion.turno_codigo).all()
        turnos_por_tipo = {s.turno_codigo: s.cantidad for s in stats}
        
        return {
            "total_turnos": sum(turnos_por_tipo.values()),
            "descansos": turnos_por_tipo.get('FR', 0),
            "guardias": turnos_por_tipo.get('12M', 0) + turnos_por_tipo.get('12N', 0),
            "turnos_por_tipo": turnos_por_tipo, "mes": mes, "anio": anio
        }
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Error en get_mi_estadisticas: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# ─── BORRADOR ÁREA ──────────────────────────────────
@router.get("/area/borrador/{anio}/{mes}")
async def obtener_borrador_area(
    anio: int, mes: int,
    area: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["jefe_area"]))
):
    try:
        jefe = db.query(Personal.id, Personal.area).filter(Personal.id == current_user.personal_id).first()
        if not jefe: raise HTTPException(status_code=404, detail="Jefe no encontrado")
        
        area_consulta = area if area else jefe.area
        fecha_referencia = date(anio, mes, 1)
        cache_key = f"borrador_{area_consulta}_{anio}_{mes}_{current_user.personal_id}"
        cached = planificacion_cache.get(cache_key)
        if cached: return cached
        
        solicitud = db.query(
            SolicitudCambio.id, SolicitudCambio.estado, SolicitudCambio.turno_original,
            SolicitudCambio.created_at, SolicitudCambio.comentario_revision
        ).filter(
            SolicitudCambio.tipo == "planificacion_mensual",
            SolicitudCambio.empleado_id == current_user.personal_id,
            SolicitudCambio.fecha_cambio == fecha_referencia
        ).order_by(
            case((SolicitudCambio.estado == 'pendiente', 1), (SolicitudCambio.estado == 'rechazada', 2),
                 (SolicitudCambio.estado == 'aprobada', 3), else_=4), SolicitudCambio.created_at.desc()
        ).first()
        
        if not solicitud:
            result = {"existe": False, "datos": [], "estado": "borrador", "area": area_consulta, "mes": mes, "anio": anio}
            planificacion_cache.set(cache_key, result, timeout=60)
            return result
        
        datos_array = []
        if solicitud.turno_original:
            if isinstance(solicitud.turno_original, list): datos_array = solicitud.turno_original
            elif isinstance(solicitud.turno_original, dict) and 'datos' in solicitud.turno_original: datos_array = solicitud.turno_original['datos']
        
        result = {
            "existe": True, "id": str(solicitud.id), "estado": solicitud.estado,
            "datos": datos_array, "fecha_creacion": solicitud.created_at.isoformat() if solicitud.created_at else None,
            "area": area_consulta, "mes": mes, "anio": anio, "comentario_revision": solicitud.comentario_revision
        }
        planificacion_cache.set(cache_key, result, timeout=300)
        return result
    except Exception as e:
        logger.error(f"❌ Error en obtener_borrador_area: {str(e)}")
        return {"existe": False, "datos": [], "estado": "borrador", "area": area if area else "unknown", "mes": mes, "anio": anio, "error": str(e)}

# ─── ESTADO MENSUAL ─────────────────────────────────
@router.get("/{anio}/{mes}/estado")
async def obtener_estado_mensual(
    anio: int, mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    try:
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        stats_query = db.query(Planificacion.turno_codigo, func.count(Planificacion.id).label('cantidad')).filter(
            Planificacion.fecha >= fecha_inicio, Planificacion.fecha < fecha_fin
        )
        stats_query = aplicar_filtro_empresa(stats_query, current_user, Planificacion)
        stats = stats_query.group_by(Planificacion.turno_codigo).all()
        
        obs_query = db.query(
            Planificacion.personal_id, Planificacion.fecha, Planificacion.observacion,
            Personal.nombre.label("personal_nombre")
        ).join(Personal, Personal.id == Planificacion.personal_id).filter(
            Planificacion.fecha >= fecha_inicio, Planificacion.fecha < fecha_fin,
            Planificacion.observacion.isnot(None)
        )
        obs_query = aplicar_filtro_empresa_personal(obs_query, current_user)
        observaciones = obs_query.all()
        
        return {
            "fecha": fecha_inicio.isoformat(), "total_turnos": sum({s.turno_codigo: s.cantidad for s in stats}.values()),
            "turnos_por_tipo": {s.turno_codigo: s.cantidad for s in stats},
            "personal_con_observaciones": [
                {"personal_id": str(o.personal_id), "nombre": o.personal_nombre,
                 "fecha": o.fecha.isoformat(), "observacion": o.observacion} for o in observaciones
            ]
        }
    except Exception as e:
        logger.error(f"❌ Error en obtener_estado_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# ─── PLANIFICACIÓN MENSUAL ──────────────────────────
@router.get("/{anio}/{mes}")
async def obtener_planificacion_mensual(
    anio: int, mes: int,
    area: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    if mes < 1 or mes > 12: raise HTTPException(status_code=400, detail="Mes inválido")
    try:
        area_value = area if area else "todas"
        cache_key = f"{anio}-{mes:02d}-{area_value}-{str(current_user.id)}"
        cached_result = planificacion_cache.get(cache_key)
        if cached_result is not None: return cached_result
        
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        query = db.query(
            Planificacion.personal_id, Planificacion.fecha, Planificacion.turno_codigo,
            Planificacion.hora_inicio, Planificacion.hora_fin,
            Planificacion.observacion, Planificacion.dm_info,
            Personal.nombre.label("personal_nombre"), Personal.grado.label("personal_grado"),
            Personal.area.label("personal_area"), Personal.dni, Personal.cip,
            Personal.especialidad, Personal.condicion
        ).join(Personal, Personal.id == Planificacion.personal_id).filter(
            Planificacion.fecha >= fecha_inicio, Planificacion.fecha < fecha_fin
        )
        
        query = aplicar_filtro_empresa_personal(query, current_user)
        if area: query = query.filter(Personal.area == area)
        if "jefe_area" in current_user.roles and "admin" not in current_user.roles:
            jefe = get_jefe_area(db, current_user.personal_id)
            if jefe and jefe.area: query = query.filter(Personal.area == jefe.area)
            else: return []
        
        resultados = query.all()
        result = [{
            "personal_id": str(r.personal_id), "fecha": r.fecha.isoformat(),
            "turno_codigo": r.turno_codigo,
            "hora_inicio": str(r.hora_inicio) if r.hora_inicio else None,
            "hora_fin": str(r.hora_fin) if r.hora_fin else None,
            "observacion": r.observacion, "dm_info": r.dm_info,
            "personal_nombre": r.personal_nombre, "personal_grado": r.personal_grado,
            "personal_area": r.personal_area, "dni": r.dni, "cip": r.cip,
            "especialidad": r.especialidad, "condicion": r.condicion
        } for r in resultados]
        
        planificacion_cache.set(cache_key, result)
        return result
    except Exception as e:
        logger.error(f"❌ Error en obtener_planificacion_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# =====================================================
# ENDPOINTS POST, PUT, DELETE
# =====================================================

@router.post("/turno")
async def crear_turno(
    turno_data: PlanificacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    try:
        personal = db.query(Personal).filter(Personal.id == turno_data.personal_id).first()
        if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
        if current_user.empresa_id and current_user.rol_global != "super_admin":
            if personal.empresa_id != current_user.empresa_id:
                raise HTTPException(status_code=403, detail="Este personal no pertenece a su empresa")
        
        existente = db.query(Planificacion).filter(
            Planificacion.personal_id == turno_data.personal_id, Planificacion.fecha == turno_data.fecha
        ).first()
        
        if existente:
            existente.turno_codigo = turno_data.turno_codigo
            existente.hora_inicio = parse_hora(turno_data.hora_inicio)
            existente.hora_fin = parse_hora(turno_data.hora_fin)
            existente.observacion = turno_data.observacion
            existente.dm_info = turno_data.dm_info
            existente.updated_at = datetime.utcnow()
            existente.created_by = current_user.id
            db.commit()
            planificacion_cache.invalidate_for_mes(turno_data.fecha.year, turno_data.fecha.month)
            return {
                "id": str(existente.id), "personal_id": str(existente.personal_id),
                "fecha": existente.fecha.isoformat(), "turno_codigo": existente.turno_codigo,
                "hora_inicio": str(existente.hora_inicio) if existente.hora_inicio else None,
                "hora_fin": str(existente.hora_fin) if existente.hora_fin else None,
                "observacion": existente.observacion, "dm_info": existente.dm_info,
                "personal_nombre": personal.nombre
            }
        else:
            turno = Planificacion(
                personal_id=turno_data.personal_id, fecha=turno_data.fecha,
                turno_codigo=turno_data.turno_codigo,
                hora_inicio=parse_hora(turno_data.hora_inicio),
                hora_fin=parse_hora(turno_data.hora_fin),
                observacion=turno_data.observacion,
                dm_info=turno_data.dm_info, created_by=current_user.id
            )
            db.add(turno); db.commit(); db.refresh(turno)
            planificacion_cache.invalidate_for_mes(turno_data.fecha.year, turno_data.fecha.month)
            return {
                "id": str(turno.id), "personal_id": str(turno.personal_id),
                "fecha": turno.fecha.isoformat(), "turno_codigo": turno.turno_codigo,
                "hora_inicio": str(turno.hora_inicio) if turno.hora_inicio else None,
                "hora_fin": str(turno.hora_fin) if turno.hora_fin else None,
                "observacion": turno.observacion, "dm_info": turno.dm_info,
                "personal_nombre": personal.nombre
            }
    except Exception as e:
        logger.error(f"❌ Error en crear_turno: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

# =====================================================
# 🚀 NUEVO: CARGA MASIVA ULTRARRÁPIDA
# =====================================================

@router.post("/carga-masiva")
async def carga_masiva_turnos(
    asignaciones: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente", "jefe_area"]))
):
    """
    Carga masiva de turnos ultrarrápida.
    Recibe una lista de asignaciones y las procesa en una sola transacción.
    
    Formato: [
        {"personal_id": "uuid", "fecha": "2024-01-15", "turno_codigo": "M1"},
        ...
    ]
    """
    if not asignaciones:
        raise HTTPException(status_code=400, detail="No se recibieron datos")
    
    try:
        # Extraer todas las fechas y personal_ids únicos
        fechas = list(set(a["fecha"] for a in asignaciones))
        personal_ids = list(set(UUID(a["personal_id"]) for a in asignaciones))
        
        # 1. Obtener todos los registros existentes en UNA SOLA consulta
        existentes = db.query(Planificacion).filter(
            Planificacion.personal_id.in_(personal_ids),
            Planificacion.fecha.in_(fechas)
        ).all()
        
        # 2. Crear un mapa para búsqueda rápida O(1)
        existentes_map = {}
        for e in existentes:
            key = (str(e.personal_id), e.fecha.isoformat())
            existentes_map[key] = e
        
        # 3. Preparar lotes para inserción/actualización
        creados = 0
        actualizados = 0
        nuevos_registros = []
        meses_afectados = set()
        
        for asignacion in asignaciones:
            personal_id = UUID(asignacion["personal_id"])
            fecha_str = asignacion["fecha"]
            turno_codigo = asignacion.get("turno_codigo")
            
            # Parsear fecha
            fecha = date.fromisoformat(fecha_str)
            meses_afectados.add((fecha.year, fecha.month))
            
            key = (str(personal_id), fecha_str)
            
            if key in existentes_map:
                # Actualizar existente
                existente = existentes_map[key]
                existente.turno_codigo = turno_codigo
                existente.updated_at = datetime.utcnow()
                existente.created_by = current_user.id
                actualizados += 1
            else:
                # Nuevo registro
                nuevos_registros.append({
                    "personal_id": personal_id,
                    "fecha": fecha,
                    "turno_codigo": turno_codigo,
                    "created_by": current_user.id
                })
                creados += 1
        
        # 4. Insertar todos los nuevos en UNA SOLA operación
        if nuevos_registros:
            # Usar inserción masiva nativa de SQLAlchemy
            db.execute(
                Planificacion.__table__.insert(),
                nuevos_registros
            )
        
        # 5. Commit único
        db.commit()
        
        # 6. Invalidar caché para los meses afectados
        for anio, mes in meses_afectados:
            planificacion_cache.invalidate_for_mes(anio, mes)
        
        logger.info(f"🚀 Carga masiva completada: {creados} creados, {actualizados} actualizados en {len(meses_afectados)} meses")
        
        return {
            "message": "Carga masiva completada exitosamente",
            "creados": creados,
            "actualizados": actualizados,
            "total": creados + actualizados,
            "meses_afectados": len(meses_afectados),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error en carga_masiva_turnos: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error en carga masiva: {str(e)}")

# =====================================================
# RESTO DE ENDPOINTS (sin cambios)
# =====================================================

@router.post("/masivo")
async def crear_planificacion_masiva(
    data: PlanificacionMasiva,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    try:
        creados, actualizados, errores = 0, 0, []
        meses_afectados = set()
        fechas = [t.fecha for t in data.planificaciones]
        personal_ids = [t.personal_id for t in data.planificaciones]
        existentes = db.query(Planificacion).filter(
            Planificacion.personal_id.in_(personal_ids), Planificacion.fecha.in_(fechas)
        ).all()
        existentes_map = {(str(p.personal_id), p.fecha.isoformat()): p for p in existentes}
        
        for turno_data in data.planificaciones:
            try:
                key = (str(turno_data.personal_id), turno_data.fecha.isoformat())
                existente = existentes_map.get(key)
                if existente:
                    existente.turno_codigo = turno_data.turno_codigo
                    existente.hora_inicio = parse_hora(turno_data.hora_inicio)
                    existente.hora_fin = parse_hora(turno_data.hora_fin)
                    existente.observacion = turno_data.observacion
                    existente.dm_info = turno_data.dm_info
                    existente.updated_at = datetime.utcnow()
                    existente.created_by = current_user.id
                    actualizados += 1
                else:
                    nuevo = Planificacion(
                        personal_id=turno_data.personal_id, fecha=turno_data.fecha,
                        turno_codigo=turno_data.turno_codigo,
                        hora_inicio=parse_hora(turno_data.hora_inicio),
                        hora_fin=parse_hora(turno_data.hora_fin),
                        observacion=turno_data.observacion,
                        dm_info=turno_data.dm_info, created_by=current_user.id
                    )
                    db.add(nuevo); creados += 1
                meses_afectados.add((turno_data.fecha.year, turno_data.fecha.month))
            except Exception as e:
                errores.append({"personal_id": str(turno_data.personal_id), "fecha": turno_data.fecha.isoformat(), "error": str(e)})
        
        db.commit()
        for anio, mes in meses_afectados: planificacion_cache.invalidate_for_mes(anio, mes)
        return {"message": "Planificación guardada exitosamente", "creados": creados, "actualizados": actualizados, "errores": errores if errores else None}
    except Exception as e:
        logger.error(f"❌ Error en crear_planificacion_masiva: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.post("/observacion")
async def agregar_observacion(obs_data: ObservacionCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))):
    try:
        planificacion = db.query(Planificacion).filter(Planificacion.personal_id == obs_data.personal_id, Planificacion.fecha == obs_data.fecha).first()
        if not planificacion: raise HTTPException(status_code=404, detail="Turno no encontrado")
        planificacion.observacion = obs_data.observacion
        planificacion.updated_at = datetime.utcnow()
        db.commit()
        planificacion_cache.invalidate_for_mes(obs_data.fecha.year, obs_data.fecha.month)
        return {"message": "Observación agregada exitosamente"}
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Error en agregar_observacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.delete("/observacion/{key}")
async def eliminar_observacion(key: str, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))):
    try:
        parts = key.split('_')
        if len(parts) != 2: raise ValueError("Formato inválido")
        personal_id = UUID(parts[0]); fecha = date.fromisoformat(parts[1])
        planificacion = db.query(Planificacion).filter(Planificacion.personal_id == personal_id, Planificacion.fecha == fecha).first()
        if not planificacion: raise HTTPException(status_code=404, detail="Turno no encontrado")
        planificacion.observacion = None; planificacion.updated_at = datetime.utcnow()
        db.commit()
        planificacion_cache.invalidate_for_mes(fecha.year, fecha.month)
        return {"message": "Observación eliminada exitosamente"}
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Error en eliminar_observacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.post("/area/borrador")
async def guardar_borrador_area(area: str, mes: int, anio: int, datos: Dict, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["jefe_area"]))):
    try:
        jefe = db.query(Personal.id, Personal.area).filter(Personal.id == current_user.personal_id).first()
        if not jefe or jefe.area != area: raise HTTPException(status_code=403, detail="No eres jefe de esta área")
        if mes < 1 or mes > 12: raise HTTPException(status_code=400, detail="Mes inválido")
        fecha_referencia = date(anio, mes, 1)
        solicitud_existente = db.query(SolicitudCambio).filter(
            SolicitudCambio.tipo == "planificacion_mensual", SolicitudCambio.empleado_id == current_user.personal_id,
            SolicitudCambio.fecha_cambio == fecha_referencia
        ).first()
        datos_array = datos['datos'] if isinstance(datos, dict) and 'datos' in datos else datos
        
        if solicitud_existente:
            solicitud_existente.turno_original = datos_array; solicitud_existente.estado = "borrador"
            if hasattr(solicitud_existente, 'updated_at'): solicitud_existente.updated_at = datetime.utcnow()
            if not solicitud_existente.historial: solicitud_existente.historial = []
            solicitud_existente.historial.append({"fecha": datetime.utcnow().isoformat(), "usuario": str(current_user.id), "accion": "actualización_borrador", "estado": "borrador", "registros": len(datos_array)})
            db.commit()
            return {"message": "Borrador actualizado exitosamente", "id": str(solicitud_existente.id), "estado": solicitud_existente.estado, "registros": len(datos_array)}
        else:
            nueva_solicitud = SolicitudCambio(tipo="planificacion_mensual", estado="borrador", fecha_cambio=fecha_referencia, motivo="ENVIO_MENSUAL", empleado_id=current_user.personal_id, turno_original=datos_array, historial=[{"fecha": datetime.utcnow().isoformat(), "usuario": str(current_user.id), "accion": "creación_borrador", "estado": "borrador", "registros": len(datos_array)}], created_by=current_user.id)
            db.add(nueva_solicitud); db.commit(); db.refresh(nueva_solicitud)
            return {"message": "Borrador creado exitosamente", "id": str(nueva_solicitud.id), "estado": nueva_solicitud.estado, "registros": len(datos_array)}
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Error en guardar_borrador_area: {str(e)}")
        db.rollback(); raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.post("/area/enviar-revision")
async def enviar_planificacion_revision(area: str, mes: int, anio: int, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["jefe_area"]))):
    try:
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if not jefe or jefe.area != area: raise HTTPException(status_code=403, detail="No eres jefe de esta área")
        fecha_referencia = date(anio, mes, 1)
        solicitud = db.query(SolicitudCambio).filter(SolicitudCambio.tipo == "planificacion_mensual", SolicitudCambio.empleado_id == current_user.personal_id, SolicitudCambio.fecha_cambio == fecha_referencia, SolicitudCambio.estado == "borrador").first()
        if not solicitud: raise HTTPException(status_code=404, detail="No hay borrador para enviar")
        solicitud.estado = "pendiente"
        if not solicitud.historial: solicitud.historial = []
        solicitud.historial.append({"fecha": datetime.utcnow().isoformat(), "usuario": str(current_user.id), "accion": "envío_a_revisión", "estado": "pendiente"})
        db.commit()
        return {"message": "Planificación enviada a revisión exitosamente", "id": str(solicitud.id), "estado": solicitud.estado}
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Error en enviar_planificacion_revision: {str(e)}")
        db.rollback(); raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.delete("/{planificacion_id}", status_code=204)
async def eliminar_planificacion(planificacion_id: UUID, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin"]))):
    try:
        planificacion = db.query(Planificacion).filter(Planificacion.id == planificacion_id).first()
        if not planificacion: raise HTTPException(status_code=404, detail="Planificación no encontrada")
        fecha = planificacion.fecha
        db.delete(planificacion); db.commit()
        planificacion_cache.invalidate_for_mes(fecha.year, fecha.month)
        return None
    except HTTPException: raise
    except Exception as e:
        logger.error(f"❌ Error en eliminar_planificacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")

@router.delete("/personal/{personal_id}/mes/{anio}/{mes}", status_code=204)
async def eliminar_planificacion_mensual(personal_id: UUID, anio: int, mes: int, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin"]))):
    try:
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        db.query(Planificacion).filter(Planificacion.personal_id == personal_id, Planificacion.fecha >= fecha_inicio, Planificacion.fecha < fecha_fin).delete(synchronize_session=False)
        db.commit()
        planificacion_cache.invalidate_for_mes(anio, mes)
        return None
    except Exception as e:
        logger.error(f"❌ Error en eliminar_planificacion_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")