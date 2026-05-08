# app/api/clientes.py
# GESTIÓN DE CLIENTES - SUPER ADMIN
# Jerarquía: super_admin → clientes → empresas

from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone, date

from app.database import get_db
from app.core.dependencies import get_current_super_admin, get_current_active_user
from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.core.security import is_super_admin, is_admin_cliente
from app.schemas.empresa import ClienteCreate, ClienteUpdate, ClienteResponse

router = APIRouter()


def ahora_utc():
    """Retorna datetime UTC con timezone aware"""
    return datetime.now(timezone.utc)


# =====================================================
# ENDPOINTS PARA SUPER ADMIN
# =====================================================

@router.get("/")
async def listar_clientes(
    activo: Optional[bool] = Query(None),
    plan: Optional[str] = Query(None),
    busqueda: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Lista todos los clientes (solo super_admin)."""
    query = db.query(Cliente)
    
    if activo is not None:
        query = query.filter(Cliente.activo == activo)
    if plan:
        query = query.filter(Cliente.plan == plan)
    if busqueda:
        patron = f"%{busqueda}%"
        query = query.filter(
            db.or_(
                Cliente.nombre.ilike(patron),
                Cliente.razon_social.ilike(patron),
                Cliente.email_contacto.ilike(patron)
            )
        )
    
    clientes = query.order_by(Cliente.created_at.desc()).all()
    
    result = []
    for cliente in clientes:
        # Contar empresas del cliente
        total_empresas = db.query(Empresa).filter(
            Empresa.cliente_id == cliente.id
        ).count()
        
        empresas_activas = db.query(Empresa).filter(
            Empresa.cliente_id == cliente.id,
            Empresa.activo == True
        ).count()
        
        # Contar usuarios del cliente
        total_usuarios = db.query(Usuario).filter(
            Usuario.cliente_id == cliente.id,
            Usuario.activo == True
        ).count()
        
        # Verificar vencimiento
        vencida = False
        dias_restantes = None
        if cliente.fecha_vencimiento:
            fecha_venc = cliente.fecha_vencimiento
            if isinstance(fecha_venc, date):
                fecha_venc = datetime.combine(fecha_venc, datetime.min.time()).replace(tzinfo=timezone.utc)
            vencida = fecha_venc < ahora_utc()
            if not vencida:
                dias_restantes = (fecha_venc - ahora_utc()).days
        
        result.append({
            "id": str(cliente.id),
            "nombre": cliente.nombre,
            "razon_social": cliente.razon_social,
            "ruc": cliente.ruc,
            "email_contacto": cliente.email_contacto,
            "telefono": cliente.telefono,
            "direccion": cliente.direccion,
            "plan": cliente.plan,
            "fecha_vencimiento": cliente.fecha_vencimiento.isoformat() if cliente.fecha_vencimiento else None,
            "activo": cliente.activo,
            "total_empresas": total_empresas,
            "empresas_activas": empresas_activas,
            "total_usuarios": total_usuarios,
            "vencida": vencida,
            "dias_restantes": dias_restantes,
            "created_at": cliente.created_at.isoformat() if cliente.created_at else None,
        })
    
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
async def crear_cliente(
    data: ClienteCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Crea un nuevo cliente (solo super_admin)."""
    
    # Validar unicidad del nombre
    if db.query(Cliente).filter(Cliente.nombre == data.nombre).first():
        raise HTTPException(status_code=400, detail=f"El cliente '{data.nombre}' ya existe")
    
    # Si no se especifica fecha de vencimiento, dar 30 días de prueba
    fecha_vencimiento = data.fecha_vencimiento or (ahora_utc() + timedelta(days=30)).date()
    
    cliente = Cliente(
        nombre=data.nombre,
        razon_social=data.razon_social,
        ruc=data.ruc,
        email_contacto=data.email_contacto,
        telefono=data.telefono,
        direccion=data.direccion,
        plan=data.plan,
        fecha_vencimiento=fecha_vencimiento,
        activo=True
    )
    
    db.add(cliente)
    db.commit()
    db.refresh(cliente)
    
    return {
        "message": "Cliente creado exitosamente",
        "cliente_id": str(cliente.id),
        "nombre": cliente.nombre,
        "plan": cliente.plan,
        "fecha_vencimiento": cliente.fecha_vencimiento.isoformat() if cliente.fecha_vencimiento else None,
    }


@router.get("/{cliente_id}")
async def obtener_cliente(
    cliente_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Obtiene detalle de un cliente con sus empresas."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # Verificar acceso
    if not is_super_admin(current_user.rol_global):
        if not is_admin_cliente(current_user.rol_global) or current_user.cliente_id != cliente_id:
            raise HTTPException(status_code=403, detail="No tienes acceso a este cliente")
    
    empresas = db.query(Empresa).filter(Empresa.cliente_id == cliente_id).all()
    
    ahora = ahora_utc()
    vencida = False
    dias_restantes = None
    if cliente.fecha_vencimiento:
        fecha_venc = cliente.fecha_vencimiento
        if isinstance(fecha_venc, date):
            fecha_venc = datetime.combine(fecha_venc, datetime.min.time()).replace(tzinfo=timezone.utc)
        vencida = fecha_venc < ahora
        if not vencida:
            dias_restantes = (fecha_venc - ahora).days
    
    return {
        "id": str(cliente.id),
        "nombre": cliente.nombre,
        "razon_social": cliente.razon_social,
        "ruc": cliente.ruc,
        "email_contacto": cliente.email_contacto,
        "telefono": cliente.telefono,
        "direccion": cliente.direccion,
        "plan": cliente.plan,
        "fecha_vencimiento": cliente.fecha_vencimiento.isoformat() if cliente.fecha_vencimiento else None,
        "activo": cliente.activo,
        "vencida": vencida,
        "dias_restantes": dias_restantes,
        "created_at": cliente.created_at.isoformat() if cliente.created_at else None,
        "updated_at": cliente.updated_at.isoformat() if cliente.updated_at else None,
        "empresas": [
            {
                "id": str(e.id),
                "nombre": e.nombre,
                "nombre_corto": e.nombre_corto,
                "subdominio": e.subdominio,
                "activo": e.activo,
                "plan": e.plan,
                "fecha_vencimiento": e.fecha_vencimiento.isoformat() if e.fecha_vencimiento else None,
            }
            for e in empresas
        ],
        "total_empresas": len(empresas),
        "empresas_activas": sum(1 for e in empresas if e.activo),
    }


@router.put("/{cliente_id}")
async def actualizar_cliente(
    cliente_id: UUID,
    data: ClienteUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Actualiza datos de un cliente (solo super_admin)."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(cliente, field, value)
    
    cliente.updated_at = ahora_utc()
    db.commit()
    db.refresh(cliente)
    
    return {
        "message": "Cliente actualizado exitosamente",
        "id": str(cliente.id),
        "nombre": cliente.nombre,
        "activo": cliente.activo,
        "plan": cliente.plan,
        "fecha_vencimiento": cliente.fecha_vencimiento.isoformat() if cliente.fecha_vencimiento else None
    }


@router.post("/{cliente_id}/toggle-estado")
async def toggle_estado_cliente(
    cliente_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Activa o desactiva un cliente (solo super_admin)."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    cliente.activo = not cliente.activo
    cliente.updated_at = ahora_utc()
    db.commit()
    
    return {
        "message": f"Cliente {'activado' if cliente.activo else 'desactivado'} exitosamente",
        "id": str(cliente.id),
        "activo": cliente.activo
    }


@router.post("/{cliente_id}/renovar")
async def renovar_cliente(
    cliente_id: UUID,
    dias: int = Body(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Extiende la suscripción de un cliente por N días (solo super_admin)."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    ahora = ahora_utc().date()
    
    if cliente.fecha_vencimiento and cliente.fecha_vencimiento < ahora:
        cliente.fecha_vencimiento = ahora + timedelta(days=dias)
    elif cliente.fecha_vencimiento:
        cliente.fecha_vencimiento = cliente.fecha_vencimiento + timedelta(days=dias)
    else:
        cliente.fecha_vencimiento = ahora + timedelta(days=dias)
    
    cliente.activo = True
    cliente.updated_at = ahora_utc()
    db.commit()
    
    return {
        "message": f"Suscripción renovada por {dias} días",
        "id": str(cliente.id),
        "dias_agregados": dias,
        "nueva_fecha_vencimiento": cliente.fecha_vencimiento.isoformat() if cliente.fecha_vencimiento else None
    }


@router.get("/{cliente_id}/empresas")
async def empresas_del_cliente(
    cliente_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Lista las empresas de un cliente específico."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # Verificar acceso
    if not is_super_admin(current_user.rol_global):
        if not is_admin_cliente(current_user.rol_global) or current_user.cliente_id != cliente_id:
            raise HTTPException(status_code=403, detail="No tienes acceso a este cliente")
    
    empresas = db.query(Empresa).filter(
        Empresa.cliente_id == cliente_id,
        Empresa.activo == True
    ).order_by(Empresa.nombre).all()
    
    return {
        "cliente_id": str(cliente.id),
        "cliente_nombre": cliente.nombre,
        "empresas": [
            {
                "id": str(e.id),
                "nombre": e.nombre,
                "nombre_corto": e.nombre_corto,
                "subdominio": e.subdominio,
                "plan": e.plan,
                "logo_url": e.logo_url,
                "color_primario": e.color_primario,
            }
            for e in empresas
        ]
    }