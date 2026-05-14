# app/api/publicaciones.py
# ROUTER PARA PUBLICACIONES - JERARQUÍA CORREGIDA - USA FUNCIONES EXISTENTES

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date
import logging

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

# 🆕 USAMOS LAS MISMAS FUNCIONES DE personal.py
from app.utils.roles import (
    ROLES_ADMIN, 
    ROLES_JEFE,
    ROLES_JEFATURA,
)

logger = logging.getLogger(__name__)

router = APIRouter()

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
# FUNCIONES AUXILIARES DE ROLES (misma lógica que personal.py)
# =====================================================

def get_roles_normalizados(roles) -> List[str]:
    """Idéntico a personal.py"""
    import json
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
    """Verifica si el usuario tiene rol de administrador"""
    if user.rol_global in ROLES_ADMIN:
        return True
    roles = get_roles_normalizados(user.roles)
    return any(r in ROLES_ADMIN for r in roles)

def es_jefe(user: Usuario) -> bool:
    """Verifica si el usuario tiene rol de jefe"""
    if user.rol_global == 'jefe':
        return True
    roles = get_roles_normalizados(user.roles)
    return 'jefe' in roles

def es_visitante(user: Usuario) -> bool:
    """Verifica si el usuario es visitante"""
    if user.rol_global == 'visitante':
        return True
    roles = get_roles_normalizados(user.roles)
    return 'visitante' in roles

def tiene_jefatura(user: Usuario) -> bool:
    """Verifica si el usuario tiene algún rol de jefatura"""
    if user.rol_global in ROLES_JEFATURA:
        return True
    roles = get_roles_normalizados(user.roles)
    return any(r in ROLES_JEFATURA for r in roles)


# =====================================================
# FUNCIONES DE JERARQUÍA (misma lógica que personal.py)
# =====================================================

def get_areas_jefatura(jefe_personal: Personal) -> List[str]:
    """
    IDÉNTICO a personal.py - Obtiene todas las áreas que están bajo la jefatura.
    """
    if not jefe_personal:
        return []
    
    areas = []
    
    if jefe_personal.areas_que_jefatura and isinstance(jefe_personal.areas_que_jefatura, list):
        for item in jefe_personal.areas_que_jefatura:
            if isinstance(item, str):
                if ':' in item:
                    areas.append(item.split(':', 1)[1])
                else:
                    areas.append(item)
    
    if jefe_personal.areas_jefatura and isinstance(jefe_personal.areas_jefatura, dict):
        for tipo, areas_lista in jefe_personal.areas_jefatura.items():
            if isinstance(areas_lista, list):
                areas.extend(areas_lista)
    
    # Si no tiene áreas explícitas pero tiene un área asignada, jefatura esa área
    if not areas and jefe_personal.area:
        areas = [jefe_personal.area]
    
    return list(set(areas))


def get_subordinados(db: Session, jefe_personal: Personal) -> List[Personal]:
    """
    IDÉNTICO a personal.py - Obtiene todos los subordinados de un jefe.
    """
    areas = get_areas_jefatura(jefe_personal)
    
    if not areas:
        return []
    
    subordinados = db.query(Personal).filter(
        Personal.activo == True,
        Personal.area.in_(areas),
        Personal.id != jefe_personal.id
    ).all()
    
    return subordinados


def obtener_visitantes_de_jefe(db: Session, usuario_jefe: Usuario) -> List[Usuario]:
    """
    Obtiene los USUARIOS visitantes que están bajo la jefatura de un jefe.
    Usa get_subordinados() y luego filtra por rol 'visitante'.
    """
    # Obtener el registro Personal del jefe
    jefe_personal = db.query(Personal).filter(Personal.id == usuario_jefe.personal_id).first()
    
    if not jefe_personal:
        return []
    
    # Obtener subordinados (todo personal en sus áreas)
    subordinados = get_subordinados(db, jefe_personal)
    subordinados_ids = [s.id for s in subordinados]
    
    if not subordinados_ids:
        return []
    
    # De los subordinados, filtrar solo los que son VISITANTES
    # Buscamos en Usuario donde personal_id está en subordinados y rol es 'visitante'
    usuarios_subordinados = db.query(Usuario).filter(
        and_(
            Usuario.personal_id.in_(subordinados_ids),
            Usuario.activo == True
        )
    ).all()
    
    # Filtrar por rol visitante
    visitantes = []
    for u in usuarios_subordinados:
        if es_visitante(u):
            visitantes.append(u)
    
    return visitantes


def obtener_jefe_de_visitante(db: Session, usuario_visitante: Usuario) -> Optional[Usuario]:
    """
    Encuentra el jefe a cargo de un visitante.
    Busca qué jefe tiene en sus áreas el área del visitante.
    """
    if not usuario_visitante.personal_id:
        return None
    
    visitante_personal = db.query(Personal).filter(Personal.id == usuario_visitante.personal_id).first()
    
    if not visitante_personal or not visitante_personal.area:
        return None
    
    area_visitante = visitante_personal.area
    
    # Buscar todos los jefes activos
    jefes_personal = db.query(Personal).filter(
        and_(
            Personal.activo == True,
            or_(
                Personal.roles.contains('jefe'),
                Personal.rol_global == 'jefe'
            )
        )
    ).all()
    
    # Buscar el jefe cuya área de jefatura incluya el área del visitante
    for jefe_p in jefes_personal:
        areas_jefe = get_areas_jefatura(jefe_p)
        if area_visitante in areas_jefe:
            # Encontrar el Usuario asociado a este jefe
            jefe_usuario = db.query(Usuario).filter(
                and_(
                    Usuario.personal_id == jefe_p.id,
                    Usuario.activo == True
                )
            ).first()
            if jefe_usuario:
                return jefe_usuario
    
    return None


def publicacion_visible_para_usuario(publicacion: Publicacion, usuario: Usuario, db: Session) -> bool:
    """
    Determina si una publicación debe ser visible para un usuario específico.
    
    REGLAS JERÁRQUICAS:
    - Admin/Super admin: ve TODAS las publicaciones
    - Jefe: ve sus propias publicaciones + publicaciones de admins + 
            publicaciones de otros jefes de su empresa
    - Usuario normal (no visitante): ve publicaciones de jefes de su empresa + admins
    - Visitante: SOLO ve publicaciones de SU jefe asignado + publicaciones de admins
    """
    # 1. Los administradores ven todo
    if es_admin(usuario):
        return True
    
    # 2. Verificar empresa (seguridad básica)
    if usuario.empresa_id and publicacion.empresa_id:
        if str(usuario.empresa_id) != str(publicacion.empresa_id):
            return False
    
    # 3. Si no tiene autor, usar lógica de audiencia (publicaciones del sistema)
    if not publicacion.autor_id:
        audiencia = getattr(publicacion, 'audiencia', 'toda_empresa') or 'toda_empresa'
        
        if es_visitante(usuario):
            return audiencia in ['visitantes', 'toda_empresa']
        else:
            return audiencia in ['personal', 'toda_empresa']
    
    # 4. Si tiene autor, aplicar jerarquía
    autor = db.query(Usuario).filter(Usuario.id == publicacion.autor_id).first()
    
    if not autor:
        return True  # Si no encontramos al autor, permitir por seguridad
    
    # 4a. Si el autor es admin → visible para todos en la empresa
    if es_admin(autor):
        return True
    
    # 4b. Si el autor es jefe → visible según jerarquía
    if es_jefe(autor):
        if es_visitante(usuario):
            # Visitante solo ve publicaciones de SU jefe
            jefe_del_visitante = obtener_jefe_de_visitante(db, usuario)
            return jefe_del_visitante is not None and str(jefe_del_visitante.id) == str(autor.id)
        elif es_jefe(usuario):
            # Un jefe ve publicaciones de otros jefes en su empresa
            return usuario.empresa_id == autor.empresa_id
        else:
            # Usuario normal ve publicaciones de jefes de su empresa
            return usuario.empresa_id == autor.empresa_id
    
    # 4c. Para otros roles, usar audiencia
    audiencia = getattr(publicacion, 'audiencia', 'toda_empresa') or 'toda_empresa'
    
    if es_visitante(usuario):
        return audiencia in ['visitantes', 'toda_empresa']
    else:
        return audiencia in ['personal', 'toda_empresa']


def obtener_destinatarios_publicacion(db: Session, publicacion: Publicacion) -> List[Usuario]:
    """
    Obtiene los destinatarios CORRECTOS de una publicación según jerarquía.
    
    - Admin publica → todos en su alcance
    - Jefe publica → SOLO sus visitantes asignados
    - Sistema publica → según audiencia configurada
    """
    # Si no tiene autor (sistema)
    if not publicacion.autor_id:
        audiencia = getattr(publicacion, 'audiencia', 'toda_empresa') or 'toda_empresa'
        query = db.query(Usuario).filter(Usuario.activo == True)
        
        if publicacion.empresa_id:
            query = query.filter(Usuario.empresa_id == publicacion.empresa_id)
        
        if audiencia == 'visitantes':
            query = query.filter(
                or_(
                    Usuario.rol_global == 'visitante',
                    Usuario.roles.contains('visitante')
                )
            )
        elif audiencia == 'personal':
            query = query.filter(
                and_(
                    Usuario.rol_global != 'visitante',
                    ~Usuario.roles.contains('visitante')
                )
            )
        
        return query.all()
    
    # Publicación con autor
    autor = db.query(Usuario).filter(Usuario.id == publicacion.autor_id).first()
    
    if not autor:
        return []
    
    # Admin: todos en su empresa
    if es_admin(autor):
        query = db.query(Usuario).filter(Usuario.activo == True)
        if autor.empresa_id:
            query = query.filter(Usuario.empresa_id == autor.empresa_id)
        return query.all()
    
    # Jefe: SOLO sus visitantes
    if es_jefe(autor):
        return obtener_visitantes_de_jefe(db, autor)
    
    # Otros roles: según audiencia
    audiencia = getattr(publicacion, 'audiencia', 'toda_empresa') or 'toda_empresa'
    query = db.query(Usuario).filter(Usuario.activo == True)
    
    if publicacion.empresa_id:
        query = query.filter(Usuario.empresa_id == publicacion.empresa_id)
    
    if audiencia == 'visitantes':
        query = query.filter(
            or_(
                Usuario.rol_global == 'visitante',
                Usuario.roles.contains('visitante')
            )
        )
    elif audiencia == 'personal':
        query = query.filter(
            and_(
                Usuario.rol_global != 'visitante',
                ~Usuario.roles.contains('visitante')
            )
        )
    
    return query.all()


def enriquecer_publicacion(db: Session, publicacion: Publicacion) -> dict:
    """Enriquece una publicación con datos del autor, vistas y empresa"""
    result = {
        "id": publicacion.id,
        "titulo": publicacion.titulo,
        "tipo": publicacion.tipo,
        "contenido_texto": publicacion.contenido_texto,
        "url_archivo": publicacion.url_archivo,
        "descripcion": publicacion.descripcion,
        "categoria": publicacion.categoria,
        "es_automatica": publicacion.es_automatica,
        "autor_id": publicacion.autor_id,
        "empresa_id": publicacion.empresa_id,
        "audiencia": getattr(publicacion, 'audiencia', 'toda_empresa'),
        "fecha_publicacion": publicacion.fecha_publicacion,
        "fecha_expiracion": publicacion.fecha_expiracion,
        "activo": publicacion.activo,
        "fijado": publicacion.fijado,
        "total_vistas": publicacion.total_vistas or 0,
        "created_at": publicacion.created_at,
        "updated_at": publicacion.updated_at,
        "vistas": []
    }
    
    if publicacion.autor_id:
        autor = db.query(Usuario).filter(Usuario.id == publicacion.autor_id).first()
        if autor:
            personal = db.query(Personal).filter(Personal.id == autor.personal_id).first()
            if personal:
                result["autor_nombre"] = personal.nombre
                result["autor_area"] = personal.area
                partes = personal.nombre.split()
                result["autor_iniciales"] = ''.join([p[0] for p in partes[:2]]).upper()
    
    return result


# =====================================================
# ENDPOINTS
# =====================================================

@router.get("/", response_model=List[PublicacionResponse])
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
    """
    Lista publicaciones con filtro jerárquico correcto.
    - Visitante: SOLO ve publicaciones de SU jefe + admins
    - Jefe: ve sus publicaciones + admins + otros jefes de la empresa
    - Admin: ve todo
    """
    try:
        query = db.query(Publicacion)
        
        # Filtros básicos
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
        
        # Ordenar
        query = query.order_by(desc(Publicacion.fijado), desc(Publicacion.fecha_publicacion))
        
        publicaciones = query.offset(offset).limit(limit).all()
        
        # 🆕 FILTRO JERÁRQUICO
        resultado = []
        for pub in publicaciones:
            if publicacion_visible_para_usuario(pub, current_user, db):
                resultado.append(enriquecer_publicacion(db, pub))
        
        logger.info(f"📋 {len(resultado)} publicaciones para usuario {current_user.id} (rol_global: {current_user.rol_global})")
        return resultado
        
    except Exception as e:
        logger.error(f"❌ Error listando publicaciones: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}", response_model=PublicacionResponse)
async def obtener_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe", "usuario", "visitante", "escaner"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicación no encontrada")
        
        if not publicacion_visible_para_usuario(publicacion, current_user, db):
            raise HTTPException(status_code=403, detail="No tiene acceso a esta publicación")
        
        return enriquecer_publicacion(db, publicacion)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error obteniendo publicación: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", response_model=PublicacionResponse, status_code=201)
async def crear_publicacion(
    publicacion_data: PublicacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Crea una publicación con notificaciones CORRECTAS.
    - Jefe publica → notifica SOLO a sus visitantes
    - Admin publica → notifica a todos en su empresa
    """
    try:
        # Validaciones
        if publicacion_data.tipo == 'TEXTO' and not publicacion_data.contenido_texto:
            raise HTTPException(status_code=400, detail="contenido_texto es requerido para tipo TEXTO")
        
        if publicacion_data.tipo in ['IMAGEN', 'PDF'] and not publicacion_data.url_archivo:
            raise HTTPException(status_code=400, detail=f"url_archivo es requerido para tipo {publicacion_data.tipo}")
        
        empresa_id = publicacion_data.empresa_id or current_user.empresa_id
        audiencia = getattr(publicacion_data, 'audiencia', 'toda_empresa') or 'toda_empresa'
        
        # Crear publicación
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
            fecha_publicacion=publicacion_data.fecha_publicacion or datetime.now(),
            fecha_expiracion=publicacion_data.fecha_expiracion,
            fijado=publicacion_data.fijado or False,
            activo=True,
            total_vistas=0
        )
        
        db.add(publicacion)
        db.commit()
        db.refresh(publicacion)
        
        logger.info(f"✅ Publicación creada: {publicacion.id} - {publicacion.titulo[:30]}...")
        
        # 🆕 NOTIFICACIONES CON DESTINATARIOS CORRECTOS
        try:
            destinatarios = obtener_destinatarios_publicacion(db, publicacion)
            
            if destinatarios:
                tipo_notif = "cumpleanios" if publicacion.categoria == "cumpleanios" else "nueva_publicacion"
                titulo_notif = "🎂 ¡Feliz Cumpleaños!" if tipo_notif == "cumpleanios" else "📢 Nueva publicación"
                
                if es_jefe(current_user):
                    logger.info(f"🔔 Jefe {current_user.id} notificando a {len(destinatarios)} visitantes asignados")
                elif es_admin(current_user):
                    logger.info(f"🔔 Admin {current_user.id} notificando a {len(destinatarios)} usuarios de la empresa")
                
                crear_notificacion_masiva(
                    db=db,
                    usuarios_ids=[u.id for u in destinatarios],
                    tipo=tipo_notif,
                    titulo=titulo_notif,
                    mensaje=publicacion.titulo[:100],
                    publicacion_id=publicacion.id
                )
                logger.info(f"🔔 {len(destinatarios)} notificaciones enviadas")
            else:
                logger.info(f"ℹ️ Sin destinatarios para notificar")
        
        except Exception as e:
            logger.error(f"⚠️ Error creando notificaciones (no crítico): {e}")
        
        return enriquecer_publicacion(db, publicacion)
    
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error en crear_publicacion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{id}", response_model=PublicacionResponse)
async def actualizar_publicacion(
    id: UUID,
    publicacion_data: PublicacionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicación no encontrada")
        
        # Solo el autor o admin pueden editar
        if str(publicacion.autor_id) != str(current_user.id) and not es_admin(current_user):
            raise HTTPException(status_code=403, detail="No tiene permiso para editar esta publicación")
        
        update_data = publicacion_data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(publicacion, field, value)
        
        db.commit()
        db.refresh(publicacion)
        logger.info(f"✏️ Publicación actualizada: {id}")
        return enriquecer_publicacion(db, publicacion)
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error actualizando publicación: {e}")
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
            raise HTTPException(status_code=404, detail="Publicación no encontrada")
        
        # Solo el autor o admin pueden eliminar
        if str(publicacion.autor_id) != str(current_user.id) and not es_admin(current_user):
            raise HTTPException(status_code=403, detail="No tiene permiso para eliminar esta publicación")
        
        publicacion.activo = False
        db.commit()
        logger.info(f"🗑️ Publicación desactivada: {id}")
        return {"success": True, "message": "Publicación desactivada correctamente", "id": str(id)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error eliminando publicación: {e}")
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
            raise HTTPException(status_code=404, detail="Publicación no encontrada")
        if not publicacion.activo:
            raise HTTPException(status_code=400, detail="La publicación no está activa")
        
        usuario = db.query(Usuario).filter(Usuario.id == request.usuario_id).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        # Verificar acceso
        if not publicacion_visible_para_usuario(publicacion, usuario, db):
            raise HTTPException(status_code=403, detail="Este usuario no tiene acceso a esta publicación")
        
        vista_existente = db.query(PublicacionVista).filter(
            and_(PublicacionVista.publicacion_id == id, PublicacionVista.usuario_id == request.usuario_id)
        ).first()
        
        if vista_existente:
            return {"message": "Publicación ya marcada como vista", "ya_vista": True}
        
        nueva_vista = PublicacionVista(publicacion_id=id, usuario_id=request.usuario_id)
        db.add(nueva_vista)
        publicacion.total_vistas = (publicacion.total_vistas or 0) + 1
        db.commit()
        
        return {"success": True, "message": "Publicación marcada como vista", "id": str(nueva_vista.id)}
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error marcando vista: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}/vistas", response_model=List[PublicacionVistaResponse])
async def obtener_vistas_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicación no encontrada")
        
        vistas = db.query(PublicacionVista).filter(
            PublicacionVista.publicacion_id == id
        ).order_by(desc(PublicacionVista.fecha_vista)).all()
        
        return vistas
    except Exception as e:
        logger.error(f"❌ Error obteniendo vistas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{id}/estadisticas", response_model=PublicacionEstadisticas)
async def obtener_estadisticas_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Estadísticas CORRECTAS según jerarquía.
    - Jefe ve estadísticas SOLO de sus visitantes
    - Admin ve estadísticas de todos en la empresa
    """
    try:
        publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
        if not publicacion:
            raise HTTPException(status_code=404, detail="Publicación no encontrada")
        
        # 🆕 Obtener destinatarios correctos según jerarquía
        destinatarios = obtener_destinatarios_publicacion(db, publicacion)
        total_destinatarios = len(destinatarios)
        destinatarios_ids = [d.id for d in destinatarios]
        
        # Obtener todas las vistas
        vistas = db.query(PublicacionVista).filter(PublicacionVista.publicacion_id == id).all()
        
        # Filtrar vistas que corresponden a destinatarios reales
        vistas_validas = [v for v in vistas if v.usuario_id in destinatarios_ids]
        total_vistas = len(vistas_validas)
        porcentaje = (total_vistas / total_destinatarios * 100) if total_destinatarios > 0 else 0
        
        # Usuarios que vieron
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
        
        # Usuarios que NO vieron (solo entre los destinatarios reales)
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
        
        logger.info(f"📊 Estadísticas pub {id}: {total_vistas}/{total_destinatarios} ({porcentaje:.1f}%)")
        
        return {
            "publicacion_id": id,
            "titulo": publicacion.titulo,
            "total_vistas": total_vistas,
            "total_empleados": total_destinatarios,
            "porcentaje_vistas": round(porcentaje, 2),
            "usuarios_vieron": usuarios_vieron,
            "usuarios_no_vieron": usuarios_no_vieron
        }
    except Exception as e:
        logger.error(f"❌ Error obteniendo estadísticas: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/estadisticas/globales", response_model=EstadisticasGlobales)
async def obtener_estadisticas_globales(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Estadísticas globales según alcance del usuario.
    - Jefe: solo sus propias publicaciones
    - Admin: todas las de su empresa
    """
    try:
        query_publicaciones = db.query(Publicacion).filter(Publicacion.activo == True)
        
        if es_jefe(current_user) and not es_admin(current_user):
            # Jefe solo ve SUS publicaciones
            query_publicaciones = query_publicaciones.filter(Publicacion.autor_id == current_user.id)
        elif current_user.empresa_id and not es_admin(current_user):
            query_publicaciones = query_publicaciones.filter(
                or_(Publicacion.empresa_id == current_user.empresa_id, Publicacion.empresa_id == None)
            )
        
        publicaciones_activas = query_publicaciones.all()
        total_publicaciones = len(publicaciones_activas)
        publicaciones_ids = [p.id for p in publicaciones_activas]
        
        # Obtener destinatarios únicos
        todos_destinatarios = set()
        for pub in publicaciones_activas:
            destinatarios = obtener_destinatarios_publicacion(db, pub)
            for d in destinatarios:
                todos_destinatarios.add(d.id)
        
        total_destinatarios = len(todos_destinatarios)
        
        # Contar vistas
        total_vistas = db.query(PublicacionVista).filter(
            PublicacionVista.publicacion_id.in_(publicaciones_ids)
        ).count()
        
        # Usuarios que vieron todo
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
        logger.error(f"❌ Error obteniendo estadísticas globales: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cumpleanios/auto", status_code=201)
async def generar_publicacion_cumpleanios(
    empresa_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "jefe"]))
):
    """
    Genera publicación de cumpleaños.
    - Jefe: solo ve cumpleaños de sus visitantes
    - Admin: todos los de la empresa
    """
    try:
        hoy = date.today()
        emp_id = empresa_id or current_user.empresa_id
        
        fecha_inicio = datetime(hoy.year, hoy.month, hoy.day, 0, 0, 0)
        fecha_fin = datetime(hoy.year, hoy.month, hoy.day, 23, 59, 59)
        
        # Verificar si ya existe
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
            return {"message": "Ya existe una publicación de cumpleaños para hoy", "id": str(existente.id)}
        
        # Buscar cumpleañeros según alcance
        if es_jefe(current_user) and not es_admin(current_user):
            # Jefe: solo cumpleaños de sus visitantes
            visitantes = obtener_visitantes_de_jefe(db, current_user)
            visitantes_personal_ids = [v.personal_id for v in visitantes if v.personal_id]
            
            empleados = db.query(Personal).filter(
                and_(
                    Personal.activo == True,
                    Personal.id.in_(visitantes_personal_ids)
                )
            ).all()
        else:
            # Admin: todos los de la empresa
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
            return {"message": "No hay cumpleañeros hoy", "cantidad": 0}
        
        meses = {1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo", 6: "junio",
                 7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"}
        fecha_formateada = f"{hoy.day} de {meses[hoy.month]}"
        
        lista = []
        for emp in cumpleanieros:
            edad = hoy.year - emp.fecha_nacimiento.year
            if hoy.month < emp.fecha_nacimiento.month or (hoy.month == emp.fecha_nacimiento.month and hoy.day < emp.fecha_nacimiento.day):
                edad -= 1
            grado = emp.grado if emp.grado else ""
            lista.append(f"🎂 {grado} {emp.nombre} ({edad} años) - {emp.area or '—'}")
        
        mensaje_intro = f"¡Hoy celebramos el cumpleaños de nuestro compañero!" if len(cumpleanieros) == 1 else f"¡Hoy celebramos los cumpleaños de {len(cumpleanieros)} compañeros!"
        
        contenido = f"""{mensaje_intro}

{chr(10).join(lista)}

¡Les deseamos un feliz día lleno de alegría y bendiciones! 🎂🎈

Que este nuevo año de vida esté lleno de éxitos, salud y momentos inolvidables.

¡Felicitaciones de parte de todo el equipo! 🎉"""
        
        publicacion = Publicacion(
            titulo=f"🎉 ¡Feliz Cumpleaños! - {fecha_formateada}",
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
        logger.info(f"🎂 Publicación automática de cumpleaños creada: {publicacion.id}")
        
        # Notificaciones a destinatarios correctos
        try:
            destinatarios = obtener_destinatarios_publicacion(db, publicacion)
            
            if destinatarios:
                crear_notificacion_masiva(
                    db=db,
                    usuarios_ids=[u.id for u in destinatarios],
                    tipo="cumpleanios",
                    titulo="🎂 ¡Feliz Cumpleaños!",
                    mensaje=f"Hoy celebramos a {len(cumpleanieros)} compañero(s)",
                    publicacion_id=publicacion.id
                )
                logger.info(f"🔔 Notificaciones de cumpleaños enviadas a {len(destinatarios)} destinatarios")
        except Exception as e:
            logger.error(f"⚠️ Error creando notificaciones de cumpleaños: {e}")
        
        return {
            "success": True,
            "message": f"Publicación de cumpleaños creada con {len(cumpleanieros)} cumpleañeros",
            "id": str(publicacion.id),
            "cumpleanieros": len(cumpleanieros)
        }
    except Exception as e:
        db.rollback()
        logger.error(f"❌ Error en generar_publicacion_cumpleanios: {e}")
        raise HTTPException(status_code=500, detail=str(e))