from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import and_
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime
import json
import logging

from app.database import get_db
from app.core.dependencies import require_roles, get_current_user
from app.models.catalogo_item import CatalogoItem
from app.models.inventario_unidad import InventarioUnidad
from app.models.usuario import Usuario
from app.schemas.inventario import (
    CatalogoItemCreate, CatalogoItemUpdate, CatalogoItemResponse,
    InventarioUnidadCreate, InventarioUnidadUpdate, InventarioUnidadResponse
)

router = APIRouter()
logger = logging.getLogger(__name__)

# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def aplicar_filtro_empresa(query, current_user, modelo):
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if hasattr(modelo, 'empresa_id'):
            query = query.filter(modelo.empresa_id == current_user.empresa_id)
    return query

def get_unidad_usuario(db: Session, current_user) -> str:
    """Obtiene el nombre de la unidad del usuario actual."""
    if not current_user.personal_id:
        return None
    
    from app.models.personal import Personal
    personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
    if personal:
        return personal.area
    return None

# =====================================================
# CATALOGO DE ITEMS
# =====================================================

@router.get("/catalogo")
async def listar_catalogo(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Lista todos los items del catalogo maestro."""
    try:
        query = db.query(CatalogoItem).filter(CatalogoItem.activo == True)
        query = aplicar_filtro_empresa(query, current_user, CatalogoItem)
        items = query.order_by(CatalogoItem.nombre).all()
        
        return [{
            "id": str(item.id),
            "nombre": item.nombre,
            "icono": item.icono,
            "categoria": item.categoria,
            "precio_unitario": float(item.precio_unitario) if item.precio_unitario else 0,
            "stock_minimo": item.stock_minimo,
            "detalles": item.detalles if isinstance(item.detalles, list) else [],
            "activo": item.activo,
            "created_at": item.created_at.isoformat() if item.created_at else None
        } for item in items]
        
    except Exception as e:
        logger.error(f"Error listando catalogo: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


@router.post("/catalogo")
async def crear_item_catalogo(
    data: CatalogoItemCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "admin_cliente", "super_admin"]))
):
    """Crea un nuevo item en el catalogo maestro. Solo administradores."""
    try:
        item = CatalogoItem(
            nombre=data.nombre,
            icono=data.icono or "mdi:package-variant-closed",
            categoria=data.categoria,
            precio_unitario=data.precio_unitario or 0,
            stock_minimo=data.stock_minimo or 5,
            detalles=data.detalles or [],
            creado_por=current_user.id,
            empresa_id=current_user.empresa_id
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        
        return {
            "id": str(item.id),
            "nombre": item.nombre,
            "icono": item.icono,
            "categoria": item.categoria,
            "precio_unitario": float(item.precio_unitario) if item.precio_unitario else 0,
            "stock_minimo": item.stock_minimo,
            "detalles": item.detalles if isinstance(item.detalles, list) else [],
            "created_at": item.created_at.isoformat() if item.created_at else None
        }
        
    except Exception as e:
        db.rollback()
        logger.error(f"Error creando item catalogo: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al crear item")


@router.put("/catalogo/{item_id}")
async def actualizar_item_catalogo(
    item_id: UUID,
    data: CatalogoItemUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "admin_cliente", "super_admin"]))
):
    """Actualiza un item del catalogo. Solo administradores."""
    try:
        item = db.query(CatalogoItem).filter(CatalogoItem.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item no encontrado")
        
        if data.nombre is not None:
            item.nombre = data.nombre
        if data.icono is not None:
            item.icono = data.icono
        if data.categoria is not None:
            item.categoria = data.categoria
        if data.precio_unitario is not None:
            item.precio_unitario = data.precio_unitario
        if data.stock_minimo is not None:
            item.stock_minimo = data.stock_minimo
        if data.detalles is not None:
            item.detalles = data.detalles
        
        item.updated_at = datetime.utcnow()
        db.commit()
        db.refresh(item)
        
        return {"message": "Item actualizado exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error actualizando item: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al actualizar item")


@router.delete("/catalogo/{item_id}")
async def eliminar_item_catalogo(
    item_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin_empresa", "admin_cliente", "super_admin"]))
):
    """Elimina (desactiva) un item del catalogo."""
    try:
        item = db.query(CatalogoItem).filter(CatalogoItem.id == item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail="Item no encontrado")
        
        item.activo = False
        item.updated_at = datetime.utcnow()
        db.commit()
        
        return {"message": "Item eliminado exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error eliminando item: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al eliminar item")


# =====================================================
# INVENTARIO POR UNIDAD
# =====================================================

@router.get("/unidades")
async def listar_inventario_unidades(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Admin: ve todas las unidades.
    Jefe: ve solo su unidad.
    """
    try:
        es_admin = current_user.rol_global in ['super_admin', 'admin_cliente', 'admin_empresa'] or \
                   any(r in ['admin', 'admin_empresa'] for r in (current_user.roles or []))
        
        query = db.query(InventarioUnidad)
        query = aplicar_filtro_empresa(query, current_user, InventarioUnidad)
        
        if not es_admin:
            unidad = get_unidad_usuario(db, current_user)
            if unidad:
                query = query.filter(InventarioUnidad.unidad_nombre == unidad)
            else:
                return []
        
        registros = query.all()
        
        return [{
            "id": str(r.id),
            "catalogo_item_id": str(r.catalogo_item_id),
            "unidad_nombre": r.unidad_nombre,
            "cantidades": r.cantidades if isinstance(r.cantidades, dict) else {},
            "movimientos": r.movimientos if isinstance(r.movimientos, list) else [],
            "actualizado_por": str(r.actualizado_por) if r.actualizado_por else None,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None
        } for r in registros]
        
    except Exception as e:
        logger.error(f"Error listando inventario: {str(e)}")
        raise HTTPException(status_code=500, detail="Error interno del servidor")


@router.post("/unidades")
async def crear_inventario_unidad(
    data: InventarioUnidadCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Registra o actualiza el inventario de una unidad."""
    try:
        unidad = data.unidad_nombre or get_unidad_usuario(db, current_user)
        if not unidad:
            raise HTTPException(status_code=400, detail="No se pudo determinar la unidad")
        
        # Verificar si ya existe
        existente = db.query(InventarioUnidad).filter(
            InventarioUnidad.catalogo_item_id == data.catalogo_item_id,
            InventarioUnidad.unidad_nombre == unidad
        ).first()
        
        if existente:
            existente.cantidades = data.cantidades or {}
            existente.movimientos = data.movimientos or []
            existente.actualizado_por = current_user.id
            existente.updated_at = datetime.utcnow()
            db.commit()
            return {"message": "Inventario actualizado", "id": str(existente.id)}
        else:
            registro = InventarioUnidad(
                catalogo_item_id=data.catalogo_item_id,
                unidad_nombre=unidad,
                cantidades=data.cantidades or {},
                movimientos=data.movimientos or [],
                actualizado_por=current_user.id,
                empresa_id=current_user.empresa_id
            )
            db.add(registro)
            db.commit()
            db.refresh(registro)
            return {"message": "Inventario registrado", "id": str(registro.id)}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error guardando inventario: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al guardar inventario")


@router.put("/unidades/{registro_id}")
async def actualizar_inventario_unidad(
    registro_id: UUID,
    data: InventarioUnidadUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Actualiza cantidades y movimientos de una unidad."""
    try:
        registro = db.query(InventarioUnidad).filter(InventarioUnidad.id == registro_id).first()
        if not registro:
            raise HTTPException(status_code=404, detail="Registro no encontrado")
        
        if data.cantidades is not None:
            registro.cantidades = data.cantidades
        if data.movimientos is not None:
            registro.movimientos = data.movimientos
        
        registro.actualizado_por = current_user.id
        registro.updated_at = datetime.utcnow()
        db.commit()
        
        return {"message": "Inventario actualizado exitosamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        logger.error(f"Error actualizando inventario: {str(e)}")
        raise HTTPException(status_code=500, detail="Error al actualizar inventario")