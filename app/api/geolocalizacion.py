# app/api/geolocalizacion.py

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, date, timedelta
from uuid import UUID
import math
import logging

from app.database import get_db, SessionLocal
from app.core.dependencies import require_roles, get_current_user
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.models.asistencia import Asistencia
from app.models.configuracion import ConfigUnidad
from app.models.geolocalizacion import Sede, ConfigGeolocalizacion, RegistroGeolocalizacion
from app.schemas.geolocalizacion import (
    GeolocalizacionRequest,
    GeolocalizacionResponse,
    EstadoGeolocalizacionResponse,
    SedeCreate,
    SedeUpdate,
    SedeResponse,
    ConfigGeolocalizacionUpdate
)

logger = logging.getLogger(__name__)
router = APIRouter()

# Roles permitidos
ROLES_GEOLOCALIZACION = ["admin_empresa", "jefe", "usuario", "visitante", "escaner"]
ROLES_ADMIN = ["admin_empresa", "jefe"]


# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def calcular_haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcula la distancia en metros entre dos coordenadas usando la fórmula de Haversine
    """
    R = 6371000  # Radio de la Tierra en metros
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    
    a = math.sin(dlat/2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    return round(R * c, 2)


def aplicar_filtro_empresa(query, current_user, modelo):
    """Aplica filtro por empresa si el usuario no es super_admin"""
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if hasattr(modelo, 'empresa_id'):
            query = query.filter(modelo.empresa_id == current_user.empresa_id)
    return query


# =====================================================
# CONFIGURACIÓN DE GEOLOCALIZACIÓN
# =====================================================

@router.get("/config/geolocalizacion")
async def obtener_config_geolocalizacion(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_GEOLOCALIZACION))
):
    """
    Obtiene la configuración de geolocalización de la empresa del usuario
    """
    try:
        if not current_user.empresa_id:
            return {
                "activo": False,
                "radio_tolerancia_default": 50,
                "precision_minima": 100,
                "exigir_alta_precision": False,
                "permitir_sin_gps": False,
                "mostrar_distancia": True
            }
        
        config = db.query(ConfigGeolocalizacion).filter(
            ConfigGeolocalizacion.empresa_id == current_user.empresa_id
        ).first()
        
        if not config:
            config = ConfigGeolocalizacion(
                empresa_id=current_user.empresa_id,
                activo=False,
                radio_tolerancia_default=50,
                precision_minima=100
            )
            db.add(config)
            db.commit()
            db.refresh(config)
        
        return {
            "id": str(config.id),
            "activo": config.activo,
            "radio_tolerancia_default": config.radio_tolerancia_default,
            "precision_minima": config.precision_minima,
            "exigir_alta_precision": config.exigir_alta_precision,
            "permitir_sin_gps": config.permitir_sin_gps,
            "mostrar_distancia": config.mostrar_distancia
        }
        
    except Exception as e:
        logger.error(f"Error en obtener_config_geolocalizacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener configuración: {str(e)}")


@router.put("/config/geolocalizacion")
async def actualizar_config_geolocalizacion(
    data: ConfigGeolocalizacionUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_ADMIN))
):
    """
    Actualiza la configuración de geolocalización (solo admin/jefe)
    """
    try:
        if not current_user.empresa_id:
            raise HTTPException(status_code=400, detail="Usuario sin empresa asignada")
        
        config = db.query(ConfigGeolocalizacion).filter(
            ConfigGeolocalizacion.empresa_id == current_user.empresa_id
        ).first()
        
        if not config:
            config = ConfigGeolocalizacion(empresa_id=current_user.empresa_id)
            db.add(config)
        
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(config, key, value)
        
        db.commit()
        db.refresh(config)
        
        return {
            "success": True,
            "message": "Configuración actualizada correctamente",
            "config": {
                "activo": config.activo,
                "radio_tolerancia_default": config.radio_tolerancia_default,
                "precision_minima": config.precision_minima
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en actualizar_config_geolocalizacion: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar configuración: {str(e)}")


# =====================================================
# GESTIÓN DE SEDES
# =====================================================

@router.get("/sedes", response_model=List[SedeResponse])
async def obtener_sedes(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_GEOLOCALIZACION))
):
    """
    Obtiene todas las sedes autorizadas de la empresa
    """
    try:
        query = db.query(Sede).filter(Sede.activo == True)
        query = aplicar_filtro_empresa(query, current_user, Sede)
        sedes = query.all()
        
        return [
            {
                "id": str(s.id),
                "nombre": s.nombre,
                "descripcion": s.descripcion,
                "latitud": s.latitud,
                "longitud": s.longitud,
                "radio_permitido": s.radio_permitido,
                "activo": s.activo
            }
            for s in sedes
        ]
        
    except Exception as e:
        logger.error(f"Error en obtener_sedes: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener sedes: {str(e)}")


@router.post("/sedes")
async def crear_sede(
    data: SedeCreate,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_ADMIN))
):
    """
    Crea una nueva sede autorizada
    """
    try:
        if not current_user.empresa_id:
            raise HTTPException(status_code=400, detail="Usuario sin empresa asignada")
        
        sede = Sede(
            empresa_id=current_user.empresa_id,
            nombre=data.nombre,
            descripcion=data.descripcion,
            latitud=data.latitud,
            longitud=data.longitud,
            radio_permitido=data.radio_permitido
        )
        db.add(sede)
        db.commit()
        db.refresh(sede)
        
        return {
            "success": True,
            "message": "Sede creada correctamente",
            "sede": {
                "id": str(sede.id),
                "nombre": sede.nombre,
                "latitud": sede.latitud,
                "longitud": sede.longitud,
                "radio_permitido": sede.radio_permitido
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en crear_sede: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al crear sede: {str(e)}")


@router.put("/sedes/{sede_id}")
async def actualizar_sede(
    sede_id: UUID,
    data: SedeUpdate,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_ADMIN))
):
    """
    Actualiza una sede existente
    """
    try:
        sede = db.query(Sede).filter(Sede.id == sede_id).first()
        if not sede:
            raise HTTPException(status_code=404, detail="Sede no encontrada")
        
        update_data = data.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(sede, key, value)
        
        db.commit()
        db.refresh(sede)
        
        return {
            "success": True,
            "message": "Sede actualizada correctamente"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en actualizar_sede: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al actualizar sede: {str(e)}")


@router.delete("/sedes/{sede_id}")
async def eliminar_sede(
    sede_id: UUID,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_ADMIN))
):
    """
    Desactiva una sede (soft delete)
    """
    try:
        sede = db.query(Sede).filter(Sede.id == sede_id).first()
        if not sede:
            raise HTTPException(status_code=404, detail="Sede no encontrada")
        
        sede.activo = False
        db.commit()
        
        return {
            "success": True,
            "message": "Sede desactivada correctamente"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en eliminar_sede: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al eliminar sede: {str(e)}")


# =====================================================
# REGISTRO DE ASISTENCIA POR GEOLOCALIZACIÓN
# =====================================================

@router.post("/asistencia/geolocalizacion", response_model=GeolocalizacionResponse)
async def registrar_por_geolocalizacion(
    request: Request,
    data: GeolocalizacionRequest,
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_GEOLOCALIZACION))
):
    """
    Registra asistencia validando coordenadas GPS.
    Verifica que el usuario esté dentro del radio de la sede asignada a su área.
    """
    try:
        # Verificar que el usuario tenga personal asociado
        if not current_user.personal_id:
            raise HTTPException(status_code=400, detail="Usuario sin personal asociado")
        
        personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if not personal:
            raise HTTPException(status_code=404, detail="Personal no encontrado")
        
        # Obtener configuración
        config = db.query(ConfigGeolocalizacion).filter(
            ConfigGeolocalizacion.empresa_id == current_user.empresa_id
        ).first()
        
        if config and not config.activo:
            raise HTTPException(status_code=400, detail="Geolocalización no está activa para esta empresa")
        
        # Validar precisión del GPS
        precision_maxima = config.precision_minima if config else 100
        if data.precision and data.precision > precision_maxima:
            return GeolocalizacionResponse(
                success=False,
                mensaje=f"Precisión GPS insuficiente ({data.precision:.0f}m). Máxima aceptable: {precision_maxima}m"
            )
        
        # 🆕 Validar que el área del usuario tenga una sede asignada
        sede_asignada = None
        if personal.area:
            unidad_usuario = db.query(ConfigUnidad).filter(
                ConfigUnidad.nombre == personal.area,
                ConfigUnidad.activo == True,
                ConfigUnidad.empresa_id == current_user.empresa_id
            ).first()
            
            if unidad_usuario and unidad_usuario.sede_id:
                sede_asignada = db.query(Sede).filter(
                    Sede.id == unidad_usuario.sede_id,
                    Sede.activo == True
                ).first()
                
                if not sede_asignada:
                    return GeolocalizacionResponse(
                        success=False,
                        mensaje="La sede asignada a su área no está activa. Contacte al administrador."
                    )
            elif unidad_usuario and not unidad_usuario.sede_id:
                return GeolocalizacionResponse(
                    success=False,
                    mensaje="Su área no tiene una sede asignada para geolocalización. Contacte al administrador."
                )
        
        # Buscar sedes activas
        sedes = db.query(Sede).filter(
            Sede.activo == True,
            Sede.empresa_id == current_user.empresa_id
        ).all() if current_user.empresa_id else []
        
        if not sedes:
            return GeolocalizacionResponse(
                success=False,
                mensaje="No hay sedes configuradas para esta empresa."
            )
        
        # Encontrar la sede más cercana
        sede_cercana = None
        distancia_minima = float('inf')
        
        for sede in sedes:
            distancia = calcular_haversine(
                data.latitud, data.longitud,
                sede.latitud, sede.longitud
            )
            if distancia < distancia_minima:
                distancia_minima = distancia
                sede_cercana = sede
        
        # 🆕 Validar que la sede detectada coincida con la sede asignada al área
        if sede_asignada and sede_cercana:
            if str(sede_asignada.id) != str(sede_cercana.id):
                return GeolocalizacionResponse(
                    success=False,
                    distancia=distancia_minima,
                    dentro_del_radio=False,
                    sede_nombre=sede_cercana.nombre,
                    mensaje=f"No puede registrar en '{sede_cercana.nombre}'. Su área pertenece a '{sede_asignada.nombre}'."
                )
        
        # Validar distancia
        radio_maximo = sede_cercana.radio_permitido if sede_cercana else (config.radio_tolerancia_default if config else 50)
        dentro_del_radio = distancia_minima <= radio_maximo if sede_cercana else True
        
        if not dentro_del_radio:
            return GeolocalizacionResponse(
                success=False,
                distancia=distancia_minima,
                dentro_del_radio=False,
                sede_nombre=sede_cercana.nombre if sede_cercana else None,
                mensaje=f"Fuera del área permitida. Distancia: {distancia_minima:.0f}m. Máximo: {radio_maximo}m"
            )
        
        # Determinar tipo de registro (ENTRADA o SALIDA)
        ahora = datetime.utcnow()
        hoy = ahora.date()
        inicio_dia = datetime.combine(hoy, datetime.min.time())
        
        ultimo = db.query(Asistencia).filter(
            Asistencia.personal_id == current_user.personal_id,
            Asistencia.timestamp >= inicio_dia
        ).order_by(Asistencia.timestamp.desc()).first()
        
        tipo = "SALIDA" if (ultimo and ultimo.tipo == "ENTRADA") else "ENTRADA"
        
        # Crear registro de asistencia
        asistencia = Asistencia(
            personal_id=current_user.personal_id,
            timestamp=ahora,
            tipo=tipo,
            tipo_registro="GEOLOCALIZACION",
            created_by=current_user.id,
            empresa_id=current_user.empresa_id
        )
        db.add(asistencia)
        db.flush()
        
        # Obtener IP del cliente
        ip_origen = request.client.host if request.client else None
        
        # Crear registro de geolocalización
        registro_geo = RegistroGeolocalizacion(
            asistencia_id=asistencia.id,
            usuario_id=current_user.id,
            sede_id=sede_cercana.id if sede_cercana else None,
            latitud=data.latitud,
            longitud=data.longitud,
            precision_gps=data.precision,
            distancia_calculada=distancia_minima if sede_cercana else 0,
            dentro_del_radio=dentro_del_radio,
            ip_origen=ip_origen,
            navegador=data.navegador,
            dispositivo=data.dispositivo
        )
        db.add(registro_geo)
        
        db.commit()
        db.refresh(asistencia)
        
        logger.info(f"Registro por geolocalización: {personal.nombre} - {tipo} - Distancia: {distancia_minima:.0f}m - Sede: {sede_cercana.nombre if sede_cercana else 'N/A'}")
        
        return GeolocalizacionResponse(
            success=True,
            registro={
                "id": str(asistencia.id),
                "tipo": tipo,
                "timestamp": asistencia.timestamp.isoformat(),
                "personal_nombre": personal.nombre,
                "metodo": "GEOLOCALIZACION"
            },
            distancia=distancia_minima if sede_cercana else 0,
            dentro_del_radio=dentro_del_radio,
            sede_nombre=sede_cercana.nombre if sede_cercana else None,
            mensaje=f"Asistencia {tipo} registrada correctamente en {sede_cercana.nombre if sede_cercana else 'sede'}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en registrar_por_geolocalizacion: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Error al registrar asistencia: {str(e)}")


# =====================================================
# ESTADO DE GEOLOCALIZACIÓN
# =====================================================

@router.get("/asistencia/geolocalizacion/estado", response_model=EstadoGeolocalizacionResponse)
async def obtener_estado_geolocalizacion(
    db: Session = Depends(get_db),
    current_user = Depends(require_roles(ROLES_GEOLOCALIZACION))
):
    """
    Obtiene el último estado de geolocalización del usuario
    """
    try:
        if not current_user.personal_id:
            return EstadoGeolocalizacionResponse(
                ultimo_registro=None,
                config=None
            )
        
        ultimo = db.query(Asistencia).filter(
            Asistencia.personal_id == current_user.personal_id,
            Asistencia.tipo_registro == "GEOLOCALIZACION"
        ).order_by(Asistencia.timestamp.desc()).first()
        
        ultimo_registro = None
        if ultimo:
            ultimo_registro = {
                "id": str(ultimo.id),
                "tipo": ultimo.tipo,
                "timestamp": ultimo.timestamp.isoformat(),
                "fecha": ultimo.timestamp.strftime("%Y-%m-%d"),
                "hora": ultimo.timestamp.strftime("%H:%M:%S")
            }
        
        config = None
        if current_user.empresa_id:
            config_data = db.query(ConfigGeolocalizacion).filter(
                ConfigGeolocalizacion.empresa_id == current_user.empresa_id
            ).first()
            if config_data:
                config = {
                    "activo": config_data.activo,
                    "radio_tolerancia": config_data.radio_tolerancia_default,
                    "precision_minima": config_data.precision_minima
                }
        
        return EstadoGeolocalizacionResponse(
            ultimo_registro=ultimo_registro,
            config=config
        )
        
    except Exception as e:
        logger.error(f"Error en obtener_estado_geolocalizacion: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error al obtener estado: {str(e)}")


# =====================================================
# HEALTH CHECK
# =====================================================

@router.get("/health")
async def health_check():
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
        return JSONResponse(status_code=200, content={
            "status": "healthy",
            "service": "geolocalizacion",
            "database": "connected"
        })
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "status": "unhealthy",
            "error": str(e)
        })