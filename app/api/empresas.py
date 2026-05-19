# app/api/empresas.py
# GESTIÓN DE EMPRESAS - SUPER ADMIN + ADMIN CLIENTE
# VERSIÓN COMPLETA CORREGIDA - CREA PERSONAL + USUARIO AUTOMÁTICAMENTE
# Jerarquía: super_admin → admin_cliente → admin_empresa → jefe → usuario

from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone, date
import re
import random

from app.database import get_db
from app.core.dependencies import get_current_super_admin, get_current_active_user
from app.models.empresa import Empresa
from app.models.usuario import Usuario
from app.models.personal import Personal
from app.models.cliente import Cliente
from app.core.security import get_password_hash, is_admin, is_super_admin, is_admin_cliente
from app.schemas.empresa import EmpresaCreate, EmpresaUpdate, EmpresaResponse, EmpresaStatsResponse

router = APIRouter()


def ahora_utc():
    """Retorna datetime UTC con timezone aware"""
    return datetime.now(timezone.utc)


def generar_subdominio(nombre: str) -> str:
    """Genera un subdominio limpio a partir del nombre de la empresa"""
    sub = nombre.lower().strip()
    # Reemplazar caracteres especiales
    reemplazos = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'à': 'a', 'è': 'e', 'ì': 'i', 'ò': 'o', 'ù': 'u',
        'ä': 'a', 'ë': 'e', 'ï': 'i', 'ö': 'o', 'ü': 'u',
        'â': 'a', 'ê': 'e', 'î': 'i', 'ô': 'o', 'û': 'u',
        'ã': 'a', 'õ': 'o', 'ñ': 'n', 'ç': 'c'
    }
    for char, reemplazo in reemplazos.items():
        sub = sub.replace(char, reemplazo)
    
    sub = re.sub(r'[^a-z0-9\s-]', '', sub)
    sub = re.sub(r'[\s_]+', '-', sub)
    sub = re.sub(r'-+', '-', sub)
    sub = sub.strip('-')
    return sub[:50] or 'empresa'


# =====================================================
# ENDPOINTS PARA SUPER ADMIN
# =====================================================

@router.get("/")
async def listar_empresas(
    activo: Optional[bool] = Query(None),
    plan: Optional[str] = Query(None),
    busqueda: Optional[str] = Query(None),
    cliente_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_super_admin)
):
    """Lista todas las empresas con métricas en tiempo real (solo super_admin)."""
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
    if cliente_id:
        query = query.filter(Empresa.cliente_id == cliente_id)
    
    empresas = query.order_by(Empresa.created_at.desc()).all()
    ahora = ahora_utc()
    
    result = []
    for empresa in empresas:
        total_auth = db.query(Usuario).filter(
            Usuario.empresa_id == empresa.id, 
            Usuario.activo == True
        ).count()
        
        total_personal = db.query(Personal).filter(
            Personal.empresa_id == empresa.id
        ).count()
        
        personal_activo = db.query(Personal).filter(
            Personal.empresa_id == empresa.id, 
            Personal.activo == True
        ).count()
        
        completitud = round((total_auth / personal_activo * 100), 1) if personal_activo > 0 else 0
        
        ultimo = db.query(Usuario).filter(
            Usuario.empresa_id == empresa.id,
            Usuario.ultimo_acceso.isnot(None)
        ).order_by(Usuario.ultimo_acceso.desc()).first()
        
        vencida = False
        dias_restantes = None
        if empresa.fecha_vencimiento:
            fecha_venc = empresa.fecha_vencimiento
            if isinstance(fecha_venc, date):
                fecha_venc = datetime.combine(fecha_venc, datetime.min.time()).replace(tzinfo=timezone.utc)
            elif isinstance(fecha_venc, datetime) and fecha_venc.tzinfo is None:
                fecha_venc = fecha_venc.replace(tzinfo=timezone.utc)
            vencida = fecha_venc < ahora
            if not vencida:
                dias_restantes = (fecha_venc - ahora).days
        
        admin = db.query(Usuario).filter(Usuario.id == empresa.admin_id).first()
        cliente = db.query(Cliente).filter(Cliente.id == empresa.cliente_id).first()
        
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
            "admin_email": admin.email if admin else None,
            "cliente_id": str(empresa.cliente_id) if empresa.cliente_id else None,
            "cliente_nombre": cliente.nombre if cliente else None,
        })
    
    return result


@router.post("/", status_code=status.HTTP_201_CREATED)
async def crear_empresa(
    data: EmpresaCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)  # ✅ Permite super_admin y admin_cliente
):
    """
    Crea una nueva empresa con su administrador.
    
    PERMISOS:
    - super_admin: puede crear empresas en cualquier cliente
    - admin_cliente: solo puede crear empresas en su propio cliente
    
    FLUJO COMPLETO:
    1. Valida permisos y cliente
    2. Crea la empresa vinculada al cliente
    3. Crea el registro personal del admin_empresa
    4. Crea el usuario admin_empresa vinculado al personal y cliente
    5. Vincula el admin a la empresa
    """
    
    # =====================================================
    # 🔐 VALIDACIONES DE PERMISOS Y CLIENTE
    # =====================================================
    
    # Validar que el cliente existe y está activo
    if data.cliente_id:
        cliente = db.query(Cliente).filter(
            Cliente.id == data.cliente_id,
            Cliente.activo == True
        ).first()
        if not cliente:
            raise HTTPException(
                status_code=400, 
                detail="El cliente seleccionado no existe o está inactivo"
            )
        
        # Verificar permisos: admin_cliente solo puede crear en su cliente
        if is_admin_cliente(current_user.rol_global):
            if str(current_user.cliente_id) != str(data.cliente_id):
                raise HTTPException(
                    status_code=403, 
                    detail="Solo puedes crear empresas en tu propio cliente"
                )
    else:
        # Si no se proporciona cliente_id, solo super_admin puede crear sin cliente
        if not is_super_admin(current_user.rol_global):
            raise HTTPException(
                status_code=400, 
                detail="Debes seleccionar un cliente para crear la empresa"
            )
    
    # =====================================================
    # 🔤 GENERAR VALORES AUTOMÁTICOS
    # =====================================================
    subdominio = data.subdominio or generar_subdominio(data.nombre)
    dominio_email = data.dominio_email or f"{subdominio}.com"
    email_contacto = data.email_contacto or f"admin@{dominio_email}"
    admin_email = data.admin_email or f"admin@{dominio_email}"
    
    # =====================================================
    # ✅ VALIDACIONES DE UNICIDAD
    # =====================================================
    if db.query(Empresa).filter(Empresa.subdominio == subdominio).first():
        raise HTTPException(
            status_code=400, 
            detail=f"El subdominio '{subdominio}' ya está registrado"
        )
    
    if db.query(Usuario).filter(Usuario.email == admin_email).first():
        raise HTTPException(
            status_code=400, 
            detail=f"El email '{admin_email}' ya está registrado como usuario"
        )
    
    # =====================================================
    # 📅 FECHA DE VENCIMIENTO
    # =====================================================
    # Heredar fecha del cliente si tiene, sino 30 días de prueba
    if data.cliente_id and cliente and cliente.fecha_vencimiento:
        fecha_vencimiento = cliente.fecha_vencimiento
        if isinstance(fecha_vencimiento, datetime):
            fecha_vencimiento = fecha_vencimiento.date()
    else:
        fecha_vencimiento = (ahora_utc() + timedelta(days=30)).date()
    
    ahora = ahora_utc()
    
    # =====================================================
    # 1. CREAR EMPRESA
    # =====================================================
    empresa = Empresa(
        nombre=data.nombre,
        nombre_corto=data.nombre_corto or (data.nombre.split()[0] if data.nombre else None),
        subdominio=subdominio,
        dominio_email=dominio_email,
        email_contacto=email_contacto,
        plan=data.plan,
        max_usuarios=data.max_usuarios,
        ruc=data.ruc,
        telefono=data.telefono,
        direccion=data.direccion,
        activo=True,
        fecha_vencimiento=fecha_vencimiento,
        cliente_id=data.cliente_id,  # ✅ Vinculado al cliente
    )
    db.add(empresa)
    db.flush()  # Obtener ID sin hacer commit
    
        # =====================================================
    # 2. CREAR REGISTRO PERSONAL DEL ADMIN_EMPRESA
    # =====================================================
    import random
    dni_admin = f"{random.randint(10000000, 99999999)}"
    
    admin_personal = Personal(
        dni=dni_admin,
        nombre=f"ADMINISTRADOR {data.nombre.upper()}",
        email=admin_email,
        area="ADMINISTRACION",
        grado="ADMIN",
        roles=["admin_empresa", "usuario"],
        activo=True,
        condicion="Titular",
        empresa_id=empresa.id,
        sexo="No especificado",
        areas_que_jefatura=[],
        areas_jefatura={
            "area": [], 
            "grupo": [], 
            "departamento": [], 
            "direccion": []
        },
        fecha_ingreso=ahora.date()
    )
    db.add(admin_personal)
    db.flush()
    
    # =====================================================
    # 3. CREAR USUARIO ADMIN_EMPRESA VINCULADO AL PERSONAL
    # =====================================================
    admin_usuario = Usuario(
        email=admin_email,
        username=admin_email,
        password_hash=get_password_hash(data.admin_password),
        rol_global="admin_empresa",
        roles=["admin_empresa", "usuario"],
        empresa_id=empresa.id,          # ✅ Pertenece a esta empresa
        cliente_id=empresa.cliente_id,  # ✅ Hereda el cliente de la empresa
        personal_id=admin_personal.id,  # ✅ Vinculado a su registro personal
        activo=True
    )
    db.add(admin_usuario)
    db.flush()
    
    # =====================================================
    # 4. VINCULAR ADMIN A LA EMPRESA
    # =====================================================
    empresa.admin_id = admin_usuario.id
    
    # =====================================================
    # 5. CONFIRMAR TRANSACCIÓN
    # =====================================================
    db.commit()
    db.refresh(empresa)
    db.refresh(admin_usuario)
    db.refresh(admin_personal)
    
    return {
        "message": "Empresa creada exitosamente",
        "empresa_id": str(empresa.id),
        "nombre": empresa.nombre,
        "subdominio": empresa.subdominio,
        "dominio_email": empresa.dominio_email,
        "email_contacto": empresa.email_contacto,
        "admin_email": admin_email,
        "admin_id": str(admin_usuario.id),
        "admin_personal_id": str(admin_personal.id),
        "cliente_id": str(empresa.cliente_id) if empresa.cliente_id else None,
        "cliente_nombre": cliente.nombre if data.cliente_id and cliente else None,
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
    en_30_dias = ahora + timedelta(days=30)
    
    total_empresas = db.query(Empresa).count()
    empresas_activas = db.query(Empresa).filter(Empresa.activo == True).count()
    total_clientes = db.query(Cliente).filter(Cliente.activo == True).count()
    
    por_vencer_7 = db.query(Empresa).filter(
        Empresa.activo == True,
        Empresa.fecha_vencimiento >= ahora.date(),
        Empresa.fecha_vencimiento <= en_7_dias.date()
    ).count()
    
    por_vencer_30 = db.query(Empresa).filter(
        Empresa.activo == True,
        Empresa.fecha_vencimiento >= ahora.date(),
        Empresa.fecha_vencimiento <= en_30_dias.date()
    ).count()
    
    vencidas = db.query(Empresa).filter(
        Empresa.activo == True,
        Empresa.fecha_vencimiento < ahora.date()
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
        "total_clientes": total_clientes,
        "total_empresas": total_empresas,
        "empresas_activas": empresas_activas,
        "empresas_suspendidas": total_empresas - empresas_activas,
        "empresas_vencidas": vencidas,
        "empresas_por_vencer_7d": por_vencer_7,
        "empresas_por_vencer_30d": por_vencer_30,
        "nuevas_este_mes": nuevas_este_mes,
        "total_usuarios": total_usuarios,
        "total_personal": total_personal,
        "por_plan": por_plan
    }


# =====================================================
# ENDPOINTS PARA ADMIN CLIENTE (Mis Empresas)
# =====================================================

@router.get("/mis-empresas/")
async def mis_empresas(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Retorna las empresas asignadas al usuario actual.
    - super_admin: ve todas
    - admin_cliente: ve las de su cliente
    - admin_empresa/usuario: ve solo su empresa
    """
    
    if is_super_admin(current_user.rol_global):
        empresas = db.query(Empresa).filter(Empresa.activo == True).all()
    elif is_admin_cliente(current_user.rol_global) and current_user.cliente_id:
        empresas = db.query(Empresa).filter(
            Empresa.cliente_id == current_user.cliente_id,
            Empresa.activo == True
        ).all()
    else:
        empresas = db.query(Empresa).filter(
            Empresa.id == current_user.empresa_id,
            Empresa.activo == True
        ).all()
    
    return {
        "empresas": [
            {
                "id": str(e.id),
                "nombre": e.nombre,
                "nombre_corto": e.nombre_corto,
                "subdominio": e.subdominio,
                "plan": e.plan,
                "logo_url": e.logo_url,
                "color_primario": e.color_primario,
                "rol_en_empresa": current_user.rol_global
            }
            for e in empresas
        ]
    }


# =====================================================
# ENDPOINTS COMUNES
# =====================================================

@router.get("/{empresa_id}")
async def obtener_empresa(
    empresa_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Obtiene detalle completo de una empresa"""
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    # Verificar acceso
    if not is_super_admin(current_user.rol_global):
        if is_admin_cliente(current_user.rol_global):
            if str(empresa.cliente_id) != str(current_user.cliente_id):
                raise HTTPException(status_code=403, detail="No tienes acceso a esta empresa")
        elif str(empresa.id) != str(current_user.empresa_id):
            raise HTTPException(status_code=403, detail="No tienes acceso a esta empresa")
    
    ahora = ahora_utc()
    
    total_auth = db.query(Usuario).filter(
        Usuario.empresa_id == empresa.id, 
        Usuario.activo == True
    ).count()
    
    total_personal = db.query(Personal).filter(
        Personal.empresa_id == empresa.id
    ).count()
    
    personal_activo = db.query(Personal).filter(
        Personal.empresa_id == empresa.id, 
        Personal.activo == True
    ).count()
    
    areas = db.query(Personal.area).filter(
        Personal.empresa_id == empresa.id, 
        Personal.activo == True
    ).distinct().count()
    
    completitud = round((total_auth / personal_activo * 100), 1) if personal_activo > 0 else 0
    
    ultimo = db.query(Usuario).filter(
        Usuario.empresa_id == empresa.id, 
        Usuario.ultimo_acceso.isnot(None)
    ).order_by(Usuario.ultimo_acceso.desc()).first()
    
    admin = db.query(Usuario).filter(Usuario.id == empresa.admin_id).first()
    cliente = db.query(Cliente).filter(Cliente.id == empresa.cliente_id).first()
    
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
        "cliente_id": str(empresa.cliente_id) if empresa.cliente_id else None,
        "cliente_nombre": cliente.nombre if cliente else None,
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
    current_user: Usuario = Depends(get_current_active_user)
):
    """Actualiza datos de una empresa"""
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    # Solo super_admin, admin_cliente y admin_empresa pueden actualizar
    if not is_admin(current_user.rol_global):
        raise HTTPException(status_code=403, detail="No tienes permisos para actualizar empresas")
    
    # Admin cliente solo puede actualizar empresas de su cliente
    if is_admin_cliente(current_user.rol_global):
        if str(empresa.cliente_id) != str(current_user.cliente_id):
            raise HTTPException(status_code=403, detail="No tienes acceso a esta empresa")
    
    # Admin empresa solo puede actualizar su propia empresa
    if current_user.rol_global == "admin_empresa":
        if str(empresa.id) != str(current_user.empresa_id):
            raise HTTPException(status_code=403, detail="Solo puedes actualizar tu propia empresa")
    
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
    current_user: Usuario = Depends(get_current_active_user)  # ✅ Permite super_admin y admin_cliente
):
    """Activa o desactiva una empresa y sus usuarios"""
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    # Verificar permisos
    if not is_super_admin(current_user.rol_global):
        if is_admin_cliente(current_user.rol_global):
            if str(empresa.cliente_id) != str(current_user.cliente_id):
                raise HTTPException(status_code=403, detail="No tienes acceso a esta empresa")
        else:
            raise HTTPException(status_code=403, detail="No tienes permisos para esta acción")
    
    empresa.activo = not empresa.activo
    empresa.updated_at = ahora_utc()
    
    # También activar/desactivar usuarios de la empresa (excepto admins)
    if not empresa.activo:
        db.query(Usuario).filter(
            Usuario.empresa_id == empresa_id,
            Usuario.rol_global.notin_(["super_admin", "admin_cliente"])
        ).update({"activo": False, "updated_at": ahora_utc()})
    else:
        db.query(Usuario).filter(
            Usuario.empresa_id == empresa_id,
            Usuario.rol_global.notin_(["super_admin", "admin_cliente"])
        ).update({"activo": True, "updated_at": ahora_utc()})
    
    db.commit()
    
    return {
        "message": f"Empresa {'activada' if empresa.activo else 'desactivada'} exitosamente",
        "id": str(empresa.id),
        "activo": empresa.activo,
        "usuarios_afectados": db.query(Usuario).filter(
            Usuario.empresa_id == empresa_id,
            Usuario.rol_global.notin_(["super_admin", "admin_cliente"])
        ).count()
    }


@router.post("/{empresa_id}/renovar")
async def renovar_empresa(
    empresa_id: UUID,
    dias: int = Body(30, ge=1, le=365),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)  # ✅ Permite super_admin y admin_cliente
):
    """Extiende la suscripción de una empresa por N días"""
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if not empresa:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    
    # Verificar permisos
    if not is_super_admin(current_user.rol_global):
        if is_admin_cliente(current_user.rol_global):
            if str(empresa.cliente_id) != str(current_user.cliente_id):
                raise HTTPException(status_code=403, detail="No tienes acceso a esta empresa")
        else:
            raise HTTPException(status_code=403, detail="No tienes permisos para esta acción")
    
    ahora = ahora_utc().date()
    
    if empresa.fecha_vencimiento:
        fecha_venc = empresa.fecha_vencimiento
        if isinstance(fecha_venc, datetime):
            fecha_venc = fecha_venc.date()
        
        if fecha_venc < ahora:
            empresa.fecha_vencimiento = ahora + timedelta(days=dias)
        else:
            empresa.fecha_vencimiento = fecha_venc + timedelta(days=dias)
    else:
        empresa.fecha_vencimiento = ahora + timedelta(days=dias)
    
    empresa.activo = True
    empresa.updated_at = ahora_utc()
    db.commit()
    
    return {
        "message": f"Suscripción renovada por {dias} días",
        "id": str(empresa.id),
        "dias_agregados": dias,
        "nueva_fecha_vencimiento": empresa.fecha_vencimiento.isoformat() if empresa.fecha_vencimiento else None
    }