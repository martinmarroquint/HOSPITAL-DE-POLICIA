# app/api/clientes.py
# GESTIÓN DE CLIENTES - SUPER ADMIN
# VERSIÓN COMPLETA - CREA CLIENTE + ADMIN_CLIENTE AUTOMÁTICAMENTE
# Jerarquía: super_admin → clientes → empresas

from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone, date
import secrets
import string

from app.database import get_db
from app.core.dependencies import get_current_super_admin, get_current_active_user
from app.models.cliente import Cliente
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.models.personal import Personal
from app.core.security import get_password_hash, is_super_admin, is_admin_cliente
from app.schemas.empresa import ClienteCreate, ClienteUpdate, ClienteResponse

router = APIRouter()


def ahora_utc():
    """Retorna datetime UTC con timezone aware"""
    return datetime.now(timezone.utc)


def generar_password_segura(length=16):
    """Genera una contraseña segura aleatoria"""
    alphabet = string.ascii_letters + string.digits + '!@#$%&*'
    return ''.join(secrets.choice(alphabet) for _ in range(length))


def generar_email_admin(nombre_cliente: str) -> str:
    """Genera un email para el admin del cliente basado en el nombre"""
    nombre_limpio = nombre_cliente.lower().strip()
    # Remover caracteres especiales y espacios
    nombre_limpio = nombre_limpio.replace('á', 'a').replace('é', 'e').replace('í', 'i')
    nombre_limpio = nombre_limpio.replace('ó', 'o').replace('ú', 'u').replace('ñ', 'n')
    nombre_limpio = ''.join(c for c in nombre_limpio if c.isalnum())
    return f"admin@{nombre_limpio}.com"


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
    """Lista todos los clientes con métricas (solo super_admin)."""
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
    ahora = ahora_utc()
    
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
        
        # Contar usuarios del cliente (todos los que pertenecen a este cliente)
        total_usuarios = db.query(Usuario).filter(
            Usuario.cliente_id == cliente.id,
            Usuario.activo == True
        ).count()
        
        # Obtener admin del cliente
        admin_cliente = db.query(Usuario).filter(
            Usuario.cliente_id == cliente.id,
            Usuario.rol_global == "admin_cliente",
            Usuario.activo == True
        ).first()
        
        # Verificar vencimiento
        vencida = False
        dias_restantes = None
        if cliente.fecha_vencimiento:
            fecha_venc = cliente.fecha_vencimiento
            if isinstance(fecha_venc, date):
                fecha_venc = datetime.combine(fecha_venc, datetime.min.time()).replace(tzinfo=timezone.utc)
            vencida = fecha_venc < ahora
            if not vencida:
                dias_restantes = (fecha_venc - ahora).days
        
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
            "admin_email": admin_cliente.email if admin_cliente else None,
            "admin_id": str(admin_cliente.id) if admin_cliente else None,
            "created_at": cliente.created_at.isoformat() if cliente.created_at else None,
        })
    
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
async def crear_cliente(
    data: ClienteCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """
    Crea un nuevo cliente con su admin_cliente automáticamente (solo super_admin).
    
    FLUJO COMPLETO:
    1. Crea el registro del cliente
    2. Crea el registro personal del admin_cliente
    3. Crea el usuario admin_cliente vinculado al personal
    4. Retorna las credenciales del admin_cliente
    """
    
    # Validar unicidad del nombre
    if db.query(Cliente).filter(Cliente.nombre == data.nombre).first():
        raise HTTPException(status_code=400, detail=f"El cliente '{data.nombre}' ya existe")
    
    # Generar email del admin si no se proporciona email_contacto
    admin_email = data.email_contacto or generar_email_admin(data.nombre)
    
    # Validar que el email no esté en uso
    if db.query(Usuario).filter(Usuario.email == admin_email).first():
        raise HTTPException(status_code=400, detail=f"El email '{admin_email}' ya está registrado como usuario")
    
    # Generar contraseña segura para el admin_cliente
    password = generar_password_segura()
    
    # Si no se especifica fecha de vencimiento, dar 30 días de prueba
    fecha_vencimiento = data.fecha_vencimiento or (ahora_utc() + timedelta(days=30)).date()
    ahora = ahora_utc()
    
    # =====================================================
    # 1. CREAR CLIENTE
    # =====================================================
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
    db.flush()  # Obtener ID sin hacer commit aún
    
    # =====================================================
    # 2. CREAR REGISTRO PERSONAL DEL ADMIN_CLIENTE
    # =====================================================
    ## Generar DNI numérico de 8 dígitos
    import random
    dni_generado = f"{random.randint(10000000, 99999999)}"
    
    admin_personal = Personal(
        dni=dni_generado,
        nombre=f"ADMINISTRADOR {data.nombre.upper()}",
        email=admin_email,
        area="ADMINISTRACION",
        grado="ADMIN",
        roles=["admin_cliente"],
        activo=True,
        condicion="Titular",
        sexo="No especificado",
        fecha_ingreso=ahora.date(),
        empresa_id=None,
        areas_que_jefatura=[],
        areas_jefatura={"area": [], "grupo": [], "departamento": [], "direccion": []}
    )
    db.add(admin_personal)
    db.flush()
    
    # =====================================================
    # 3. CREAR USUARIO ADMIN_CLIENTE VINCULADO AL PERSONAL
    # =====================================================
    admin_usuario = Usuario(
        email=admin_email,
        username=admin_email,
        password_hash=get_password_hash(password),
        rol_global="admin_cliente",
        roles=["admin_cliente"],
        cliente_id=cliente.id,          # Pertenece a este cliente
        empresa_id=None,                 # No pertenece a una empresa específica
        personal_id=admin_personal.id,   # Vinculado a su registro personal
        activo=True
    )
    db.add(admin_usuario)
    
    # =====================================================
    # 4. CONFIRMAR TRANSACCIÓN
    # =====================================================
    db.commit()
    db.refresh(cliente)
    db.refresh(admin_usuario)
    db.refresh(admin_personal)
    
    return {
        "message": "Cliente creado exitosamente",
        "cliente_id": str(cliente.id),
        "nombre": cliente.nombre,
        "plan": cliente.plan,
        "fecha_vencimiento": cliente.fecha_vencimiento.isoformat() if cliente.fecha_vencimiento else None,
        # Credenciales del admin_cliente (mostrar solo una vez)
        "admin_email": admin_email,
        "admin_password": password,
        "admin_id": str(admin_usuario.id),
        "admin_personal_id": str(admin_personal.id),
        "dias_prueba": 30
    }


@router.get("/{cliente_id}")
async def obtener_cliente(
    cliente_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Obtiene detalle de un cliente con sus empresas y admin."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # Verificar acceso
    if not is_super_admin(current_user.rol_global):
        if not is_admin_cliente(current_user.rol_global) or current_user.cliente_id != cliente_id:
            raise HTTPException(status_code=403, detail="No tienes acceso a este cliente")
    
    empresas = db.query(Empresa).filter(Empresa.cliente_id == cliente_id).all()
    
    # Obtener admin del cliente
    admin_cliente = db.query(Usuario).filter(
        Usuario.cliente_id == cliente.id,
        Usuario.rol_global == "admin_cliente",
        Usuario.activo == True
    ).first()
    
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
        "admin": {
            "id": str(admin_cliente.id) if admin_cliente else None,
            "email": admin_cliente.email if admin_cliente else None,
            "activo": admin_cliente.activo if admin_cliente else None,
            "ultimo_acceso": admin_cliente.ultimo_acceso.isoformat() if admin_cliente and admin_cliente.ultimo_acceso else None
        } if admin_cliente else None,
        "empresas": [
            {
                "id": str(e.id),
                "nombre": e.nombre,
                "nombre_corto": e.nombre_corto,
                "subdominio": e.subdominio,
                "activo": e.activo,
                "plan": e.plan,
                "fecha_vencimiento": e.fecha_vencimiento.isoformat() if e.fecha_vencimiento else None,
                "total_usuarios": db.query(Usuario).filter(
                    Usuario.empresa_id == e.id,
                    Usuario.activo == True
                ).count()
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
    """Activa o desactiva un cliente y todas sus empresas (solo super_admin)."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    cliente.activo = not cliente.activo
    cliente.updated_at = ahora_utc()
    
    # También activar/desactivar todas las empresas del cliente
    db.query(Empresa).filter(Empresa.cliente_id == cliente_id).update(
        {"activo": cliente.activo, "updated_at": ahora_utc()}
    )
    
    # También activar/desactivar usuarios del cliente
    db.query(Usuario).filter(
        Usuario.cliente_id == cliente_id,
        Usuario.rol_global != "super_admin"  # No afectar super_admins
    ).update(
        {"activo": cliente.activo, "updated_at": ahora_utc()}
    )
    
    db.commit()
    
    return {
        "message": f"Cliente {'activado' if cliente.activo else 'desactivado'} exitosamente",
        "id": str(cliente.id),
        "activo": cliente.activo,
        "empresas_afectadas": db.query(Empresa).filter(Empresa.cliente_id == cliente_id).count()
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
    
    # También renovar todas las empresas del cliente
    empresas = db.query(Empresa).filter(Empresa.cliente_id == cliente_id).all()
    for empresa in empresas:
        if empresa.fecha_vencimiento and empresa.fecha_vencimiento < ahora:
            empresa.fecha_vencimiento = ahora + timedelta(days=dias)
        elif empresa.fecha_vencimiento:
            empresa.fecha_vencimiento = empresa.fecha_vencimiento + timedelta(days=dias)
        else:
            empresa.fecha_vencimiento = ahora + timedelta(days=dias)
        empresa.activo = True
        empresa.updated_at = ahora_utc()
    
    db.commit()
    
    return {
        "message": f"Suscripción renovada por {dias} días",
        "id": str(cliente.id),
        "dias_agregados": dias,
        "nueva_fecha_vencimiento": cliente.fecha_vencimiento.isoformat() if cliente.fecha_vencimiento else None,
        "empresas_renovadas": len(empresas)
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
        "total_empresas": len(empresas),
        "empresas": [
            {
                "id": str(e.id),
                "nombre": e.nombre,
                "nombre_corto": e.nombre_corto,
                "subdominio": e.subdominio,
                "plan": e.plan,
                "max_usuarios": e.max_usuarios,
                "logo_url": e.logo_url,
                "color_primario": e.color_primario,
                "activo": e.activo,
                "fecha_vencimiento": e.fecha_vencimiento.isoformat() if e.fecha_vencimiento else None,
                "total_usuarios": db.query(Usuario).filter(
                    Usuario.empresa_id == e.id,
                    Usuario.activo == True
                ).count()
            }
            for e in empresas
        ]
    }


@router.get("/{cliente_id}/stats")
async def estadisticas_cliente(
    cliente_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Obtiene estadísticas detalladas de un cliente."""
    cliente = db.query(Cliente).filter(Cliente.id == cliente_id).first()
    if not cliente:
        raise HTTPException(status_code=404, detail="Cliente no encontrado")
    
    # Verificar acceso
    if not is_super_admin(current_user.rol_global):
        if not is_admin_cliente(current_user.rol_global) or current_user.cliente_id != cliente_id:
            raise HTTPException(status_code=403, detail="No tienes acceso a este cliente")
    
    ahora = ahora_utc()
    
    # Conteos
    total_empresas = db.query(Empresa).filter(Empresa.cliente_id == cliente_id).count()
    empresas_activas = db.query(Empresa).filter(
        Empresa.cliente_id == cliente_id,
        Empresa.activo == True
    ).count()
    
    total_usuarios = db.query(Usuario).filter(
        Usuario.cliente_id == cliente_id,
        Usuario.activo == True
    ).count()
    
    total_personal = db.query(Personal).filter(
        Personal.empresa_id.in_(
            db.query(Empresa.id).filter(Empresa.cliente_id == cliente_id)
        )
    ).count() if total_empresas > 0 else 0
    
    # Distribución por plan
    empresas_por_plan = {}
    for empresa in db.query(Empresa).filter(Empresa.cliente_id == cliente_id).all():
        plan_name = empresa.plan or "sin_plan"
        empresas_por_plan[plan_name] = empresas_por_plan.get(plan_name, 0) + 1
    
    return {
        "cliente_id": str(cliente.id),
        "cliente_nombre": cliente.nombre,
        "total_empresas": total_empresas,
        "empresas_activas": empresas_activas,
        "empresas_suspendidas": total_empresas - empresas_activas,
        "total_usuarios": total_usuarios,
        "total_personal": total_personal,
        "empresas_por_plan": empresas_por_plan,
        "plan_cliente": cliente.plan,
        "fecha_vencimiento": cliente.fecha_vencimiento.isoformat() if cliente.fecha_vencimiento else None
    }