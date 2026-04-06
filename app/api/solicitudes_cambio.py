# D:\Por si fallamos en la actualizacion\back\app\api\solicitudes_cambio.py
# VERSIÓN COMPLETA CORREGIDA - CON SOPORTE PARA VACACIONES, TIMEDELTA E HISTORIAL
# ✅ CORREGIDO: Endpoints específicos ANTES que rutas dinámicas /{id}

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc
from typing import List, Optional
from datetime import datetime, date, timedelta
from uuid import UUID
import json
import logging
from app.models.usuario import Usuario

from app.database import get_db
from app.core.dependencies import require_roles
from app.models.solicitud_cambio import SolicitudCambio
from app.models.personal import Personal
from app.models.planificacion import Planificacion
from app.models.planificacion_borrador import PlanificacionBorrador
from app.schemas.solicitud_cambio import (
    SolicitudCambioResponse, SolicitudCambioUpdate
)
from app.utils.file_handler import save_upload_file
from app.utils.validators import validar_dias_franco_consecutivos, validar_disponibilidad_turno

# Configurar logger
logger = logging.getLogger(__name__)

router = APIRouter()

# =====================================================
# FUNCIÓN AUXILIAR PARA EXTRAER CÓDIGO DE TURNO
# =====================================================
def extraer_codigo_turno(turno):
    """
    Extrae el código del turno sin importar si es string o diccionario
    """
    if not turno:
        return None
    if isinstance(turno, dict):
        return turno.get("codigo")
    return str(turno)

# =====================================================
# FUNCIÓN AUXILIAR PARA OBTENER NOMBRE DE USUARIO
# =====================================================
def obtener_nombre_usuario(db, usuario):
    """
    Obtiene el nombre del usuario desde la tabla Personal
    """
    if not usuario:
        return "Sistema"
    
    if usuario.personal_id:
        personal = db.query(Personal).filter(Personal.id == usuario.personal_id).first()
        if personal and personal.nombre:
            return personal.nombre
    
    return usuario.email or "Sistema"

# =====================================================
# 🆕 FUNCIÓN PARA MARCAR VACACIONES EN PLANIFICACIÓN (CORREGIDA CON TIMEDELTA)
# =====================================================
def marcar_vacaciones_en_planificacion(db: Session, empleado_id: UUID, fecha_inicio: date, fecha_fin: date, usuario_id: UUID):
    """
    Marca todos los días del período como VAC en la planificación
    Usa timedelta para incrementar fechas correctamente entre meses
    """
    try:
        logger.info(f"🏖️ Marcando vacaciones para empleado {empleado_id} del {fecha_inicio} al {fecha_fin}")
        
        fecha_actual = fecha_inicio
        dias_marcados = 0
        errores = 0
        
        while fecha_actual <= fecha_fin:
            try:
                # Buscar si ya existe planificación para esta fecha
                planificacion_existente = db.query(Planificacion).filter(
                    Planificacion.personal_id == empleado_id,
                    Planificacion.fecha == fecha_actual
                ).first()
                
                if planificacion_existente:
                    # Actualizar turno existente
                    planificacion_existente.turno_codigo = "VAC"
                    planificacion_existente.updated_at = datetime.utcnow()
                    logger.info(f"   ✅ Actualizado {fecha_actual} → VAC")
                else:
                    # Crear nueva planificación
                    nueva_planificacion = Planificacion(
                        personal_id=empleado_id,
                        fecha=fecha_actual,
                        turno_codigo="VAC",
                        created_by=usuario_id
                    )
                    db.add(nueva_planificacion)
                    logger.info(f"   ✅ Creado {fecha_actual} → VAC")
                
                dias_marcados += 1
                
            except Exception as e:
                logger.error(f"   ❌ Error en fecha {fecha_actual}: {e}")
                errores += 1
            
            # ✅ INCREMENTAR FECHA CORRECTAMENTE CON TIMEDELTA (cruza meses correctamente)
            fecha_actual = fecha_actual + timedelta(days=1)
        
        db.flush()
        logger.info(f"✅ Marcados {dias_marcados} días como VAC (errores: {errores})")
        return dias_marcados
        
    except Exception as e:
        logger.error(f"❌ Error marcando vacaciones: {e}")
        import traceback
        traceback.print_exc()
        return 0

# =====================================================
# FUNCIÓN AUXILIAR PARA OBTENER CADENA JERÁRQUICA
# =====================================================
def obtener_cadena_jerarquica(area):
    """
    Determina la cadena de aprobación según el área del solicitante
    """
    if not area:
        return ['jefe_area', 'jefe_direccion']
    
    area_upper = area.upper()
    
    # Emergencia tiene estructura completa
    if 'EMERGENCIA' in area_upper:
        return ['jefe_grupo', 'jefe_area', 'jefe_departamento', 'jefe_direccion']
    
    # Áreas médicas con estructura de 3 niveles
    if any(med in area_upper for med in ['HOSPITALIZACION', 'CIRUGIA', 'MEDICINA', 'CARDIOLOGIA', 'NEUROLOGIA']):
        return ['jefe_area', 'jefe_departamento', 'jefe_direccion']
    
    # Divisiones y departamentos
    if any(div in area_upper for div in ['DIVISION', 'DEPARTAMENTO']):
        return ['jefe_departamento', 'jefe_direccion']
    
    # Para todas las demás áreas
    return ['jefe_area', 'jefe_direccion']

# =====================================================
# FUNCIÓN AUXILIAR PARA FORMATEAR SOLICITUDES
# =====================================================
def formatear_solicitud(s):
    """Formatea una solicitud para respuesta JSON"""
    return {
        "id": s.id,
        "tipo": s.tipo,
        "estado": s.estado,
        "fecha_solicitud": s.fecha_solicitud,
        "fecha_cambio": s.fecha_cambio,
        "motivo": s.motivo,
        "observaciones": s.observaciones,
        "empleado_id": s.empleado_id,
        "empleado2_id": s.empleado2_id,
        "turno_original": s.turno_original,
        "turno_solicitado": s.turno_solicitado,
        "turno_original_solicitante": s.turno_original_solicitante,
        "turno_original_colega": s.turno_original_colega,
        "turno_solicitante_recibe": s.turno_solicitante_recibe,
        "turno_colega_recibe": s.turno_colega_recibe,
        "validacion_dias_libres": s.validacion_dias_libres,
        "documentos": s.documentos if s.documentos else [],
        "historial": s.historial if s.historial else [],
        "created_by": s.created_by,
        "created_at": s.created_at,
        "fecha_revision": s.fecha_revision,
        "revisado_por": s.revisado_por,
        "comentario_revision": s.comentario_revision,
        "nivel_actual": s.nivel_actual,
        "proximo_nivel": s.proximo_nivel,
        "niveles_pendientes": s.niveles_pendientes if s.niveles_pendientes else [],
        "niveles_aprobados": s.niveles_aprobados if s.niveles_aprobados else [],
        "empleado_nombre": s.empleado_rel.nombre if s.empleado_rel else None,
        "empleado_grado": s.empleado_rel.grado if s.empleado_rel else None,
        "area_nombre": s.empleado_rel.area if s.empleado_rel else None,
        "empleado2_nombre": s.empleado2_rel.nombre if s.empleado2_rel else None,
        "empleado2_grado": s.empleado2_rel.grado if s.empleado2_rel else None,
        # Campos de vacaciones
        "fecha_inicio": s.fecha_inicio.isoformat() if s.fecha_inicio else None,
        "fecha_fin": s.fecha_fin.isoformat() if s.fecha_fin else None,
        "dias_solicitados": s.dias_solicitados,
        "tipo_vacaciones": s.tipo_vacaciones
    }

# =====================================================
# =====================================================
# ✅ ENDPOINTS ESPECÍFICOS (SIN PARÁMETROS DINÁMICOS)
# =====================================================
# =====================================================

@router.get("/pendientes")
async def listar_pendientes(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion"]))
):
    """
    Lista las solicitudes pendientes que el usuario puede aprobar
    según su rol y nivel jerárquico.
    """
    try:
        # Admin puede ver todo
        if "admin" in current_user.roles:
            query = db.query(SolicitudCambio).filter(SolicitudCambio.estado == "pendiente")
            solicitudes = query.options(
                joinedload(SolicitudCambio.empleado_rel),
                joinedload(SolicitudCambio.empleado2_rel)
            ).order_by(SolicitudCambio.created_at.desc()).all()
            return [formatear_solicitud(s) for s in solicitudes]
        
        # Obtener información del usuario
        usuario = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if not usuario:
            raise HTTPException(status_code=403, detail="Usuario no encontrado")
        
        # Construir condiciones de filtro según roles
        condiciones = []
        
        # Jefe de área
        if "jefe_area" in current_user.roles:
            areas_jefatura = usuario.areas_que_jefatura if usuario.areas_que_jefatura else []
            
            if areas_jefatura:
                for area in areas_jefatura:
                    condiciones.append(
                        and_(
                            SolicitudCambio.proximo_nivel == "jefe_area",
                            Personal.area == area
                        )
                    )
        
        # Jefe de dirección
        if "jefe_direccion" in current_user.roles and usuario.area_que_jefatura_direccion:
            condiciones.append(
                and_(
                    SolicitudCambio.proximo_nivel == "jefe_direccion",
                    Personal.area == usuario.area_que_jefatura_direccion
                )
            )
        
        if not condiciones:
            return []
        
        # Aplicar filtros
        query = db.query(SolicitudCambio).filter(
            SolicitudCambio.estado == "pendiente"
        ).join(
            Personal, Personal.id == SolicitudCambio.empleado_id
        ).filter(or_(*condiciones))
        
        solicitudes = query.options(
            joinedload(SolicitudCambio.empleado_rel),
            joinedload(SolicitudCambio.empleado2_rel)
        ).order_by(SolicitudCambio.created_at.desc()).all()
        
        return [formatear_solicitud(s) for s in solicitudes]
        
    except Exception as e:
        logger.error(f"Error en listar_pendientes: {e}")
        raise HTTPException(status_code=500, detail=f"Error al cargar solicitudes pendientes: {str(e)}")

@router.get("/todas")
async def listar_todas_solicitudes(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion"]))
):
    """
    Lista TODAS las solicitudes (pendientes, aprobadas, rechazadas)
    Solo para administradores y jefes
    """
    try:
        solicitudes = db.query(SolicitudCambio).options(
            joinedload(SolicitudCambio.empleado_rel),
            joinedload(SolicitudCambio.empleado2_rel)
        ).order_by(SolicitudCambio.created_at.desc()).all()
        
        return [formatear_solicitud(s) for s in solicitudes]
        
    except Exception as e:
        logger.error(f"Error en listar_todas_solicitudes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/historial")
async def obtener_historial_solicitudes(
    tipo: Optional[str] = Query(None, description="Filtrar por tipo: propio, intercambio, vacaciones"),
    estado: Optional[str] = Query(None, description="Filtrar por estado: aprobada, rechazada"),
    mes: Optional[str] = Query(None, description="Filtrar por mes (YYYY-MM)"),
    busqueda: Optional[str] = Query(None, description="Búsqueda por nombre o área"),
    limit: int = Query(100, ge=1, le=500, description="Límite de registros"),
    offset: int = Query(0, ge=0, description="Número de registros a saltar"),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion", "usuario"]))
):
    """
    Obtiene el historial de solicitudes aprobadas y rechazadas
    """
    try:
        # Base: solicitudes aprobadas o rechazadas
        query = db.query(SolicitudCambio).filter(
            SolicitudCambio.estado.in_(["aprobada", "rechazada"])
        )
        
        # Filtrar por tipo
        if tipo and tipo != "todos":
            query = query.filter(SolicitudCambio.tipo == tipo)
        
        # Filtrar por estado
        if estado and estado != "todas":
            query = query.filter(SolicitudCambio.estado == estado)
        
        # Filtrar por mes
        if mes and mes != "todos":
            try:
                anio, mes_num = map(int, mes.split('-'))
                fecha_inicio = date(anio, mes_num, 1)
                if mes_num == 12:
                    fecha_fin = date(anio + 1, 1, 1)
                else:
                    fecha_fin = date(anio, mes_num + 1, 1)
                query = query.filter(SolicitudCambio.created_at >= fecha_inicio)
                query = query.filter(SolicitudCambio.created_at < fecha_fin)
            except:
                pass
        
        # Unir con Personal para búsqueda
        if busqueda:
            busqueda_lower = busqueda.lower()
            query = query.join(
                Personal, Personal.id == SolicitudCambio.empleado_id
            ).filter(
                or_(
                    Personal.nombre.ilike(f"%{busqueda}%"),
                    Personal.area.ilike(f"%{busqueda}%")
                )
            )
        else:
            query = query.options(
                joinedload(SolicitudCambio.empleado_rel),
                joinedload(SolicitudCambio.empleado2_rel)
            )
        
        # Contar total antes de paginar
        total = query.count()
        
        # Ordenar y paginar
        solicitudes = query.order_by(
            desc(SolicitudCambio.fecha_revision),
            desc(SolicitudCambio.created_at)
        ).offset(offset).limit(limit).all()
        
        result = []
        for s in solicitudes:
            solicitud_dict = formatear_solicitud(s)
            
            # Agregar campos específicos para historial
            solicitud_dict["fecha_resolucion"] = s.fecha_revision.isoformat() if s.fecha_revision else s.updated_at.isoformat() if hasattr(s, 'updated_at') and s.updated_at else None
            solicitud_dict["resuelto_por"] = None
            solicitud_dict["motivo_rechazo"] = s.comentario_revision if s.estado == "rechazada" else None
            solicitud_dict["tiempo_resolucion"] = None
            
            # Calcular tiempo de resolución si tenemos fechas
            if s.fecha_revision and s.created_at:
                tiempo = (s.fecha_revision - s.created_at).total_seconds() / 3600
                solicitud_dict["tiempo_resolucion"] = round(tiempo, 1)
            
            # Obtener nombre del resolutor
            if s.revisado_por:
                resolutor = db.query(Usuario).filter(Usuario.id == s.revisado_por).first()
                if resolutor:
                    personal_resolutor = db.query(Personal).filter(Personal.id == resolutor.personal_id).first()
                    solicitud_dict["resuelto_por"] = personal_resolutor.nombre if personal_resolutor else resolutor.email
            
            result.append(solicitud_dict)
        
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "data": result
        }
        
    except Exception as e:
        logger.error(f"Error en obtener_historial_solicitudes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/estadisticas/historial")
async def obtener_estadisticas_historial(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion"]))
):
    """
    Obtiene estadísticas del historial de solicitudes
    """
    try:
        solicitudes = db.query(SolicitudCambio).filter(
            SolicitudCambio.estado.in_(["aprobada", "rechazada"])
        ).all()
        
        total = len(solicitudes)
        aprobadas = len([s for s in solicitudes if s.estado == "aprobada"])
        rechazadas = len([s for s in solicitudes if s.estado == "rechazada"])
        tasa_aprobacion = round((aprobadas / total) * 100, 1) if total > 0 else 0
        
        # Por tipo
        por_tipo = {}
        tipos = ["propio", "intercambio", "vacaciones", "permiso"]
        for t in tipos:
            count = len([s for s in solicitudes if s.tipo == t])
            por_tipo[t] = count
        
        # Por mes (últimos 6 meses)
        por_mes = []
        from datetime import timedelta
        hoy = date.today()
        
        for i in range(6):
            fecha = hoy.replace(day=1) - timedelta(days=30 * i)
            mes_key = f"{fecha.year}-{fecha.month}"
            mes_label = fecha.strftime("%B %Y")
            
            mes_solicitudes = [
                s for s in solicitudes 
                if s.created_at and 
                s.created_at.year == fecha.year and 
                s.created_at.month == fecha.month
            ]
            
            por_mes.append({
                "mes": mes_key,
                "label": mes_label,
                "total": len(mes_solicitudes),
                "aprobadas": len([s for s in mes_solicitudes if s.estado == "aprobada"]),
                "rechazadas": len([s for s in mes_solicitudes if s.estado == "rechazada"])
            })
        
        return {
            "total": total,
            "aprobadas": aprobadas,
            "rechazadas": rechazadas,
            "tasa_aprobacion": tasa_aprobacion,
            "por_tipo": por_tipo,
            "por_mes": por_mes
        }
        
    except Exception as e:
        logger.error(f"Error en obtener_estadisticas_historial: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/planificaciones/pendientes")
async def listar_planificaciones_pendientes(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin"]))
):
    """
    Lista SOLO solicitudes de planificación mensual pendientes
    """
    try:
        solicitudes = db.query(SolicitudCambio).filter(
            SolicitudCambio.tipo == "planificacion_mensual",
            SolicitudCambio.estado == "pendiente"
        ).options(
            joinedload(SolicitudCambio.empleado_rel)
        ).order_by(SolicitudCambio.created_at.desc()).all()
        
        result = []
        for s in solicitudes:
            result.append({
                "id": str(s.id),
                "tipo": s.tipo,
                "estado": s.estado,
                "fecha_solicitud": s.fecha_solicitud.isoformat() if s.fecha_solicitud else None,
                "fecha_cambio": s.fecha_cambio.isoformat() if s.fecha_cambio else None,
                "motivo": s.motivo,
                "empleado_id": str(s.empleado_id) if s.empleado_id else None,
                "empleado_nombre": s.empleado_rel.nombre if s.empleado_rel else None,
                "empleado_grado": s.empleado_rel.grado if s.empleado_rel else None,
                "area_nombre": s.empleado_rel.area if s.empleado_rel else None,
                "datos": s.turno_original,
                "comentario_revision": s.comentario_revision,
                "historial": s.historial
            })
        
        logger.info(f"✅ {len(result)} planificaciones pendientes encontradas")
        return result
        
    except Exception as e:
        logger.error(f"Error en listar_planificaciones_pendientes: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/personal/{personal_id}", response_model=List[SolicitudCambioResponse])
async def listar_por_personal(
    personal_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Lista solicitudes de un personal específico
    """
    if "usuario" in current_user.roles and "admin" not in current_user.roles:
        if str(current_user.personal_id) != str(personal_id):
            raise HTTPException(status_code=403, detail="No autorizado")
    
    try:
        solicitudes = db.query(SolicitudCambio).filter(
            or_(
                SolicitudCambio.empleado_id == personal_id,
                SolicitudCambio.empleado2_id == personal_id
            )
        ).options(
            joinedload(SolicitudCambio.empleado_rel),
            joinedload(SolicitudCambio.empleado2_rel)
        ).order_by(SolicitudCambio.created_at.desc()).all()
        
        result = []
        for s in solicitudes:
            empleado = s.empleado_rel
            result.append({
                "id": s.id,
                "tipo": s.tipo,
                "estado": s.estado,
                "fecha_solicitud": s.fecha_solicitud,
                "fecha_cambio": s.fecha_cambio,
                "motivo": s.motivo,
                "observaciones": s.observaciones,
                "empleado_id": s.empleado_id,
                "empleado2_id": s.empleado2_id,
                "turno_original": s.turno_original,
                "turno_solicitado": s.turno_solicitado,
                "turno_original_solicitante": s.turno_original_solicitante,
                "turno_original_colega": s.turno_original_colega,
                "turno_solicitante_recibe": s.turno_solicitante_recibe,
                "turno_colega_recibe": s.turno_colega_recibe,
                "validacion_dias_libres": s.validacion_dias_libres,
                "documentos": s.documentos if s.documentos else [],
                "historial": s.historial if s.historial else [],
                "created_by": s.created_by,
                "created_at": s.created_at,
                "fecha_revision": s.fecha_revision,
                "revisado_por": s.revisado_por,
                "comentario_revision": s.comentario_revision,
                "nivel_actual": s.nivel_actual,
                "proximo_nivel": s.proximo_nivel,
                "niveles_pendientes": s.niveles_pendientes if s.niveles_pendientes else [],
                "niveles_aprobados": s.niveles_aprobados if s.niveles_aprobados else [],
                "empleado_nombre": empleado.nombre if empleado else None,
                "empleado_grado": empleado.grado if empleado else None,
                "area_nombre": empleado.area if empleado else None,
                "empleado2_nombre": s.empleado2_rel.nombre if s.empleado2_rel else None,
                "empleado2_grado": s.empleado2_rel.grado if s.empleado2_rel else None,
                "fecha_inicio": s.fecha_inicio.isoformat() if s.fecha_inicio else None,
                "fecha_fin": s.fecha_fin.isoformat() if s.fecha_fin else None,
                "dias_solicitados": s.dias_solicitados,
                "tipo_vacaciones": s.tipo_vacaciones
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error en listar_por_personal: {e}")
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================
# =====================================================
# ✅ ENDPOINTS CON PARÁMETROS DINÁMICOS (AL FINAL)
# =====================================================
# =====================================================

@router.post("/planificacion/{solicitud_id}/aprobar")
async def aprobar_planificacion_mensual(
    solicitud_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    APRUEBA una planificación de área
    """
    try:
        solicitud = db.query(SolicitudCambio).filter(
            SolicitudCambio.id == solicitud_id,
            SolicitudCambio.tipo == "planificacion_mensual"
        ).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud de planificación no encontrada")
        
        if solicitud.estado != "pendiente":
            raise HTTPException(status_code=400, detail=f"La solicitud ya está {solicitud.estado}")
        
        datos_horario = solicitud.turno_original
        if not datos_horario or not isinstance(datos_horario, list):
            raise HTTPException(status_code=400, detail="La solicitud no contiene datos de planificación válidos")
        
        logger.info(f"📦 Procesando {len(datos_horario)} registros de planificación")
        
        jefe = db.query(Personal).filter(Personal.id == solicitud.empleado_id).first()
        if not jefe or not jefe.area:
            raise HTTPException(status_code=400, detail="No se pudo determinar el área del solicitante")
        
        area = jefe.area
        mes = solicitud.fecha_cambio.month
        anio = solicitud.fecha_cambio.year
        
        logger.info(f"📍 Área: {area}, Mes: {mes}/{anio}")
        
        fecha_inicio = date(anio, mes, 1)
        if mes == 12:
            fecha_fin = date(anio + 1, 1, 1)
        else:
            fecha_fin = date(anio, mes + 1, 1)
        
        borrador = db.query(PlanificacionBorrador).filter(
            PlanificacionBorrador.area == area,
            PlanificacionBorrador.mes == mes,
            PlanificacionBorrador.año == anio
        ).first()
        
        if borrador:
            logger.info(f"📋 Borrador encontrado, actualizando estado a aprobado")
            borrador.estado = 'aprobado'
            borrador.fecha_aprobacion = datetime.utcnow()
            borrador.datos = datos_horario
        else:
            logger.info(f"📋 Creando nuevo registro de borrador aprobado")
            borrador = PlanificacionBorrador(
                area=area,
                mes=mes,
                año=anio,
                estado='aprobado',
                datos=datos_horario,
                fecha_aprobacion=datetime.utcnow(),
                creado_por=solicitud.empleado_id,
                fecha_envio=solicitud.fecha_solicitud
            )
            db.add(borrador)
        
        personal_del_area = db.query(Personal.id).filter(Personal.area == area).subquery()
        
        eliminados = db.query(Planificacion).filter(
            Planificacion.fecha >= fecha_inicio,
            Planificacion.fecha < fecha_fin,
            Planificacion.personal_id.in_(personal_del_area)
        ).delete(synchronize_session=False)
        
        logger.info(f"🗑️ Eliminados {eliminados} registros anteriores")
        
        registros_creados = 0
        errores = 0
        
        mapa_turnos = {
            'M': 'MAN', 'T': 'TAR', 'N': 'NOC',
            'F': 'FRA', 'V': 'VAC', 'D': 'DM',
            'L': 'LIB', '24': 'DIA24', 'D24': 'DIA24'
        }
        
        for idx, registro in enumerate(datos_horario):
            try:
                if not registro.get('personal_id') or not registro.get('fecha') or not registro.get('turno_codigo'):
                    logger.warning(f"⚠️ Registro {idx} inválido: {registro}")
                    errores += 1
                    continue
                
                turno_codigo = registro['turno_codigo']
                if turno_codigo in mapa_turnos:
                    turno_codigo = mapa_turnos[turno_codigo]
                    logger.debug(f"🔄 Normalizado: {registro['turno_codigo']} -> {turno_codigo}")
                
                nuevo = Planificacion(
                    personal_id=UUID(registro["personal_id"]) if isinstance(registro["personal_id"], str) else registro["personal_id"],
                    fecha=date.fromisoformat(registro["fecha"]) if isinstance(registro["fecha"], str) else registro["fecha"],
                    turno_codigo=turno_codigo,
                    observacion=registro.get("observacion"),
                    dm_info=registro.get("dm_info"),
                    created_by=current_user.id
                )
                db.add(nuevo)
                registros_creados += 1
                
            except Exception as e:
                logger.error(f"❌ Error insertando registro {idx}: {e}")
                errores += 1
                continue
        
        solicitud.estado = "aprobada"
        solicitud.fecha_revision = datetime.utcnow()
        solicitud.revisado_por = current_user.id
        solicitud.nivel_actual = "aprobada"
        
        if not solicitud.historial:
            solicitud.historial = []
        
        usuario_nombre = obtener_nombre_usuario(db, current_user)
        
        solicitud.historial.append({
            "fecha": datetime.utcnow().isoformat(),
            "usuario": str(current_user.id),
            "usuario_nombre": usuario_nombre,
            "nivel": "admin",
            "accion": "aprobación_planificación",
            "estado": "aprobada",
            "registros_creados": registros_creados,
            "errores": errores,
            "total": len(datos_horario)
        })
        
        db.commit()
        
        try:
            from app.api.planificacion import planificacion_cache
            planificacion_cache.invalidate_for_mes(anio, mes)
        except ImportError:
            pass
        
        resultado = {
            "message": "Planificación aprobada exitosamente",
            "solicitud_id": str(solicitud.id),
            "area": area,
            "mes": mes,
            "anio": anio,
            "registros_procesados": len(datos_horario),
            "registros_creados": registros_creados,
            "errores": errores
        }
        
        logger.info(f"✅ {resultado}")
        return resultado
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en aprobar_planificacion_mensual: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

@router.post("/planificacion/{solicitud_id}/rechazar")
async def rechazar_planificacion_mensual(
    solicitud_id: UUID,
    comentario: str = Query(..., description="Motivo del rechazo"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    RECHAZA una planificación de área - PRESERVA los datos
    """
    try:
        solicitud = db.query(SolicitudCambio).filter(
            SolicitudCambio.id == solicitud_id,
            SolicitudCambio.tipo == "planificacion_mensual"
        ).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud de planificación no encontrada")
        
        if solicitud.estado != "pendiente":
            raise HTTPException(status_code=400, detail=f"La solicitud ya está {solicitud.estado}")
        
        jefe = db.query(Personal).filter(Personal.id == solicitud.empleado_id).first()
        if not jefe or not jefe.area:
            raise HTTPException(status_code=400, detail="No se pudo determinar el área del solicitante")
        
        area = jefe.area
        mes = solicitud.fecha_cambio.month
        anio = solicitud.fecha_cambio.year
        
        logger.info(f"📝 Rechazando planificación para área: {area}, mes: {mes}/{anio}")
        logger.info(f"💬 Motivo: {comentario}")
        
        borrador = db.query(PlanificacionBorrador).filter(
            PlanificacionBorrador.area == area,
            PlanificacionBorrador.mes == mes,
            PlanificacionBorrador.año == anio
        ).first()
        
        if borrador:
            logger.info(f"📋 Borrador encontrado con ID: {borrador.id}")
            borrador.estado = 'rechazado'
            borrador.comentario_rechazo = comentario
            logger.info(f"✅ Borrador actualizado a estado: rechazado")
            logger.info(f"✅ Datos preservados: {len(borrador.datos) if borrador.datos else 0} registros")
            
        else:
            logger.warning("⚠️ No se encontró borrador, creando uno nuevo desde la solicitud")
            
            if not solicitud.turno_original:
                logger.error("❌ La solicitud no tiene datos en turno_original")
                raise HTTPException(status_code=400, detail="La solicitud no contiene datos de planificación")
            
            logger.info(f"📦 Creando borrador con {len(solicitud.turno_original)} registros")
            
            borrador = PlanificacionBorrador(
                area=area,
                mes=mes,
                año=anio,
                estado='rechazado',
                datos=solicitud.turno_original,
                creado_por=solicitud.empleado_id,
                fecha_envio=solicitud.fecha_solicitud,
                comentario_rechazo=comentario
            )
            db.add(borrador)
            logger.info(f"✅ Borrador creado con {len(solicitud.turno_original)} registros")
        
        solicitud.estado = "rechazada"
        solicitud.fecha_revision = datetime.utcnow()
        solicitud.revisado_por = current_user.id
        solicitud.comentario_revision = comentario
        solicitud.nivel_actual = "rechazada"
        
        if not solicitud.historial:
            solicitud.historial = []
        
        usuario_nombre = obtener_nombre_usuario(db, current_user)
        
        solicitud.historial.append({
            "fecha": datetime.utcnow().isoformat(),
            "usuario": str(current_user.id),
            "usuario_nombre": usuario_nombre,
            "nivel": "admin",
            "accion": "rechazo_planificación",
            "estado": "rechazada",
            "comentario": comentario,
            "datos_preservados": True,
            "registros": len(borrador.datos) if borrador.datos else 0
        })
        
        db.commit()
        
        logger.info(f"✅ Planificación {solicitud_id} rechazada - DATOS PRESERVADOS")
        
        return {
            "message": "Planificación rechazada - los datos se han preservado",
            "solicitud_id": str(solicitud.id),
            "estado": solicitud.estado,
            "comentario": comentario,
            "datos_preservados": True,
            "area": area,
            "mes": mes,
            "anio": anio,
            "registros": len(borrador.datos) if borrador.datos else 0
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en rechazar_planificacion_mensual: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/")
async def crear_solicitud(
    data: str = Form(...),
    archivos: List[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "usuario"]))
):
    """
    Crea una nueva solicitud (vacaciones, cambio de turno, intercambio, etc.)
    """
    try:
        solicitud_data = json.loads(data)
        fecha_cambio = date.fromisoformat(solicitud_data["fecha_cambio"])
        
        # Extraer campos de vacaciones
        fecha_inicio = solicitud_data.get("fecha_inicio")
        fecha_fin = solicitud_data.get("fecha_fin")
        dias_solicitados = solicitud_data.get("dias_solicitados")
        tipo_vacaciones = solicitud_data.get("tipo_vacaciones")
        
        # También buscar dentro del campo "datos" (por compatibilidad)
        if not fecha_inicio and solicitud_data.get("datos"):
            datos_extra = solicitud_data.get("datos", {})
            fecha_inicio = datos_extra.get("fecha_inicio")
            fecha_fin = datos_extra.get("fecha_fin")
            dias_solicitados = datos_extra.get("dias_solicitados")
            tipo_vacaciones = datos_extra.get("tipo_vacaciones")
        
        logger.info(f"📥 Campos de vacaciones: fecha_inicio={fecha_inicio}, fecha_fin={fecha_fin}, dias={dias_solicitados}, tipo={tipo_vacaciones}")
        
        # Convertir fechas de vacaciones
        fecha_inicio_date = None
        fecha_fin_date = None
        if fecha_inicio:
            try:
                fecha_inicio_date = date.fromisoformat(fecha_inicio)
            except:
                pass
        if fecha_fin:
            try:
                fecha_fin_date = date.fromisoformat(fecha_fin)
            except:
                pass
        
        empleado = db.query(Personal).filter(Personal.id == solicitud_data["empleado_id"]).first()
        area_empleado = empleado.area if empleado else None
        cadena_jerarquica = obtener_cadena_jerarquica(area_empleado)
        
        # VALIDACIONES (solo para cambios de turno e intercambio)
        if solicitud_data["tipo"] in ["propio", "intercambio"]:
            if solicitud_data["tipo"] == "propio":
                if not validar_disponibilidad_turno(db, solicitud_data["empleado_id"], fecha_cambio):
                    raise HTTPException(status_code=400, detail="El empleado no tiene turno asignado en esa fecha")
                
                turno_solicitado = solicitud_data.get("turno_solicitado")
                turnos_simulados = {}
                codigo_turno = extraer_codigo_turno(turno_solicitado)
                if codigo_turno:
                    turnos_simulados = {fecha_cambio.isoformat(): codigo_turno}
                
                valido, msg = validar_dias_franco_consecutivos(db, solicitud_data["empleado_id"], fecha_cambio, turnos_simulados)
                if not valido:
                    raise HTTPException(status_code=400, detail=msg)
            
            elif solicitud_data["tipo"] == "intercambio":
                if not validar_disponibilidad_turno(db, solicitud_data["empleado_id"], fecha_cambio):
                    raise HTTPException(status_code=400, detail="El solicitante no tiene turno asignado en esa fecha")
                
                if not validar_disponibilidad_turno(db, solicitud_data.get("empleado2_id"), fecha_cambio):
                    raise HTTPException(status_code=400, detail="El colega no tiene turno asignado en esa fecha")
                
                turno_colega_recibe = solicitud_data.get("turno_colega_recibe")
                turnos_simulados_sol = {}
                codigo_colega_recibe = extraer_codigo_turno(turno_colega_recibe)
                if codigo_colega_recibe:
                    turnos_simulados_sol = {fecha_cambio.isoformat(): codigo_colega_recibe}
                
                valido_sol, msg_sol = validar_dias_franco_consecutivos(db, solicitud_data["empleado_id"], fecha_cambio, turnos_simulados_sol)
                
                turno_solicitante_recibe = solicitud_data.get("turno_solicitante_recibe")
                turnos_simulados_col = {}
                codigo_solicitante_recibe = extraer_codigo_turno(turno_solicitante_recibe)
                if codigo_solicitante_recibe:
                    turnos_simulados_col = {fecha_cambio.isoformat(): codigo_solicitante_recibe}
                
                valido_col, msg_col = validar_dias_franco_consecutivos(db, solicitud_data["empleado2_id"], fecha_cambio, turnos_simulados_col)
                
                if not valido_sol:
                    raise HTTPException(status_code=400, detail=f"Solicitante: {msg_sol}")
                if not valido_col:
                    raise HTTPException(status_code=400, detail=f"Colega: {msg_col}")
        
        # PROCESAR DOCUMENTOS
        documentos = []
        if archivos:
            for archivo in archivos:
                url = await save_upload_file(archivo, subfolder="solicitudes")
                documentos.append({
                    "nombre": archivo.filename,
                    "url": url,
                    "tipo": archivo.content_type,
                    "fecha_subida": datetime.utcnow().isoformat()
                })
        
        usuario_nombre = obtener_nombre_usuario(db, current_user)
        
        # Crear solicitud con campos de vacaciones
        solicitud = SolicitudCambio(
            tipo=solicitud_data["tipo"],
            fecha_cambio=fecha_cambio,
            motivo=solicitud_data["motivo"],
            observaciones=solicitud_data.get("observaciones"),
            empleado_id=solicitud_data["empleado_id"],
            empleado2_id=solicitud_data.get("empleado2_id"),
            turno_original=solicitud_data.get("turno_original"),
            turno_solicitado=solicitud_data.get("turno_solicitado"),
            turno_original_solicitante=solicitud_data.get("turno_original_solicitante"),
            turno_original_colega=solicitud_data.get("turno_original_colega"),
            turno_solicitante_recibe=solicitud_data.get("turno_solicitante_recibe"),
            turno_colega_recibe=solicitud_data.get("turno_colega_recibe"),
            validacion_dias_libres=solicitud_data.get("validacion_dias_libres"),
            documentos=documentos,
            # Campos de vacaciones
            fecha_inicio=fecha_inicio_date,
            fecha_fin=fecha_fin_date,
            dias_solicitados=dias_solicitados,
            tipo_vacaciones=tipo_vacaciones,
            nivel_actual="usuario",
            proximo_nivel=cadena_jerarquica[0] if cadena_jerarquica else None,
            niveles_pendientes=cadena_jerarquica,
            niveles_aprobados=[],
            historial=[{
                "fecha": datetime.utcnow().isoformat(),
                "usuario": str(current_user.id),
                "usuario_nombre": usuario_nombre,
                "nivel": "usuario",
                "accion": "creación",
                "estado": "pendiente"
            }],
            created_by=current_user.id
        )
        
        db.add(solicitud)
        db.commit()
        db.refresh(solicitud)
        
        return formatear_solicitud(solicitud)
        
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Error en formato JSON")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en crear_solicitud: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{id}/aprobar")
async def aprobar_solicitud(
    id: UUID,
    update_data: SolicitudCambioUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion"]))
):
    """
    Aprueba una solicitud de cambio de turno o vacaciones
    Soporta múltiples niveles de aprobación según el área del empleado
    """
    try:
        # Obtener la solicitud actual
        solicitud = db.query(SolicitudCambio).filter(SolicitudCambio.id == id).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if solicitud.estado != "pendiente":
            raise HTTPException(status_code=400, detail=f"La solicitud ya está {solicitud.estado}")
        
        # Preparar datos
        fecha_ahora = datetime.utcnow()
        usuario_nombre = obtener_nombre_usuario(db, current_user)
        nivel_aprobado = solicitud.proximo_nivel
        
        # Validar permisos
        if "admin" not in current_user.roles:
            usuario_aprobador = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if not usuario_aprobador:
                raise HTTPException(status_code=403, detail="Usuario no encontrado")
            
            if nivel_aprobado == "jefe_area":
                areas_jefatura = usuario_aprobador.areas_que_jefatura or []
                if solicitud.empleado_rel.area not in areas_jefatura:
                    raise HTTPException(status_code=403, detail="No tiene permisos para aprobar esta solicitud")
            elif nivel_aprobado == "jefe_direccion":
                if usuario_aprobador.area_que_jefatura_direccion != solicitud.empleado_rel.area:
                    raise HTTPException(status_code=403, detail="No tiene permisos para aprobar esta solicitud")
        
        # Obtener listas actuales
        pendientes = solicitud.niveles_pendientes or []
        aprobados = solicitud.niveles_aprobados or []
        
        # Agregar el nivel actual a los aprobados
        if nivel_aprobado and nivel_aprobado not in aprobados:
            nuevos_aprobados = aprobados + [nivel_aprobado]
        else:
            nuevos_aprobados = aprobados
        
        # Buscar el siguiente nivel pendiente
        siguiente_nivel = next((n for n in pendientes if n not in nuevos_aprobados), None)
        
        # Determinar el nuevo estado
        if not siguiente_nivel:
            solicitud.estado = "aprobada"
            solicitud.nivel_actual = "aprobada"
            logger.info(f"✅ Solicitud {id} completamente aprobada")
        else:
            solicitud.estado = "pendiente"
            solicitud.nivel_actual = "en_revision"
        
        # Actualizar campos
        solicitud.proximo_nivel = siguiente_nivel
        solicitud.niveles_aprobados = nuevos_aprobados
        solicitud.fecha_revision = fecha_ahora
        solicitud.revisado_por = current_user.id
        solicitud.comentario_revision = update_data.comentario_revision
        
        # Crear nuevo evento para el historial
        historial_actual = solicitud.historial or []
        
        nuevo_evento = {
            "fecha": fecha_ahora.isoformat(),
            "usuario": str(current_user.id),
            "usuario_nombre": usuario_nombre,
            "nivel": nivel_aprobado,
            "accion": "aprobación",
            "estado": solicitud.estado,
            "siguiente_nivel": siguiente_nivel if siguiente_nivel else None,
            "comentario": update_data.comentario_revision,
            "niveles_aprobados_hasta_ahora": nuevos_aprobados,
            "niveles_pendientes_restantes": [n for n in pendientes if n not in nuevos_aprobados]
        }
        
        nueva_lista_historial = historial_actual + [nuevo_evento]
        solicitud.historial = nueva_lista_historial
        
        db.commit()
        
        # =====================================================
        # 🆕 ACTUALIZAR PLANIFICACIÓN DESPUÉS DE APROBAR
        # =====================================================
        
        # Si la solicitud está completamente aprobada
        if solicitud.estado == "aprobada":
            
            # 🆕 PROCESAR VACACIONES (con timedelta)
            if solicitud.tipo == "vacaciones" and solicitud.fecha_inicio and solicitud.fecha_fin:
                try:
                    logger.info(f"🏖️ Procesando vacaciones para solicitud {id}")
                    logger.info(f"   Fechas: {solicitud.fecha_inicio} → {solicitud.fecha_fin}")
                    
                    dias_marcados = marcar_vacaciones_en_planificacion(
                        db, 
                        solicitud.empleado_id, 
                        solicitud.fecha_inicio, 
                        solicitud.fecha_fin, 
                        current_user.id
                    )
                    
                    logger.info(f"✅ Marcados {dias_marcados} días como VAC para empleado {solicitud.empleado_id}")
                    
                    # Agregar evento al historial
                    solicitud.historial.append({
                        "fecha": datetime.utcnow().isoformat(),
                        "usuario": str(current_user.id),
                        "usuario_nombre": usuario_nombre,
                        "accion": "vacaciones_aplicadas",
                        "dias_marcados": dias_marcados,
                        "fecha_inicio": solicitud.fecha_inicio.isoformat(),
                        "fecha_fin": solicitud.fecha_fin.isoformat()
                    })
                    db.commit()
                    
                except Exception as e:
                    logger.error(f"❌ Error procesando vacaciones: {e}")
                    import traceback
                    traceback.print_exc()
                    solicitud.historial.append({
                        "fecha": datetime.utcnow().isoformat(),
                        "usuario": str(current_user.id),
                        "usuario_nombre": usuario_nombre,
                        "accion": "error_vacaciones",
                        "error": str(e)
                    })
                    db.commit()
            
            # =====================================================
            # ✅ PROCESAR CAMBIOS DE TURNO - CORREGIDO PARA INTERCAMBIO
            # =====================================================
            elif solicitud.tipo in ["propio", "intercambio"]:
                try:
                    logger.info(f"🔄 Actualizando planificación para solicitud {id}")
                    logger.info(f"   Tipo: {solicitud.tipo}")
                    
                    fecha_cambio = solicitud.fecha_cambio
                    
                    # =====================================================
                    # CASO 1: CAMBIO PROPIO
                    # =====================================================
                    if solicitud.tipo == "propio":
                        # El solicitante cambia su turno
                        planificacion_solicitante = db.query(Planificacion).filter(
                            Planificacion.personal_id == solicitud.empleado_id,
                            Planificacion.fecha == fecha_cambio
                        ).first()
                        
                        if planificacion_solicitante:
                            turno_anterior = planificacion_solicitante.turno_codigo
                            planificacion_solicitante.turno_codigo = solicitud.turno_solicitado
                            planificacion_solicitante.updated_at = datetime.utcnow()
                            logger.info(f"   ✅ Solicitante: {turno_anterior} → {solicitud.turno_solicitado}")
                        else:
                            nueva_planificacion = Planificacion(
                                personal_id=solicitud.empleado_id,
                                fecha=fecha_cambio,
                                turno_codigo=solicitud.turno_solicitado,
                                created_by=current_user.id
                            )
                            db.add(nueva_planificacion)
                            logger.info(f"   ✅ Creada nueva planificación para solicitante: {solicitud.turno_solicitado}")
                    
                    # =====================================================
                    # CASO 2: INTERCAMBIO - CORREGIDO ✅
                    # =====================================================
                    elif solicitud.tipo == "intercambio":
                        # Validar que tenemos todos los datos necesarios
                        if not solicitud.empleado2_id:
                            logger.error("❌ Intercambio sin empleado2_id")
                            raise ValueError("La solicitud de intercambio no tiene empleado2_id")
                        
                        # Usar los campos correctos de intercambio
                        turno_que_recibe_solicitante = solicitud.turno_solicitante_recibe
                        turno_que_recibe_colega = solicitud.turno_colega_recibe
                        
                        logger.info(f"   📋 Datos de intercambio:")
                        logger.info(f"      Solicitante ({solicitud.empleado_id}) recibe: {turno_que_recibe_solicitante}")
                        logger.info(f"      Colega ({solicitud.empleado2_id}) recibe: {turno_que_recibe_colega}")
                        
                        # 1. Actualizar planificación del SOLICITANTE (recibe el turno del colega)
                        planificacion_solicitante = db.query(Planificacion).filter(
                            Planificacion.personal_id == solicitud.empleado_id,
                            Planificacion.fecha == fecha_cambio
                        ).first()
                        
                        if planificacion_solicitante:
                            turno_anterior = planificacion_solicitante.turno_codigo
                            planificacion_solicitante.turno_codigo = turno_que_recibe_solicitante
                            planificacion_solicitante.updated_at = datetime.utcnow()
                            logger.info(f"   ✅ Solicitante: {turno_anterior} → {turno_que_recibe_solicitante}")
                        else:
                            # Crear planificación si no existe
                            nueva_planificacion = Planificacion(
                                personal_id=solicitud.empleado_id,
                                fecha=fecha_cambio,
                                turno_codigo=turno_que_recibe_solicitante,
                                created_by=current_user.id
                            )
                            db.add(nueva_planificacion)
                            logger.info(f"   ✅ Creada planificación para solicitante: {turno_que_recibe_solicitante}")
                        
                        # 2. Actualizar planificación del COLEGA (recibe el turno del solicitante)
                        planificacion_colega = db.query(Planificacion).filter(
                            Planificacion.personal_id == solicitud.empleado2_id,
                            Planificacion.fecha == fecha_cambio
                        ).first()
                        
                        if planificacion_colega:
                            turno_anterior = planificacion_colega.turno_codigo
                            planificacion_colega.turno_codigo = turno_que_recibe_colega
                            planificacion_colega.updated_at = datetime.utcnow()
                            logger.info(f"   ✅ Colega: {turno_anterior} → {turno_que_recibe_colega}")
                        else:
                            # Crear planificación si no existe
                            nueva_planificacion_colega = Planificacion(
                                personal_id=solicitud.empleado2_id,
                                fecha=fecha_cambio,
                                turno_codigo=turno_que_recibe_colega,
                                created_by=current_user.id
                            )
                            db.add(nueva_planificacion_colega)
                            logger.info(f"   ✅ Creada planificación para colega: {turno_que_recibe_colega}")
                    
                    db.commit()
                    logger.info(f"✅ Planificación actualizada para solicitud {id}")
                    
                    # Agregar evento al historial
                    solicitud.historial.append({
                        "fecha": datetime.utcnow().isoformat(),
                        "usuario": str(current_user.id),
                        "usuario_nombre": usuario_nombre,
                        "accion": "planificacion_actualizada",
                        "tipo": solicitud.tipo,
                        "fecha_cambio": fecha_cambio.isoformat()
                    })
                    db.commit()
                    
                except Exception as e:
                    logger.error(f"❌ Error actualizando planificación: {e}")
                    import traceback
                    traceback.print_exc()
                    solicitud.historial.append({
                        "fecha": datetime.utcnow().isoformat(),
                        "usuario": str(current_user.id),
                        "usuario_nombre": usuario_nombre,
                        "accion": "error_planificacion",
                        "error": str(e)
                    })
                    db.commit()
        
        db.refresh(solicitud)
        
        logger.info(f"✅ Solicitud {id} aprobada en nivel {nivel_aprobado}")
        
        return formatear_solicitud(solicitud)
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error en aprobar_solicitud: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/{id}/rechazar")
async def rechazar_solicitud(
    id: UUID,
    update_data: SolicitudCambioUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion"]))
):
    """
    Rechaza una solicitud de cambio de turno
    """
    try:
        solicitud = db.query(SolicitudCambio).filter(SolicitudCambio.id == id).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if solicitud.estado != "pendiente":
            raise HTTPException(status_code=400, detail=f"La solicitud ya está {solicitud.estado}")
        
        solicitud.estado = "rechazada"
        solicitud.fecha_revision = datetime.utcnow()
        solicitud.revisado_por = current_user.id
        solicitud.comentario_revision = update_data.comentario_revision
        solicitud.nivel_actual = "rechazada"
        
        usuario_nombre = obtener_nombre_usuario(db, current_user)
        
        historial_entry = {
            "fecha": datetime.utcnow().isoformat(),
            "usuario": str(current_user.id),
            "usuario_nombre": usuario_nombre,
            "nivel": solicitud.proximo_nivel,
            "accion": "rechazo",
            "estado": "rechazada",
            "comentario": update_data.comentario_revision,
            "niveles_aprobados_hasta_ahora": solicitud.niveles_aprobados or []
        }
        
        if not solicitud.historial:
            solicitud.historial = []
        solicitud.historial.append(historial_entry)
        
        db.commit()
        db.refresh(solicitud)
        
        logger.info(f"❌ Solicitud {id} rechazada en nivel {solicitud.proximo_nivel}")
        
        return formatear_solicitud(solicitud)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en rechazar_solicitud: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/planificaciones/historial/{area}")
async def obtener_historial_planificaciones(
    area: str,
    anio: Optional[int] = Query(None),
    mes: Optional[int] = Query(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Obtiene el historial de envíos de planificación de un área
    """
    try:
        if "jefe_area" in current_user.roles and "admin" not in current_user.roles:
            jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if not jefe or jefe.area != area:
                raise HTTPException(status_code=403, detail="No puedes ver historial de otra área")
        
        query = db.query(SolicitudCambio).filter(
            SolicitudCambio.tipo == "planificacion_mensual"
        ).join(
            Personal, Personal.id == SolicitudCambio.empleado_id
        ).filter(
            Personal.area == area
        )
        
        if anio and mes:
            fecha_referencia = date(anio, mes, 1)
            query = query.filter(SolicitudCambio.fecha_cambio == fecha_referencia)
        
        solicitudes = query.order_by(SolicitudCambio.created_at.desc()).all()
        
        result = []
        for s in solicitudes:
            result.append({
                "id": str(s.id),
                "estado": s.estado,
                "fecha_solicitud": s.fecha_solicitud.isoformat() if s.fecha_solicitud else None,
                "fecha_cambio": s.fecha_cambio.isoformat() if s.fecha_cambio else None,
                "fecha_revision": s.fecha_revision.isoformat() if s.fecha_revision else None,
                "comentario_revision": s.comentario_revision,
                "empleado_nombre": s.empleado_rel.nombre if s.empleado_rel else None,
                "revisado_por": str(s.revisado_por) if s.revisado_por else None,
                "historial": s.historial
            })
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en obtener_historial_planificaciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{id}")
async def obtener_solicitud(
    id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Obtiene una solicitud por ID
    """
    try:
        solicitud = db.query(SolicitudCambio).filter(
            SolicitudCambio.id == id
        ).options(
            joinedload(SolicitudCambio.empleado_rel),
            joinedload(SolicitudCambio.empleado2_rel)
        ).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if "usuario" in current_user.roles and "admin" not in current_user.roles:
            if str(current_user.personal_id) != str(solicitud.empleado_id):
                raise HTTPException(status_code=403, detail="No autorizado")
        
        return formatear_solicitud(solicitud)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en obtener_solicitud: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/{id}/historial")
async def obtener_historial_completo(
    id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Obtiene el historial completo de una solicitud con todos los eventos
    """
    try:
        solicitud = db.query(SolicitudCambio).filter(SolicitudCambio.id == id).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if "usuario" in current_user.roles and "admin" not in current_user.roles:
            if str(current_user.personal_id) != str(solicitud.empleado_id):
                raise HTTPException(status_code=403, detail="No autorizado")
        
        return {
            "id": str(solicitud.id),
            "tipo": solicitud.tipo,
            "estado": solicitud.estado,
            "nivel_actual": solicitud.nivel_actual,
            "proximo_nivel": solicitud.proximo_nivel,
            "niveles_pendientes": solicitud.niveles_pendientes,
            "niveles_aprobados": solicitud.niveles_aprobados,
            "historial": solicitud.historial,
            "total_eventos": len(solicitud.historial) if solicitud.historial else 0,
            "eventos_por_nivel": {
                nivel: len([e for e in (solicitud.historial or []) if e.get("nivel") == nivel])
                for nivel in (solicitud.niveles_pendientes or [])
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en obtener_historial_completo: {e}")
        raise HTTPException(status_code=500, detail=str(e))