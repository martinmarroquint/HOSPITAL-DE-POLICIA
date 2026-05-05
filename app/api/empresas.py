# api/empresas.py
# PANEL SUPER ADMIN - GESTIÓN DE EMPRESAS
# Solo accesible por super_admin

from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone

from app.database import get_db
from app.core.dependencies import get_current_super_admin, get_current_active_user
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.models.personal import Personal
from app.core.security import get_password_hash
from app.schemas.empresa import EmpresaCreate, EmpresaUpdate, EmpresaResponse, EmpresaStatsResponse

router = APIRouter()


def ahora_utc():
    """Retorna datetime UTC con timezone aware"""
    return datetime.now(timezone.utc)


@router.get("/")
async def listar_empresas(
    activo: Optional[bool] = Query(None),
    plan: Optional[str] = Query(None),
    busqueda: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Lista todas las empresas con métricas en tiempo real."""
    query = db.query(Empresa)
    
    if activo is not None:
        query = query.filter(Empresa.activo == activo)
    if plan:
        query = query.filter(Empresa.plan == plan)
    if busqueda:
        patron = f"%{busqueda}%"
        query = query.filter(
            db.or_(
                Empresa.nombre.ilike(patron),
                Empresa.subdominio.ilike(patron),
                Empresa.email_contacto.ilike(patron),
                Empresa.nombre_corto.ilike(patron)
            )
        )
    
    empresas = query.order_by(Empresa.created_at.desc()).all()
    
    ahora = ahora_utc()
    
    result = []
    for empresa in empresas:
        total_auth = db.query(Usuario).filter(
            Usuario.empresa_id == empresa.id, Usuario.activo == True
        ).count()
        
        total_personal = db.query(Personal).filter(
            Personal.empresa_id == empresa.id
        ).count()
        
        personal_activo = db.query(Personal).filter(
            Personal.empresa_id == empresa.id, Personal.activo == True
        ).count()
        
        completitud = round((total_auth / personal_activo * 100), 1) if personal_activo > 0 else 0
        
        ultimo = db.query(Usuario).filter(
            Usuario.empresa_id == empresa.id,
            Usuario.ultimo_acceso.isnot(None)
        ).order_by(Usuario.ultimo_acceso.desc()).first()
        
        vencida = False
        dias_restantes = None
        if empresa.fecha_vencimiento:
            if empresa.fecha_vencimiento.tzinfo is None:
                vencida = empresa.fecha_vencimiento.replace(tzinfo=timezone.utc) < ahora
            else:
                vencida = empresa.fecha_vencimiento < ahora
            if not vencida:
                dias_restantes = (empresa.fecha_vencimiento - ahora).days
        
        admin = db.query(Usuario).filter(Usuario.id == empresa.admin_id).first()
        
        result.append({
            "id": str(empresa.id),
            "nombre": empresa.nombre,
            "nombre_corto": empresa.nombre_corto or (empresa.nombre.split()[0] if empresa.nombre else None),
            "subdominio": empresa.subdominio,
            "dominio_email": empresa.dominio_email,
            "ruc": empresa.ruc,
            "email_contacto": empresa.email_contacto,
            "telefono": empresa.telefono,
            "direccion": empresa.direccion,
            "activo": empresa.activo,
            "plan": empresa.plan,
            "max_usuarios": empresa.max_usuarios,
            "total_usuarios": total_auth,
            "total_personal": total_personal,
            "personal_activo": personal_activo,
            "completitud": completitud,
            "vencida": vencida,
            "dias_restantes": dias_restantes,
            "fecha_vencimiento": empresa.fecha_vencimiento.isoformat() if empresa.fecha_vencimiento else None,
            "created_at": empresa.created_at.isoformat() if empresa.created_at else None,
            "ultimo_acceso": ultimo.ultimo_acceso.isoformat() if ultimo and ultimo.ultimo_acceso else None,
            "ultimo_acceso_email": ultimo.email if ultimo else None,
            "color_primario": empresa.color_primario,
            "logo_url": empresa.logo_url,
            "admin_email": admin.email if admin else None
        })
    
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
async def crear_empresa(
    data: EmpresaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Crea una nueva empresa con su administrador."""
    if db.query(Empresa).filter(Empresa.subdominio == data.subdominio).first():
        raise HTTPException(status_code=400, detail="Subdominio ya registrado")
    if db.query(Usuario).filter(Usuario.email == data.admin_email).first():
        raise HTTPException(status_code=400, detail="Email de administrador ya registrado")
    
    fecha_prueba = ahora_utc() + timedelta(days=30)
    
    # 1. Crear empresa primero (sin admin_id)
    empresa = Empresa(
        nombre=data.nombre,
        nombre_corto=data.nombre_corto or (data.nombre.split()[0] if data.nombre else None),
        subdominio=data.subdominio,
        dominio_email=data.dominio_email,
        email_contacto=data.email_contacto,
        plan=data.plan,
        max_usuarios=data.max_usuarios,
        ruc=data.ruc,
        telefono=data.telefono,
        direccion=data.direccion,
        activo=True,
        fecha_vencimiento=fecha_prueba
    )
    db.add(empresa)
    db.flush()  # Now empresa.id exists
    
    # 2. Crear admin
    admin_usuario = Usuario(
        email=data.admin_email,
        username=data.admin_email.split('@')[0],
        password_hash=get_password_hash(data.admin_password),
        empresa_id=empresa.id,
        rol_global="admin_empresa",
        roles=["admin"],
        activo=True
    )
    db.add(admin_usuario)
    db.flush()  # Now admin_usuario.id exists
    
    # 3. Assign admin_id to empresa
    empresa.admin_id = admin_usuario.id
    db.commit()
    db.refresh(empresa)
    
    return {
        "message": "Empresa creada exitosamente",
        "empresa_id": str(empresa.id),
        "nombre": empresa.nombre,
        "subdominio": empresa.subdominio,
        "dominio_email": empresa.dominio_email,
        "admin_email": data.admin_email,
        "plan": empresa.plan,
        "fecha_vencimiento": empresa.fecha_vencimiento.isoformat() if empresa.fecha_vencimiento else None,
        "dias_prueba": 30
    }


@router.get("/stats/global")
async def estadisticas_globales(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Estadísticas globales para el dashboard del super_admin"""
    ahora = ahora_utc()
    en_7_dias = ahora + timedelta(days=7)
    
    total_empresas = db.query(Empresa).count()
    empresas_activas = db.query(Empresa).filter(Empresa.activo == True).count()
    
    por_vencer_7 = db.query(Empresa).filter(
        Empresa.activo == True,
        Empresa.fecha_vencimiento >= ahora,
        Empresa.fecha_vencimiento <= en_7_dias
    ).count()
    
    total_usuarios = db.query(Usuario).filter(Usuario.activo == True).count()
    total_personal = db.query(Personal).filter(Personal.activo == True).count()
    
    por_plan = {}
    for emp in db.query(Empresa).all():
        plan_name = emp.plan or "sin_plan"
        por_plan[plan_name] = por_plan.get(plan_name, 0) + 1
    
    inicio_mes = ahora.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    nuevas_este_mes = db.query(Empresa).filter(Empresa.created_at >= inicio_mes).count()
    
    return {
        "total_empresas": total_empresas,
        "empresas_activas": empresas_activas,
        "empresas_suspendidas": total_empresas - empresas_activas,
        "empresas_vencidas": 0,
        "empresas_por_vencer_7d": por_vencer_7,
        "nuevas_este_mes": nuevas_este_mes,
        "total_usuarios": total_usuarios,
        "total_personal": total_personal,
        "por_plan": por_plan
    }


@router.get("/{empresa_id}")
async def obtener_empresa(
    empresa_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Obtiene detalle completo de una empresa"""
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    ahora = ahora_utc()
    
    total_auth = db.query(Usuario).filter(Usuario.empresa_id == empresa.id, Usuario.activo == True).count()
    total_personal = db.query(Personal).filter(Personal.empresa_id == empresa.id).count()
    personal_activo = db.query(Personal).filter(Personal.empresa_id == empresa.id, Personal.activo == True).count()
    areas = db.query(Personal.area).filter(Personal.empresa_id == empresa.id, Personal.activo == True).distinct().count()
    completitud = round((total_auth / personal_activo * 100), 1) if personal_activo > 0 else 0
    
    ultimo = db.query(Usuario).filter(
        Usuario.empresa_id == empresa.id, Usuario.ultimo_acceso.isnot(None)
    ).order_by(Usuario.ultimo_acceso.desc()).first()
    
    admin = db.query(Usuario).filter(Usuario.id == empresa.admin_id).first()
    
    vencida = False
    dias_restantes = None
    if empresa.fecha_vencimiento:
        if empresa.fecha_vencimiento.tzinfo is None:
            vencida = empresa.fecha_vencimiento.replace(tzinfo=timezone.utc) < ahora
        else:
            vencida = empresa.fecha_vencimiento < ahora
        if not vencida:
            dias_restantes = (empresa.fecha_vencimiento - ahora).days
    
    return {
        "id": str(empresa.id),
        "nombre": empresa.nombre,
        "nombre_corto": empresa.nombre_corto,
        "subdominio": empresa.subdominio,
        "dominio_email": empresa.dominio_email,
        "ruc": empresa.ruc,
        "email_contacto": empresa.email_contacto,
        "telefono": empresa.telefono,
        "direccion": empresa.direccion,
        "activo": empresa.activo,
        "plan": empresa.plan,
        "max_usuarios": empresa.max_usuarios,
        "total_auth": total_auth,
        "total_personal": total_personal,
        "personal_activo": personal_activo,
        "personal_inactivo": total_personal - personal_activo,
        "areas_configuradas": areas,
        "completitud": completitud,
        "vencida": vencida,
        "dias_restantes": dias_restantes,
        "fecha_vencimiento": empresa.fecha_vencimiento.isoformat() if empresa.fecha_vencimiento else None,
        "created_at": empresa.created_at.isoformat() if empresa.created_at else None,
        "updated_at": empresa.updated_at.isoformat() if empresa.updated_at else None,
        "ultimo_acceso": ultimo.ultimo_acceso.isoformat() if ultimo and ultimo.ultimo_acceso else None,
        "ultimo_acceso_email": ultimo.email if ultimo else None,
        "logo_url": empresa.logo_url,
        "color_primario": empresa.color_primario,
        "color_secundario": empresa.color_secundario,
        "color_fondo": empresa.color_fondo,
        "color_texto": empresa.color_texto,
        "configuracion": empresa.configuracion,
        "admin": {
            "id": str(admin.id) if admin else None,
            "email": admin.email if admin else None,
            "username": admin.username if admin else None,
            "activo": admin.activo if admin else None,
            "ultimo_acceso": admin.ultimo_acceso.isoformat() if admin and admin.ultimo_acceso else None
        } if admin else None
    }


@router.put("/{empresa_id}")
async def actualizar_empresa(
    empresa_id: UUID,
    data: EmpresaUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Actualiza datos de una empresa"""
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(empresa, field, value)
    
    empresa.updated_at = ahora_utc()
    db.commit()
    db.refresh(empresa)
    
    return {
        "message": "Empresa actualizada exitosamente",
        "id": str(empresa.id),
        "nombre": empresa.nombre,
        "activo": empresa.activo,
        "plan": empresa.plan,
        "max_usuarios": empresa.max_usuarios,
        "fecha_vencimiento": empresa.fecha_vencimiento.isoformat() if empresa.fecha_vencimiento else None
    }


@router.post("/{empresa_id}/toggle-estado")
async def toggle_estado_empresa(
    empresa_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Activa o desactiva una empresa"""
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    empresa.activo = not empresa.activo
    empresa.updated_at = ahora_utc()
    db.commit()
    
    return {
        "message": f"Empresa {'activada' if empresa.activo else 'desactivada'} exitosamente",
        "id": str(empresa.id),
        "activo": empresa.activo
    }


@router.post("/{empresa_id}/renovar")
async def renovar_empresa(
    empresa_id: UUID,
    dias: int = Body(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Extiende la suscripción de una empresa por N días"""
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    ahora = ahora_utc()
    
    if empresa.fecha_vencimiento and empresa.fecha_vencimiento < ahora:
        empresa.fecha_vencimiento = ahora + timedelta(days=dias)
    elif empresa.fecha_vencimiento:
        empresa.fecha_vencimiento = empresa.fecha_vencimiento + timedelta(days=dias)
    else:
        empresa.fecha_vencimiento = ahora + timedelta(days=dias)
    
    empresa.activo = True
    empresa.updated_at = ahora
    db.commit()
    
    return {
        "message": f"Suscripción renovada por {dias} días",
        "id": str(empresa.id),
        "dias_agregados": dias,
        "nueva_fecha_vencimiento": empresa.fecha_vencimiento.isoformat() if empresa.fecha_vencimiento else None
    }