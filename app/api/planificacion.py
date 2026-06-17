# api/planificacion.py
# VERSION COMPLETA - SOPORTE MULTI-JEFATURA CORREGIDO + ROLES + METAS + ROTACIONES

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
from app.models.meta_cumplimiento import MetaCumplimiento
from app.schemas.planificacion import (
    PlanificacionCreate, PlanificacionResponse, PlanificacionMasiva,
    ObservacionCreate, EstadoPlanificacion
)

router = APIRouter()
logger = logging.getLogger(__name__)

# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def aplicar_filtro_empresa(query, current_user, modelo):
    """Filtra por empresa si el usuario no es super_admin."""
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if hasattr(modelo, 'empresa_id'):
            query = query.filter(modelo.empresa_id == current_user.empresa_id)
    return query


def aplicar_filtro_empresa_personal(query, current_user):
    """Filtra por empresa en la tabla Personal."""
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    return query


def parse_hora(hora_str: Optional[str]) -> Optional[time]:
    """Convierte string HH:MM a objeto time."""
    if not hora_str:
        return None
    try:
        parts = hora_str.strip().split(':')
        return time(int(parts[0]), int(parts[1]))
    except:
        return None


def get_areas_jefatura(db: Session, personal_id: UUID) -> List[str]:
    """
    Obtiene todas las areas donde un jefe tiene autoridad.
    Soporta jefes con multiples areas de jefatura.
    
    Args:
        db: Sesion de base de datos
        personal_id: ID del personal (jefe)
    
    Returns:
        Lista de nombres de areas donde el jefe tiene autoridad
    """
    jefe = db.query(Personal).filter(Personal.id == personal_id).first()
    if not jefe:
        return []
    
    areas = []
    
    # 1. Area directa del jefe (donde trabaja)
    if jefe.area and jefe.area not in areas:
        areas.append(jefe.area)
    
    # 2. Areas de jefatura (puede tener multiples)
    if jefe.areas_que_jefatura:
        for item in jefe.areas_que_jefatura:
            if isinstance(item, str):
                if ':' in item:
                    # Formato: "prefijo:Nombre del Area"
                    area_nombre = item.split(':', 1)[1].strip()
                    if area_nombre and area_nombre not in areas:
                        areas.append(area_nombre)
                else:
                    # Formato simple: "Nombre del Area"
                    if item not in areas:
                        areas.append(item)
    
    return areas


# =====================================================
# CACHE EN MEMORIA CON EXPIRACION (5 minutos)
# =====================================================

class PlanificacionCache:
    """Cache en memoria con expiracion para planificaciones."""
    
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
        self.default_timeout = 300  # 5 minutos
    
    def get(self, key: str):
        """Obtiene un valor del cache si no ha expirado."""
        if key in self._cache and key in self._timestamps:
            if datetime.now() - self._timestamps[key] < timedelta(seconds=self.default_timeout):
                return self._cache[key]
            else:
                del self._cache[key]
                del self._timestamps[key]
        return None
    
    def set(self, key: str, value: Any, timeout: int = None):
        """Guarda un valor en el cache."""
        self._cache[key] = value
        self._timestamps[key] = datetime.now()
        if timeout:
            self.default_timeout = timeout
    
    def invalidate(self, key_pattern: str = None):
        """Invalida el cache por patron de clave."""
        if key_pattern:
            keys_to_delete = [k for k in self._cache.keys() if key_pattern in k]
            for key in keys_to_delete:
                del self._cache[key]
                del self._timestamps[key]
        else:
            self._cache.clear()
            self._timestamps.clear()
    
    def invalidate_for_mes(self, anio: int, mes: int):
        """Invalida el cache para un mes especifico."""
        pattern = f"{anio}-{mes:02d}"
        self.invalidate(pattern)


planificacion_cache = PlanificacionCache()


# =====================================================
# ENDPOINTS
# =====================================================

@router.get("/health")
async def health_check():
    """Endpoint de salud del servicio."""
    return {
        "status": "healthy",
        "service": "planificacion",
        "timestamp": datetime.utcnow().isoformat()
    }


# =====================================================
# EXCEPCIONES
# =====================================================

@router.get("/excepciones")
async def obtener_excepciones(
    fecha: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene las excepciones de planificacion para una fecha especifica.
    Busca: solicitudes de cambio aprobadas (vacaciones, suspensiones, feriados)
    y descansos medicos activos para esa fecha.
    """
    try:
        excepciones = []
        
        # 1. Buscar solicitudes de cambio aprobadas para esa fecha
        solicitudes = db.query(SolicitudCambio).filter(
            SolicitudCambio.fecha_cambio == fecha,
            SolicitudCambio.estado.in_(['aprobada', 'aprobado'])
        ).all()
        
        for sol in solicitudes:
            personal = db.query(Personal).filter(Personal.id == sol.empleado_id).first()
            excepciones.append({
                "id": str(sol.id),
                "personal_id": str(sol.empleado_id),
                "personal_nombre": personal.nombre if personal else "Desconocido",
                "tipo": sol.tipo or "CAMBIO",
                "motivo": sol.motivo,
                "fecha": fecha.isoformat(),
                "turno_original": sol.turno_original,
                "turno_solicitado": sol.turno_solicitado if hasattr(sol, 'turno_solicitado') else None,
            })
        
        # 2. Buscar descansos medicos activos para esa fecha
        from app.models.descanso_medico import DescansoMedico
        
        dms = db.query(DescansoMedico).filter(
            DescansoMedico.fecha_inicio <= fecha,
            DescansoMedico.fecha_fin >= fecha,
            DescansoMedico.estado == 'aprobado'
        ).all()
        
        for dm in dms:
            personal = db.query(Personal).filter(Personal.id == dm.paciente_id).first()
            excepciones.append({
                "id": str(dm.id),
                "personal_id": str(dm.paciente_id),
                "personal_nombre": personal.nombre if personal else "Desconocido",
                "tipo": "DM",
                "motivo": dm.diagnostico or "Descanso medico",
                "fecha": fecha.isoformat(),
                "fecha_inicio": dm.fecha_inicio.isoformat(),
                "fecha_fin": dm.fecha_fin.isoformat(),
            })
        
        return {
            "fecha": fecha.isoformat(),
            "total": len(excepciones),
            "excepciones": excepciones
        }
    except Exception as e:
        logger.error(f"Error en obtener_excepciones: {str(e)}")
        return {
            "fecha": fecha.isoformat(),
            "total": 0,
            "excepciones": []
        }


# =====================================================
# PLANIFICACION DIARIA
# =====================================================

@router.get("/dia/{fecha}")
async def obtener_planificacion_dia(
    fecha: date,
    area: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe", "usuario", "visitante", "escaner"]))
):
    """
    Obtiene la planificacion de un dia especifico.
    Soporta filtro por area y roles.
    """
    try:
        query = db.query(
            Planificacion.id,
            Planificacion.personal_id,
            Planificacion.fecha,
            Planificacion.turno_codigo,
            Planificacion.hora_inicio,
            Planificacion.hora_fin,
            Planificacion.observacion,
            Planificacion.dm_info,
            Personal.nombre.label("personal_nombre"),
            Personal.grado.label("personal_grado"),
            Personal.area.label("personal_area"),
            Personal.dni,
            Personal.cip,
            Personal.especialidad,
            Personal.condicion
        ).join(
            Personal, Personal.id == Planificacion.personal_id
        ).filter(
            Planificacion.fecha == fecha
        )
        
        query = aplicar_filtro_empresa_personal(query, current_user)
        
        if area:
            query = query.filter(Personal.area == area)
        
        roles = current_user.roles or []
        
        # Usuario normal: solo ve su propia planificacion
        if "usuario" in roles and "admin_empresa" not in roles and "jefe" not in roles and "visitante" in roles:
            if current_user.personal_id:
                query = query.filter(Planificacion.personal_id == current_user.personal_id)
        
        # Jefe de area: ve la planificacion de todas sus areas de jefatura
        elif "jefe" in roles and "admin_empresa" not in roles:
            if current_user.personal_id:
                areas_jefatura = get_areas_jefatura(db, current_user.personal_id)
                if areas_jefatura:
                    query = query.filter(Personal.area.in_(areas_jefatura))
        
        resultados = query.all()
        
        return [{
            "id": str(r.id),
            "personal_id": str(r.personal_id),
            "fecha": r.fecha.isoformat(),
            "turno_codigo": r.turno_codigo,
            "hora_inicio": str(r.hora_inicio) if r.hora_inicio else None,
            "hora_fin": str(r.hora_fin) if r.hora_fin else None,
            "observacion": r.observacion,
            "dm_info": r.dm_info,
            "personal_nombre": r.personal_nombre,
            "personal_grado": r.personal_grado,
            "personal_area": r.personal_area,
            "dni": r.dni,
            "cip": r.cip,
            "especialidad": r.especialidad,
            "condicion": r.condicion
        } for r in resultados]
        
    except Exception as e:
        logger.error(f"Error en obtener_planificacion_dia: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# PLANIFICACION POR PERSONAL
# =====================================================

@router.get("/personal/{personal_id}")
async def obtener_planificacion_personal(
    personal_id: UUID,
    inicio: date = Query(...),
    fin: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe", "usuario", "visitante"]))
):
    """
    Obtiene la planificacion de un personal especifico en un rango de fechas.
    """
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        # Verificar acceso por empresa
        if current_user.empresa_id and current_user.rol_global != "super_admin":
            if personal.empresa_id != current_user.empresa_id:
                raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
        
        roles = current_user.roles or []
        es_visitante = "visitante" in roles
        es_usuario = "usuario" in roles
        es_admin = "admin_empresa" in roles
        es_jefe = "jefe" in roles
        
        # Usuario normal/visitante: solo ve su propia planificacion
        if (es_usuario or es_visitante) and not es_admin and not es_jefe:
            if str(current_user.personal_id) != str(personal_id):
                raise HTTPException(status_code=403, detail="No puede ver planificacion de otro personal")
        
        # Jefe: solo ve planificacion de personal en sus areas de jefatura
        if es_jefe and not es_admin:
            areas_jefatura = get_areas_jefatura(db, current_user.personal_id)
            if personal.area not in areas_jefatura:
                raise HTTPException(status_code=403, detail="No puede ver personal de otra area")
        
        query = db.query(
            Planificacion.fecha,
            Planificacion.turno_codigo,
            Planificacion.hora_inicio,
            Planificacion.hora_fin,
            Planificacion.observacion,
            Planificacion.dm_info
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= inicio,
            Planificacion.fecha <= fin
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
        logger.error(f"Error en obtener_planificacion_personal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.get("/publico/personal/{personal_id}")
async def obtener_planificacion_publica_personal(
    personal_id: UUID,
    inicio: date = Query(...),
    fin: date = Query(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene la planificacion publica de un personal (sin restricciones de rol).
    """
    try:
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        if current_user.empresa_id and current_user.rol_global != "super_admin":
            if personal.empresa_id != current_user.empresa_id:
                raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
        
        query = db.query(
            Planificacion.fecha,
            Planificacion.turno_codigo,
            Planificacion.hora_inicio,
            Planificacion.hora_fin,
            Planificacion.observacion,
            Planificacion.dm_info
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= inicio,
            Planificacion.fecha <= fin
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
        logger.error(f"Error en obtener_planificacion_publica_personal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# MI HORARIO
# =====================================================

@router.get("/mi-horario/{anio}/{mes}")
async def get_mi_horario(
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene el horario del usuario autenticado para un mes especifico.
    """
    try:
        if mes < 1 or mes > 12:
            raise HTTPException(status_code=400, detail="Mes invalido")
        
        personal_id = current_user.personal_id
        if not personal_id:
            return []
        
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        query = db.query(
            Planificacion.fecha,
            Planificacion.turno_codigo,
            Planificacion.hora_inicio,
            Planificacion.hora_fin,
            Planificacion.dm_info
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        )
        
        planificaciones = query.order_by(Planificacion.fecha).all()
        
        return [{
            "fecha": p.fecha.isoformat(),
            "turno_codigo": p.turno_codigo,
            "hora_inicio": str(p.hora_inicio) if p.hora_inicio else None,
            "hora_fin": str(p.hora_fin) if p.hora_fin else None,
            "dm_info": p.dm_info
        } for p in planificaciones]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_mi_horario: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.get("/mi-horario/{anio}/{mes}/estadisticas")
async def get_mi_estadisticas(
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene estadisticas del horario del usuario autenticado para un mes.
    """
    try:
        personal_id = current_user.personal_id
        if not personal_id:
            return {"total_turnos": 0, "turnos_por_tipo": {}, "mes": mes, "anio": anio}
        
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        stats_query = db.query(
            Planificacion.turno_codigo,
            func.count(Planificacion.id).label('cantidad')
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        )
        
        stats = stats_query.group_by(Planificacion.turno_codigo).all()
        turnos_por_tipo = {s.turno_codigo: s.cantidad for s in stats}
        
        return {
            "total_turnos": sum(turnos_por_tipo.values()),
            "turnos_por_tipo": turnos_por_tipo,
            "mes": mes,
            "anio": anio
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en get_mi_estadisticas: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# BORRADOR DE AREA
# =====================================================

@router.get("/area/borrador/{anio}/{mes}")
async def obtener_borrador_area(
    anio: int,
    mes: int,
    area: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Obtiene el borrador de planificacion de un area para un mes especifico.
    """
    try:
        jefe = db.query(Personal.id, Personal.area).filter(
            Personal.id == current_user.personal_id
        ).first()
        
        if not jefe:
            raise HTTPException(status_code=404, detail="Jefe no encontrado")
        
        area_consulta = area if area else jefe.area
        fecha_referencia = date(anio, mes, 1)
        
        solicitud = db.query(
            SolicitudCambio.id,
            SolicitudCambio.estado,
            SolicitudCambio.turno_original,
            SolicitudCambio.created_at,
            SolicitudCambio.comentario_revision
        ).filter(
            SolicitudCambio.tipo == "planificacion_mensual",
            SolicitudCambio.empleado_id == current_user.personal_id,
            SolicitudCambio.fecha_cambio == fecha_referencia
        ).order_by(SolicitudCambio.created_at.desc()).first()
        
        if not solicitud:
            return {
                "existe": False,
                "datos": [],
                "estado": "borrador",
                "area": area_consulta,
                "mes": mes,
                "anio": anio
            }
        
        datos_array = solicitud.turno_original if isinstance(solicitud.turno_original, list) else []
        
        return {
            "existe": True,
            "id": str(solicitud.id),
            "estado": solicitud.estado,
            "datos": datos_array,
            "area": area_consulta,
            "mes": mes,
            "anio": anio,
            "comentario_revision": solicitud.comentario_revision
        }
        
    except Exception as e:
        logger.error(f"Error en obtener_borrador_area: {str(e)}")
        return {
            "existe": False,
            "datos": [],
            "estado": "borrador",
            "area": area if area else "unknown",
            "mes": mes,
            "anio": anio,
            "error": str(e)
        }


# =====================================================
# ESTADO MENSUAL
# =====================================================

@router.get("/{anio}/{mes}/estado")
async def obtener_estado_mensual(
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Obtiene el estado de la planificacion mensual (turnos, observaciones).
    """
    try:
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        stats_query = db.query(
            Planificacion.turno_codigo,
            func.count(Planificacion.id).label('cantidad')
        ).filter(
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        )
        stats_query = aplicar_filtro_empresa(stats_query, current_user, Planificacion)
        stats = stats_query.group_by(Planificacion.turno_codigo).all()
        
        obs_query = db.query(
            Planificacion.personal_id,
            Planificacion.fecha,
            Planificacion.observacion,
            Personal.nombre.label("personal_nombre")
        ).join(
            Personal, Personal.id == Planificacion.personal_id
        ).filter(
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin,
            Planificacion.observacion.isnot(None)
        )
        obs_query = aplicar_filtro_empresa_personal(obs_query, current_user)
        observaciones = obs_query.all()
        
        return {
            "fecha": fecha_inicio.isoformat(),
            "total_turnos": sum({s.turno_codigo: s.cantidad for s in stats}.values()),
            "turnos_por_tipo": {s.turno_codigo: s.cantidad for s in stats},
            "personal_con_observaciones": [
                {
                    "personal_id": str(o.personal_id),
                    "nombre": o.personal_nombre,
                    "fecha": o.fecha.isoformat(),
                    "observacion": o.observacion
                } for o in observaciones
            ]
        }
        
    except Exception as e:
        logger.error(f"Error en obtener_estado_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# PLANIFICACION MENSUAL (ENDPOINT PRINCIPAL)
# =====================================================

@router.get("/{anio}/{mes}")
async def obtener_planificacion_mensual(
    anio: int,
    mes: int,
    area: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Obtiene la planificacion completa de un mes.
    
    - Admin: ve todas las areas de su empresa
    - Jefe: ve todas las areas donde tiene jefatura (soporta multi-jefatura)
    
    Parametros:
    - anio: Ano de la planificacion
    - mes: Mes de la planificacion (1-12)
    - area: (Opcional) Filtrar por area especifica
    """
    if mes < 1 or mes > 12:
        raise HTTPException(status_code=400, detail="Mes invalido")
    
    try:
        area_value = area if area else "todas"
        cache_key = f"{anio}-{mes:02d}-{area_value}-{str(current_user.id)}"
        
        # Verificar cache
        cached_result = planificacion_cache.get(cache_key)
        if cached_result is not None:
            return cached_result
        
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        query = db.query(
            Planificacion.personal_id,
            Planificacion.fecha,
            Planificacion.turno_codigo,
            Planificacion.hora_inicio,
            Planificacion.hora_fin,
            Planificacion.observacion,
            Planificacion.dm_info,
            Personal.nombre.label("personal_nombre"),
            Personal.grado.label("personal_grado"),
            Personal.area.label("personal_area"),
            Personal.dni,
            Personal.cip,
            Personal.especialidad,
            Personal.condicion
        ).join(
            Personal, Personal.id == Planificacion.personal_id
        ).filter(
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        )
        
        query = aplicar_filtro_empresa_personal(query, current_user)
        
        # Filtrar por area si se especifica
        if area:
            query = query.filter(Personal.area == area)
        
        # Jefe de area: filtrar por todas sus areas de jefatura
        if "jefe" in current_user.roles and "admin_empresa" not in current_user.roles:
            if current_user.personal_id:
                areas_jefatura = get_areas_jefatura(db, current_user.personal_id)
                if areas_jefatura:
                    query = query.filter(Personal.area.in_(areas_jefatura))
                else:
                    # Si no tiene areas de jefatura, devolver vacio
                    return []
        
        resultados = query.all()
        
        result = [{
            "personal_id": str(r.personal_id),
            "fecha": r.fecha.isoformat(),
            "turno_codigo": r.turno_codigo,
            "hora_inicio": str(r.hora_inicio) if r.hora_inicio else None,
            "hora_fin": str(r.hora_fin) if r.hora_fin else None,
            "observacion": r.observacion,
            "dm_info": r.dm_info,
            "personal_nombre": r.personal_nombre,
            "personal_grado": r.personal_grado,
            "personal_area": r.personal_area,
            "dni": r.dni,
            "cip": r.cip,
            "especialidad": r.especialidad,
            "condicion": r.condicion
        } for r in resultados]
        
        # Guardar en cache
        planificacion_cache.set(cache_key, result)
        
        return result
        
    except Exception as e:
        logger.error(f"Error en obtener_planificacion_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# CREAR/ACTUALIZAR TURNO
# =====================================================

@router.post("/turno")
async def crear_turno(
    turno_data: PlanificacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Crea o actualiza un turno en la planificacion.
    """
    try:
        personal = db.query(Personal).filter(Personal.id == turno_data.personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        if current_user.empresa_id and current_user.rol_global != "super_admin":
            if personal.empresa_id != current_user.empresa_id:
                raise HTTPException(status_code=403, detail="Este personal no pertenece a su empresa")
        
        existente = db.query(Planificacion).filter(
            Planificacion.personal_id == turno_data.personal_id,
            Planificacion.fecha == turno_data.fecha
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
                "id": str(existente.id),
                "personal_id": str(existente.personal_id),
                "fecha": existente.fecha.isoformat(),
                "turno_codigo": existente.turno_codigo,
                "hora_inicio": str(existente.hora_inicio) if existente.hora_inicio else None,
                "hora_fin": str(existente.hora_fin) if existente.hora_fin else None,
                "observacion": existente.observacion,
                "dm_info": existente.dm_info,
                "personal_nombre": personal.nombre
            }
        else:
            turno = Planificacion(
                personal_id=turno_data.personal_id,
                fecha=turno_data.fecha,
                turno_codigo=turno_data.turno_codigo,
                hora_inicio=parse_hora(turno_data.hora_inicio),
                hora_fin=parse_hora(turno_data.hora_fin),
                observacion=turno_data.observacion,
                dm_info=turno_data.dm_info,
                created_by=current_user.id
            )
            db.add(turno)
            db.commit()
            db.refresh(turno)
            planificacion_cache.invalidate_for_mes(turno_data.fecha.year, turno_data.fecha.month)
            
            return {
                "id": str(turno.id),
                "personal_id": str(turno.personal_id),
                "fecha": turno.fecha.isoformat(),
                "turno_codigo": turno.turno_codigo,
                "hora_inicio": str(turno.hora_inicio) if turno.hora_inicio else None,
                "hora_fin": str(turno.hora_fin) if turno.hora_fin else None,
                "observacion": turno.observacion,
                "dm_info": turno.dm_info,
                "personal_nombre": personal.nombre
            }
            
    except Exception as e:
        logger.error(f"Error en crear_turno: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# CARGA MASIVA
# =====================================================

@router.post("/carga-masiva")
async def carga_masiva_turnos(
    asignaciones: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Carga masiva de turnos. Recibe una lista de asignaciones.
    """
    if not asignaciones:
        raise HTTPException(status_code=400, detail="No se recibieron datos")
    
    try:
        fechas = list(set(a["fecha"] for a in asignaciones))
        personal_ids = list(set(UUID(a["personal_id"]) for a in asignaciones))
        
        existentes = db.query(Planificacion).filter(
            Planificacion.personal_id.in_(personal_ids),
            Planificacion.fecha.in_(fechas)
        ).all()
        
        existentes_map = {}
        for e in existentes:
            existentes_map[(str(e.personal_id), e.fecha.isoformat())] = e
        
        creados, actualizados = 0, 0
        nuevos_registros = []
        meses_afectados = set()
        
        for asignacion in asignaciones:
            personal_id = UUID(asignacion["personal_id"])
            fecha_str = asignacion["fecha"]
            turno_codigo = asignacion.get("turno_codigo")
            fecha = date.fromisoformat(fecha_str)
            meses_afectados.add((fecha.year, fecha.month))
            key = (str(personal_id), fecha_str)
            
            if key in existentes_map:
                existente = existentes_map[key]
                existente.turno_codigo = turno_codigo
                existente.updated_at = datetime.utcnow()
                existente.created_by = current_user.id
                actualizados += 1
            else:
                nuevos_registros.append({
                    "personal_id": personal_id,
                    "fecha": fecha,
                    "turno_codigo": turno_codigo,
                    "created_by": current_user.id
                })
                creados += 1
        
        if nuevos_registros:
            db.execute(Planificacion.__table__.insert(), nuevos_registros)
        
        db.commit()
        
        for anio, mes in meses_afectados:
            planificacion_cache.invalidate_for_mes(anio, mes)
        
        logger.info(f"Carga masiva: {creados} creados, {actualizados} actualizados")
        
        return {
            "message": "Carga masiva completada",
            "creados": creados,
            "actualizados": actualizados,
            "total": creados + actualizados,
            "meses_afectados": len(meses_afectados),
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error en carga_masiva: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error en carga masiva: {str(e)}")


@router.post("/masivo")
async def crear_planificacion_masiva(
    data: PlanificacionMasiva,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Crea o actualiza multiples turnos en una sola solicitud.
    """
    try:
        creados, actualizados, errores = 0, 0, []
        meses_afectados = set()
        fechas = [t.fecha for t in data.planificaciones]
        personal_ids = [t.personal_id for t in data.planificaciones]
        
        existentes = db.query(Planificacion).filter(
            Planificacion.personal_id.in_(personal_ids),
            Planificacion.fecha.in_(fechas)
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
                        personal_id=turno_data.personal_id,
                        fecha=turno_data.fecha,
                        turno_codigo=turno_data.turno_codigo,
                        hora_inicio=parse_hora(turno_data.hora_inicio),
                        hora_fin=parse_hora(turno_data.hora_fin),
                        observacion=turno_data.observacion,
                        dm_info=turno_data.dm_info,
                        created_by=current_user.id
                    )
                    db.add(nuevo)
                    creados += 1
                
                meses_afectados.add((turno_data.fecha.year, turno_data.fecha.month))
                
            except Exception as e:
                errores.append({
                    "personal_id": str(turno_data.personal_id),
                    "fecha": turno_data.fecha.isoformat(),
                    "error": str(e)
                })
        
        db.commit()
        
        for anio, mes in meses_afectados:
            planificacion_cache.invalidate_for_mes(anio, mes)
        
        return {
            "message": "Planificacion guardada exitosamente",
            "creados": creados,
            "actualizados": actualizados,
            "errores": errores if errores else None
        }
        
    except Exception as e:
        logger.error(f"Error en crear_planificacion_masiva: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# OBSERVACIONES
# =====================================================

@router.post("/observacion")
async def agregar_observacion(
    obs_data: ObservacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Agrega una observacion a un turno."""
    try:
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == obs_data.personal_id,
            Planificacion.fecha == obs_data.fecha
        ).first()
        
        if not planificacion:
            raise HTTPException(status_code=404, detail="Turno no encontrado")
        
        planificacion.observacion = obs_data.observacion
        planificacion.updated_at = datetime.utcnow()
        db.commit()
        planificacion_cache.invalidate_for_mes(obs_data.fecha.year, obs_data.fecha.month)
        
        return {"message": "Observacion agregada exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en agregar_observacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.delete("/observacion/{key}")
async def eliminar_observacion(
    key: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Elimina una observacion de un turno."""
    try:
        parts = key.split('_')
        if len(parts) != 2:
            raise ValueError("Formato invalido")
        
        personal_id = UUID(parts[0])
        fecha = date.fromisoformat(parts[1])
        
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha == fecha
        ).first()
        
        if not planificacion:
            raise HTTPException(status_code=404, detail="Turno no encontrado")
        
        planificacion.observacion = None
        planificacion.updated_at = datetime.utcnow()
        db.commit()
        planificacion_cache.invalidate_for_mes(fecha.year, fecha.month)
        
        return {"message": "Observacion eliminada exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en eliminar_observacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# 🆕 BORRADOR Y ENVIO A REVISION - CORREGIDO MULTI-JEFATURA
# =====================================================

@router.post("/area/borrador")
async def guardar_borrador_area(
    area: str,
    mes: int,
    anio: int,
    datos: Dict,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Guarda el borrador de planificacion de un area."""
    try:
        jefe = db.query(Personal).filter(
            Personal.id == current_user.personal_id
        ).first()
        
        if not jefe:
            raise HTTPException(status_code=403, detail="Jefe no encontrado")
        
        areas_jefatura = get_areas_jefatura(db, current_user.personal_id)
        
        if area not in areas_jefatura:
            raise HTTPException(
                status_code=403, 
                detail=f"No eres jefe de esta area. Tus areas de jefatura son: {areas_jefatura}"
            )
        
        if mes < 1 or mes > 12:
            raise HTTPException(status_code=400, detail="Mes invalido")
        
        fecha_referencia = date(anio, mes, 1)
        
        solicitud_existente = db.query(SolicitudCambio).filter(
            SolicitudCambio.tipo == "planificacion_mensual",
            SolicitudCambio.empleado_id == current_user.personal_id,
            SolicitudCambio.fecha_cambio == fecha_referencia
        ).first()
        
        datos_array = datos['datos'] if isinstance(datos, dict) and 'datos' in datos else datos
        
        if solicitud_existente:
            solicitud_existente.turno_original = datos_array
            solicitud_existente.estado = "borrador"
            # 🆕 Guardar el área en el motivo para referencia
            solicitud_existente.motivo = f"ENVIO_MENSUAL - {area}"
            if hasattr(solicitud_existente, 'updated_at'):
                solicitud_existente.updated_at = datetime.utcnow()
            if not solicitud_existente.historial:
                solicitud_existente.historial = []
            solicitud_existente.historial.append({
                "fecha": datetime.utcnow().isoformat(),
                "usuario": str(current_user.id),
                "accion": "actualizacion_borrador",
                "estado": "borrador",
                "area": area,  # 🆕 Guardar área en historial
                "registros": len(datos_array)
            })
            db.commit()
            return {
                "message": "Borrador actualizado exitosamente",
                "id": str(solicitud_existente.id),
                "estado": solicitud_existente.estado,
                "registros": len(datos_array)
            }
        else:
            nueva_solicitud = SolicitudCambio(
                tipo="planificacion_mensual",
                estado="borrador",
                fecha_cambio=fecha_referencia,
                motivo=f"ENVIO_MENSUAL - {area}",  # 🆕 Incluir área en el motivo
                empleado_id=current_user.personal_id,
                turno_original=datos_array,
                historial=[{
                    "fecha": datetime.utcnow().isoformat(),
                    "usuario": str(current_user.id),
                    "accion": "creacion_borrador",
                    "estado": "borrador",
                    "area": area,  # 🆕 Guardar área en historial
                    "registros": len(datos_array)
                }],
                created_by=current_user.id
            )
            db.add(nueva_solicitud)
            db.commit()
            db.refresh(nueva_solicitud)
            return {
                "message": "Borrador creado exitosamente",
                "id": str(nueva_solicitud.id),
                "estado": nueva_solicitud.estado,
                "registros": len(datos_array)
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en guardar_borrador_area: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.post("/area/enviar-revision")
async def enviar_planificacion_revision(
    area: str,
    mes: int,
    anio: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Envia la planificacion de un area a revision."""
    try:
        jefe = db.query(Personal).filter(
            Personal.id == current_user.personal_id
        ).first()
        
        if not jefe:
            raise HTTPException(status_code=403, detail="Jefe no encontrado")
        
        areas_jefatura = get_areas_jefatura(db, current_user.personal_id)
        
        if area not in areas_jefatura:
            raise HTTPException(
                status_code=403, 
                detail=f"No eres jefe de esta area. Tus areas de jefatura son: {areas_jefatura}"
            )
        
        fecha_referencia = date(anio, mes, 1)
        
        solicitud = db.query(SolicitudCambio).filter(
            SolicitudCambio.tipo == "planificacion_mensual",
            SolicitudCambio.empleado_id == current_user.personal_id,
            SolicitudCambio.fecha_cambio == fecha_referencia,
            SolicitudCambio.estado == "borrador"
        ).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="No hay borrador para enviar")
        
        solicitud.estado = "pendiente"
        # 🆕 Asegurar que el motivo tenga el área
        if "ENVIO_MENSUAL" in (solicitud.motivo or "") and area not in (solicitud.motivo or ""):
            solicitud.motivo = f"ENVIO_MENSUAL - {area}"
        if not solicitud.historial:
            solicitud.historial = []
        solicitud.historial.append({
            "fecha": datetime.utcnow().isoformat(),
            "usuario": str(current_user.id),
            "accion": "envio_a_revision",
            "estado": "pendiente",
            "area": area  # 🆕 Guardar área en historial
        })
        db.commit()
        
        return {
            "message": "Planificacion enviada a revision exitosamente",
            "id": str(solicitud.id),
            "estado": solicitud.estado
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en enviar_planificacion_revision: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# ELIMINAR PLANIFICACION
# =====================================================

@router.delete("/{planificacion_id}", status_code=204)
async def eliminar_planificacion(
    planificacion_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Elimina un registro de planificacion."""
    try:
        planificacion = db.query(Planificacion).filter(Planificacion.id == planificacion_id).first()
        if not planificacion:
            raise HTTPException(status_code=404, detail="Planificacion no encontrada")
        
        fecha = planificacion.fecha
        db.delete(planificacion)
        db.commit()
        planificacion_cache.invalidate_for_mes(fecha.year, fecha.month)
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en eliminar_planificacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.delete("/personal/{personal_id}/mes/{anio}/{mes}", status_code=204)
async def eliminar_planificacion_mensual(
    personal_id: UUID,
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Elimina toda la planificacion de un personal en un mes."""
    try:
        fecha_inicio = date(anio, mes, 1)
        fecha_fin = date(anio + 1, 1, 1) if mes == 12 else date(anio, mes + 1, 1)
        
        db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        ).delete(synchronize_session=False)
        
        db.commit()
        planificacion_cache.invalidate_for_mes(anio, mes)
        return None
        
    except Exception as e:
        logger.error(f"Error en eliminar_planificacion_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# ROTACIONES
# =====================================================

@router.get("/rotaciones")
async def obtener_rotaciones(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Obtiene todas las rotaciones de la empresa."""
    try:
        from app.models.rotacion import Rotacion
        
        query = db.query(Rotacion).filter(Rotacion.activo == True)
        
        if current_user.empresa_id and current_user.rol_global != "super_admin":
            query = query.filter(
                (Rotacion.empresa_id == current_user.empresa_id) | 
                (Rotacion.empresa_id.is_(None))
            )
        
        rotaciones = query.order_by(Rotacion.nombre).all()
        
        return {
            "rotaciones": [
                {
                    "id": str(r.id),
                    "nombre": r.nombre,
                    "descripcion": r.descripcion,
                    "patron": r.patron,
                    "duracion_ciclo": r.duracion_ciclo,
                    "color": r.color,
                    "activo": r.activo,
                    "created_at": r.created_at.isoformat() if r.created_at else None
                }
                for r in rotaciones
            ]
        }
    except Exception as e:
        logger.error(f"Error en obtener_rotaciones: {str(e)}")
        return {"rotaciones": []}


@router.post("/rotaciones")
async def crear_rotacion(
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Crea una nueva rotacion."""
    try:
        from app.models.rotacion import Rotacion
        
        rotacion = Rotacion(
            empresa_id=current_user.empresa_id,
            nombre=data["nombre"],
            descripcion=data.get("descripcion"),
            patron=data.get("patron", []),
            duracion_ciclo=data.get("duracion_ciclo", len(data.get("patron", []))),
            color=data.get("color", "#6366F1")
        )
        
        db.add(rotacion)
        db.commit()
        db.refresh(rotacion)
        
        return {
            "id": str(rotacion.id),
            "nombre": rotacion.nombre,
            "descripcion": rotacion.descripcion,
            "patron": rotacion.patron,
            "duracion_ciclo": rotacion.duracion_ciclo,
            "color": rotacion.color,
            "activo": rotacion.activo,
            "created_at": rotacion.created_at.isoformat() if rotacion.created_at else None
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error en crear_rotacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al crear rotacion: {str(e)}")


@router.put("/rotaciones/{rotacion_id}")
async def actualizar_rotacion(
    rotacion_id: UUID,
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Actualiza una rotacion existente."""
    try:
        from app.models.rotacion import Rotacion
        
        rotacion = db.query(Rotacion).filter(Rotacion.id == rotacion_id).first()
        if not rotacion:
            raise HTTPException(status_code=404, detail="Rotacion no encontrada")
        
        if current_user.empresa_id and rotacion.empresa_id and rotacion.empresa_id != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No tiene acceso a esta rotacion")
        
        if "nombre" in data:
            rotacion.nombre = data["nombre"]
        if "descripcion" in data:
            rotacion.descripcion = data["descripcion"]
        if "patron" in data:
            rotacion.patron = data["patron"]
            rotacion.duracion_ciclo = data.get("duracion_ciclo", len(data["patron"]))
        if "color" in data:
            rotacion.color = data["color"]
        if "activo" in data:
            rotacion.activo = data["activo"]
        
        db.commit()
        db.refresh(rotacion)
        
        return {
            "id": str(rotacion.id),
            "nombre": rotacion.nombre,
            "patron": rotacion.patron,
            "duracion_ciclo": rotacion.duracion_ciclo,
            "color": rotacion.color
        }
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error en actualizar_rotacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al actualizar rotacion: {str(e)}")


@router.delete("/rotaciones/{rotacion_id}")
async def eliminar_rotacion(
    rotacion_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Elimina (desactiva) una rotacion."""
    try:
        from app.models.rotacion import Rotacion
        
        rotacion = db.query(Rotacion).filter(Rotacion.id == rotacion_id).first()
        if not rotacion:
            raise HTTPException(status_code=404, detail="Rotacion no encontrada")
        
        if current_user.empresa_id and rotacion.empresa_id and rotacion.empresa_id != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No tiene acceso a esta rotacion")
        
        rotacion.activo = False
        db.commit()
        
        return {"message": "Rotacion eliminada correctamente"}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error en eliminar_rotacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al eliminar rotacion: {str(e)}")


@router.post("/rotaciones/aplicar")
async def aplicar_rotacion(
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """Aplica una rotacion a una lista de empleados desde una fecha de inicio."""
    try:
        personas = data.get("personas", [])
        patron = data.get("patron", [])
        fecha_inicio_str = data.get("fecha_inicio")
        mes = data.get("mes")
        anio = data.get("anio")
        
        if not personas:
            raise HTTPException(status_code=400, detail="Debe especificar al menos una persona")
        if not patron:
            raise HTTPException(status_code=400, detail="Debe especificar un patron")
        if not fecha_inicio_str:
            raise HTTPException(status_code=400, detail="Debe especificar una fecha de inicio")
        
        fecha_inicio = date.fromisoformat(fecha_inicio_str)
        ciclo = len(patron)
        
        # Calcular ultimo dia del mes
        if mes == 12:
            ultimo_dia = 31
        else:
            ultimo_dia = date(anio, mes + 1, 1).replace(day=1) - timedelta(days=1)
            ultimo_dia = ultimo_dia.day
        
        asignaciones_creadas = 0
        asignaciones_actualizadas = 0
        
        for persona_id_str in personas:
            persona_id = UUID(persona_id_str)
            
            for dia in range(fecha_inicio.day, ultimo_dia + 1):
                fecha_actual = date(anio, mes, dia)
                posicion_ciclo = ((dia - fecha_inicio.day) % ciclo)
                turno_codigo = patron[posicion_ciclo].get("turno_codigo", "FRANCO")
                
                existente = db.query(Planificacion).filter(
                    Planificacion.personal_id == persona_id,
                    Planificacion.fecha == fecha_actual
                ).first()
                
                if existente:
                    existente.turno_codigo = turno_codigo
                    existente.updated_at = datetime.utcnow()
                    existente.created_by = current_user.id
                    asignaciones_actualizadas += 1
                else:
                    nuevo = Planificacion(
                        personal_id=persona_id,
                        fecha=fecha_actual,
                        turno_codigo=turno_codigo,
                        created_by=current_user.id
                    )
                    db.add(nuevo)
                    asignaciones_creadas += 1
        
        db.commit()
        planificacion_cache.invalidate_for_mes(anio, mes)
        
        return {
            "message": "Rotacion aplicada correctamente",
            "creados": asignaciones_creadas,
            "actualizados": asignaciones_actualizadas,
            "total": asignaciones_creadas + asignaciones_actualizadas
        }
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error en aplicar_rotacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al aplicar rotacion: {str(e)}")


# =====================================================
# METAS DE CUMPLIMIENTO POR EMPLEADO
# =====================================================

@router.get("/metas/{anio}/{mes}")
async def obtener_metas_mensuales(
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Obtiene las metas de cumplimiento definidas para cada empleado en un mes especifico.
    """
    try:
        query = db.query(MetaCumplimiento).filter(
            MetaCumplimiento.anio == anio,
            MetaCumplimiento.mes == mes
        )
        
        if current_user.empresa_id and current_user.rol_global != "super_admin":
            query = query.join(Personal, Personal.id == MetaCumplimiento.personal_id)
            query = query.filter(Personal.empresa_id == current_user.empresa_id)
        
        metas = query.all()
        
        return {
            "metas": [
                {
                    "id": str(m.id),
                    "personal_id": str(m.personal_id),
                    "mes": m.mes,
                    "anio": m.anio,
                    "meta_turnos": m.meta_turnos,
                    "ajustada_por": str(m.ajustada_por) if m.ajustada_por else None,
                    "fecha_ajuste": m.fecha_ajuste.isoformat() if m.fecha_ajuste else None,
                    "justificacion": m.justificacion
                }
                for m in metas
            ]
        }
    except Exception as e:
        logger.error(f"Error en obtener_metas_mensuales: {str(e)}")
        return {"metas": []}


@router.post("/metas")
async def guardar_metas_mensuales(
    data: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Guarda o actualiza las metas de cumplimiento para empleados en un mes especifico.
    """
    try:
        metas = data.get("metas", [])
        if not metas:
            raise HTTPException(status_code=400, detail="No se recibieron metas")
        
        creados = 0
        actualizados = 0
        eliminados = 0
        
        for meta_data in metas:
            personal_id = UUID(meta_data["personal_id"])
            mes = meta_data["mes"]
            anio = meta_data["anio"]
            meta_turnos = meta_data.get("meta_turnos")
            
            existente = db.query(MetaCumplimiento).filter(
                MetaCumplimiento.personal_id == personal_id,
                MetaCumplimiento.mes == mes,
                MetaCumplimiento.anio == anio
            ).first()
            
            if meta_turnos is None:
                if existente:
                    db.delete(existente)
                    eliminados += 1
            else:
                if existente:
                    existente.meta_turnos = meta_turnos
                    existente.ajustada_por = UUID(meta_data["ajustada_por"]) if meta_data.get("ajustada_por") else current_user.id
                    existente.fecha_ajuste = datetime.fromisoformat(meta_data["fecha_ajuste"]) if meta_data.get("fecha_ajuste") else datetime.utcnow()
                    existente.justificacion = meta_data.get("justificacion")
                    actualizados += 1
                else:
                    nueva_meta = MetaCumplimiento(
                        personal_id=personal_id,
                        mes=mes,
                        anio=anio,
                        meta_turnos=meta_turnos,
                        ajustada_por=UUID(meta_data["ajustada_por"]) if meta_data.get("ajustada_por") else current_user.id,
                        fecha_ajuste=datetime.fromisoformat(meta_data["fecha_ajuste"]) if meta_data.get("fecha_ajuste") else datetime.utcnow(),
                        justificacion=meta_data.get("justificacion")
                    )
                    db.add(nueva_meta)
                    creados += 1
        
        db.commit()
        
        return {
            "message": "Metas guardadas exitosamente",
            "creados": creados,
            "actualizados": actualizados,
            "eliminados": eliminados,
            "total": creados + actualizados + eliminados
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error en guardar_metas_mensuales: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al guardar metas: {str(e)}")