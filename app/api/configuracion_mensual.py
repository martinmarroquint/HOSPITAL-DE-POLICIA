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
from app.core.dependencies import get_current_user, get_current_admin_user
from app.core.security import has_role

print("🔴🔴🔴 ESTOY EJECUTANDO EL ARCHIVO CORRECTO - CON /validar")
print("🔴🔴🔴 FECHA/HORA:", __import__('datetime').datetime.now())
# =====================================================
# 🚨 DIAGNÓSTICO DE CARGA DEL MÓDULO
# =====================================================
print("="*60)
print("🚨🚨🚨 CARGANDO MÓDULO: configuracion_mensual.py")
print("="*60)

# =====================================================
# ✅ VERSIÓN CORREGIDA - CON PREFIJO EN EL ROUTER
# =====================================================
router = APIRouter(
    prefix="/configuracion-mensual",
    tags=["Configuración Mensual"]
)

print(f"🔧 Router creado con prefix: '{router.prefix}'")
print(f"📊 Router tags: {router.tags}")
print(f"📊 Rutas definidas inicialmente: {len(router.routes)}")

# =====================================================
# ENDPOINTS PÚBLICOS (cualquier usuario autenticado)
# =====================================================

@router.get("/{año}/{mes}", response_model=Optional[ConfiguracionMensualResponse])
def obtener_configuracion_mes(
    año: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtener configuración de un mes específico (cualquier usuario autenticado)
    """
    import traceback
    print("="*60)
    print(f"🔴🔴🔴 ENDPOINT ALCANZADO: obtener_configuracion_mes({año}, {mes})")
    print(f"📌 Tipo de año: {type(año)}")
    print(f"📌 Tipo de mes: {type(mes)}")
    print(f"📌 DB Session: {db}")
    print(f"📌 Current User: {current_user}")
    print(f"📌 Current User Email: {current_user.email if current_user else 'None'}")
    print(f"📌 Current User Roles: {current_user.roles if current_user else 'None'}")
    
    try:
        print("🔍 Intentando consultar base de datos...")
        print(f"📡 Buscando configuración para {año}/{mes}")
        
        # Verificar que la tabla existe
        from sqlalchemy import inspect
        inspector = inspect(db.bind)
        tables = inspector.get_table_names()
        print(f"📊 Tablas en DB: {tables}")
        
        if 'configuraciones_mensuales' not in tables:
            print(f"❌ La tabla 'configuraciones_mensuales' NO existe en la base de datos")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="La tabla de configuraciones no existe en la base de datos"
            )
        
        # Intentar la consulta
        print("🔍 Ejecutando query...")
        config = db.query(ConfiguracionMensual).filter(
            ConfiguracionMensual.año == año,
            ConfiguracionMensual.mes == mes
        ).first()
        
        print(f"✅ Consulta ejecutada. Resultado: {config}")
        
        if config:
            print(f"✅ Configuración encontrada: ID={config.id}, turnos={config.turnos_base}")
        else:
            print(f"📭 No hay configuración para {año}/{mes}")
        
        return config
        
    except HTTPException:
        # Re-lanzar HTTPExceptions sin modificar
        raise
    except Exception as e:
        print(f"❌ ERROR en endpoint: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error interno: {str(e)}"
        )


@router.get("/rango/", response_model=ConfiguracionMensualRangoResponse)
def obtener_configuraciones_rango(
    año_inicio: int,
    mes_inicio: int,
    año_fin: int,
    mes_fin: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_user)
):
    """
    Obtener configuraciones en un rango de meses
    """
    print(f"🔵 RANGO ENDPOINT ALCANZADO: {año_inicio}/{mes_inicio} - {año_fin}/{mes_fin}")
    
    # Validar rango
    if año_inicio > año_fin or (año_inicio == año_fin and mes_inicio > mes_fin):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Rango inválido: fecha inicio debe ser menor o igual a fecha fin"
        )
    
    # Construir consulta
    query = db.query(ConfiguracionMensual).filter(
        ((ConfiguracionMensual.año == año_inicio) & (ConfiguracionMensual.mes >= mes_inicio)) |
        ((ConfiguracionMensual.año > año_inicio) & (ConfiguracionMensual.año < año_fin)) |
        ((ConfiguracionMensual.año == año_fin) & (ConfiguracionMensual.mes <= mes_fin))
    )
    
    configs = query.all()
    
    # Organizar por clave "YYYY-MM"
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
    """
    Obtener configuraciones de todos los meses de un año
    """
    print(f"🔵 ANUAL ENDPOINT ALCANZADO: año={año}")
    
    configs = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año
    ).all()
    
    # Organizar por mes
    result = {}
    for c in configs:
        key = f"{c.año}-{str(c.mes).zfill(2)}"
        result[key] = c
    
    print(f"✅ Encontradas {len(configs)} configuraciones para {año}")
    return result


# =====================================================
# ENDPOINTS DE ADMIN (solo admin) - TODOS CORREGIDOS
# =====================================================

# ✅ POST para crear/actualizar configuración
@router.post("/{año}/{mes}", response_model=ConfiguracionMensualResponse)
def crear_o_actualizar_configuracion(
    año: int,
    mes: int,
    config_data: ConfiguracionMensualCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin_user)
):
    """
    Crear o actualizar configuración de un mes (solo admin)
    """
    print(f"🔵 POST ENDPOINT ALCANZADO: {año}/{mes}")
    print(f"📦 Datos recibidos: {config_data}")
    
    # Validar que si no es 25, tenga motivo
    if config_data.turnos_base != 25 and not config_data.motivo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes proporcionar un motivo al cambiar el número de turnos (23 o 24)"
        )
    
    # Verificar si ya existe
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    
    if config:
        # Guardar estado anterior en historial si hay cambios importantes
        if config.turnos_base != config_data.turnos_base or config.validado != config_data.validado:
            historial_entry = {
                "fecha": datetime.now().isoformat(),
                "usuario_id": str(current_user.id),
                "usuario_nombre": current_user.nombre,
                "turnos_base_anterior": config.turnos_base,
                "turnos_base_nuevo": config_data.turnos_base,
                "validado_anterior": config.validado,
                "validado_nuevo": config_data.validado
            }
            
            if not config.historial:
                config.historial = []
            config.historial.append(historial_entry)
        
        # Actualizar existente
        for key, value in config_data.dict(exclude_unset=True).items():
            setattr(config, key, value)
        config.actualizado_en = datetime.now()
        
        print(f"✅ Configuración actualizada para {año}/{mes}")
    else:
        # Crear nuevo
        config = ConfiguracionMensual(
            año=año,
            mes=mes,
            turnos_base=config_data.turnos_base,
            motivo=config_data.motivo,
            observacion=config_data.observacion,
            validado=config_data.validado,
            creado_en=datetime.now()
        )
        db.add(config)
        print(f"✅ Nueva configuración creada para {año}/{mes}")
    
    db.commit()
    db.refresh(config)
    
    return config


# ✅ POST específico para validar (CORREGIDO)
@router.post("/validar/{año}/{mes}", response_model=ConfiguracionMensualResponse)
def validar_configuracion_mes(
    año: int,
    mes: int,
    validar_data: ConfiguracionMensualValidar,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin_user)
):
    """
    Validar la configuración de un mes (solo admin)
    """
    print(f"🔵 VALIDAR ENDPOINT ALCANZADO: {año}/{mes}")
    print(f"📦 Datos: turnos_base={validar_data.turnos_base}")
    
    # Validar que si no es 25, tenga motivo
    if validar_data.turnos_base != 25 and not validar_data.motivo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Debes proporcionar un motivo al cambiar el número de turnos (23 o 24)"
        )
    
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    
    if not config:
        # Crear si no existe
        config = ConfiguracionMensual(
            año=año,
            mes=mes,
            turnos_base=validar_data.turnos_base,
            motivo=validar_data.motivo,
            observacion=validar_data.observacion,
            validado=True,
            fecha_validacion=datetime.now(),
            validado_por=current_user.id,
            creado_en=datetime.now()
        )
        db.add(config)
        print(f"✅ Nueva configuración creada y validada para {año}/{mes}")
    else:
        # Guardar estado anterior en historial
        historial_entry = {
            "fecha": datetime.now().isoformat(),
            "usuario_id": str(current_user.id),
            "usuario_nombre": current_user.nombre,
            "turnos_base_anterior": config.turnos_base,
            "turnos_base_nuevo": validar_data.turnos_base,
            "validado_anterior": config.validado,
            "validado_nuevo": True,
            "motivo_anterior": config.motivo,
            "motivo_nuevo": validar_data.motivo
        }
        
        if not config.historial:
            config.historial = []
        
        config.historial.append(historial_entry)
        
        # Actualizar
        config.turnos_base = validar_data.turnos_base
        config.motivo = validar_data.motivo
        config.observacion = validar_data.observacion
        config.validado = True
        config.fecha_validacion = datetime.now()
        config.validado_por = current_user.id
        config.actualizado_en = datetime.now()
        
        print(f"✅ Configuración existente validada para {año}/{mes}")
    
    db.commit()
    db.refresh(config)
    
    return config


# ✅ PUT para actualizar
@router.put("/{año}/{mes}", response_model=ConfiguracionMensualResponse)
def actualizar_configuracion(
    año: int,
    mes: int,
    config_data: ConfiguracionMensualUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin_user)
):
    """
    Actualizar configuración existente (solo admin)
    """
    print(f"🔵 PUT ENDPOINT ALCANZADO: {año}/{mes}")
    
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuración no encontrada"
        )
    
    # Guardar en historial si hay cambios importantes
    cambios = config_data.dict(exclude_unset=True)
    if cambios:
        historial_entry = {
            "fecha": datetime.now().isoformat(),
            "usuario_id": str(current_user.id),
            "usuario_nombre": current_user.nombre,
            "cambios": cambios
        }
        
        if not config.historial:
            config.historial = []
        config.historial.append(historial_entry)
    
    # Aplicar cambios
    for key, value in cambios.items():
        setattr(config, key, value)
    
    config.actualizado_en = datetime.now()
    db.commit()
    db.refresh(config)
    
    print(f"✅ Configuración actualizada para {año}/{mes}")
    return config


# ✅ DELETE para eliminar
@router.delete("/{año}/{mes}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_configuracion(
    año: int,
    mes: int,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin_user)
):
    """
    Eliminar configuración de un mes (solo admin)
    """
    print(f"🔵 DELETE ENDPOINT ALCANZADO: {año}/{mes}")
    
    config = db.query(ConfiguracionMensual).filter(
        ConfiguracionMensual.año == año,
        ConfiguracionMensual.mes == mes
    ).first()
    
    if not config:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Configuración no encontrada"
        )
    
    db.delete(config)
    db.commit()
    
    print(f"✅ Configuración eliminada para {año}/{mes}")
    return None


# ✅ POST para múltiples configuraciones
@router.post("/multiple", response_model=List[ConfiguracionMensualResponse])
def crear_multiple_configuraciones(
    configs: List[ConfiguracionMensualCreate],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_admin_user)
):
    """
    Crear múltiples configuraciones a la vez (solo admin)
    """
    print(f"🔵 MULTIPLE ENDPOINT ALCANZADO: {len(configs)} configuraciones")
    
    resultados = []
    
    for config_data in configs:
        # Validar que si no es 25, tenga motivo
        if config_data.turnos_base != 25 and not config_data.motivo:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Mes {config_data.mes}/{config_data.año}: Debes proporcionar un motivo al cambiar el número de turnos"
            )
        
        # Verificar si ya existe
        existente = db.query(ConfiguracionMensual).filter(
            ConfiguracionMensual.año == config_data.año,
            ConfiguracionMensual.mes == config_data.mes
        ).first()
        
        if existente:
            # Guardar en historial
            historial_entry = {
                "fecha": datetime.now().isoformat(),
                "usuario_id": str(current_user.id),
                "usuario_nombre": current_user.nombre,
                "accion": "actualizacion_multiple",
                "cambios": config_data.dict()
            }
            
            if not existente.historial:
                existente.historial = []
            existente.historial.append(historial_entry)
            
            # Actualizar
            for key, value in config_data.dict(exclude_unset=True).items():
                setattr(existente, key, value)
            existente.actualizado_en = datetime.now()
            resultados.append(existente)
            print(f"  ↪ Actualizada: {config_data.año}/{config_data.mes}")
        else:
            # Crear nuevo
            nueva = ConfiguracionMensual(
                año=config_data.año,
                mes=config_data.mes,
                turnos_base=config_data.turnos_base,
                motivo=config_data.motivo,
                observacion=config_data.observacion,
                validado=config_data.validado,
                creado_en=datetime.now()
            )
            db.add(nueva)
            resultados.append(nueva)
            print(f"  ✅ Creada: {config_data.año}/{config_data.mes}")
    
    db.commit()
    
    # Refrescar todos
    for r in resultados:
        db.refresh(r)
    
    print(f"✅ {len(resultados)} configuraciones procesadas exitosamente")
    return resultados


# =====================================================
# 🧪 ENDPOINTS DE PRUEBA (SIN DEPENDENCIAS)
# =====================================================

@router.get("/ping")
async def ping():
    """Endpoint de prueba ultra simple sin dependencias"""
    print("🔵🔵🔵 PING ENDPOINT ALCANZADO")
    return {
        "message": "pong",
        "timestamp": datetime.now().isoformat(),
        "status": "ok"
    }

@router.get("/test-simple")
def test_simple():
    """Endpoint de prueba ultra simple"""
    print("🔵🔵🔵 TEST SIMPLE ALCANZADO")
    return {
        "message": "Funciona!",
        "timestamp": str(datetime.now()),
        "router_prefix": router.prefix
    }

@router.get("/test-db")
def test_db(db: Session = Depends(get_db)):
    """Endpoint de prueba con base de datos"""
    print("🔵🔵🔵 TEST DB ALCANZADO")
    try:
        from sqlalchemy import text
        result = db.execute(text("SELECT 1")).scalar()
        return {
            "message": "DB conectada",
            "result": result,
            "timestamp": str(datetime.now())
        }
    except Exception as e:
        return {
            "error": str(e),
            "timestamp": str(datetime.now())
        }

@router.get("/test-user")
def test_user(current_user: Usuario = Depends(get_current_user)):
    """Endpoint de prueba con usuario"""
    print("🔵🔵🔵 TEST USER ALCANZADO")
    if current_user:
        return {
            "message": "Usuario autenticado",
            "email": current_user.email,
            "roles": current_user.roles,
            "id": str(current_user.id)
        }
    else:
        return {
            "message": "No hay usuario autenticado"
        }

# =====================================================
# 🚨 ENDPOINT DE DIAGNÓSTICO COMPLETO
# =====================================================
@router.get("/debug-endpoint")
def debug_endpoint(db: Session = Depends(get_db)):
    """Endpoint de diagnóstico completo"""
    from sqlalchemy import inspect, text
    import sys
    import traceback
    
    resultado = {
        "timestamp": datetime.now().isoformat(),
        "estado": "iniciando",
        "pasos": []
    }
    
    # 1. Verificar conexión DB
    try:
        db.execute(text("SELECT 1")).scalar()
        resultado["pasos"].append({"paso": "db_connection", "ok": True})
    except Exception as e:
        resultado["pasos"].append({"paso": "db_connection", "ok": False, "error": str(e)})
        return resultado
    
    # 2. Verificar tablas
    try:
        inspector = inspect(db.bind)
        tables = inspector.get_table_names()
        resultado["pasos"].append({
            "paso": "list_tables", 
            "ok": True, 
            "tablas": tables,
            "config_table_exists": 'configuraciones_mensuales' in tables
        })
    except Exception as e:
        resultado["pasos"].append({"paso": "list_tables", "ok": False, "error": str(e)})
    
    # 3. Verificar modelo
    try:
        from app.models.configuracion_mensual import ConfiguracionMensual
        resultado["pasos"].append({"paso": "model_import", "ok": True})
    except Exception as e:
        resultado["pasos"].append({"paso": "model_import", "ok": False, "error": str(e), "traceback": traceback.format_exc()})
    
    # 4. Verificar que la tabla existe con SQL directo
    try:
        result = db.execute(
            text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = 'configuraciones_mensuales')")
        ).scalar()
        resultado["pasos"].append({"paso": "table_exists_check", "ok": True, "existe": result})
    except Exception as e:
        resultado["pasos"].append({"paso": "table_exists_check", "ok": False, "error": str(e)})
    
    # 5. Intentar consulta SQL directa
    try:
        resultado_sql = db.execute(
            text("SELECT COUNT(*) FROM configuraciones_mensuales")
        ).scalar()
        resultado["pasos"].append({
            "paso": "sql_direct_count", 
            "ok": True, 
            "count": resultado_sql
        })
    except Exception as e:
        resultado["pasos"].append({"paso": "sql_direct_count", "ok": False, "error": str(e)})
    
    # 6. Intentar consulta con modelo
    try:
        from app.models.configuracion_mensual import ConfiguracionMensual
        configs = db.query(ConfiguracionMensual).limit(5).all()
        resultado["pasos"].append({
            "paso": "model_query", 
            "ok": True, 
            "count": len(configs),
            "sample": [{"año": c.año, "mes": c.mes, "turnos": c.turnos_base} for c in configs[:3]]
        })
    except Exception as e:
        resultado["pasos"].append({"paso": "model_query", "ok": False, "error": str(e), "traceback": traceback.format_exc()})
    
    resultado["estado"] = "completado"
    return resultado

# =====================================================
# 🚨 DIAGNÓSTICO FINAL DE CARGA
# =====================================================
print(f"📊 Rutas definidas después de cargar todos los endpoints: {len(router.routes)}")
print("📋 Lista de rutas registradas:")
for i, route in enumerate(router.routes):
    methods = list(route.methods) if hasattr(route, 'methods') else []
    print(f"   {i+1}. {route.path} [{', '.join(methods)}]")
print("="*60)