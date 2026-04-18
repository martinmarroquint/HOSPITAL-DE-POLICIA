# app/api/notificaciones.py
# ROUTER PARA NOTIFICACIONES - SIGUIENDO EL PATRÓN EXISTENTE

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from uuid import UUID
from datetime import datetime
import logging
import json

from app.database import get_db
from app.core.dependencies import require_roles
from app.models.notificacion import Notificacion
from app.models.usuario import Usuario
from app.schemas.notificacion import (
    NotificacionCreate, NotificacionResponse,
    NotificacionesCountResponse, MarcarLeidaResponse, MarcarTodasLeidasResponse
)

# Configurar logger
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
    publicacion_id: Optional[UUID] = None,
    data: Optional[dict] = None
) -> Notificacion:
    """
    Crea una notificación para un usuario específico.
    Esta función puede ser llamada desde otros módulos.
    """
    try:
        notificacion = Notificacion(
            usuario_id=usuario_id,
            tipo=tipo,
            titulo=titulo,
            mensaje=mensaje,
            publicacion_id=publicacion_id,
            data=json.dumps(data) if data else None
        )
        
        db.add(notificacion)
        db.commit()
        db.refresh(notificacion)
        
        logger.info(f"✅ Notificación creada: {tipo} para usuario {usuario_id}")
        return notificacion
        
    except Exception as e:
        logger.error(f"❌ Error creando notificación: {e}")
        db.rollback()
        raise


def crear_notificacion_masiva(
    db: Session,
    usuarios_ids: List[UUID],
    tipo: str,
    titulo: str,
    mensaje: str,
    publicacion_id: Optional[UUID] = None,
    data: Optional[dict] = None
) -> int:
    """
    Crea la misma notificación para múltiples usuarios.
    Retorna el número de notificaciones creadas.
    """
    try:
        notificaciones = []
        for usuario_id in usuarios_ids:
            notificaciones.append(
                Notificacion(
                    usuario_id=usuario_id,
                    tipo=tipo,
                    titulo=titulo,
                    mensaje=mensaje,
                    publicacion_id=publicacion_id,
                    data=json.dumps(data) if data else None
                )
            )
        
        db.bulk_save_objects(notificaciones)
        db.commit()
        
        logger.info(f"✅ {len(notificaciones)} notificaciones masivas creadas: {tipo}")
        return len(notificaciones)
        
    except Exception as e:
        logger.error(f"❌ Error creando notificaciones masivas: {e}")
        db.rollback()
        raise


# =====================================================
# ENDPOINTS PRINCIPALES
# =====================================================

@router.get("/", response_model=List[NotificacionResponse])
async def listar_notificaciones(
    limite: int = Query(20, ge=1, le=50),
    no_leidas: bool = Query(False),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Lista las notificaciones del usuario actual.
    """
    query = db.query(Notificacion).filter(
        Notificacion.usuario_id == current_user.id
    )
    
    if no_leidas:
        query = query.filter(Notificacion.leida == False)
    
    notificaciones = query.order_by(desc(Notificacion.creada_en)).limit(limite).all()
    
    # Convertir data de string a dict
    for n in notificaciones:
        if n.data:
            try:
                n.data = json.loads(n.data)
            except:
                n.data = {}
    
    logger.info(f"📋 {len(notificaciones)} notificaciones listadas para usuario {current_user.id}")
    return notificaciones


@router.get("/no-leidas/count", response_model=NotificacionesCountResponse)
async def contar_no_leidas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Cuenta las notificaciones no leídas del usuario actual.
    """
    total = db.query(Notificacion).filter(
        Notificacion.usuario_id == current_user.id
    ).count()
    
    no_leidas = db.query(Notificacion).filter(
        Notificacion.usuario_id == current_user.id,
        Notificacion.leida == False
    ).count()
    
    return {"total": total, "no_leidas": no_leidas}


@router.put("/{id}/leer", response_model=MarcarLeidaResponse)
async def marcar_como_leida(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Marca una notificación como leída.
    """
    notificacion = db.query(Notificacion).filter(
        Notificacion.id == id,
        Notificacion.usuario_id == current_user.id
    ).first()
    
    if not notificacion:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    
    if not notificacion.leida:
        notificacion.leida = True
        notificacion.leida_en = datetime.now()
        db.commit()
        logger.info(f"✅ Notificación {id} marcada como leída")
    
    return {
        "success": True,
        "message": "Notificación marcada como leída",
        "id": id
    }


@router.put("/leer-todas", response_model=MarcarTodasLeidasResponse)
async def marcar_todas_como_leidas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Marca todas las notificaciones del usuario como leídas.
    """
    notificaciones = db.query(Notificacion).filter(
        Notificacion.usuario_id == current_user.id,
        Notificacion.leida == False
    ).all()
    
    marcadas = len(notificaciones)
    
    if marcadas > 0:
        ahora = datetime.now()
        for n in notificaciones:
            n.leida = True
            n.leida_en = ahora
        
        db.commit()
        logger.info(f"✅ {marcadas} notificaciones marcadas como leídas para usuario {current_user.id}")
    
    return {
        "success": True,
        "message": f"{marcadas} notificaciones marcadas como leídas",
        "marcadas": marcadas
    }


@router.delete("/{id}")
async def eliminar_notificacion(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Elimina una notificación.
    """
    notificacion = db.query(Notificacion).filter(
        Notificacion.id == id,
        Notificacion.usuario_id == current_user.id
    ).first()
    
    if not notificacion:
        raise HTTPException(status_code=404, detail="Notificación no encontrada")
    
    db.delete(notificacion)
    db.commit()
    
    logger.info(f"🗑️ Notificación {id} eliminada")
    
    return {
        "success": True,
        "message": "Notificación eliminada correctamente",
        "id": str(id)
    }


# =====================================================
# ENDPOINT PARA ADMIN (ENVIAR NOTIFICACIÓN MANUAL)
# =====================================================

@router.post("/enviar", response_model=NotificacionResponse, status_code=201)
async def enviar_notificacion_manual(
    notificacion_data: NotificacionCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    Envía una notificación manual a un usuario específico.
    Solo administradores.
    """
    # Verificar que el usuario existe
    usuario = db.query(Usuario).filter(Usuario.id == notificacion_data.usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    notificacion = crear_notificacion(
        db=db,
        usuario_id=notificacion_data.usuario_id,
        tipo=notificacion_data.tipo,
        titulo=notificacion_data.titulo,
        mensaje=notificacion_data.mensaje,
        publicacion_id=notificacion_data.publicacion_id,
        data=notificacion_data.data
    )
    
    return notificacion