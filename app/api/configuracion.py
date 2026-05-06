"""
API de Configuración Dinámica
Endpoints para gestionar la configuración del sistema
CADA EMPRESA TIENE SU PROPIA CONFIGURACIÓN
CORREGIDO: empresa_id asignado automáticamente al crear recursos
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID, uuid4
import os

from app.database import get_db
from app.core.dependencies import require_roles, get_current_active_user, get_current_super_admin
from app.services.configuracion_service import ConfiguracionService
from app.models.configuracion import ConfigCliente
from app.models.usuario import Usuario
from app.models.empresa import Empresa
from app.schemas.configuracion import (
    TurnoCreate, TurnoUpdate, TurnoResponse,
    ReglaCreate, ReglaResponse,
    NivelJerarquicoCreate, NivelJerarquicoResponse,
    UnidadCreate, UnidadUpdate, UnidadResponse,
    OrganigramaResponse,
    RolCreate, RolUpdate, RolResponse,
    CampoPersonalCreate, CampoPersonalResponse, CamposPersonalUpdateBulk,
    CatalogoCreate, CatalogoResponse,
    EstadoConfigResponse,
    ClienteConfigUpdate, ClienteConfigResponse,
)

router = APIRouter()

# =====================================================
# DIRECTORIO DE LOGOS
# =====================================================
UPLOAD_DIR = "static/logos"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# =====================================================
# DEPENDENCIA DEL SERVICIO
# =====================================================

def get_config_service(db: Session = Depends(get_db)) -> ConfiguracionService:
    return ConfiguracionService(db)


# =====================================================
# FUNCIÓN AUXILIAR: Obtener o crear config del cliente
# =====================================================

def get_or_create_config_cliente(db: Session, empresa_id: UUID, empresa_nombre: str = None) -> ConfigCliente:
    """Obtiene la configuración de una empresa o la crea si no existe"""
    config = db.query(ConfigCliente).filter(
        ConfigCliente.empresa_id == empresa_id
    ).first()
    
    if not config:
        if not empresa_nombre:
            empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
            empresa_nombre = empresa.nombre if empresa else "Mi Empresa"
        
        config = ConfigCliente(
            empresa_id=empresa_id,
            nombre_organizacion=empresa_nombre,
            nombre_corto=empresa_nombre.split()[0] if empresa_nombre else "EMP",
            color_primario="#1E3A5F",
            color_secundario="#2B6CB0",
            color_fondo="#F1F5F9",
            color_texto="#1A202C",
            pie_pagina="Sistema de Gestión"
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    
    return config


# =====================================================
# FUNCIÓN AUXILIAR: Obtener empresa_id del usuario
# =====================================================

def get_empresa_id_from_user(current_user: Usuario) -> Optional[UUID]:
    """Obtiene el empresa_id del usuario actual"""
    return current_user.empresa_id if current_user.empresa_id else None


# =====================================================
# ESTADO DE CONFIGURACIÓN
# =====================================================

@router.get("/estado", response_model=EstadoConfigResponse, tags=["Configuración"])
async def get_estado_configuracion(
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Retorna el estado de completitud de la configuración"""
    return service.get_estado()


# =====================================================
# TURNOS
# =====================================================

@router.get("/turnos", response_model=List[TurnoResponse], tags=["Configuración"])
async def listar_turnos(
    incluir_inactivos: bool = Query(False),
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Lista todos los turnos configurados para la empresa del usuario"""
    turnos = service.get_turnos(incluir_inactivos)
    empresa_id = get_empresa_id_from_user(current_user)
    if empresa_id and current_user.rol_global != "super_admin":
        turnos = [t for t in turnos if not t.empresa_id or t.empresa_id == empresa_id]
    return [t.to_dict() for t in turnos]


@router.post("/turnos", response_model=TurnoResponse, status_code=201, tags=["Configuración"])
async def crear_turno(
    turno: TurnoCreate,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea un nuevo tipo de turno asignado a la empresa del usuario"""
    try:
        turno_data = turno.model_dump()
        empresa_id = get_empresa_id_from_user(current_user)
        if empresa_id:
            turno_data['empresa_id'] = str(empresa_id)
        return service.crear_turno(turno_data).to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/turnos/{turno_id}", response_model=TurnoResponse, tags=["Configuración"])
async def actualizar_turno(
    turno_id: UUID,
    turno: TurnoUpdate,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Actualiza un tipo de turno"""
    try:
        return service.actualizar_turno(turno_id, turno.model_dump(exclude_unset=True)).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/turnos/{turno_id}", tags=["Configuración"])
async def eliminar_turno(
    turno_id: UUID,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina un tipo de turno"""
    try:
        service.eliminar_turno(turno_id)
        return {"success": True, "message": "Turno eliminado"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/turnos/masivo", tags=["Configuración"])
async def crear_turnos_masivo(
    data: dict,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea múltiples turnos a la vez"""
    turnos_data = data.get("turnos", [])
    empresa_id = get_empresa_id_from_user(current_user)
    if empresa_id:
        for t in turnos_data:
            t['empresa_id'] = str(empresa_id)
    turnos = service.crear_turnos_masivo(turnos_data)
    return {"success": True, "creados": len(turnos)}


# =====================================================
# REGLAS
# =====================================================

@router.get("/reglas", response_model=ReglaResponse, tags=["Configuración"])
async def get_reglas(
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Obtiene las reglas de cumplimiento"""
    reglas = service.get_reglas()
    if not reglas:
        return {}
    return reglas.to_dict()


@router.put("/reglas", response_model=ReglaResponse, tags=["Configuración"])
async def guardar_reglas(
    reglas: ReglaCreate,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Guarda o actualiza las reglas de cumplimiento"""
    reglas_data = reglas.model_dump()
    empresa_id = get_empresa_id_from_user(current_user)
    if empresa_id:
        reglas_data['empresa_id'] = str(empresa_id)
    return service.guardar_reglas(reglas_data).to_dict()


# =====================================================
# ORGANIGRAMA
# =====================================================

@router.get("/organigrama", response_model=OrganigramaResponse, tags=["Configuración"])
async def get_organigrama(
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Obtiene el organigrama completo"""
    return service.get_organigrama()


@router.put("/organigrama/niveles", response_model=List[NivelJerarquicoResponse], tags=["Configuración"])
async def guardar_niveles(
    data: dict,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Guarda los niveles jerárquicos"""
    niveles_data = data.get("niveles", [])
    empresa_id = get_empresa_id_from_user(current_user)
    if empresa_id:
        for n in niveles_data:
            n['empresa_id'] = str(empresa_id)
    niveles = service.guardar_niveles(niveles_data)
    return [n.to_dict() for n in niveles]


@router.post("/organigrama/unidades", response_model=UnidadResponse, status_code=201, tags=["Configuración"])
async def crear_unidad(
    unidad: UnidadCreate,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea una unidad organizacional"""
    try:
        unidad_data = unidad.model_dump()
        empresa_id = get_empresa_id_from_user(current_user)
        if empresa_id:
            unidad_data['empresa_id'] = str(empresa_id)
        return service.crear_unidad(unidad_data).to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/organigrama/unidades/{unidad_id}", response_model=UnidadResponse, tags=["Configuración"])
async def actualizar_unidad(
    unidad_id: UUID,
    unidad: UnidadUpdate,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Actualiza una unidad organizacional"""
    try:
        return service.actualizar_unidad(unidad_id, unidad.model_dump(exclude_unset=True)).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/organigrama/unidades/{unidad_id}", tags=["Configuración"])
async def eliminar_unidad(
    unidad_id: UUID,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina una unidad organizacional"""
    try:
        service.eliminar_unidad(unidad_id)
        return {"success": True, "message": "Unidad eliminada"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =====================================================
# ROLES
# =====================================================

@router.get("/roles", response_model=List[RolResponse], tags=["Configuración"])
async def listar_roles(
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Lista todos los roles"""
    roles = service.get_roles()
    return [r.to_dict() for r in roles]


@router.post("/roles", response_model=RolResponse, status_code=201, tags=["Configuración"])
async def crear_rol(
    rol: RolCreate,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea un nuevo rol"""
    try:
        rol_data = rol.model_dump()
        empresa_id = get_empresa_id_from_user(current_user)
        if empresa_id:
            rol_data['empresa_id'] = str(empresa_id)
        return service.crear_rol(rol_data).to_dict()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.put("/roles/{rol_id}", response_model=RolResponse, tags=["Configuración"])
async def actualizar_rol(
    rol_id: UUID,
    rol: RolUpdate,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Actualiza un rol"""
    try:
        return service.actualizar_rol(rol_id, rol.model_dump(exclude_unset=True)).to_dict()
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/roles/{rol_id}", tags=["Configuración"])
async def eliminar_rol(
    rol_id: UUID,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina un rol"""
    try:
        service.eliminar_rol(rol_id)
        return {"success": True, "message": "Rol eliminado"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =====================================================
# CAMPOS DEL PERSONAL
# =====================================================

@router.get("/campos-personal", response_model=List[CampoPersonalResponse], tags=["Configuración"])
async def get_campos_personal(
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Obtiene la configuración de campos del personal para la empresa del usuario"""
    empresa_id = get_empresa_id_from_user(current_user)
    campos = service.get_campos_personal(empresa_id)
    return [c.to_dict() for c in campos]


@router.put("/campos-personal", tags=["Configuración"])
async def guardar_campos_personal(
    data: CamposPersonalUpdateBulk,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Guarda la configuración de campos del personal para la empresa del usuario"""
    empresa_id = get_empresa_id_from_user(current_user)
    campos = service.guardar_campos_personal(
        [c.model_dump() for c in data.campos], 
        empresa_id
    )
    return {"success": True, "campos": len(campos)}


# =====================================================
# CATÁLOGOS
# =====================================================

@router.get("/catalogos", response_model=List[CatalogoResponse], tags=["Configuración"])
async def listar_catalogos(
    tipo: Optional[str] = Query(None),
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Lista catálogos, opcionalmente filtrados por tipo"""
    catalogos = service.get_catalogos(tipo)
    return [c.to_dict() for c in catalogos]


@router.post("/catalogos", response_model=CatalogoResponse, status_code=201, tags=["Configuración"])
async def crear_catalogo(
    catalogo: CatalogoCreate,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea una entrada de catálogo"""
    catalogo_data = catalogo.model_dump()
    empresa_id = get_empresa_id_from_user(current_user)
    if empresa_id:
        catalogo_data['empresa_id'] = str(empresa_id)
    return service.crear_catalogo(catalogo_data).to_dict()


@router.delete("/catalogos/{catalogo_id}", tags=["Configuración"])
async def eliminar_catalogo(
    catalogo_id: UUID,
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina una entrada de catálogo"""
    try:
        service.eliminar_catalogo(catalogo_id)
        return {"success": True, "message": "Catálogo eliminado"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# =====================================================
# CONFIGURACIÓN DEL CLIENTE (POR EMPRESA)
# =====================================================

@router.get("/cliente", response_model=ClienteConfigResponse, tags=["Configuración"])
async def get_config_cliente(
    db: Session = Depends(get_db),
    current_user: Optional[Usuario] = Depends(get_current_active_user)
):
    """
    Obtiene la configuración del cliente (nombre, logo, colores).
    Si hay usuario autenticado, devuelve la config de SU empresa.
    Si no hay usuario, devuelve la primera config (fallback).
    """
    if current_user and current_user.empresa_id:
        config = get_or_create_config_cliente(db, current_user.empresa_id)
    else:
        config = db.query(ConfigCliente).first()
        if not config:
            config = ConfigCliente()
            db.add(config)
            db.commit()
            db.refresh(config)
    
    return config.to_dict()


@router.put("/cliente", response_model=ClienteConfigResponse, tags=["Configuración"])
async def update_config_cliente(
    data: ClienteConfigUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Actualiza la configuración del cliente. Solo administradores de la empresa."""
    if not current_user.empresa_id:
        raise HTTPException(status_code=400, detail="Usuario sin empresa asignada")
    
    config = get_or_create_config_cliente(db, current_user.empresa_id)
    
    for key, value in data.model_dump(exclude_unset=True).items():
        setattr(config, key, value)
    
    db.commit()
    db.refresh(config)
    return config.to_dict()


# =====================================================
# SUBIDA DE LOGO (POR EMPRESA)
# =====================================================

@router.post("/cliente/logo", tags=["Configuración"])
async def subir_logo_cliente(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Sube el logo de la organización"""
    if not current_user.empresa_id:
        raise HTTPException(status_code=400, detail="Usuario sin empresa asignada")
    
    filename = file.filename or "logo.png"
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if ext not in ['png', 'jpg', 'jpeg', 'svg']:
        raise HTTPException(status_code=400, detail="Formato no permitido. Use PNG, JPG, JPEG o SVG.")
    
    contents = await file.read()
    if len(contents) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="El logo no debe superar los 2MB.")
    
    unique_filename = f"{uuid4().hex}_{filename}"
    filepath = os.path.join(UPLOAD_DIR, unique_filename)
    
    with open(filepath, "wb") as f:
        f.write(contents)
    
    logo_url = f"/static/logos/{unique_filename}"
    config = get_or_create_config_cliente(db, current_user.empresa_id)
    
    if config.logo_url and config.logo_url.startswith("/static/logos/"):
        old_path = config.logo_url.replace("/static/", "static/")
        if os.path.exists(old_path):
            os.remove(old_path)
    
    config.logo_url = logo_url
    db.commit()
    db.refresh(config)
    
    return {"success": True, "logo_url": logo_url, "filename": unique_filename}


@router.delete("/cliente/logo", tags=["Configuración"])
async def eliminar_logo_cliente(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina el logo actual"""
    if not current_user.empresa_id:
        raise HTTPException(status_code=400, detail="Usuario sin empresa asignada")
    
    config = db.query(ConfigCliente).filter(
        ConfigCliente.empresa_id == current_user.empresa_id
    ).first()
    
    if not config or not config.logo_url:
        raise HTTPException(status_code=404, detail="No hay logo para eliminar")
    
    if config.logo_url.startswith("/static/logos/"):
        filepath = config.logo_url.replace("/static/", "static/")
        if os.path.exists(filepath):
            os.remove(filepath)
    
    config.logo_url = None
    db.commit()
    
    return {"success": True, "message": "Logo eliminado"}


# =====================================================
# SEMILLA DE NIVELES POR DEFECTO
# =====================================================

@router.post("/organigrama/niveles/semilla", tags=["Configuración"])
async def crear_niveles_semilla(
    service: ConfiguracionService = Depends(get_config_service),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea los niveles jerárquicos por defecto"""
    niveles_default = [
        {"nombre": "Sede / Región",   "color": "#1E3A5F", "orden": 1,  "requiere_jefe": True},
        {"nombre": "Dirección",       "color": "#3FB4B4", "orden": 2,  "requiere_jefe": True},
        {"nombre": "Sub-Dirección",   "color": "#6366F1", "orden": 3,  "requiere_jefe": True},
        {"nombre": "División",        "color": "#8B5CF6", "orden": 4,  "requiere_jefe": True},
        {"nombre": "Departamento",    "color": "#F59E0B", "orden": 5,  "requiere_jefe": True},
        {"nombre": "Servicio",        "color": "#10B981", "orden": 6,  "requiere_jefe": True},
        {"nombre": "Unidad",          "color": "#EF4444", "orden": 7,  "requiere_jefe": True},
        {"nombre": "Área",            "color": "#06B6D4", "orden": 8,  "requiere_jefe": False},
        {"nombre": "Oficina",         "color": "#EC4899", "orden": 9,  "requiere_jefe": False},
        {"nombre": "Grupo / Equipo",  "color": "#6B7280", "orden": 10, "requiere_jefe": False},
    ]
    
    empresa_id = get_empresa_id_from_user(current_user)
    if empresa_id:
        for n in niveles_default:
            n['empresa_id'] = str(empresa_id)
    
    try:
        niveles = service.guardar_niveles(niveles_default)
        return {
            "success": True,
            "message": f"{len(niveles)} niveles creados correctamente",
            "creados": len(niveles),
            "niveles": [n.to_dict() for n in niveles]
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error al crear niveles: {str(e)}")


# =====================================================
# CONFIG PÚBLICA (SIN AUTENTICACIÓN)
# =====================================================

@router.get("/cliente/publico", tags=["Configuración"])
async def get_config_cliente_publico(
    subdominio: str = Query("default", description="Subdominio de la empresa"),
    db: Session = Depends(get_db)
):
    """
    Endpoint PÚBLICO - Obtiene la configuración de una empresa por subdominio.
    No requiere autenticación. Lo usa el login para mostrar logo y colores.
    """
    empresa = db.query(Empresa).filter(Empresa.subdominio == subdominio).first()
    
    if not empresa:
        empresa = db.query(Empresa).filter(Empresa.subdominio == "default").first()
    
    if empresa:
        config = db.query(ConfigCliente).filter(
            ConfigCliente.empresa_id == empresa.id
        ).first()
        if config:
            return config.to_dict()
    
    return {
        "nombre_organizacion": "Sistema de Gestión",
        "nombre_corto": "SISTEMA",
        "logo_url": None,
        "color_primario": "#1E3A5F",
        "color_secundario": "#2B6CB0",
        "color_fondo": "#F1F5F9",
        "color_texto": "#1A202C",
        "pie_pagina": "Sistema de Gestión de Personal"
    }