# api/configuracion_mensual.py
# VERSIÓN CORREGIDA - usa require_roles en lugar de get_current_admin_user

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import List, Dict, Optional
from datetime import datetime

from app.database import get_db
from app.models.configuracion_mensual import ConfiguracionMensual
from app.models.usuario import Usuario
from app.schemas.configuracion_mensual import (
    ConfiguracionMensualCreate,
    ConfiguracionMensualUpdate,
    ConfiguracionMensualValidar,
    ConfiguracionMensualResponse,
    ConfiguracionMensualDetailResponse,
    ConfiguracionMensualRangoResponse
)
from app.core.dependencies import get_current_user, get_current_active_user, require_roles

print("🔴🔴🔴 ESTOY EJECUTANDO EL ARCHIVO CORRECTO - CON /validar")
print("🔴🔴🔴 FECHA/HORA:", __import__('datetime').datetime.now())

print("="*60)
print("🚨🚨🚨 CARGANDO MÓDULO: configuracion_mensual.py")
print("="*60)

router = APIRouter(
    prefix="/configuracion-mensual",
    tags=["Configuración Mensual"]
)

print(f"🔧 Router creado con prefix: '{router.prefix}'")

# =====================================================
# ENDPOINTS PÚBLICOS
# =====================================================

@router.get("/{año}/{mes}", response_model=Optional[ConfiguracionMensualResponse])
def obtener_configuracion_mes(
    año: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtener configuración de un mes específico"""
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    return config


@router.get("/rango/", response_model=ConfiguracionMensualRangoResponse)
def obtener_configuraciones_rango(
    año_inicio: int,
    mes_inicio: int,
    año_fin: int,
    mes_fin: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtener configuraciones en un rango de meses"""
    if año_inicio > año_fin or (año_inicio == año_fin and mes_inicio > mes_fin):
        raise HTTPException(status_code=400, detail="Rango inválido")
    
    query = db.query(ConfiguracionMensual).filter(
        ((ConfiguracionMensual.año == año_inicio) & (ConfiguracionMensual.mes >= mes_inicio)) |
        ((ConfiguracionMensual.año > año_inicio) & (ConfiguracionMensual.año < año_fin)) |
        ((ConfiguracionMensual.año == año_fin) & (ConfiguracionMensual.mes <= mes_fin))
    )
    
    configs = query.all()
    config_dict = {}
    validados = 0
    
    for c in configs:
        key = f"{c.año}-{str(c.mes).zfill(2)}"
        config_dict[key] = c
        if c.validado:
            validados += 1
    
    return ConfiguracionMensualRangoResponse(
        configuraciones=config_dict,
        total=len(configs),
        validados=validados,
        pendientes=len(configs) - validados
    )


@router.get("/anual/{año}", response_model=Dict[str, ConfiguracionMensualResponse])
def obtener_configuracion_anual(
    año: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """Obtener configuraciones de todos los meses de un año"""
    configs = db.query(ConfiguracionMensual).filter(ConfiguracionMensual.año == año).all()
    result = {}
    for c in configs:
        key = f"{c.año}-{str(c.mes).zfill(2)}"
        result[key] = c
    return result


# =====================================================
# ENDPOINTS DE ADMIN (requieren rol admin)
# =====================================================

@router.post("/{año}/{mes}", response_model=ConfiguracionMensualResponse)
def crear_o_actualizar_configuracion(
    año: int,
    mes: int,
    config_data: ConfiguracionMensualCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crear o actualizar configuración de un mes (solo admin)"""
    if config_data.turnos_base != 25 and not config_data.motivo:
        raise HTTPException(status_code=400, detail="Debes proporcionar un motivo al cambiar el número de turnos")
    
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    
    if config:
        if config.turnos_base != config_data.turnos_base or config.validado != config_data.validado:
            historial_entry = {
                "fecha": datetime.now().isoformat(),
                "usuario_id": str(current_user.id),
                "usuario_nombre": current_user.nombre if hasattr(current_user, 'nombre') else current_user.email,
                "turnos_base_anterior": config.turnos_base,
                "turnos_base_nuevo": config_data.turnos_base,
            }
            if not config.historial:
                config.historial = []
            config.historial.append(historial_entry)
        
        for key, value in config_data.dict(exclude_unset=True).items():
            setattr(config, key, value)
        config.actualizado_en = datetime.now()
    else:
        config = ConfiguracionMensual(
            año=año, mes=mes,
            turnos_base=config_data.turnos_base,
            motivo=config_data.motivo,
            observacion=config_data.observacion,
            validado=config_data.validado,
            creado_en=datetime.now()
        )
        db.add(config)
    
    db.commit()
    db.refresh(config)
    return config


@router.post("/validar/{año}/{mes}", response_model=ConfiguracionMensualResponse)
def validar_configuracion_mes(
    año: int,
    mes: int,
    validar_data: ConfiguracionMensualValidar,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Validar la configuración de un mes (solo admin)"""
    if validar_data.turnos_base != 25 and not validar_data.motivo:
        raise HTTPException(status_code=400, detail="Debes proporcionar un motivo")
    
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    
    if not config:
        config = ConfiguracionMensual(
            año=año, mes=mes,
            turnos_base=validar_data.turnos_base,
            motivo=validar_data.motivo,
            observacion=validar_data.observacion,
            validado=True,
            fecha_validacion=datetime.now(),
            validado_por=current_user.id,
            creado_en=datetime.now()
        )
        db.add(config)
    else:
        config.turnos_base = validar_data.turnos_base
        config.motivo = validar_data.motivo
        config.observacion = validar_data.observacion
        config.validado = True
        config.fecha_validacion = datetime.now()
        config.validado_por = current_user.id
        config.actualizado_en = datetime.now()
    
    db.commit()
    db.refresh(config)
    return config


@router.put("/{año}/{mes}", response_model=ConfiguracionMensualResponse)
def actualizar_configuracion(
    año: int,
    mes: int,
    config_data: ConfiguracionMensualUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Actualizar configuración existente (solo admin)"""
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    
    for key, value in config_data.dict(exclude_unset=True).items():
        setattr(config, key, value)
    
    config.actualizado_en = datetime.now()
    db.commit()
    db.refresh(config)
    return config


@router.delete("/{año}/{mes}", status_code=204)
def eliminar_configuracion(
    año: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Eliminar configuración de un mes (solo admin)"""
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    
    if not config:
        raise HTTPException(status_code=404, detail="Configuración no encontrada")
    
    db.delete(config)
    db.commit()
    return None


@router.get("/ping")
async def ping():
    return {"message": "pong", "timestamp": datetime.now().isoformat()}

@router.get("/test-simple")
def test_simple():
    return {"message": "Funciona!", "timestamp": str(datetime.now()), "router_prefix": router.prefix}

@router.get("/test-user")
def test_user(current_user: Usuario = Depends(get_current_user)):
    if current_user:
        return {"message": "Usuario autenticado", "email": current_user.email}
    return {"message": "No hay usuario"}