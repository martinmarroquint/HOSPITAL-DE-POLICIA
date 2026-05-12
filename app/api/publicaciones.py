# app/api/publicaciones.py
# ROUTER PARA PUBLICACIONES - CON FILTRO POR EMPRESA Y NOTIFICACIONES

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date
import logging

from app.database import get_db
from app.core.dependencies import require_roles, get_current_user_id
from app.models.publicacion import Publicacion, PublicacionVista
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.schemas.publicacion import (
    PublicacionCreate, PublicacionUpdate, PublicacionResponse,
    PublicacionVistaCreate, PublicacionVistaResponse, MarcarVistaRequest,
    PublicacionEstadisticas, EstadisticasGlobales, PublicacionListResponse
)

from app.api.notificaciones import crear_notificacion_masiva

logger = logging.getLogger(__name__)

router = APIRouter()


# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

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
        "audiencia": getattr(publicacion, 'audiencia', 'toda_empresa'),  # 🆕 Incluir audiencia
        "fecha_publicacion": publicacion.fecha_publicacion,
        "fecha_expiracion": publicacion.fecha_expiracion,
        "activo": publicacion.activo,
        "fijado": publicacion.fijado,
        "total_vistas": publicacion.total_vistas or 0,
        "created_at": publicacion.created_at,
        "updated_at": publicacion.updated_at,
        "vistas": [v.usuario_id for v in publicacion.vistas] if publicacion.vistas else []
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


def verificar_acceso_publicacion(current_user: Usuario, publicacion: Publicacion, db: Session) -> bool:
    """
    Verifica si el usuario actual tiene acceso a la publicación.
    🆕 Visitantes solo ven publicaciones con audiencia 'visitantes' o 'toda_empresa'
    """
    # Admin y roles con acceso global pueden ver todo
    roles_globales = ['admin', 'recursos_humanos', 'oficina_central', 'oficial_permanencia']
    if any(rol in current_user.roles for rol in roles_globales):
        return True
    
    # 🆕 VISITANTES: solo ven publicaciones dirigidas a ellos o a toda la empresa
    if 'visitante' in current_user.roles:
        audiencia = getattr(publicacion, 'audiencia', 'toda_empresa')
        if audiencia not in ['visitantes', 'toda_empresa']:
            return False
    
    # Verificar por empresa
    if current_user.empresa_id and publicacion.empresa_id:
        if str(current_user.empresa_id) != str(publicacion.empresa_id):
            return False
    
    return publicacion.activo


# =====================================================
# 🆕 ENDPOINT PÚBLICO PARA VISITANTES (SIN RESTRICCIÓN DE ROLES FUERTES)
# =====================================================

@router.get("/publico", response_model=List[PublicacionResponse])
async def listar_publicaciones_publico(
    activo: Optional[bool] = Query(True),
    empresa_id: Optional[UUID] = Query(None),
    audiencia: Optional[str] = Query(None),  # 🆕 Filtrar por audiencia
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario", "visitante", "escaner"]))  # ✅ AGREGADO visitante y escaner
):
    """
    Endpoint para visitantes y usuarios regulares.
    🆕 Filtra automáticamente por audiencia para visitantes.
    """
    query = db.query(Publicacion)
    
    if activo is not None:
        query = query.filter(Publicacion.activo == activo)
    
    # 🆕 Para visitantes, filtrar SOLO publicaciones dirigidas a ellos
    if 'visitante' in current_user.roles:
        query = query.filter(
            or_(
                Publicacion.audiencia == 'visitantes',
                Publicacion.audiencia == 'toda_empresa',
                Publicacion.audiencia == None  # Publicaciones antiguas sin audiencia definida
            )
        )
    elif audiencia:
        query = query.filter(Publicacion.audiencia == audiencia)
    
    # Filtrar por empresa
    if empresa_id:
        query = query.filter(
            or_(
                Publicacion.empresa_id == empresa_id,
                Publicacion.empresa_id == None
            )
        )
    elif current_user.empresa_id and current_user.rol_global != "super_admin":
        query = query.filter(
            or_(
                Publicacion.empresa_id == current_user.empresa_id,
                Publicacion.empresa_id == None
            )
        )
    
    query = query.order_by(desc(Publicacion.fijado), desc(Publicacion.fecha_publicacion))
    
    publicaciones = query.offset(offset).limit(limit).all()
    
    resultado = []
    for pub in publicaciones:
        if verificar_acceso_publicacion(current_user, pub, db):
            resultado.append(enriquecer_publicacion(db, pub))
    
    logger.info(f"📋 {len(resultado)} publicaciones listadas (público) para usuario {current_user.id} | roles: {current_user.roles}")
    return resultado


# =====================================================
# ENDPOINTS PRINCIPALES
# =====================================================

@router.get("/", response_model=List[PublicacionResponse])
async def listar_publicaciones(
    activo: Optional[bool] = Query(True),
    tipo: Optional[str] = Query(None),
    categoria: Optional[str] = Query(None),
    empresa_id: Optional[UUID] = Query(None),
    audiencia: Optional[str] = Query(None),  # 🆕
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario", "visitante", "escaner"]))  # ✅ AGREGADO
):
    """
    Lista todas las publicaciones con filtros opcionales.
    🆕 Visitantes y escaner pueden ver publicaciones (solo las dirigidas a ellos).
    """
    query = db.query(Publicacion)
    
    if activo is not None:
        query = query.filter(Publicacion.activo == activo)
    if tipo:
        query = query.filter(Publicacion.tipo == tipo.upper())
    if categoria:
        query = query.filter(Publicacion.categoria == categoria)
    
    # 🆕 Para visitantes, filtrar SOLO publicaciones dirigidas a ellos
    if 'visitante' in current_user.roles:
        query = query.filter(
            or_(
                Publicacion.audiencia == 'visitantes',
                Publicacion.audiencia == 'toda_empresa',
                Publicacion.audiencia == None
            )
        )
    elif audiencia:
        query = query.filter(Publicacion.audiencia == audiencia)
    
    # Filtrar por empresa
    if empresa_id:
        query = query.filter(
            or_(
                Publicacion.empresa_id == empresa_id,
                Publicacion.empresa_id == None
            )
        )
    elif current_user.empresa_id and current_user.rol_global != "super_admin":
        query = query.filter(
            or_(
                Publicacion.empresa_id == current_user.empresa_id,
                Publicacion.empresa_id == None
            )
        )
    
    query = query.order_by(desc(Publicacion.fijado), desc(Publicacion.fecha_publicacion))
    
    publicaciones = query.offset(offset).limit(limit).all()
    
    resultado = []
    for pub in publicaciones:
        if verificar_acceso_publicacion(current_user, pub, db):
            resultado.append(enriquecer_publicacion(db, pub))
    
    logger.info(f"📋 {len(resultado)} publicaciones listadas para usuario {current_user.id} | empresa: {empresa_id or current_user.empresa_id}")
    return resultado


@router.get("/{id}", response_model=PublicacionResponse)
async def obtener_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario", "visitante", "escaner"]))  # ✅ AGREGADO
):
    """Obtiene una publicación específica por ID"""
    publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
    
    if not publicacion:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    if not verificar_acceso_publicacion(current_user, publicacion, db):
        raise HTTPException(status_code=403, detail="No tiene acceso a esta publicación")
    
    return enriquecer_publicacion(db, publicacion)


@router.post("/", response_model=PublicacionResponse, status_code=201)
async def crear_publicacion(
    publicacion_data: PublicacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))  # Solo admin crea
):
    """
    Crea una nueva publicación.
    Solo administradores pueden crear publicaciones.
    """
    if publicacion_data.tipo == 'TEXTO' and not publicacion_data.contenido_texto:
        raise HTTPException(status_code=400, detail="contenido_texto es requerido para tipo TEXTO")
    
    if publicacion_data.tipo in ['IMAGEN', 'PDF'] and not publicacion_data.url_archivo:
        raise HTTPException(status_code=400, detail=f"url_archivo es requerido para tipo {publicacion_data.tipo}")
    
    empresa_id = publicacion_data.empresa_id or current_user.empresa_id
    
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
        audiencia=getattr(publicacion_data, 'audiencia', 'toda_empresa'),  # 🆕 Guardar audiencia
        fecha_publicacion=publicacion_data.fecha_publicacion or datetime.now(),
        fecha_expiracion=publicacion_data.fecha_expiracion,
        fijado=publicacion_data.fijado or False,
        activo=True,
        total_vistas=0
    )
    
    db.add(publicacion)
    db.commit()
    db.refresh(publicacion)
    
    logger.info(f"✅ Publicación creada: {publicacion.id} - {publicacion.titulo[:30]}... | empresa: {empresa_id}")
    
    # Crear notificaciones
    try:
        from app.models.notificacion import Notificacion
        
        query_usuarios = db.query(Usuario).filter(Usuario.activo == True)
        if empresa_id:
            query_usuarios = query_usuarios.filter(
                or_(
                    Usuario.empresa_id == empresa_id,
                    Usuario.empresa_id == None
                )
            )
        
        # 🆕 Si la audiencia es 'visitantes', notificar solo a visitantes
        audiencia = getattr(publicacion_data, 'audiencia', 'toda_empresa')
        if audiencia == 'visitantes':
            query_usuarios = query_usuarios.filter(Usuario.roles.contains('visitante'))
        elif audiencia == 'personal':
            query_usuarios = query_usuarios.filter(~Usuario.roles.contains('visitante'))
        
        usuarios_activos = query_usuarios.all()
        
        if usuarios_activos:
            tipo_notificacion = "nueva_publicacion"
            if publicacion.categoria == "cumpleanios":
                tipo_notificacion = "cumpleanios"
            
            notificaciones_creadas = 0
            for usuario in usuarios_activos:
                try:
                    nueva_notificacion = Notificacion(
                        usuario_id=usuario.id,
                        tipo=tipo_notificacion,
                        titulo="📢 Nueva publicación" if tipo_notificacion == "nueva_publicacion" else "🎂 ¡Feliz Cumpleaños!",
                        mensaje=publicacion.titulo[:100],
                        publicacion_id=publicacion.id
                    )
                    db.add(nueva_notificacion)
                    notificaciones_creadas += 1
                except Exception as e:
                    logger.error(f"Error creando notificación para usuario {usuario.id}: {e}")
                    continue
            
            db.commit()
            logger.info(f"🔔 {notificaciones_creadas} notificaciones creadas")
    
    except Exception as e:
        logger.error(f"⚠️ Error creando notificaciones: {e}")
        db.rollback()
    
    return enriquecer_publicacion(db, publicacion)


@router.put("/{id}", response_model=PublicacionResponse)
async def actualizar_publicacion(
    id: UUID,
    publicacion_data: PublicacionUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))  # Solo admin edita
):
    """Actualiza una publicación existente. Solo administradores."""
    publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
    
    if not publicacion:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    update_data = publicacion_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(publicacion, field, value)
    
    db.commit()
    db.refresh(publicacion)
    
    logger.info(f"✏️ Publicación actualizada: {id}")
    
    return enriquecer_publicacion(db, publicacion)


@router.delete("/{id}")
async def eliminar_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))  # Solo admin elimina
):
    """Elimina (desactiva) una publicación. Solo administradores."""
    publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
    
    if not publicacion:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    publicacion.activo = False
    db.commit()
    
    logger.info(f"🗑️ Publicación desactivada: {id}")
    
    return {
        "success": True,
        "message": "Publicación desactivada correctamente",
        "id": str(id)
    }


# =====================================================
# ENDPOINTS PARA VISTAS
# =====================================================

@router.post("/{id}/vistas", status_code=201)
async def marcar_como_vista(
    id: UUID,
    request: MarcarVistaRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario", "visitante", "escaner"]))  # ✅ AGREGADO
):
    """Marca una publicación como vista por un usuario."""
    publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
    if not publicacion:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    if not publicacion.activo:
        raise HTTPException(status_code=400, detail="La publicación no está activa")
    
    usuario = db.query(Usuario).filter(Usuario.id == request.usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    vista_existente = db.query(PublicacionVista).filter(
        and_(
            PublicacionVista.publicacion_id == id,
            PublicacionVista.usuario_id == request.usuario_id
        )
    ).first()
    
    if vista_existente:
        return {"message": "Publicación ya marcada como vista", "ya_vista": True}
    
    nueva_vista = PublicacionVista(
        publicacion_id=id,
        usuario_id=request.usuario_id
    )
    
    db.add(nueva_vista)
    publicacion.total_vistas = (publicacion.total_vistas or 0) + 1
    db.commit()
    
    logger.info(f"👁️ Publicación {id} marcada como vista por usuario {request.usuario_id}")
    
    return {
        "success": True,
        "message": "Publicación marcada como vista",
        "id": str(nueva_vista.id)
    }


@router.get("/{id}/vistas", response_model=List[PublicacionVistaResponse])
async def obtener_vistas_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))  # Solo admin ve estadísticas
):
    """Obtiene la lista de usuarios que han visto una publicación."""
    publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
    if not publicacion:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    vistas = db.query(PublicacionVista).filter(
        PublicacionVista.publicacion_id == id
    ).order_by(desc(PublicacionVista.fecha_vista)).all()
    
    return vistas


@router.get("/{id}/estadisticas", response_model=PublicacionEstadisticas)
async def obtener_estadisticas_publicacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))  # Solo admin
):
    """Obtiene estadísticas detalladas de visualización de una publicación."""
    publicacion = db.query(Publicacion).filter(Publicacion.id == id).first()
    if not publicacion:
        raise HTTPException(status_code=404, detail="Publicación no encontrada")
    
    query_empleados = db.query(Personal).filter(Personal.activo == True)
    if publicacion.empresa_id:
        query_empleados = query_empleados.filter(
            or_(
                Personal.empresa_id == publicacion.empresa_id,
                Personal.empresa_id == None
            )
        )
    empleados = query_empleados.all()
    total_empleados = len(empleados)
    
    vistas = db.query(PublicacionVista).filter(
        PublicacionVista.publicacion_id == id
    ).all()
    
    usuarios_vieron_ids = [v.usuario_id for v in vistas]
    total_vistas = len(vistas)
    porcentaje = (total_vistas / total_empleados * 100) if total_empleados > 0 else 0
    
    usuarios_vieron = []
    for vista in vistas:
        usuario = db.query(Usuario).filter(Usuario.id == vista.usuario_id).first()
        if usuario:
            personal = db.query(Personal).filter(Personal.id == usuario.personal_id).first()
            if personal:
                usuarios_vieron.append({
                    "id": str(personal.id),
                    "nombre": personal.nombre,
                    "area": personal.area,
                    "fecha_vista": vista.fecha_vista.isoformat()
                })
    
    usuarios_no_vieron = []
    for emp in empleados:
        usuario_auth = db.query(Usuario).filter(Usuario.personal_id == emp.id).first()
        if usuario_auth and usuario_auth.id not in usuarios_vieron_ids:
            usuarios_no_vieron.append({
                "id": str(emp.id),
                "nombre": emp.nombre,
                "area": emp.area
            })
    
    return {
        "publicacion_id": id,
        "titulo": publicacion.titulo,
        "total_vistas": total_vistas,
        "total_empleados": total_empleados,
        "porcentaje_vistas": round(porcentaje, 2),
        "usuarios_vieron": usuarios_vieron,
        "usuarios_no_vieron": usuarios_no_vieron
    }


@router.get("/estadisticas/globales", response_model=EstadisticasGlobales)
async def obtener_estadisticas_globales(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))  # Solo admin/jefe
):
    """Obtiene estadísticas globales de todas las publicaciones."""
    query_publicaciones = db.query(Publicacion).filter(Publicacion.activo == True)
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        query_publicaciones = query_publicaciones.filter(
            or_(
                Publicacion.empresa_id == current_user.empresa_id,
                Publicacion.empresa_id == None
            )
        )
    total_publicaciones = query_publicaciones.count()
    
    query_empleados = db.query(Personal).filter(Personal.activo == True)
    if current_user.empresa_id:
        query_empleados = query_empleados.filter(
            or_(
                Personal.empresa_id == current_user.empresa_id,
                Personal.empresa_id == None
            )
        )
    empleados = query_empleados.all()
    total_empleados = len(empleados)
    
    total_vistas = db.query(PublicacionVista).count()
    
    publicaciones_activas = query_publicaciones.all()
    publicaciones_ids = [p.id for p in publicaciones_activas]
    
    usuarios_vieron_todo = 0
    for emp in empleados:
        usuario_auth = db.query(Usuario).filter(Usuario.personal_id == emp.id).first()
        if usuario_auth:
            vistas_usuario = db.query(PublicacionVista).filter(
                and_(
                    PublicacionVista.usuario_id == usuario_auth.id,
                    PublicacionVista.publicacion_id.in_(publicaciones_ids)
                )
            ).count()
            if vistas_usuario >= len(publicaciones_ids) and len(publicaciones_ids) > 0:
                usuarios_vieron_todo += 1
    
    porcentaje = (usuarios_vieron_todo / total_empleados * 100) if total_empleados > 0 else 0
    
    return {
        "total_publicaciones": total_publicaciones,
        "total_vistas": total_vistas,
        "total_empleados": total_empleados,
        "usuarios_vieron_todo": usuarios_vieron_todo,
        "porcentaje_lectura_completa": round(porcentaje, 2)
    }


@router.post("/cumpleanios/auto", status_code=201)
async def generar_publicacion_cumpleanios(
    empresa_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))  # Solo admin
):
    """Genera automáticamente una publicación con los cumpleañeros del día."""
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
            or_(
                Publicacion.empresa_id == emp_id,
                Publicacion.empresa_id == None
            )
        )
    
    existente = query_existente.first()
    if existente:
        return {"message": "Ya existe una publicación de cumpleaños para hoy", "id": str(existente.id)}
    
    query_empleados = db.query(Personal).filter(Personal.activo == True)
    if emp_id:
        query_empleados = query_empleados.filter(
            or_(
                Personal.empresa_id == emp_id,
                Personal.empresa_id == None
            )
        )
    empleados = query_empleados.all()
    
    cumpleanieros = []
    for emp in empleados:
        if emp.fecha_nacimiento:
            if emp.fecha_nacimiento.month == hoy.month and emp.fecha_nacimiento.day == hoy.day:
                cumpleanieros.append(emp)
    
    if not cumpleanieros:
        return {"message": "No hay cumpleañeros hoy", "cantidad": 0}
    
    meses = {
        1: "enero", 2: "febrero", 3: "marzo", 4: "abril",
        5: "mayo", 6: "junio", 7: "julio", 8: "agosto",
        9: "septiembre", 10: "octubre", 11: "noviembre", 12: "diciembre"
    }
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
        fecha_publicacion=datetime.now(),
        activo=True
    )
    
    db.add(publicacion)
    db.commit()
    db.refresh(publicacion)
    
    logger.info(f"🎂 Publicación automática de cumpleaños creada: {publicacion.id}")
    
    try:
        query_usuarios = db.query(Usuario).filter(Usuario.activo == True)
        if emp_id:
            query_usuarios = query_usuarios.filter(
                or_(
                    Usuario.empresa_id == emp_id,
                    Usuario.empresa_id == None
                )
            )
        usuarios_activos = query_usuarios.all()
        
        if usuarios_activos:
            usuarios_ids = [u.id for u in usuarios_activos]
            cantidad = crear_notificacion_masiva(
                db=db,
                usuarios_ids=usuarios_ids,
                tipo="cumpleanios",
                titulo="🎂 ¡Feliz Cumpleaños!",
                mensaje=f"Hoy celebramos a {len(cumpleanieros)} compañero(s)",
                publicacion_id=publicacion.id
            )
            logger.info(f"🔔 {cantidad} notificaciones de cumpleaños creadas")
    except Exception as e:
        logger.error(f"⚠️ Error creando notificaciones de cumpleaños: {e}")
    
    return {
        "success": True,
        "message": f"Publicación de cumpleaños creada con {len(cumpleanieros)} cumpleañeros",
        "id": str(publicacion.id),
        "cumpleanieros": len(cumpleanieros)
    }