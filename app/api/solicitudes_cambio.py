# api/solicitudes_cambio.py
# VERSIÓN COMPLETA - CON SOPORTE PARA TODOS LOS ROLES DE JEFATURA
# ✅ CORREGIDO: Endpoints específicos ANTES que rutas dinámicas /{id}
# ✅ AGREGADO: Soporte para jefe_grupo, jefe_departamento, jefe_direccion, recursos_humanos, oficina_central

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import or_, and_, desc
from typing import List, Optional, Dict, Any
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
# ROLES DE JEFATURA Y ACCESO GLOBAL
# =====================================================
ROLES_JEFATURA = ['jefe_grupo', 'jefe_area', 'jefe_departamento', 'jefe_direccion']
ROLES_ACCESO_GLOBAL = ['admin', 'recursos_humanos', 'oficina_central']

# Mapeo de rol a tipo de jefatura
ROL_A_TIPO = {
    'jefe_grupo': 'grupo',
    'jefe_area': 'area',
    'jefe_departamento': 'departamento',
    'jefe_direccion': 'direccion'
}

# =====================================================
# FUNCIÓN PARA PROCESAR ÁREAS DE JEFATURA (COMPATIBILIDAD DUAL)
# =====================================================
def procesar_areas_jefatura(areas_que_jefatura: Optional[List], areas_jefatura: Optional[Dict]) -> Dict[str, List[str]]:
    """
    Procesa y combina ambos formatos de áreas de jefatura.
    
    Args:
        areas_que_jefatura: Array plano (legacy)
        areas_jefatura: Objeto estructurado (nuevo)
        
    Returns:
        Diccionario con áreas por tipo: {'grupo': [], 'area': [], 'departamento': [], 'direccion': []}
    """
    resultado = {
        'grupo': [],
        'area': [],
        'departamento': [],
        'direccion': []
    }
    
    # Procesar formato nuevo (estructurado)
    if areas_jefatura and isinstance(areas_jefatura, dict):
        for tipo in resultado.keys():
            if tipo in areas_jefatura and isinstance(areas_jefatura[tipo], list):
                resultado[tipo].extend(areas_jefatura[tipo])
    
    # Procesar formato legacy (array con prefijos)
    if areas_que_jefatura and isinstance(areas_que_jefatura, list):
        prefijo_map = {
            'grupo': 'grupo:',
            'area': 'area:',
            'departamento': 'depto:',
            'direccion': 'direccion:'
        }
        
        for tipo, prefijo in prefijo_map.items():
            for item in areas_que_jefatura:
                if isinstance(item, str):
                    if item.startswith(prefijo):
                        resultado[tipo].append(item.replace(prefijo, ''))
                    elif ':' not in item and tipo == 'area':
                        # Sin prefijo = área (legacy puro)
                        resultado[tipo].append(item)
    
    # Eliminar duplicados
    for tipo in resultado:
        resultado[tipo] = list(set(resultado[tipo]))
    
    return resultado


# =====================================================
# FUNCIÓN PARA OBTENER ÁREAS QUE JEFATURA UN USUARIO (TODAS COMBINADAS)
# =====================================================
def obtener_areas_jefatura_usuario(usuario: Personal) -> List[str]:
    """
    Obtiene TODAS las áreas que jefatura un usuario (todos los tipos combinados).
    """
    if not usuario:
        return []
    
    areas_procesadas = procesar_areas_jefatura(usuario.areas_que_jefatura, usuario.areas_jefatura)
    
    todas_areas = []
    for areas in areas_procesadas.values():
        todas_areas.extend(areas)
    
    # Caso especial: jefe_area sin áreas asignadas -> su propia área
    if 'jefe_area' in (usuario.roles or []) and not todas_areas and usuario.area:
        todas_areas = [usuario.area]
    
    return list(set(todas_areas))


# =====================================================
# FUNCIÓN PARA VERIFICAR SI UN USUARIO PUEDE APROBAR UNA SOLICITUD
# =====================================================
def puede_aprobar_solicitud(usuario: Personal, solicitud: SolicitudCambio) -> bool:
    """
    Verifica si un usuario puede aprobar una solicitud específica.
    Considera el nivel requerido y el área de la solicitud.
    """
    if not usuario or not solicitud:
        return False
    
    roles = usuario.roles or []
    
    # Admin y roles globales pueden aprobar todo
    if any(rol in roles for rol in ROLES_ACCESO_GLOBAL):
        return True
    
    # Verificar si el próximo nivel corresponde a un rol que tiene el usuario
    proximo_nivel = solicitud.proximo_nivel
    if not proximo_nivel or proximo_nivel not in roles:
        return False
    
    # Obtener área de la solicitud
    area_solicitud = solicitud.empleado_rel.area if solicitud.empleado_rel else None
    if not area_solicitud:
        return False
    
    # Para jefes, verificar que el área esté en sus áreas que jefatura
    areas_procesadas = procesar_areas_jefatura(usuario.areas_que_jefatura, usuario.areas_jefatura)
    
    tipo = ROL_A_TIPO.get(proximo_nivel)
    if not tipo:
        return False
    
    areas_permitidas = areas_procesadas.get(tipo, [])
    
    # Caso especial: jefe_area sin áreas asignadas
    if proximo_nivel == 'jefe_area' and not areas_permitidas and usuario.area:
        areas_permitidas = [usuario.area]
    
    return area_solicitud in areas_permitidas


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
# FUNCIÓN PARA MARCAR VACACIONES EN PLANIFICACIÓN
# =====================================================
def marcar_vacaciones_en_planificacion(db: Session, empleado_id: UUID, fecha_inicio: date, fecha_fin: date, usuario_id: UUID):
    """
    Marca todos los días del período como VAC en la planificación
    """
    try:
        logger.info(f"🏖️ Marcando vacaciones para empleado {empleado_id} del {fecha_inicio} al {fecha_fin}")
        
        fecha_actual = fecha_inicio
        dias_marcados = 0
        errores = 0
        
        while fecha_actual <= fecha_fin:
            try:
                planificacion_existente = db.query(Planificacion).filter(
                    Planificacion.personal_id == empleado_id,
                    Planificacion.fecha == fecha_actual
                ).first()
                
                if planificacion_existente:
                    planificacion_existente.turno_codigo = "VAC"
                    planificacion_existente.updated_at = datetime.utcnow()
                else:
                    nueva_planificacion = Planificacion(
                        personal_id=empleado_id,
                        fecha=fecha_actual,
                        turno_codigo="VAC",
                        created_by=usuario_id
                    )
                    db.add(nueva_planificacion)
                
                dias_marcados += 1
                
            except Exception as e:
                logger.error(f"   ❌ Error en fecha {fecha_actual}: {e}")
                errores += 1
            
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
def obtener_cadena_jerarquica(area: str) -> List[str]:
    """
    Determina la cadena de aprobación según el área del solicitante
    """
    if not area:
        return ['jefe_area']
    
    area_upper = area.upper()
    
    # Áreas con estructura jerárquica completa
    if any(x in area_upper for x in ['EMERGENCIA', 'UCI', 'CRITICOS']):
        return ['jefe_grupo', 'jefe_area', 'jefe_departamento', 'jefe_direccion']
    
    # Áreas médicas con 3 niveles
    if any(x in area_upper for x in ['HOSPITALIZACION', 'CIRUGIA', 'MEDICINA', 'CARDIOLOGIA', 'NEUROLOGIA', 'PEDIATRIA']):
        return ['jefe_area', 'jefe_departamento', 'jefe_direccion']
    
    # Divisiones y departamentos
    if any(x in area_upper for x in ['DIVISION', 'DEPARTAMENTO']):
        return ['jefe_departamento', 'jefe_direccion']
    
    # Default: jefe de área
    return ['jefe_area']


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
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion", "jefe_grupo", "jefe_departamento", "recursos_humanos", "oficina_central"]))
):
    """
    Lista las solicitudes pendientes que el usuario puede aprobar
    según su rol y nivel jerárquico.
    Soporta TODOS los roles de jefatura.
    """
    try:
        # Roles globales pueden ver todo
        if any(rol in current_user.roles for rol in ROLES_ACCESO_GLOBAL):
            query = db.query(SolicitudCambio).filter(SolicitudCambio.estado == "pendiente")
            solicitudes = query.options(
                joinedload(SolicitudCambio.empleado_rel),
                joinedload(SolicitudCambio.empleado2_rel)
            ).order_by(SolicitudCambio.created_at.desc()).all()
            logger.info(f"✅ Admin/Global: {len(solicitudes)} solicitudes pendientes")
            return [formatear_solicitud(s) for s in solicitudes]
        
        # Obtener información del usuario
        usuario = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if not usuario:
            raise HTTPException(status_code=403, detail="Usuario no encontrado")
        
        # Procesar áreas de jefatura
        areas_procesadas = procesar_areas_jefatura(usuario.areas_que_jefatura, usuario.areas_jefatura)
        
        # Construir condiciones de filtro según roles
        condiciones = []
        roles_usuario = current_user.roles or []
        
        for rol in ROLES_JEFATURA:
            if rol in roles_usuario:
                tipo = ROL_A_TIPO[rol]
                areas = areas_procesadas.get(tipo, [])
                
                # Caso especial: jefe_area sin áreas asignadas
                if rol == 'jefe_area' and not areas and usuario.area:
                    areas = [usuario.area]
                
                for area in areas:
                    condiciones.append(
                        and_(
                            SolicitudCambio.proximo_nivel == rol,
                            Personal.area == area
                        )
                    )
        
        if not condiciones:
            logger.info(f"ℹ️ Usuario {usuario.nombre} no tiene áreas asignadas para aprobar")
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
        
        logger.info(f"✅ Jefe {usuario.nombre}: {len(solicitudes)} solicitudes pendientes")
        return [formatear_solicitud(s) for s in solicitudes]
        
    except Exception as e:
        logger.error(f"Error en listar_pendientes: {e}")
        raise HTTPException(status_code=500, detail=f"Error al cargar solicitudes pendientes: {str(e)}")


@router.get("/todas")
async def listar_todas_solicitudes(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion", "jefe_grupo", "jefe_departamento", "recursos_humanos", "oficina_central"]))
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
    tipo: Optional[str] = Query(None),
    estado: Optional[str] = Query(None),
    mes: Optional[str] = Query(None),
    busqueda: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion", "jefe_grupo", "jefe_departamento", "usuario"]))
):
    """
    Obtiene el historial de solicitudes aprobadas y rechazadas
    """
    try:
        query = db.query(SolicitudCambio).filter(
            SolicitudCambio.estado.in_(["aprobada", "rechazada"])
        )
        
        if tipo and tipo != "todos":
            query = query.filter(SolicitudCambio.tipo == tipo)
        
        if estado and estado != "todas":
            query = query.filter(SolicitudCambio.estado == estado)
        
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
        
        total = query.count()
        
        solicitudes = query.order_by(
            desc(SolicitudCambio.fecha_revision),
            desc(SolicitudCambio.created_at)
        ).offset(offset).limit(limit).all()
        
        result = []
        for s in solicitudes:
            solicitud_dict = formatear_solicitud(s)
            solicitud_dict["fecha_resolucion"] = s.fecha_revision.isoformat() if s.fecha_revision else None
            solicitud_dict["resuelto_por"] = None
            solicitud_dict["motivo_rechazo"] = s.comentario_revision if s.estado == "rechazada" else None
            solicitud_dict["tiempo_resolucion"] = None
            
            if s.fecha_revision and s.created_at:
                tiempo = (s.fecha_revision - s.created_at).total_seconds() / 3600
                solicitud_dict["tiempo_resolucion"] = round(tiempo, 1)
            
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
    """Obtiene estadísticas del historial de solicitudes"""
    try:
        solicitudes = db.query(SolicitudCambio).filter(
            SolicitudCambio.estado.in_(["aprobada", "rechazada"])
        ).all()
        
        total = len(solicitudes)
        aprobadas = len([s for s in solicitudes if s.estado == "aprobada"])
        rechazadas = len([s for s in solicitudes if s.estado == "rechazada"])
        tasa_aprobacion = round((aprobadas / total) * 100, 1) if total > 0 else 0
        
        por_tipo = {}
        for t in ["propio", "intercambio", "vacaciones", "permiso"]:
            por_tipo[t] = len([s for s in solicitudes if s.tipo == t])
        
        por_mes = []
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
    """Lista SOLO solicitudes de planificación mensual pendientes"""
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
        
        return result
        
    except Exception as e:
        logger.error(f"Error en listar_planificaciones_pendientes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/mis-solicitudes")
async def obtener_mis_solicitudes(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """Obtiene las solicitudes del usuario actual"""
    try:
        personal_id = current_user.personal_id
        
        if not personal_id:
            raise HTTPException(status_code=400, detail="Usuario no tiene personal_id asociado")
        
        solicitudes = db.query(SolicitudCambio).filter(
            or_(
                SolicitudCambio.empleado_id == personal_id,
                SolicitudCambio.empleado2_id == personal_id
            )
        ).options(
            joinedload(SolicitudCambio.empleado_rel),
            joinedload(SolicitudCambio.empleado2_rel)
        ).order_by(SolicitudCambio.created_at.desc()).all()
        
        return [formatear_solicitud(s) for s in solicitudes]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en obtener_mis_solicitudes: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


# =====================================================
# =====================================================
# ✅ ENDPOINTS CON PARÁMETROS DINÁMICOS (AL FINAL)
# =====================================================
# =====================================================

@router.get("/personal/{personal_id}", response_model=List[SolicitudCambioResponse])
async def listar_por_personal(
    personal_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """Lista solicitudes de un personal específico"""
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
        
        return [formatear_solicitud(s) for s in solicitudes]
        
    except Exception as e:
        logger.error(f"Error en listar_por_personal: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/planificacion/{solicitud_id}/aprobar")
async def aprobar_planificacion_mensual(
    solicitud_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """APRUEBA una planificación de área"""
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
        
        jefe = db.query(Personal).filter(Personal.id == solicitud.empleado_id).first()
        if not jefe or not jefe.area:
            raise HTTPException(status_code=400, detail="No se pudo determinar el área del solicitante")
        
        area = jefe.area
        mes = solicitud.fecha_cambio.month
        anio = solicitud.fecha_cambio.year
        
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
            borrador.estado = 'aprobado'
            borrador.fecha_aprobacion = datetime.utcnow()
            borrador.datos = datos_horario
        else:
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
        
        for registro in datos_horario:
            try:
                if not registro.get('personal_id') or not registro.get('fecha') or not registro.get('turno_codigo'):
                    errores += 1
                    continue
                
                turno_codigo = registro['turno_codigo']
                if turno_codigo in mapa_turnos:
                    turno_codigo = mapa_turnos[turno_codigo]
                
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
                logger.error(f"❌ Error insertando registro: {e}")
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
        
        return {
            "message": "Planificación aprobada exitosamente",
            "solicitud_id": str(solicitud.id),
            "area": area,
            "mes": mes,
            "anio": anio,
            "registros_procesados": len(datos_horario),
            "registros_creados": registros_creados,
            "errores": errores
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error en aprobar_planificacion_mensual: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


@router.post("/planificacion/{solicitud_id}/rechazar")
async def rechazar_planificacion_mensual(
    solicitud_id: UUID,
    comentario: str = Query(..., description="Motivo del rechazo"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """RECHAZA una planificación de área - PRESERVA los datos"""
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
        
        borrador = db.query(PlanificacionBorrador).filter(
            PlanificacionBorrador.area == area,
            PlanificacionBorrador.mes == mes,
            PlanificacionBorrador.año == anio
        ).first()
        
        if borrador:
            borrador.estado = 'rechazado'
            borrador.comentario_rechazo = comentario
        else:
            if not solicitud.turno_original:
                raise HTTPException(status_code=400, detail="La solicitud no contiene datos de planificación")
            
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
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/")
async def crear_solicitud(
    data: str = Form(...),
    archivos: List[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(["admin", "usuario"]))
):
    """Crea una nueva solicitud (vacaciones, cambio de turno, intercambio, etc.)"""
    try:
        solicitud_data = json.loads(data)
        fecha_cambio = date.fromisoformat(solicitud_data["fecha_cambio"])
        
        fecha_inicio = solicitud_data.get("fecha_inicio")
        fecha_fin = solicitud_data.get("fecha_fin")
        dias_solicitados = solicitud_data.get("dias_solicitados")
        tipo_vacaciones = solicitud_data.get("tipo_vacaciones")
        
        if not fecha_inicio and solicitud_data.get("datos"):
            datos_extra = solicitud_data.get("datos", {})
            fecha_inicio = datos_extra.get("fecha_inicio")
            fecha_fin = datos_extra.get("fecha_fin")
            dias_solicitados = datos_extra.get("dias_solicitados")
            tipo_vacaciones = datos_extra.get("tipo_vacaciones")
        
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
        
        # Validaciones para cambios de turno
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
        
        # Procesar documentos
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
        
        # Crear solicitud
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
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion", "jefe_grupo", "jefe_departamento", "recursos_humanos", "oficina_central"]))
):
    """
    Aprueba una solicitud de cambio de turno o vacaciones
    Soporta múltiples niveles de aprobación según el área del empleado
    """
    try:
        solicitud = db.query(SolicitudCambio).filter(SolicitudCambio.id == id).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if solicitud.estado != "pendiente":
            raise HTTPException(status_code=400, detail=f"La solicitud ya está {solicitud.estado}")
        
        fecha_ahora = datetime.utcnow()
        usuario_nombre = obtener_nombre_usuario(db, current_user)
        nivel_aprobado = solicitud.proximo_nivel
        
        # Validar permisos usando la nueva función
        if "admin" not in current_user.roles:
            usuario_aprobador = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if not usuario_aprobador:
                raise HTTPException(status_code=403, detail="Usuario no encontrado")
            
            if not puede_aprobar_solicitud(usuario_aprobador, solicitud):
                raise HTTPException(status_code=403, detail="No tiene permisos para aprobar esta solicitud")
        
        pendientes = solicitud.niveles_pendientes or []
        aprobados = solicitud.niveles_aprobados or []
        
        if nivel_aprobado and nivel_aprobado not in aprobados:
            nuevos_aprobados = aprobados + [nivel_aprobado]
        else:
            nuevos_aprobados = aprobados
        
        siguiente_nivel = next((n for n in pendientes if n not in nuevos_aprobados), None)
        
        if not siguiente_nivel:
            solicitud.estado = "aprobada"
            solicitud.nivel_actual = "aprobada"
            logger.info(f"✅ Solicitud {id} completamente aprobada")
        else:
            solicitud.estado = "pendiente"
            solicitud.nivel_actual = "en_revision"
        
        solicitud.proximo_nivel = siguiente_nivel
        solicitud.niveles_aprobados = nuevos_aprobados
        solicitud.fecha_revision = fecha_ahora
        solicitud.revisado_por = current_user.id
        solicitud.comentario_revision = update_data.comentario_revision
        
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
        
        solicitud.historial = historial_actual + [nuevo_evento]
        
        db.commit()
        
        # Actualizar planificación si está completamente aprobada
        if solicitud.estado == "aprobada":
            if solicitud.tipo == "vacaciones" and solicitud.fecha_inicio and solicitud.fecha_fin:
                try:
                    dias_marcados = marcar_vacaciones_en_planificacion(
                        db, solicitud.empleado_id, solicitud.fecha_inicio, solicitud.fecha_fin, current_user.id
                    )
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
            
            elif solicitud.tipo in ["propio", "intercambio"]:
                try:
                    fecha_cambio = solicitud.fecha_cambio
                    
                    if solicitud.tipo == "propio":
                        planificacion_solicitante = db.query(Planificacion).filter(
                            Planificacion.personal_id == solicitud.empleado_id,
                            Planificacion.fecha == fecha_cambio
                        ).first()
                        
                        if planificacion_solicitante:
                            planificacion_solicitante.turno_codigo = solicitud.turno_solicitado
                            planificacion_solicitante.updated_at = datetime.utcnow()
                        else:
                            nueva = Planificacion(
                                personal_id=solicitud.empleado_id,
                                fecha=fecha_cambio,
                                turno_codigo=solicitud.turno_solicitado,
                                created_by=current_user.id
                            )
                            db.add(nueva)
                    
                    elif solicitud.tipo == "intercambio" and solicitud.empleado2_id:
                        # Solicitante recibe turno del colega
                        plan_sol = db.query(Planificacion).filter(
                            Planificacion.personal_id == solicitud.empleado_id,
                            Planificacion.fecha == fecha_cambio
                        ).first()
                        
                        if plan_sol:
                            plan_sol.turno_codigo = solicitud.turno_solicitante_recibe
                            plan_sol.updated_at = datetime.utcnow()
                        else:
                            db.add(Planificacion(
                                personal_id=solicitud.empleado_id,
                                fecha=fecha_cambio,
                                turno_codigo=solicitud.turno_solicitante_recibe,
                                created_by=current_user.id
                            ))
                        
                        # Colega recibe turno del solicitante
                        plan_col = db.query(Planificacion).filter(
                            Planificacion.personal_id == solicitud.empleado2_id,
                            Planificacion.fecha == fecha_cambio
                        ).first()
                        
                        if plan_col:
                            plan_col.turno_codigo = solicitud.turno_colega_recibe
                            plan_col.updated_at = datetime.utcnow()
                        else:
                            db.add(Planificacion(
                                personal_id=solicitud.empleado2_id,
                                fecha=fecha_cambio,
                                turno_codigo=solicitud.turno_colega_recibe,
                                created_by=current_user.id
                            ))
                    
                    db.commit()
                    
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
    current_user = Depends(require_roles(["admin", "jefe_area", "jefe_direccion", "jefe_grupo", "jefe_departamento", "recursos_humanos", "oficina_central"]))
):
    """Rechaza una solicitud de cambio de turno"""
    try:
        solicitud = db.query(SolicitudCambio).filter(SolicitudCambio.id == id).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if solicitud.estado != "pendiente":
            raise HTTPException(status_code=400, detail=f"La solicitud ya está {solicitud.estado}")
        
        # Validar permisos
        if "admin" not in current_user.roles:
            usuario_aprobador = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if not usuario_aprobador:
                raise HTTPException(status_code=403, detail="Usuario no encontrado")
            
            if not puede_aprobar_solicitud(usuario_aprobador, solicitud):
                raise HTTPException(status_code=403, detail="No tiene permisos para rechazar esta solicitud")
        
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
    """Obtiene el historial de envíos de planificación de un área"""
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
    """Obtiene una solicitud por ID"""
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
    """Obtiene el historial completo de una solicitud con todos los eventos"""
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