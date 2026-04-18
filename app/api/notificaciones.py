# app/api/notificaciones.py
# VERSIÓN FINAL - SIN DATA, CON SQLALCHEMY PURO

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging

from app.database import get_db
from app.core.dependencies import require_roles
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)
router = APIRouter()


# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def crear_notificacion(
    db: Session,
    usuario_id: UUID,
    tipo: str,
    titulo: str,
    mensaje: str,
    publicacion_id: Optional[UUID] = None
):
    notificacion = Notificacion(
        usuario_id=usuario_id,
        tipo=tipo,
        titulo=titulo,
        mensaje=mensaje,
        publicacion_id=publicacion_id
    )
    db.add(notificacion)
    db.commit()
    return notificacion


def crear_notificacion_masiva(
    db: Session,
    usuarios_ids: List[UUID],
    tipo: str,
    titulo: str,
    mensaje: str,
    publicacion_id: Optional[UUID] = None
):
    if not usuarios_ids:
        return 0
    for usuario_id in usuarios_ids:
        notificacion = Notificacion(
            usuario_id=usuario_id,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            publicacion_id=publicacion_id
        )
        db.add(notificacion)
    db.commit()
    return len(usuarios_ids)


# =====================================================
# ENDPOINTS
# =====================================================

@router.get("/")
async def listar_notificaciones(
    limite: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    notificaciones = db.query(Notificacion).filter(
        Notificacion.usuario_id == current_user.id
    ).order_by(desc(Notificacion.creada_en)).limit(limite).all()
    
    resultado = []
    for n in notificaciones:
        resultado.append({
            "id": str(n.id),
            "tipo": n.tipo,
            "titulo": n.titulo,
            "mensaje": n.mensaje,
            "publicacion_id": str(n.publicacion_id) if n.publicacion_id else None,
            "leida": n.leida,
            "leida_en": n.leida_en.isoformat() if n.leida_en else None,
            "creada_en": n.creada_en.isoformat() if n.creada_en else None
        })
    
    logger.info(f"📋 {len(resultado)} notificaciones listadas")
    return resultado


@router.get("/no-leidas/count")
async def contar_no_leidas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    total = db.query(Notificacion).filter(
        Notificacion.usuario_id == current_user.id
    ).count()
    
    no_leidas = db.query(Notificacion).filter(
        Notificacion.usuario_id == current_user.id,
        Notificacion.leida == False
    ).count()
    
    logger.info(f"📊 {no_leidas} no leídas de {total} totales")
    return {"total": total, "no_leidas": no_leidas}


@router.put("/{id}/leer")
async def marcar_como_leida(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    notificacion = db.query(Notificacion).filter(
        Notificacion.id == id,
        Notificacion.usuario_id == current_user.id
    ).first()
    
    if not notificacion:
        raise HTTPException(status_code=404, detail="No encontrada")
    
    notificacion.leida = True
    notificacion.leida_en = datetime.now()
    db.commit()
    return {"success": True, "message": "Marcada como leída"}


@router.put("/leer-todas")
async def marcar_todas_como_leidas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    ahora = datetime.now()
    notificaciones = db.query(Notificacion).filter(
        Notificacion.usuario_id == current_user.id,
        Notificacion.leida == False
    ).all()
    
    for n in notificaciones:
        n.leida = True
        n.leida_en = ahora
    
    db.commit()
    return {"success": True, "marcadas": len(notificaciones)}


@router.delete("/{id}")
async def eliminar_notificacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    notificacion = db.query(Notificacion).filter(
        Notificacion.id == id,
        Notificacion.usuario_id == current_user.id
    ).first()
    
    if not notificacion:
        raise HTTPException(status_code=404, detail="No encontrada")
    
    db.delete(notificacion)
    db.commit()
    return {"success": True, "message": "Eliminada"}