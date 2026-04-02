# D:\Centro de control Hospital PNP\back\app\api\planificacion.py
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func, text, case
from typing import List, Optional, Dict, Any
from datetime import date, datetime, timedelta
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
# 🚀 CACHE EN MEMORIA CON EXPIRACIÓN (5 minutos)
# =====================================================
class PlanificacionCache:
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
        self.default_timeout = 300  # 5 minutos
    
    def get(self, key: str):
        """Obtiene un valor del caché si no ha expirado"""
        if key in self._cache and key in self._timestamps:
            if datetime.now() - self._timestamps[key] < timedelta(seconds=self.default_timeout):
                return self._cache[key]
            else:
                # Limpiar caché expirado
                del self._cache[key]
                del self._timestamps[key]
        return None
    
    def set(self, key: str, value: Any, timeout: int = None):
        """Guarda un valor en el caché con timeout personalizado"""
        self._cache[key] = value
        self._timestamps[key] = datetime.now()
        if timeout:
            self.default_timeout = timeout
    
    def invalidate(self, key_pattern: str = None):
        """Invalida caché por patrón o todo si no hay patrón"""
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
        """Invalida caché para un mes específico"""
        pattern = f"{anio}-{mes:02d}"
        self.invalidate(pattern)

# Instancia global del caché
planificacion_cache = PlanificacionCache()

# =====================================================
# FUNCIÓN PARA OBTENER DATOS DEL JEFE (CACHEADA)
# =====================================================
def get_jefe_area(db: Session, user_id: UUID):
    """Obtiene información del jefe de área"""
    return db.query(Personal).filter(Personal.id == user_id).first()

# =====================================================
# ENDPOINTS EXISTENTES (SIN CAMBIOS)
# =====================================================

@router.get("/{anio}/{mes}")
async def obtener_planificacion_mensual(
    anio: int,
    mes: int,
    area: Optional[str] = Query(None, description="Filtrar por área"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Obtiene la planificación de un mes específico (PISCINA GENERAL)
    """
    # Validar mes
    if mes < 1 or mes > 12:
        raise HTTPException(status_code=400, detail="Mes inválido")
    
    try:
        # Normalizar área para caché
        area_value = area if area else "todas"
        
        # Generar clave de caché
        cache_key = f"{anio}-{mes:02d}-{area_value}-{str(current_user.id)}"
        
        # Verificar caché
        cached_result = planificacion_cache.get(cache_key)
        if cached_result is not None:
            logger.info(f"📦 Cache hit: {cache_key}")
            return cached_result
        
        logger.info(f"🔄 Cache miss: {cache_key} - Consultando BD...")
        start_time = datetime.now()
        
        # Construir fechas del mes
        fecha_inicio = date(anio, mes, 1)
        if mes == 12:
            fecha_fin = date(anio + 1, 1, 1)
        else:
            fecha_fin = date(anio, mes + 1, 1)
        
        # ===== CONSULTA ÚNICA CON JOIN - CON TODOS LOS CAMPOS =====
        query = db.query(
            Planificacion.personal_id,
            Planificacion.fecha,
            Planificacion.turno_codigo,
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
            Personal, 
            Personal.id == Planificacion.personal_id
        ).filter(
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        )
        
        # Filtro por área
        if area:
            query = query.filter(Personal.area == area)
        
        # Si es jefe de área (no admin), solo puede ver su área
        if "jefe_area" in current_user.roles and "admin" not in current_user.roles:
            jefe = get_jefe_area(db, current_user.personal_id)
            if jefe and jefe.area:
                query = query.filter(Personal.area == jefe.area)
            else:
                logger.warning(f"Jefe de área sin área asignada: {current_user.id}")
                return []
        
        # Ejecutar UNA SOLA CONSULTA
        resultados = query.all()
        
        # Convertir a formato ultra ligero (solo datos necesarios)
        result = [
            {
                "personal_id": str(r.personal_id),
                "fecha": r.fecha.isoformat(),
                "turno_codigo": r.turno_codigo,
                "observacion": r.observacion,
                "dm_info": r.dm_info,
                "personal_nombre": r.personal_nombre,
                "personal_grado": r.personal_grado,
                "personal_area": r.personal_area,
                "dni": r.dni,
                "cip": r.cip,
                "especialidad": r.especialidad,
                "condicion": r.condicion
            }
            for r in resultados
        ]
        
        query_time = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"✅ Consulta completada: {len(result)} registros en {query_time:.2f}ms")
        
        # Guardar en caché
        planificacion_cache.set(cache_key, result)
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error en obtener_planificacion_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.get("/personal/{personal_id}")
async def obtener_planificacion_personal(
    personal_id: UUID,
    inicio: date = Query(..., description="Fecha inicio"),
    fin: date = Query(..., description="Fecha fin"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Obtiene la planificación de un personal en un rango de fechas
    """
    try:
        # Verificar permisos
        if "usuario" in current_user.roles and "admin" not in current_user.roles and "jefe_area" not in current_user.roles:
            if str(current_user.personal_id) != str(personal_id):
                raise HTTPException(status_code=403, detail="No puede ver planificación de otro personal")
        
        # Si es jefe de área, verificar que el personal pertenezca a su área
        if "jefe_area" in current_user.roles and "admin" not in current_user.roles:
            jefe = get_jefe_area(db, current_user.personal_id)
            personal = db.query(Personal).filter(Personal.id == personal_id).first()
            
            if not personal or not jefe or personal.area != jefe.area:
                raise HTTPException(status_code=403, detail="No puede ver personal de otra área")
        
        # Consulta optimizada
        planificaciones = db.query(
            Planificacion.fecha,
            Planificacion.turno_codigo,
            Planificacion.observacion,
            Planificacion.dm_info
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= inicio,
            Planificacion.fecha <= fin
        ).order_by(Planificacion.fecha).all()
        
        # Convertir a diccionario por fecha
        resultado = {}
        for p in planificaciones:
            resultado[p.fecha.isoformat()] = {
                "turno_codigo": p.turno_codigo,
                "observacion": p.observacion,
                "dm_info": p.dm_info
            }
        
        return resultado
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en obtener_planificacion_personal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.get("/dia/{fecha}")
async def obtener_planificacion_dia(
    fecha: date,
    area: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "oficial_permanencia", "usuario"]))
):
    """
    Obtiene la planificación de un día específico - VERSIÓN CORREGIDA CON TODOS LOS CAMPOS
    """
    try:
        logger.info(f"📡 GET /dia/{fecha} - Solicitado por: {current_user.email}")
        
        # Construir query base con TODOS los campos necesarios para ReporteDiario y Rancho
        query = db.query(
            Planificacion.personal_id,
            Planificacion.fecha,
            Planificacion.turno_codigo,
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
            Personal,
            Personal.id == Planificacion.personal_id
        ).filter(
            Planificacion.fecha == fecha
        )
        
        if area:
            query = query.filter(Personal.area == area)
        
        # Filtros por rol
        if "usuario" in current_user.roles and "admin" not in current_user.roles and "jefe_area" not in current_user.roles:
            if not current_user.personal_id:
                logger.warning(f"Usuario {current_user.id} no tiene personal_id asociado")
                return []
            query = query.filter(Planificacion.personal_id == current_user.personal_id)
            logger.info(f"👤 Usuario viendo su propio horario: {current_user.personal_id}")
        
        elif "jefe_area" in current_user.roles and "admin" not in current_user.roles:
            jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if jefe and jefe.area:
                query = query.filter(Personal.area == jefe.area)
                logger.info(f"👥 Jefe viendo horario del área: {jefe.area}")
        
        elif "oficial_permanencia" in current_user.roles and "admin" not in current_user.roles:
            oficial = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if oficial and oficial.area:
                query = query.filter(Personal.area == oficial.area)
                logger.info(f"👮 Oficial viendo horario del área: {oficial.area}")
        
        elif "admin" in current_user.roles:
            logger.info("👑 Admin viendo toda la planificación")
        
        resultados = query.all()
        
        logger.info(f"✅ {len(resultados)} registros encontrados para {fecha}")
        
        return [
            {
                "personal_id": str(r.personal_id),
                "fecha": r.fecha.isoformat(),
                "turno_codigo": r.turno_codigo,
                "observacion": r.observacion,
                "dm_info": r.dm_info,
                "personal_nombre": r.personal_nombre,
                "personal_grado": r.personal_grado,
                "personal_area": r.personal_area,
                "dni": r.dni,
                "cip": r.cip,
                "especialidad": r.especialidad,
                "condicion": r.condicion
            }
            for r in resultados
        ]
        
    except Exception as e:
        logger.error(f"❌ Error en obtener_planificacion_dia: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.post("/turno")
async def crear_turno(
    turno_data: PlanificacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Crea o actualiza un turno para un personal en una fecha específica
    """
    try:
        # Verificar si ya existe
        existente = db.query(Planificacion).filter(
            Planificacion.personal_id == turno_data.personal_id,
            Planificacion.fecha == turno_data.fecha
        ).first()
        
        if existente:
            # Actualizar existente
            existente.turno_codigo = turno_data.turno_codigo
            existente.observacion = turno_data.observacion
            existente.dm_info = turno_data.dm_info
            existente.updated_at = datetime.utcnow()
            existente.created_by = current_user.id
            db.commit()
            
            # Limpiar caché del mes afectado
            planificacion_cache.invalidate_for_mes(
                turno_data.fecha.year, 
                turno_data.fecha.month
            )
            
            # Obtener nombre del personal
            personal = db.query(Personal).filter(Personal.id == existente.personal_id).first()
            
            return {
                "id": str(existente.id),
                "personal_id": str(existente.personal_id),
                "fecha": existente.fecha.isoformat(),
                "turno_codigo": existente.turno_codigo,
                "observacion": existente.observacion,
                "dm_info": existente.dm_info,
                "personal_nombre": personal.nombre if personal else None
            }
        else:
            # Crear nuevo
            turno = Planificacion(
                personal_id=turno_data.personal_id,
                fecha=turno_data.fecha,
                turno_codigo=turno_data.turno_codigo,
                observacion=turno_data.observacion,
                dm_info=turno_data.dm_info,
                created_by=current_user.id
            )
            db.add(turno)
            db.commit()
            db.refresh(turno)
            
            # Limpiar caché del mes afectado
            planificacion_cache.invalidate_for_mes(
                turno_data.fecha.year, 
                turno_data.fecha.month
            )
            
            # Obtener nombre del personal
            personal = db.query(Personal).filter(Personal.id == turno.personal_id).first()
            
            return {
                "id": str(turno.id),
                "personal_id": str(turno.personal_id),
                "fecha": turno.fecha.isoformat(),
                "turno_codigo": turno.turno_codigo,
                "observacion": turno.observacion,
                "dm_info": turno.dm_info,
                "personal_nombre": personal.nombre if personal else None
            }
            
    except Exception as e:
        logger.error(f"❌ Error en crear_turno: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.post("/masivo")
async def crear_planificacion_masiva(
    data: PlanificacionMasiva,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Crea múltiples turnos en lote
    """
    try:
        creados = 0
        actualizados = 0
        errores = []
        meses_afectados = set()
        
        # Obtener todas las planificaciones existentes en una sola consulta
        fechas = [t.fecha for t in data.planificaciones]
        personal_ids = [t.personal_id for t in data.planificaciones]
        
        existentes = db.query(Planificacion).filter(
            Planificacion.personal_id.in_(personal_ids),
            Planificacion.fecha.in_(fechas)
        ).all()
        
        # Crear mapa de búsqueda rápida
        existentes_map = {
            (str(p.personal_id), p.fecha.isoformat()): p 
            for p in existentes
        }
        
        for turno_data in data.planificaciones:
            try:
                key = (str(turno_data.personal_id), turno_data.fecha.isoformat())
                existente = existentes_map.get(key)
                
                if existente:
                    existente.turno_codigo = turno_data.turno_codigo
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
        
        # Limpiar caché de los meses afectados
        for anio, mes in meses_afectados:
            planificacion_cache.invalidate_for_mes(anio, mes)
        
        return {
            "message": "Planificación guardada exitosamente",
            "creados": creados,
            "actualizados": actualizados,
            "errores": errores if errores else None
        }
        
    except Exception as e:
        logger.error(f"❌ Error en crear_planificacion_masiva: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.post("/observacion")
async def agregar_observacion(
    obs_data: ObservacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Agrega una observación a un turno específico
    """
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
        
        # Limpiar caché del mes afectado
        planificacion_cache.invalidate_for_mes(obs_data.fecha.year, obs_data.fecha.month)
        
        return {"message": "Observación agregada exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en agregar_observacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.delete("/observacion/{key}")
async def eliminar_observacion(
    key: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Elimina una observación (key formato: personal_id_fecha)
    """
    try:
        parts = key.split('_')
        if len(parts) != 2:
            raise ValueError("Formato inválido")
        
        personal_id = UUID(parts[0])
        fecha_str = parts[1]
        fecha = date.fromisoformat(fecha_str)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Formato de key inválido: {str(e)}")
    
    try:
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha == fecha
        ).first()
        
        if not planificacion:
            raise HTTPException(status_code=404, detail="Turno no encontrado")
        
        planificacion.observacion = None
        planificacion.updated_at = datetime.utcnow()
        db.commit()
        
        # Limpiar caché del mes afectado
        planificacion_cache.invalidate_for_mes(fecha.year, fecha.month)
        
        return {"message": "Observación eliminada exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en eliminar_observacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.get("/{anio}/{mes}/estado")
async def obtener_estado_mensual(
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Obtiene estadísticas de la planificación mensual
    """
    try:
        fecha_inicio = date(anio, mes, 1)
        if mes == 12:
            fecha_fin = date(anio + 1, 1, 1)
        else:
            fecha_fin = date(anio, mes + 1, 1)
        
        # Consulta optimizada con agrupación
        stats = db.query(
            Planificacion.turno_codigo,
            func.count(Planificacion.id).label('cantidad')
        ).filter(
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        ).group_by(
            Planificacion.turno_codigo
        ).all()
        
        turnos_por_tipo = {s.turno_codigo: s.cantidad for s in stats}
        total_turnos = sum(turnos_por_tipo.values())
        
        # Consulta para observaciones
        observaciones = db.query(
            Planificacion.personal_id,
            Planificacion.fecha,
            Planificacion.observacion,
            Personal.nombre.label("personal_nombre")
        ).join(
            Personal,
            Personal.id == Planificacion.personal_id
        ).filter(
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin,
            Planificacion.observacion.isnot(None)
        ).all()
        
        personal_con_obs = [
            {
                "personal_id": str(o.personal_id),
                "nombre": o.personal_nombre,
                "fecha": o.fecha.isoformat(),
                "observacion": o.observacion
            }
            for o in observaciones
        ]
        
        return {
            "fecha": fecha_inicio.isoformat(),
            "total_turnos": total_turnos,
            "turnos_por_tipo": turnos_por_tipo,
            "personal_con_observaciones": personal_con_obs
        }
        
    except Exception as e:
        logger.error(f"❌ Error en obtener_estado_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# 🆕 NUEVOS ENDPOINTS PARA FLUJO DE APROBACIÓN POR ÁREA
# =====================================================

@router.post("/area/borrador")
async def guardar_borrador_area(
    area: str,
    mes: int,
    anio: int,
    datos: Dict,  # El JSON completo de la planificación del área
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["jefe_area"]))
):
    """
    Guarda el borrador de planificación de un área (CUBETA)
    Solo accesible para jefes de área
    """
    try:
        # 1. Verificar que el jefe pertenece al área que dice ser
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if not jefe or jefe.area != area:
            raise HTTPException(status_code=403, detail="No eres jefe de esta área")
        
        # 2. Validar que el mes es válido
        if mes < 1 or mes > 12:
            raise HTTPException(status_code=400, detail="Mes inválido")
        
        # 3. Fecha de referencia (primer día del mes)
        fecha_referencia = date(anio, mes, 1)
        
        # 4. Buscar si ya existe una solicitud para este mes
        solicitud_existente = db.query(SolicitudCambio).filter(
            SolicitudCambio.tipo == "planificacion_mensual",
            SolicitudCambio.empleado_id == current_user.personal_id,
            SolicitudCambio.fecha_cambio == fecha_referencia
        ).first()
        
        # 5. Extraer el array de datos
        if isinstance(datos, dict) and 'datos' in datos:
            datos_array = datos['datos']
        else:
            datos_array = datos
        
        if solicitud_existente:
            # Actualizar el existente
            solicitud_existente.turno_original = datos_array
            solicitud_existente.estado = "borrador"  # Resetear a borrador
            if hasattr(solicitud_existente, 'updated_at'):
                solicitud_existente.updated_at = datetime.utcnow()
            
            # Agregar al historial
            if not solicitud_existente.historial:
                solicitud_existente.historial = []
            solicitud_existente.historial.append({
                "fecha": datetime.utcnow().isoformat(),
                "usuario": str(current_user.id),
                "accion": "actualización_borrador",
                "estado": "borrador",
                "registros": len(datos_array)
            })
            
            db.commit()
            
            logger.info(f"✅ Borrador actualizado: {len(datos_array)} registros")
            
            return {
                "message": "Borrador actualizado exitosamente",
                "id": str(solicitud_existente.id),
                "estado": solicitud_existente.estado,
                "registros": len(datos_array)
            }
        else:
            # Crear nuevo borrador
            nueva_solicitud = SolicitudCambio(
                tipo="planificacion_mensual",
                estado="borrador",
                fecha_cambio=fecha_referencia,
                motivo="ENVIO_MENSUAL",
                empleado_id=current_user.personal_id,
                turno_original=datos_array,
                historial=[{
                    "fecha": datetime.utcnow().isoformat(),
                    "usuario": str(current_user.id),
                    "accion": "creación_borrador",
                    "estado": "borrador",
                    "registros": len(datos_array)
                }],
                created_by=current_user.id
            )
            
            db.add(nueva_solicitud)
            db.commit()
            db.refresh(nueva_solicitud)
            
            logger.info(f"✅ Nuevo borrador creado: {len(datos_array)} registros")
            
            return {
                "message": "Borrador creado exitosamente",
                "id": str(nueva_solicitud.id),
                "estado": nueva_solicitud.estado,
                "registros": len(datos_array)
            }
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en guardar_borrador_area: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.post("/area/enviar-revision")
async def enviar_planificacion_revision(
    area: str,
    mes: int,
    anio: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["jefe_area"]))
):
    """
    Envía la planificación del área a revisión (CUBETA → BANDEJA)
    """
    try:
        # 1. Verificar que el jefe pertenece al área
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if not jefe or jefe.area != area:
            raise HTTPException(status_code=403, detail="No eres jefe de esta área")
        
        # 2. Fecha de referencia
        fecha_referencia = date(anio, mes, 1)
        
        # 3. Buscar el borrador actual
        solicitud = db.query(SolicitudCambio).filter(
            SolicitudCambio.tipo == "planificacion_mensual",
            SolicitudCambio.empleado_id == current_user.personal_id,
            SolicitudCambio.fecha_cambio == fecha_referencia,
            SolicitudCambio.estado == "borrador"
        ).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="No hay borrador para enviar")
        
        # 4. Cambiar estado a pendiente
        solicitud.estado = "pendiente"
        
        # 5. Agregar al historial
        if not solicitud.historial:
            solicitud.historial = []
        solicitud.historial.append({
            "fecha": datetime.utcnow().isoformat(),
            "usuario": str(current_user.id),
            "accion": "envío_a_revisión",
            "estado": "pendiente"
        })
        
        db.commit()
        
        logger.info(f"✅ Solicitud {solicitud.id} enviada a revisión. Nuevo estado: {solicitud.estado}")
        
        return {
            "message": "Planificación enviada a revisión exitosamente",
            "id": str(solicitud.id),
            "estado": solicitud.estado
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en enviar_planificacion_revision: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.get("/area/borrador/{anio}/{mes}")
async def obtener_borrador_area(
    anio: int,
    mes: int,
    area: Optional[str] = Query(None, description="Área (opcional, usa la del jefe si no se proporciona)"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["jefe_area"]))
):
    """
    Obtiene el borrador actual del área - VERSIÓN ULTRA OPTIMIZADA
    """
    try:
        # 1. Obtener el área del jefe (UNA SOLA CONSULTA - SOLO CAMPOS NECESARIOS)
        jefe = db.query(Personal.id, Personal.area).filter(
            Personal.id == current_user.personal_id
        ).first()
        
        if not jefe:
            raise HTTPException(status_code=404, detail="Jefe no encontrado")
        
        area_consulta = area if area else jefe.area
        fecha_referencia = date(anio, mes, 1)
        
        # 2. CLAVE DE CACHÉ ÚNICA
        cache_key = f"borrador_{area_consulta}_{anio}_{mes}_{current_user.personal_id}"
        cached = planificacion_cache.get(cache_key)
        if cached:
            logger.info(f"📦 Cache hit: {cache_key}")
            return cached
        
        logger.info(f"🔄 Cache miss: {cache_key} - Consultando BD...")
        start_time = datetime.now()
        
        # 3. CONSULTA ÚNICA Y OPTIMIZADA - SOLO CAMPOS NECESARIOS CON PRIORIDAD
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
        ).order_by(
            # Prioridad: pendiente > rechazada > aprobada > borrador
            case(
                (SolicitudCambio.estado == 'pendiente', 1),
                (SolicitudCambio.estado == 'rechazada', 2),
                (SolicitudCambio.estado == 'aprobada', 3),
                else_=4
            ),
            SolicitudCambio.created_at.desc()
        ).first()
        
        if not solicitud:
            logger.info(f"📭 No existe borrador para {area_consulta}/{anio}/{mes}")
            result = {
                "existe": False,
                "datos": [],
                "estado": "borrador",
                "area": area_consulta,
                "mes": mes,
                "anio": anio
            }
            # Cache corto para no existentes
            planificacion_cache.set(cache_key, result, timeout=60)
            return result
        
        # 4. Extraer datos de forma ultra rápida
        datos_array = []
        if solicitud.turno_original:
            if isinstance(solicitud.turno_original, list):
                datos_array = solicitud.turno_original
            elif isinstance(solicitud.turno_original, dict) and 'datos' in solicitud.turno_original:
                datos_array = solicitud.turno_original['datos']
        
        query_time = (datetime.now() - start_time).total_seconds() * 1000
        
        result = {
            "existe": True,
            "id": str(solicitud.id),
            "estado": solicitud.estado,
            "datos": datos_array,
            "fecha_creacion": solicitud.created_at.isoformat() if solicitud.created_at else None,
            "area": area_consulta,
            "mes": mes,
            "anio": anio,
            "comentario_revision": solicitud.comentario_revision
        }
        
        # 5. Guardar en caché
        planificacion_cache.set(cache_key, result, timeout=300)  # 5 minutos
        
        logger.info(f"✅ Borrador obtenido en {query_time:.2f}ms - {len(datos_array)} registros")
        return result
        
    except Exception as e:
        logger.error(f"❌ Error en obtener_borrador_area: {str(e)}")
        import traceback
        traceback.print_exc()
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
# MI HORARIO PERSONAL - ENDPOINTS EXISTENTES
# =====================================================

@router.get("/mi-horario/{anio}/{mes}")
async def get_mi_horario(
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene el horario personal del usuario autenticado
    """
    try:
        if mes < 1 or mes > 12:
            raise HTTPException(status_code=400, detail="Mes inválido")
        
        personal_id = current_user.personal_id
        if not personal_id:
            raise HTTPException(status_code=404, detail="Usuario no tiene personal asociado")
        
        fecha_inicio = date(anio, mes, 1)
        if mes == 12:
            fecha_fin = date(anio + 1, 1, 1)
        else:
            fecha_fin = date(anio, mes + 1, 1)
        
        # Consulta optimizada - solo campos necesarios
        planificaciones = db.query(
            Planificacion.fecha,
            Planificacion.turno_codigo,
            Planificacion.dm_info
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        ).order_by(Planificacion.fecha).all()
        
        return [
            {
                "fecha": p.fecha.isoformat(),
                "turno_codigo": p.turno_codigo,
                "dm_info": p.dm_info
            }
            for p in planificaciones
        ]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en get_mi_horario: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.get("/mi-horario/{anio}/{mes}/estadisticas")
async def get_mi_estadisticas(
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtiene estadísticas del horario personal del usuario autenticado
    """
    try:
        personal_id = current_user.personal_id
        if not personal_id:
            raise HTTPException(status_code=404, detail="Usuario no tiene personal asociado")
        
        fecha_inicio = date(anio, mes, 1)
        if mes == 12:
            fecha_fin = date(anio + 1, 1, 1)
        else:
            fecha_fin = date(anio, mes + 1, 1)
        
        # Estadísticas con agrupación
        stats = db.query(
            Planificacion.turno_codigo,
            func.count(Planificacion.id).label('cantidad')
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        ).group_by(
            Planificacion.turno_codigo
        ).all()
        
        turnos_por_tipo = {s.turno_codigo: s.cantidad for s in stats}
        total_turnos = sum(turnos_por_tipo.values())
        descansos = turnos_por_tipo.get('FR', 0)
        guardias = turnos_por_tipo.get('12M', 0) + turnos_por_tipo.get('12N', 0)
        
        return {
            "total_turnos": total_turnos,
            "descansos": descansos,
            "guardias": guardias,
            "turnos_por_tipo": turnos_por_tipo,
            "mes": mes,
            "anio": anio
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en get_mi_estadisticas: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# ENDPOINTS PÚBLICOS (para solicitudes de intercambio)
# =====================================================

@router.get("/publico/personal/{personal_id}")
async def obtener_planificacion_publica_personal(
    personal_id: UUID,
    inicio: date = Query(..., description="Fecha inicio"),
    fin: date = Query(..., description="Fecha fin"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    ENDPOINT PÚBLICO: Obtiene la planificación de un personal en un rango de fechas
    """
    try:
        # Verificar que el personal existe
        personal = db.query(Personal).filter(Personal.id == personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        # Consultar planificación
        planificaciones = db.query(
            Planificacion.fecha,
            Planificacion.turno_codigo,
            Planificacion.observacion,
            Planificacion.dm_info
        ).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= inicio,
            Planificacion.fecha <= fin
        ).order_by(Planificacion.fecha).all()
        
        # Convertir a diccionario por fecha
        resultado = {}
        for p in planificaciones:
            resultado[p.fecha.isoformat()] = {
                "turno_codigo": p.turno_codigo,
                "observacion": p.observacion,
                "dm_info": p.dm_info
            }
        
        return resultado
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en obtener_planificacion_publica_personal: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# ENDPOINTS PARA ELIMINACIÓN (Solo admin)
# =====================================================

@router.delete("/{planificacion_id}", status_code=204)
async def eliminar_planificacion(
    planificacion_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    Elimina una planificación específica
    """
    try:
        planificacion = db.query(Planificacion).filter(Planificacion.id == planificacion_id).first()
        
        if not planificacion:
            raise HTTPException(status_code=404, detail="Planificación no encontrada")
        
        # Guardar fecha para limpiar caché
        fecha = planificacion.fecha
        
        db.delete(planificacion)
        db.commit()
        
        # Limpiar caché del mes afectado
        planificacion_cache.invalidate_for_mes(fecha.year, fecha.month)
        
        return None
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en eliminar_planificacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


@router.delete("/personal/{personal_id}/mes/{anio}/{mes}", status_code=204)
async def eliminar_planificacion_mensual(
    personal_id: UUID,
    anio: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    Elimina toda la planificación de un personal en un mes específico
    """
    try:
        fecha_inicio = date(anio, mes, 1)
        if mes == 12:
            fecha_fin = date(anio + 1, 1, 1)
        else:
            fecha_fin = date(anio, mes + 1, 1)
        
        db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin
        ).delete(synchronize_session=False)
        
        db.commit()
        
        # Limpiar caché del mes afectado
        planificacion_cache.invalidate_for_mes(anio, mes)
        
        return None
        
    except Exception as e:
        logger.error(f"❌ Error en eliminar_planificacion_mensual: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error interno del servidor: {str(e)}")


# =====================================================
# ENDPOINT PARA VERIFICAR SALUD DEL SERVICIO
# =====================================================
@router.get("/health")
async def health_check():
    """Endpoint para verificar que el servicio está funcionando"""
    return {
        "status": "healthy",
        "service": "planificacion",
        "timestamp": datetime.utcnow().isoformat(),
        "cache_stats": {
            "size": len(planificacion_cache._cache),
            "keys": list(planificacion_cache._cache.keys())[:5]  # Solo primeros 5
        }
    }