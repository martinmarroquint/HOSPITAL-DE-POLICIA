# app/api/trazabilidad.py
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
import logging
from datetime import datetime

from app.database import get_db
from app.core.dependencies import get_current_active_user, require_roles
from app.models.usuario import Usuario
from app.models.solicitud import Solicitud
from app.models.personal import Personal
from app.models.trazabilidad import Trazabilidad
from app.services.trazabilidad_service import get_trazabilidad_service, TrazabilidadService
from app.services.qr_service import get_qr_service
from app.schemas.trazabilidad import (
    TrazabilidadResponse,
    CadenaTrazabilidadResponse,
    VerificacionIntegridadResponse,
    ValidacionQRRequest,
    ValidacionQRResponse,
    CertificadoResponse,
    NodoTrazabilidad
)

# Configurar logger
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trazabilidad", tags=["Trazabilidad"])

# =====================================================
# DEPENDENCIAS
# =====================================================
def get_services(db: Session = Depends(get_db)):
    return {
        "trazabilidad": get_trazabilidad_service(db),
        "qr": get_qr_service(db)
    }

# =====================================================
# ENDPOINTS DE CADENA DE TRAZABILIDAD
# =====================================================

@router.get("/cadena/{solicitud_id}", response_model=CadenaTrazabilidadResponse)
async def obtener_cadena_trazabilidad(
    solicitud_id: UUID,
    services: dict = Depends(get_services),
    usuario_actual: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Obtiene la cadena completa de trazabilidad de una solicitud
    Incluye todos los eventos en orden cronológico con sus hashes
    """
    try:
        # Verificar que la solicitud existe
        solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        # Verificar permisos (solo admin o involucrados)
        if "admin" not in usuario_actual.roles:
            if solicitud.empleado_id != usuario_actual.personal_id:
                # Verificar si es jefe del área
                personal_solicitante = db.query(Personal).filter(Personal.id == solicitud.empleado_id).first()
                personal_usuario = db.query(Personal).filter(Personal.id == usuario_actual.personal_id).first()
                
                if not personal_solicitante or not personal_usuario or \
                   personal_solicitante.area != personal_usuario.area:
                    raise HTTPException(status_code=403, detail="No autorizado para ver esta trazabilidad")
        
        # Obtener registros
        registros = services["trazabilidad"].obtener_cadena(solicitud_id)
        
        if not registros:
            return CadenaTrazabilidadResponse(
                solicitud_id=solicitud_id,
                solicitud_tipo=solicitud.tipo.value if hasattr(solicitud.tipo, 'value') else str(solicitud.tipo),
                solicitud_estado=solicitud.estado.value if hasattr(solicitud.estado, 'value') else str(solicitud.estado),
                nodos=[],
                integridad_verificada=None,
                primer_hash="",
                ultimo_hash=""
            )
        
        # Convertir a nodos
        nodos = []
        for r in registros:
            usuario_nombre = None
            
            # Obtener nombre del usuario que realizó la acción
            if r.usuario_rel:
                # Buscar el personal asociado al usuario
                personal = db.query(Personal).filter(Personal.id == r.usuario_rel.personal_id).first()
                if personal:
                    usuario_nombre = personal.nombre
                else:
                    usuario_nombre = r.usuario_rel.email
            else:
                usuario_nombre = "Sistema"
            
            # Procesar datos resumen
            datos_resumen = {}
            if r.datos:
                if isinstance(r.datos, dict):
                    datos_resumen = r.datos
                elif hasattr(r.datos, '__dict__'):
                    datos_resumen = r.datos.__dict__
            
            nodos.append(NodoTrazabilidad(
                id=r.id,
                accion=r.accion.value if hasattr(r.accion, 'value') else str(r.accion),
                usuario_nombre=usuario_nombre,
                created_at=r.created_at,
                hash_actual=r.hash_actual,
                hash_anterior=r.hash_anterior,
                comentario=r.comentario,
                datos_resumen=datos_resumen
            ))
        
        # Obtener primer y último hash
        primer_hash = registros[0].hash_actual if registros else ""
        ultimo_hash = registros[-1].hash_actual if registros else ""
        
        return CadenaTrazabilidadResponse(
            solicitud_id=solicitud_id,
            solicitud_tipo=solicitud.tipo.value if hasattr(solicitud.tipo, 'value') else str(solicitud.tipo),
            solicitud_estado=solicitud.estado.value if hasattr(solicitud.estado, 'value') else str(solicitud.estado),
            nodos=nodos,
            integridad_verificada=None,  # Se verifica aparte
            primer_hash=primer_hash,
            ultimo_hash=ultimo_hash
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en obtener_cadena_trazabilidad: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al obtener cadena de trazabilidad: {str(e)}")


@router.get("/verificar/{solicitud_id}", response_model=VerificacionIntegridadResponse)
async def verificar_integridad(
    solicitud_id: UUID,
    services: dict = Depends(get_services),
    usuario_actual: Usuario = Depends(require_roles(["admin"]))  # Solo admin puede verificar
):
    """
    Verifica la integridad de toda la cadena de trazabilidad
    Recalcula todos los hashes y compara con los guardados
    """
    try:
        verificacion = services["trazabilidad"].verificar_integridad(solicitud_id)
        
        # Convertir a diccionario si es necesario
        if isinstance(verificacion, dict):
            return VerificacionIntegridadResponse(**verificacion)
        
        return verificacion
        
    except Exception as e:
        logger.error(f"Error en verificar_integridad: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al verificar integridad: {str(e)}")


@router.get("/certificado/{solicitud_id}", response_model=CertificadoResponse)
async def generar_certificado(
    solicitud_id: UUID,
    incluir_trazabilidad: bool = Query(True, description="Incluir cadena de trazabilidad"),
    incluir_qr: bool = Query(True, description="Incluir código QR"),
    services: dict = Depends(get_services),
    usuario_actual: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Genera un certificado PDF con la cadena de trazabilidad
    """
    try:
        # Verificar solicitud
        solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        # Verificar permisos
        if "admin" not in usuario_actual.roles:
            if solicitud.empleado_id != usuario_actual.personal_id:
                # Verificar si es jefe del área
                personal_solicitante = db.query(Personal).filter(Personal.id == solicitud.empleado_id).first()
                personal_usuario = db.query(Personal).filter(Personal.id == usuario_actual.personal_id).first()
                
                if not personal_solicitante or not personal_usuario or \
                   personal_solicitante.area != personal_usuario.area:
                    raise HTTPException(status_code=403, detail="No autorizado para generar certificado")
        
        # Aquí iría la lógica de generación de PDF
        # Por ahora, respuesta simulada
        url_pdf = f"/static/certificados/{solicitud_id}.pdf"
        
        # Registrar en trazabilidad
        services["trazabilidad"].registrar_evento(
            solicitud_id=solicitud_id,
            usuario_id=usuario_actual.id,
            accion="CERTIFICADO_GENERADO",
            comentario="Se generó certificado de trazabilidad",
            datos={
                "incluir_trazabilidad": incluir_trazabilidad,
                "incluir_qr": incluir_qr
            }
        )
        
        return CertificadoResponse(
            solicitud_id=solicitud_id,
            url_pdf=url_pdf,
            fecha_generacion=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en generar_certificado: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al generar certificado: {str(e)}")


# =====================================================
# ENDPOINTS DE VALIDACIÓN QR
# =====================================================

@router.post("/validar", response_model=ValidacionQRResponse)
async def validar_por_qr(
    request: ValidacionQRRequest,
    services: dict = Depends(get_services),
    usuario_actual: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Valida un código QR de trámite
    El QR puede ser escaneado desde la app o desde una impresión
    """
    try:
        resultado = services["trazabilidad"].validar_por_qr(request.qr_data)
        
        # Si es válido, registrar en trazabilidad
        if resultado.get("valido") and resultado.get("solicitud_id"):
            services["trazabilidad"].registrar_validacion_qr(
                solicitud_id=resultado["solicitud_id"],
                usuario_id=usuario_actual.id,
                resultado=True
            )
        
        return ValidacionQRResponse(
            valido=resultado.get("valido", False),
            solicitud_id=resultado.get("solicitud_id"),
            mensaje=resultado.get("mensaje", "Error en validación"),
            datos_solicitud=resultado.get("solicitud"),
            verificado_en=datetime.now()
        )
        
    except Exception as e:
        logger.error(f"Error en validar_por_qr: {e}", exc_info=True)
        return ValidacionQRResponse(
            valido=False,
            mensaje=f"Error interno: {str(e)}",
            verificado_en=datetime.now()
        )


@router.post("/validar/asistencia")
async def validar_qr_asistencia(
    request: ValidacionQRRequest,
    services: dict = Depends(get_services),
    usuario_actual: Usuario = Depends(get_current_active_user)
):
    """
    Valida un código QR de asistencia (marcación de entrada/salida)
    """
    try:
        resultado = services["qr"].validar_qr(request.qr_data)
        return resultado
    except Exception as e:
        logger.error(f"Error en validar_qr_asistencia: {e}", exc_info=True)
        return {
            "valido": False,
            "mensaje": f"Error interno: {str(e)}"
        }


# =====================================================
# ENDPOINTS DE CONSULTA
# =====================================================

@router.get("/solicitud/{solicitud_id}/resumen")
async def resumen_trazabilidad(
    solicitud_id: UUID,
    services: dict = Depends(get_services),
    usuario_actual: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Obtiene un resumen estadístico de la trazabilidad
    """
    try:
        # Verificar que la solicitud existe
        solicitud = db.query(Solicitud).filter(Solicitud.id == solicitud_id).first()
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        # Verificar permisos
        if "admin" not in usuario_actual.roles:
            if solicitud.empleado_id != usuario_actual.personal_id:
                personal_solicitante = db.query(Personal).filter(Personal.id == solicitud.empleado_id).first()
                personal_usuario = db.query(Personal).filter(Personal.id == usuario_actual.personal_id).first()
                
                if not personal_solicitante or not personal_usuario or \
                   personal_solicitante.area != personal_usuario.area:
                    raise HTTPException(status_code=403, detail="No autorizado para ver resumen")
        
        registros = services["trazabilidad"].obtener_cadena(solicitud_id)
        
        if not registros:
            return {
                "solicitud_id": str(solicitud_id),
                "total_acciones": 0,
                "mensaje": "Sin registros de trazabilidad"
            }
        
        # Agrupar por acción
        acciones = {}
        for r in registros:
            accion = r.accion.value if hasattr(r.accion, 'value') else str(r.accion)
            if accion not in acciones:
                acciones[accion] = 0
            acciones[accion] += 1
        
        # Calcular tiempos
        primera = registros[0].created_at
        ultima = registros[-1].created_at
        tiempo_total = (ultima - primera).total_seconds() / 3600  # horas
        
        return {
            "solicitud_id": str(solicitud_id),
            "total_acciones": len(registros),
            "acciones_por_tipo": acciones,
            "primera_accion": primera.isoformat(),
            "ultima_accion": ultima.isoformat(),
            "tiempo_total_horas": round(tiempo_total, 2),
            "hash_inicial": registros[0].hash_actual,
            "hash_final": registros[-1].hash_actual
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en resumen_trazabilidad: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al obtener resumen: {str(e)}")


@router.get("/usuario/{usuario_id}/actividad")
async def actividad_usuario(
    usuario_id: UUID,
    fecha_desde: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500, description="Límite de registros"),
    services: dict = Depends(get_services),
    usuario_actual: Usuario = Depends(require_roles(["admin"])),  # Solo admin
    db: Session = Depends(get_db)
):
    """
    Obtiene la actividad de trazabilidad de un usuario específico
    Solo para administradores
    """
    try:
        from datetime import datetime
        
        query = db.query(Trazabilidad).filter(Trazabilidad.usuario_id == usuario_id)
        
        if fecha_desde:
            try:
                fecha_desde_dt = datetime.fromisoformat(fecha_desde)
                query = query.filter(Trazabilidad.created_at >= fecha_desde_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de fecha_desde inválido. Use YYYY-MM-DD")
                
        if fecha_hasta:
            try:
                fecha_hasta_dt = datetime.fromisoformat(fecha_hasta)
                query = query.filter(Trazabilidad.created_at <= fecha_hasta_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de fecha_hasta inválido. Use YYYY-MM-DD")
        
        registros = query.order_by(Trazabilidad.created_at.desc()).limit(limit).all()
        
        resultado = []
        for r in registros:
            # Obtener información de la solicitud asociada
            solicitud_info = None
            if r.solicitud_id:
                solicitud = db.query(Solicitud).filter(Solicitud.id == r.solicitud_id).first()
                if solicitud:
                    solicitud_info = {
                        "tipo": solicitud.tipo.value if hasattr(solicitud.tipo, 'value') else str(solicitud.tipo),
                        "estado": solicitud.estado.value if hasattr(solicitud.estado, 'value') else str(solicitud.estado)
                    }
            
            resultado.append({
                "id": str(r.id),
                "accion": r.accion.value if hasattr(r.accion, 'value') else str(r.accion),
                "solicitud_id": str(r.solicitud_id) if r.solicitud_id else None,
                "solicitud_info": solicitud_info,
                "created_at": r.created_at.isoformat(),
                "comentario": r.comentario,
                "ip_origen": r.ip_origen
            })
        
        return {
            "usuario_id": str(usuario_id),
            "total_encontrados": len(resultado),
            "registros": resultado
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en actividad_usuario: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al obtener actividad: {str(e)}")


# =====================================================
# ENDPOINTS DE ESTADÍSTICAS
# =====================================================

@router.get("/estadisticas/generales")
async def estadisticas_generales(
    fecha_desde: Optional[str] = Query(None, description="Fecha desde (YYYY-MM-DD)"),
    fecha_hasta: Optional[str] = Query(None, description="Fecha hasta (YYYY-MM-DD)"),
    usuario_actual: Usuario = Depends(require_roles(["admin"])),  # Solo admin
    db: Session = Depends(get_db)
):
    """
    Obtiene estadísticas generales de trazabilidad
    Solo para administradores
    """
    try:
        from datetime import datetime, timedelta
        
        query = db.query(Trazabilidad)
        
        if fecha_desde:
            try:
                fecha_desde_dt = datetime.fromisoformat(fecha_desde)
                query = query.filter(Trazabilidad.created_at >= fecha_desde_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de fecha_desde inválido")
                
        if fecha_hasta:
            try:
                fecha_hasta_dt = datetime.fromisoformat(fecha_hasta)
                query = query.filter(Trazabilidad.created_at <= fecha_hasta_dt)
            except ValueError:
                raise HTTPException(status_code=400, detail="Formato de fecha_hasta inválido")
        
        # Si no hay fechas, usar últimos 30 días por defecto
        if not fecha_desde and not fecha_hasta:
            fecha_hasta_dt = datetime.now()
            fecha_desde_dt = fecha_hasta_dt - timedelta(days=30)
            query = query.filter(Trazabilidad.created_at >= fecha_desde_dt)
        
        registros = query.all()
        
        # Estadísticas por acción
        acciones = {}
        for r in registros:
            accion = r.accion.value if hasattr(r.accion, 'value') else str(r.accion)
            if accion not in acciones:
                acciones[accion] = 0
            acciones[accion] += 1
        
        # Estadísticas por día
        dias = {}
        for r in registros:
            dia = r.created_at.strftime("%Y-%m-%d")
            if dia not in dias:
                dias[dia] = 0
            dias[dia] += 1
        
        # Usuarios más activos
        usuarios_activos = {}
        for r in registros:
            if r.usuario_id:
                usuario_key = str(r.usuario_id)
                if usuario_key not in usuarios_activos:
                    # Obtener nombre del usuario
                    usuario = db.query(Usuario).filter(Usuario.id == r.usuario_id).first()
                    if usuario:
                        personal = db.query(Personal).filter(Personal.id == usuario.personal_id).first()
                        nombre = personal.nombre if personal else usuario.email
                    else:
                        nombre = "Usuario desconocido"
                    usuarios_activos[usuario_key] = {
                        "id": str(r.usuario_id),
                        "nombre": nombre,
                        "acciones": 0
                    }
                usuarios_activos[usuario_key]["acciones"] += 1
        
        # Ordenar usuarios por acciones
        top_usuarios = sorted(
            usuarios_activos.values(), 
            key=lambda x: x["acciones"], 
            reverse=True
        )[:10]
        
        return {
            "periodo": {
                "desde": fecha_desde or fecha_desde_dt.isoformat() if 'fecha_desde_dt' in locals() else None,
                "hasta": fecha_hasta or fecha_hasta_dt.isoformat() if 'fecha_hasta_dt' in locals() else None
            },
            "total_registros": len(registros),
            "acciones_por_tipo": acciones,
            "registros_por_dia": dias,
            "usuarios_mas_activos": top_usuarios,
            "fecha_generacion": datetime.now().isoformat()
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en estadisticas_generales: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error al obtener estadísticas: {str(e)}")