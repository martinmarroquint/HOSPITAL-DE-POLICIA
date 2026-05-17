# app/api/publicaciones.py
# VERSIÓN OPTIMIZADA - RENDIMIENTO MEJORADO - FILTROS CORRECTOS

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, desc, String, cast
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date
import logging
import json

from app.database import get_db
from app.core.dependencies import require_roles, get_current_user_id
from app.models.publicacion import Publicacion, PublicacionVista
from app.models.notificacion import Notificacion
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.schemas.publicacion import (
    PublicacionCreate, PublicacionUpdate, PublicacionResponse,
    PublicacionVistaCreate, PublicacionVistaResponse, MarcarVistaRequest,
    PublicacionEstadisticas, EstadisticasGlobales, PublicacionListResponse
)

from app.api.notificaciones import crear_notificacion_masiva

from app.utils.roles import (
    ROLES_ADMIN, 
    ROLES_JEFE,
    ROLES_JEFATURA,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# =====================================================
# CACHE SIMPLE EN MEMORIA
# =====================================================
_autores_cache = {}
_vistas_cache = {}
_cache_timestamps = {}

def _cache_get(cache_dict, key, ttl=60):
    if key in cache_dict and key in _cache_timestamps:
        if (datetime.now() - _cache_timestamps[key]).total_seconds() < ttl:
            return cache_dict[key]
    return None

def _cache_set(cache_dict, key, value):
    cache_dict[key] = value
    _cache_timestamps[key] = datetime.now()


# =====================================================
# CORS OPTIONS
# =====================================================
@router.options("/{path:path}")
async def options_handler(path: str):
    return Response(status_code=200, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type, Authorization",
        "Access-Control-Allow-Credentials": "true",
        "Access-Control-Max-Age": "3600",
    })


# =====================================================
# FUNCIONES AUXILIARES DE ROLES
# =====================================================
def get_roles_normalizados(roles) -> List[str]:
    if not roles:
        return []
    if isinstance(roles, list):
        return [r.lower() for r in roles if isinstance(r, str)]
    if isinstance(roles, str):
        try:
            parsed = json.loads(roles)
            if isinstance(parsed, list):
                return [r.lower() for r in parsed if isinstance(r, str)]
        except:
            pass
    return []

def es_admin(user: Usuario) -> bool:
    if user.rol_global in ROLES_ADMIN:
        return True
    roles = get_roles_normalizados(user.roles)
    return any(r in ROLES_ADMIN for r in roles)

def es_jefe(user: Usuario) -> bool:
    if user.rol_global == 'jefe':
        return True
    roles = get_roles_normalizados(user.roles)
    return 'jefe' in roles

def es_visitante(user: Usuario) -> bool:
    if user.rol_global == 'visitante':
        return True
    roles = get_roles_normalizados(user.roles)
    return 'visitante' in roles


# =====================================================
# FUNCIONES DE ORGANIGRAMA
# =====================================================
def _obtener_areas_hijas_organigrama(db: Session, empresa_id: UUID) -> dict:
    try:
        from app.models.configuracion import UnidadOrganigrama
        unidades = db.query(UnidadOrganigrama).filter(
            UnidadOrganigrama.empresa_id == empresa_id
        ).all()
        if not unidades:
            return {}
        unidad_map = {u.id: u for u in unidades}
        hijos_por_padre = {}
        for u in unidades:
            if u.padre_id and u.padre_id in unidad_map:
                padre_nombre = unidad_map[u.padre_id].nombre
                if padre_nombre not in hijos_por_padre:
                    hijos_por_padre[padre_nombre] = []
                hijos_por_padre[padre_nombre].append(u.nombre)
        return hijos_por_padre
    except Exception as e:
        logger.warning(f"No se pudo cargar organigrama: {e}")
        return {}

def _expandir_areas_con_hijas(areas_directas: List[str], hijos_por_padre: dict) -> List[str]:
    todas = set(areas_directas)
    visitados = set()
    def obtener_recursivo(nombre_area):
        if nombre_area in visitados:
            return
        visitados.add(nombre_area)
        hijas = hijos_por_padre.get(nombre_area, [])
        for hija in hijas:
            todas.add(hija)
            obtener_recursivo(hija)
    for area in areas_directas:
        obtener_recursivo(area)
    return list(todas)


# =====================================================
# OBTENER AUTOR (CACHEADO)
# =====================================================
def _obtener_autor_info(db: Session, autor_id: UUID) -> dict:
    cache_key = str(autor_id)
    cached = _cache_get(_autores_cache, cache_key, ttl=120)
    if cached:
        return cached
    
    autor = db.query(Usuario).filter(Usuario.id == autor_id).first()
    result = {}
    if autor:
        personal = db.query(Personal).filter(Personal.id == autor.personal_id).first()
        if personal:
            result = {
                "autor_nombre": personal.nombre,
                "autor_area": personal.area,
                "autor_iniciales": ''.join([p[0] for p in (personal.nombre or '').split()[:2]]).upper()
            }
        else:
            result = {
                "autor_nombre": autor.nombre or autor.email or "Usuario",
                "autor_area": "Administracion"
            }
    
    _cache_set(_autores_cache, cache_key, result)
    return result


# =====================================================
# ENRIQUECER PUBLICACIÓN (OPTIMIZADO)
# =====================================================
def enriquecer_publicacion_optimizada(db: Session, publicacion: Publicacion, vistas_lista: List[str] = None) -> dict:
    result = {
        "id": str(publicacion.id) if publicacion.id else None,
        "titulo": publicacion.titulo,
        "tipo": publicacion.tipo,
        "contenido_texto": publicacion.contenido_texto,
        "url_archivo": publicacion.url_archivo,
        "descripcion": publicacion.descripcion,
        "categoria": publicacion.categoria,
        "es_automatica": publicacion.es_automatica,
        "autor_id": str(publicacion.autor_id) if publicacion.autor_id else None,
        "empresa_id": str(publicacion.empresa_id) if publicacion.empresa_id else None,
        "audiencia": getattr(publicacion, 'audiencia', 'toda_empresa') or 'toda_empresa',
        "destinatario_id": str(getattr(publicacion, 'destinatario_id', None)) if getattr(publicacion, 'destinatario_id', None) else None,
        "es_privado": getattr(publicacion, 'audiencia', None) == 'privado',
        "fecha_publicacion": publicacion.fecha_publicacion.isoformat() if publicacion.fecha_publicacion else None,
        "fecha_expiracion": publicacion.fecha_expiracion.isoformat() if publicacion.fecha_expiracion else None,
        "activo": publicacion.activo,
        "fijado": publicacion.fijado,
        "total_vistas": publicacion.total_vistas or 0,
        "created_at": publicacion.created_at.isoformat() if publicacion.created_at else None,
        "updated_at": publicacion.updated_at.isoformat() if publicacion.updated_at else None,
        "vistas": vistas_lista or []
    }
    
    if publicacion.autor_id:
        autor_info = _obtener_autor_info(db, publicacion.autor_id)
        result.update(autor_info)
    
    return result


# =====================================================
# OBTENER DESTINATARIOS (OPTIMIZADO)
# =====================================================
def obtener_destinatarios_publicacion(db: Session, publicacion: Publicacion) -> List[Usuario]:
    audiencia = getattr(publicacion, 'audiencia', 'toda_empresa') or 'toda_empresa'
    
    # Mensaje privado
    if audiencia == 'privado':
        destinatario_personal_id = getattr(publicacion, 'destinatario_id', None)
        if destinatario_personal_id:
            destinatario = db.query(Usuario).filter(
                Usuario.personal_id == destinatario_personal_id,
                Usuario.activo == True
            ).first()
            return [destinatario] if destinatario else []
        return []
    
    # Base query
    query = db.query(Usuario).filter(Usuario.activo == True)
    
    if publicacion.empresa_id:
        query = query.filter(Usuario.empresa_id == publicacion.empresa_id)
    
    # Filtrar por audiencia
    if audiencia == 'visitantes':
        query = query.filter(
            or_(
                Usuario.rol_global == 'visitante',
                Usuario.roles.cast(String).like('%visitante%')
            )
        )
    elif audiencia == 'personal':
        query = query.filter(
            and_(
                Usuario.rol_global != 'visitante',
                ~Usuario.roles.cast(String).like('%visitante%')
            )
        )
    
    return query.all()


# =====================================================
# LISTAR PUBLICACIONES (OPTIMIZADO)
# =====================================================
@router.get("/")
async def listar_publicaciones(
    activo: Optional[bool] = Query(True),
    tipo: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    empresa_id: Optional[UUID] = Query(None),
    audiencia: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe", "usuario", "visitante", "escaner"]))
):
    try:
        query = db.query(Publicacion)
        
        if activo is not None:
            query = query.filter(Publicacion.activo == activo)
        if tipo:
            query = query.filter(Publicacion.tipo == tipo.upper())
        if categoria:
            query = query.filter(Publicacion.categoria == categoria)
        
        # Filtro por empresa
        if empresa_id:
            query = query.filter(
                or_(Publicacion.empresa_id == empresa_id, Publicacion.empresa_id == None)
            )
        elif current_user.empresa_id and not es_admin(current_user):
            query = query.filter(
                or_(Publicacion.empresa_id == current_user.empresa_id, Publicacion.empresa_id == None)
            )
        
        # =============================================
        # FILTRO DE VISIBILIDAD - CORREGIDO
        # =============================================
        if not es_admin(current_user):
            current_user_id = str(current_user.id)
            current_personal_id = str(current_user.personal_id) if current_user.personal_id else None
            
            # Construir condiciones
            condiciones = []
            
            # 1. El usuario es el AUTOR de la publicacion (ve todo lo que creo)
            condiciones.append(Publicacion.autor_id == current_user_id)
            
            # 2. Publicaciones NO privadas visibles segun audiencia
            if es_visitante(current_user):
                # Visitante ve: publicaciones para visitantes o toda_empresa (NO privadas)
                condiciones.append(
                    and_(
                        Publicacion.audiencia != 'privado',
                        or_(
                            Publicacion.audiencia.in_(['visitantes', 'toda_empresa']),
                            Publicacion.audiencia == None,
                        )
                    )
                )
            else:
                # Personal ve: publicaciones para personal o toda_empresa (NO privadas)
                condiciones.append(
                    and_(
                        Publicacion.audiencia != 'privado',
                        or_(
                            Publicacion.audiencia.in_(['personal', 'toda_empresa']),
                            Publicacion.audiencia == None,
                        )
                    )
                )
            
            # 3. Mensajes privados donde el usuario es DESTINATARIO
            if current_personal_id:
                condiciones.append(
                    and_(
                        Publicacion.audiencia == 'privado',
                        Publicacion.destinatario_id == current_personal_id,
                    )
                )
            
            # Aplicar todas las condiciones con OR
            query = query.filter(or_(*condiciones))
        
        if audiencia:
            query = query.filter(Publicacion.audiencia == audiencia)
        
        query = query.order_by(desc(Publicacion.fijado), desc(Publicacion.fecha_publicacion))
        publicaciones = query.offset(offset).limit(limit).all()
        
        # Cargar TODAS las vistas en UNA sola query
        pub_ids = [p.id for p in publicaciones]
        todas_vistas = {}
        if pub_ids:
            vistas = db.query(PublicacionVista).filter(
                PublicacionVista.publicacion_id.in_(pub_ids)
            ).all()
            for v in vistas:
                key = str(v.publicacion_id)
                if key not in todas_vistas:
                    todas_vistas[key] = []
                todas_vistas[key].append(str(v.usuario_id))
        
        # Enriquecer sin consultas extra
        resultado = []
        for pub in publicaciones:
            data = enriquecer_publicacion_optimizada(db, pub, todas_vistas.get(str(pub.id), []))
            resultado.append(data)
        
        logger.info(f"Publicaciones: {len(resultado)} para usuario {current_user.id} (rol: {current_user.rol_global}, personal_id: {current_user.personal_id})")
        return resultado
        
    except Exception as e:
        logger.error(f"Error listando publicaciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/{id}")
async def obtener_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe", "usuario", "visitante", "escaner"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicacion no encontrada")
        
        # Verificar visibilidad
        audiencia = getattr(publicacion, 'audiencia', 'toda_empresa') or 'toda_empresa'
        if not es_admin(current_user):
            if audiencia == 'privado':
                if str(publicacion.autor_id) != str(current_user.id) and \
                   str(getattr(publicacion, 'destinatario_id', None)) != str(current_user.personal_id):
                    raise HTTPException(status_code=403, detail="No tiene acceso a esta publicacion")
            elif es_visitante(current_user) and audiencia not in ['visitantes', 'toda_empresa'] and publicacion.autor_id != current_user.id:
                raise HTTPException(status_code=403, detail="No tiene acceso a esta publicacion")
            elif not es_visitante(current_user) and audiencia not in ['personal', 'toda_empresa'] and publicacion.autor_id != current_user.id:
                raise HTTPException(status_code=403, detail="No tiene acceso a esta publicacion")
        
        vistas = db.query(PublicacionVista).filter(
            PublicacionVista.publicacion_id == id
        ).all()
        vistas_lista = [str(v.usuario_id) for v in vistas]
        
        return enriquecer_publicacion_optimizada(db, publicacion, vistas_lista)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error obteniendo publicacion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", status_code=201)
async def crear_publicacion(
    publicacion_data: PublicacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        if publicacion_data.tipo == 'TEXTO' and not publicacion_data.contenido_texto:
            raise HTTPException(status_code=400, detail="contenido_texto es requerido para tipo TEXTO")
        
        if publicacion_data.tipo in ['IMAGEN', 'PDF'] and not publicacion_data.url_archivo:
            raise HTTPException(status_code=400, detail=f"url_archivo es requerido para tipo {publicacion_data.tipo}")
        
        empresa_id = publicacion_data.empresa_id or current_user.empresa_id
        audiencia = getattr(publicacion_data, 'audiencia', 'toda_empresa') or 'toda_empresa'
        destinatario_id = getattr(publicacion_data, 'destinatario_id', None)
        
        publicacion = Publicacion(
            titulo=publicacion_data.titulo,
            tipo=publicacion_data.tipo,
            contenido_texto=publicacion_data.contenido_texto,
            url_archivo=publicacion_data.url_archivo,
            descripcion=publicacion_data.descripcion,
            categoria=publicacion_data.categoria or "general",
            es_automatica=publicacion_data.es_automatica or False,
            autor_id=current_user.id,
            empresa_id=empresa_id,
            audiencia=audiencia,
            destinatario_id=destinatario_id,
            fecha_publicacion=publicacion_data.fecha_publicacion or datetime.now(),
            fecha_expiracion=publicacion_data.fecha_expiracion,
            fijado=publicacion_data.fijado or False,
            activo=True,
            total_vistas=0
        )
        
        db.add(publicacion)
        db.commit()
        db.refresh(publicacion)
        
        logger.info(f"Publicacion creada: {publicacion.id} - {publicacion.titulo[:30]}... (audiencia: {audiencia})")
        
        # Notificaciones
        try:
            destinatarios = obtener_destinatarios_publicacion(db, publicacion)
            
            if destinatarios:
                if audiencia == 'privado':
                    tipo_notif = "mensaje_privado"
                    titulo_notif = "Nuevo mensaje privado"
                    autor_personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
                    nombre_autor = autor_personal.nombre.split(',')[0].strip() if autor_personal else (current_user.nombre or 'Alguien')
                    mensaje_notif = f"{nombre_autor} te envio un mensaje privado"
                elif publicacion.categoria == "cumpleanios":
                    tipo_notif = "cumpleanios"
                    titulo_notif = "Feliz Cumpleanos"
                    mensaje_notif = publicacion.titulo[:100]
                else:
                    tipo_notif = "nueva_publicacion"
                    titulo_notif = "Nueva publicacion"
                    mensaje_notif = publicacion.titulo[:100]
                
                crear_notificacion_masiva(
                    db=db,
                    usuarios_ids=[u.id for u in destinatarios],
                    tipo=tipo_notif,
                    titulo=titulo_notif,
                    mensaje=mensaje_notif,
                    publicacion_id=publicacion.id
                )
                
                logger.info(f"Notificaciones enviadas: {len(destinatarios)} (tipo: {tipo_notif})")
        
        except Exception as e:
            logger.error(f"Error creando notificaciones (no critico): {e}")
        
        return enriquecer_publicacion_optimizada(db, publicacion, [])
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error en crear_publicacion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{id}")
async def actualizar_publicacion(
    id: UUID,
    publicacion_data: PublicacionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicacion no encontrada")
        
        if str(publicacion.autor_id) != str(current_user.id) and not es_admin(current_user):
            raise HTTPException(status_code=403, detail="No tiene permiso para editar esta publicacion")
        
        update_data = publicacion_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(publicacion, field, value)
        
        db.commit()
        db.refresh(publicacion)
        logger.info(f"Publicacion actualizada: {id}")
        return enriquecer_publicacion_optimizada(db, publicacion)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error actualizando publicacion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{id}")
async def eliminar_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicacion no encontrada")
        
        if str(publicacion.autor_id) != str(current_user.id) and not es_admin(current_user):
            raise HTTPException(status_code=403, detail="No tiene permiso para eliminar esta publicacion")
        
        publicacion.activo = False
        db.commit()
        logger.info(f"Publicacion desactivada: {id}")
        return {"success": True, "message": "Publicacion desactivada correctamente", "id": str(id)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error eliminando publicacion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{id}/vistas", status_code=201)
async def marcar_como_vista(
    id: UUID,
    request: MarcarVistaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe", "usuario", "visitante", "escaner"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicacion no encontrada")
        if not publicacion.activo:
            raise HTTPException(status_code=400, detail="La publicacion no esta activa")
        
        usuario = db.query(Usuario).filter(Usuario.id == request.usuario_id).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        vista_existente = db.query(PublicacionVista).filter(
            and_(PublicacionVista.publicacion_id == id, PublicacionVista.usuario_id == request.usuario_id)
        ).first()
        
        if vista_existente:
            return {"message": "Publicacion ya marcada como vista", "ya_vista": True}
        
        nueva_vista = PublicacionVista(publicacion_id=id, usuario_id=request.usuario_id)
        db.add(nueva_vista)
        publicacion.total_vistas = (publicacion.total_vistas or 0) + 1
        db.commit()
        
        return {"success": True, "message": "Publicacion marcada como vista", "id": str(nueva_vista.id)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error marcando vista: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}/vistas")
async def obtener_vistas_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicacion no encontrada")
        
        vistas = db.query(PublicacionVista).filter(
            PublicacionVista.publicacion_id == id
        ).order_by(desc(PublicacionVista.fecha_vista)).all()
        
        return [{
            "id": str(v.id),
            "usuario_id": str(v.usuario_id),
            "fecha_vista": v.fecha_vista.isoformat() if v.fecha_vista else None
        } for v in vistas]
    except Exception as e:
        logger.error(f"Error obteniendo vistas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}/estadisticas")
async def obtener_estadisticas_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicacion no encontrada")
        
        destinatarios = obtener_destinatarios_publicacion(db, publicacion)
        total_destinatarios = len(destinatarios)
        destinatarios_ids = [d.id for d in destinatarios]
        
        vistas = db.query(PublicacionVista).filter(PublicacionVista.publicacion_id == id).all()
        vistas_validas = [v for v in vistas if v.usuario_id in destinatarios_ids]
        total_vistas = len(vistas_validas)
        porcentaje = (total_vistas / total_destinatarios * 100) if total_destinatarios > 0 else 0
        
        usuarios_vieron = []
        for vista in vistas_validas:
            usuario = db.query(Usuario).filter(Usuario.id == vista.usuario_id).first()
            if usuario and usuario.personal_id:
                personal = db.query(Personal).filter(Personal.id == usuario.personal_id).first()
                if personal:
                    usuarios_vieron.append({
                        "id": str(personal.id),
                        "nombre": personal.nombre,
                        "area": personal.area,
                        "fecha_vista": vista.fecha_vista.isoformat()
                    })
        
        usuarios_no_vieron = []
        for destinatario in destinatarios:
            if destinatario.id not in [v.usuario_id for v in vistas_validas]:
                if destinatario.personal_id:
                    personal = db.query(Personal).filter(Personal.id == destinatario.personal_id).first()
                    if personal:
                        usuarios_no_vieron.append({
                            "id": str(personal.id),
                            "nombre": personal.nombre,
                            "area": personal.area
                        })
        
        return {
            "publicacion_id": str(id),
            "titulo": publicacion.titulo,
            "total_vistas": total_vistas,
            "total_empleados": total_destinatarios,
            "porcentaje_vistas": round(porcentaje, 2),
            "usuarios_vieron": usuarios_vieron,
            "usuarios_no_vieron": usuarios_no_vieron
        }
    except Exception as e:
        logger.error(f"Error obteniendo estadisticas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estadisticas/globales")
async def obtener_estadisticas_globales(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        query_publicaciones = db.query(Publicacion).filter(Publicacion.activo == True)
        
        if es_jefe(current_user) and not es_admin(current_user):
            query_publicaciones = query_publicaciones.filter(Publicacion.autor_id == current_user.id)
        elif current_user.empresa_id and not es_admin(current_user):
            query_publicaciones = query_publicaciones.filter(
                or_(Publicacion.empresa_id == current_user.empresa_id, Publicacion.empresa_id == None)
            )
        
        publicaciones_activas = query_publicaciones.all()
        total_publicaciones = len(publicaciones_activas)
        publicaciones_ids = [p.id for p in publicaciones_activas]
        
        todos_destinatarios = set()
        for pub in publicaciones_activas:
            destinatarios = obtener_destinatarios_publicacion(db, pub)
            for d in destinatarios:
                todos_destinatarios.add(d.id)
        
        total_destinatarios = len(todos_destinatarios)
        
        total_vistas = db.query(PublicacionVista).filter(
            PublicacionVista.publicacion_id.in_(publicaciones_ids)
        ).count()
        
        usuarios_vieron_todo = 0
        for dest_id in todos_destinatarios:
            vistas_usuario = db.query(PublicacionVista).filter(
                and_(
                    PublicacionVista.usuario_id == dest_id,
                    PublicacionVista.publicacion_id.in_(publicaciones_ids)
                )
            ).count()
            if vistas_usuario >= total_publicaciones and total_publicaciones > 0:
                usuarios_vieron_todo += 1
        
        porcentaje = (usuarios_vieron_todo / total_destinatarios * 100) if total_destinatarios > 0 else 0
        
        return {
            "total_publicaciones": total_publicaciones,
            "total_vistas": total_vistas,
            "total_empleados": total_destinatarios,
            "usuarios_vieron_todo": usuarios_vieron_todo,
            "porcentaje_lectura_completa": round(porcentaje, 2)
        }
    except Exception as e:
        logger.error(f"Error obteniendo estadisticas globales: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cumpleanios/auto", status_code=201)
async def generar_publicacion_cumpleanios(
    empresa_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        hoy = date.today()
        emp_id = empresa_id or current_user.empresa_id
        
        fecha_inicio = datetime(hoy.year, hoy.month, hoy.day, 0, 0, 0)
        fecha_fin = datetime(hoy.year, hoy.month, hoy.day, 23, 59, 59)
        
        query_existente = db.query(Publicacion).filter(
            and_(
                Publicacion.categoria == "cumpleanios",
                Publicacion.es_automatica == True,
                Publicacion.fecha_publicacion >= fecha_inicio,
                Publicacion.fecha_publicacion <= fecha_fin
            )
        )
        if emp_id:
            query_existente = query_existente.filter(
                or_(Publicacion.empresa_id == emp_id, Publicacion.empresa_id == None)
            )
        
        existente = query_existente.first()
        if existente:
            return {"message": "Ya existe una publicacion de cumpleanos para hoy", "id": str(existente.id)}
        
        query_empleados = db.query(Personal).filter(Personal.activo == True)
        if emp_id:
            query_empleados = query_empleados.filter(
                or_(Personal.empresa_id == emp_id, Personal.empresa_id == None)
            )
        empleados = query_empleados.all()
        
        cumpleanieros = []
        for emp in empleados:
            if emp.fecha_nacimiento and emp.fecha_nacimiento.month == hoy.month and emp.fecha_nacimiento.day == hoy.day:
                cumpleanieros.append(emp)
        
        if not cumpleanieros:
            return {"message": "No hay cumpleaneros hoy", "cantidad": 0}
        
        meses = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
                 7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}
        fecha_formateada = f"{hoy.day} de {meses[hoy.month]}"
        
        lista = []
        for emp in cumpleanieros:
            edad = hoy.year - emp.fecha_nacimiento.year
            if hoy.month < emp.fecha_nacimiento.month or (hoy.month == emp.fecha_nacimiento.month and hoy.day < emp.fecha_nacimiento.day):
                edad -= 1
            grado = emp.grado if emp.grado else ""
            lista.append(f"{grado} {emp.nombre} ({edad} anos) - {emp.area or 'Sin area'}")
        
        mensaje_intro = f"Hoy celebramos el cumpleanos de nuestro companero!" if len(cumpleanieros) == 1 else f"Hoy celebramos los cumpleanos de {len(cumpleanieros)} companeros!"
        
        contenido = f"""{mensaje_intro}

{chr(10).join(lista)}

Les deseamos un feliz dia lleno de alegria y bendiciones.

Que este nuevo ano de vida este lleno de exitos, salud y momentos inolvidables.

Felicitaciones de parte de todo el equipo!"""
        
        publicacion = Publicacion(
            titulo=f"Feliz Cumpleanos - {fecha_formateada}",
            tipo="TEXTO",
            contenido_texto=contenido,
            categoria="cumpleanios",
            es_automatica=True,
            autor_id=current_user.id,
            empresa_id=emp_id,
            audiencia='toda_empresa',
            fecha_publicacion=datetime.now(),
            activo=True
        )
        
        db.add(publicacion)
        db.commit()
        db.refresh(publicacion)
        logger.info(f"Publicacion automatica de cumpleanos creada: {publicacion.id}")
        
        try:
            destinatarios = obtener_destinatarios_publicacion(db, publicacion)
            if destinatarios:
                crear_notificacion_masiva(
                    db=db,
                    usuarios_ids=[u.id for u in destinatarios],
                    tipo="cumpleanios",
                    titulo="Feliz Cumpleanos",
                    mensaje=f"Hoy celebramos a {len(cumpleanieros)} companero(s)",
                    publicacion_id=publicacion.id
                )
                logger.info(f"Notificaciones de cumpleanos enviadas a {len(destinatarios)} destinatarios")
        except Exception as e:
            logger.error(f"Error creando notificaciones de cumpleanos: {e}")
        
        return {
            "success": True,
            "message": f"Publicacion de cumpleanos creada con {len(cumpleanieros)} cumpleaneros",
            "id": str(publicacion.id),
            "cumpleanieros": len(cumpleanieros)
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Error en generar_publicacion_cumpleanios: {e}")
        raise HTTPException(status_code=500, detail=str(e))