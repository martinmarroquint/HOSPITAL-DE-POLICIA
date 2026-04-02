# app/api/solicitudes.py
from fastapi import APIRouter, Depends, HTTPException, Query, status, Form, UploadFile, File
from sqlalchemy.orm import Session
from sqlalchemy import desc
from datetime import datetime, date
from uuid import UUID
from typing import Optional, List
import logging
import json

from app.database import get_db
from app.core.dependencies import require_roles
from app.models.solicitud import Solicitud, TipoSolicitud, EstadoSolicitud
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.utils.file_handler import save_upload_file

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Solicitudes Unificadas"])


@router.get("/ping")
async def ping():
    return {"message": "pong", "status": "ok", "timestamp": datetime.utcnow().isoformat()}


@router.get("/")
async def listar_solicitudes(
    tipo: Optional[TipoSolicitud] = Query(None, description="Filtrar por tipo de solicitud"),
    estado: Optional[EstadoSolicitud] = Query(None, description="Filtrar por estado"),
    empleado_id: Optional[UUID] = Query(None, description="Filtrar por empleado"),
    fecha_desde: Optional[date] = Query(None, description="Fecha desde"),
    fecha_hasta: Optional[date] = Query(None, description="Fecha hasta"),
    skip: int = Query(0, ge=0, description="Número de registros a saltar"),
    limit: int = Query(100, ge=1, le=500, description="Límite de registros"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Lista solicitudes con filtros opcionales
    """
    try:
        query = db.query(Solicitud)
        
        # Filtros básicos
        if tipo:
            query = query.filter(Solicitud.tipo == tipo)
        if estado:
            query = query.filter(Solicitud.estado == estado)
        
        # Filtro por empleado (con permisos)
        if empleado_id:
            if "usuario" in current_user.roles and "admin" not in current_user.roles:
                if str(current_user.personal_id) != str(empleado_id):
                    raise HTTPException(status_code=403, detail="No autorizado")
            query = query.filter(Solicitud.empleado_id == empleado_id)
        elif "usuario" in current_user.roles and "admin" not in current_user.roles:
            # Usuario normal ve solo sus solicitudes
            query = query.filter(Solicitud.empleado_id == current_user.personal_id)
        
        # Filtros de fecha
        if fecha_desde:
            query = query.filter(Solicitud.fecha_cambio >= fecha_desde)
        if fecha_hasta:
            query = query.filter(Solicitud.fecha_cambio <= fecha_hasta)
        
        # Paginación
        solicitudes = query.order_by(desc(Solicitud.created_at)).offset(skip).limit(limit).all()
        
        result = []
        for s in solicitudes:
            empleado = db.query(Personal).filter(Personal.id == s.empleado_id).first()
            result.append({
                "id": str(s.id),
                "tipo": s.tipo.value if s.tipo else None,
                "estado": s.estado.value if s.estado else None,
                "fecha_cambio": s.fecha_cambio.isoformat() if s.fecha_cambio else None,
                "fecha_solicitud": s.fecha_solicitud.isoformat() if s.fecha_solicitud else None,
                "motivo": s.motivo,
                "observaciones": s.observaciones,
                "empleado_id": str(s.empleado_id),
                "empleado_nombre": empleado.nombre if empleado else None,
                "empleado_grado": empleado.grado if empleado else None,
                "area_nombre": empleado.area if empleado else None,
                "datos": s.datos,
                "fecha_inicio": s.fecha_inicio.isoformat() if s.fecha_inicio else None,
                "fecha_fin": s.fecha_fin.isoformat() if s.fecha_fin else None,
                "dias_solicitados": s.dias_solicitados,
                "tipo_vacaciones": s.tipo_vacaciones,
                "nivel_actual": s.nivel_actual,
                "nivel_maximo": s.nivel_maximo
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error en listar_solicitudes: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/", status_code=status.HTTP_201_CREATED)
async def crear_solicitud(
    data: str = Form(...),
    archivos: List[UploadFile] = File(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "usuario"]))
):
    """
    Crea una nueva solicitud (vacaciones, permiso, etc.)
    Recibe datos en FormData con campo 'data' que contiene el JSON
    """
    try:
        # ✅ Parsear el JSON del campo 'data'
        solicitud_data = json.loads(data)
        
        logger.info(f"📥 Recibiendo solicitud: {solicitud_data.get('tipo')}")
        logger.info(f"📥 Datos recibidos: {solicitud_data}")
        
        tipo = solicitud_data.get("tipo")
        if not tipo:
            raise HTTPException(status_code=400, detail="tipo es requerido")
        
        empleado_id = solicitud_data.get("empleado_id")
        if not empleado_id:
            raise HTTPException(status_code=400, detail="empleado_id es requerido")
        
        fecha_cambio = solicitud_data.get("fecha_cambio")
        if not fecha_cambio:
            raise HTTPException(status_code=400, detail="fecha_cambio es requerido")
        
        motivo = solicitud_data.get("motivo")
        if not motivo:
            raise HTTPException(status_code=400, detail="motivo es requerido")
        
        empleado = db.query(Personal).filter(Personal.id == empleado_id).first()
        if not empleado:
            raise HTTPException(status_code=404, detail="Empleado no encontrado")
        
        # Cadena jerárquica según área
        cadenas = {
            'EMERGENCIA': ['jefe_grupo', 'jefe_area', 'jefe_departamento', 'jefe_direccion', 'oficina_central'],
            'HOSPITALIZACION': ['jefe_area', 'jefe_departamento', 'jefe_direccion', 'oficina_central'],
            'ADMINISTRACION': ['jefe_departamento', 'jefe_direccion', 'oficina_central'],
            'CIRUGIA': ['jefe_area', 'jefe_direccion', 'oficina_central'],
            'RECURSOS HUMANOS': ['jefe_area', 'oficina_central'],
            'DEFAULT': ['jefe_area', 'jefe_direccion', 'oficina_central']
        }
        
        area_upper = empleado.area.upper() if empleado.area else ''
        cadena = cadenas.get(area_upper, cadenas['DEFAULT'])
        
        # ✅ EXTRAER CAMPOS DE VACACIONES - Buscar en múltiples ubicaciones
        fecha_inicio = solicitud_data.get("fecha_inicio")
        fecha_fin = solicitud_data.get("fecha_fin")
        dias_solicitados = solicitud_data.get("dias_solicitados")
        tipo_vacaciones = solicitud_data.get("tipo_vacaciones")
        
        # También buscar dentro del campo "datos"
        if not fecha_inicio and solicitud_data.get("datos"):
            datos_extra = solicitud_data.get("datos", {})
            fecha_inicio = datos_extra.get("fecha_inicio")
            fecha_fin = datos_extra.get("fecha_fin")
            dias_solicitados = datos_extra.get("dias_solicitados")
            tipo_vacaciones = datos_extra.get("tipo_vacaciones")
        
        logger.info(f"📥 Datos de vacaciones: fecha_inicio={fecha_inicio}, fecha_fin={fecha_fin}, dias={dias_solicitados}, tipo={tipo_vacaciones}")
        
        # Convertir fechas
        fecha_inicio_date = None
        fecha_fin_date = None
        if fecha_inicio:
            try:
                fecha_inicio_date = date.fromisoformat(fecha_inicio)
            except:
                pass
        if fecha_fin:
            try:
                fecha_fin_date = date.fromisoformat(fecha_fin)
            except:
                pass
        
        # Procesar archivos si hay
        documentos = []
        if archivos:
            for archivo in archivos:
                url = await save_upload_file(archivo, subfolder="solicitudes")
                documentos.append({
                    "nombre": archivo.filename,
                    "url": url,
                    "tipo": archivo.content_type,
                    "fecha_subida": datetime.utcnow().isoformat()
                })
        
        # Crear solicitud
        nueva_solicitud = Solicitud(
            tipo=TipoSolicitud(tipo),
            estado=EstadoSolicitud.PENDIENTE,
            fecha_cambio=date.fromisoformat(fecha_cambio),
            motivo=motivo,
            observaciones=solicitud_data.get("observaciones"),
            empleado_id=empleado_id,
            documentos=documentos,
            datos=solicitud_data.get("datos", {}),
            # ✅ Campos de vacaciones
            fecha_inicio=fecha_inicio_date,
            fecha_fin=fecha_fin_date,
            dias_solicitados=dias_solicitados,
            tipo_vacaciones=tipo_vacaciones,
            nivel_actual=1,
            nivel_maximo=len(cadena) + 1,
            meta_datos={
                "cadena_jerarquica": cadena,
                "creado_por": current_user.email,
                "fecha_creacion": datetime.utcnow().isoformat()
            },
            created_by=current_user.id
        )
        
        db.add(nueva_solicitud)
        db.commit()
        db.refresh(nueva_solicitud)
        
        logger.info(f"✅ Solicitud creada: {nueva_solicitud.id} - {tipo}")
        
        return {
            "id": str(nueva_solicitud.id),
            "tipo": nueva_solicitud.tipo.value,
            "estado": nueva_solicitud.estado.value,
            "fecha_cambio": nueva_solicitud.fecha_cambio.isoformat(),
            "fecha_solicitud": nueva_solicitud.fecha_solicitud.isoformat() if nueva_solicitud.fecha_solicitud else None,
            "motivo": nueva_solicitud.motivo,
            "observaciones": nueva_solicitud.observaciones,
            "empleado_id": str(nueva_solicitud.empleado_id),
            "empleado_nombre": empleado.nombre,
            "empleado_grado": empleado.grado,
            "area_nombre": empleado.area,
            "datos": nueva_solicitud.datos,
            "fecha_inicio": nueva_solicitud.fecha_inicio.isoformat() if nueva_solicitud.fecha_inicio else None,
            "fecha_fin": nueva_solicitud.fecha_fin.isoformat() if nueva_solicitud.fecha_fin else None,
            "dias_solicitados": nueva_solicitud.dias_solicitados,
            "tipo_vacaciones": nueva_solicitud.tipo_vacaciones,
            "nivel_actual": nueva_solicitud.nivel_actual,
            "nivel_maximo": nueva_solicitud.nivel_maximo
        }
        
    except json.JSONDecodeError:
        logger.error(f"Error decodificando JSON: {data}")
        raise HTTPException(status_code=400, detail="Error en formato JSON")
    except ValueError as e:
        logger.error(f"Error de validación: {e}")
        raise HTTPException(status_code=400, detail=f"Error en formato de fecha: {e}")
    except KeyError as e:
        logger.error(f"Campo faltante: {e}")
        raise HTTPException(status_code=400, detail=f"Campo requerido faltante: {e}")
    except Exception as e:
        logger.error(f"Error creando solicitud: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/pendientes")
async def listar_pendientes_aprobacion(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "jefe_direccion", "oficina_central"]))
):
    """
    Lista solicitudes pendientes de aprobación según el rol del usuario
    """
    try:
        if "admin" in current_user.roles:
            solicitudes = db.query(Solicitud).filter(
                Solicitud.estado == EstadoSolicitud.PENDIENTE
            ).order_by(desc(Solicitud.created_at)).all()
            
            result = []
            for s in solicitudes:
                empleado = db.query(Personal).filter(Personal.id == s.empleado_id).first()
                result.append({
                    "id": str(s.id),
                    "tipo": s.tipo.value if s.tipo else None,
                    "estado": s.estado.value,
                    "fecha_cambio": s.fecha_cambio.isoformat() if s.fecha_cambio else None,
                    "fecha_solicitud": s.fecha_solicitud.isoformat() if s.fecha_solicitud else None,
                    "motivo": s.motivo,
                    "empleado_id": str(s.empleado_id),
                    "empleado_nombre": empleado.nombre if empleado else None,
                    "area_nombre": empleado.area if empleado else None,
                    "datos": s.datos,
                    "fecha_inicio": s.fecha_inicio.isoformat() if s.fecha_inicio else None,
                    "fecha_fin": s.fecha_fin.isoformat() if s.fecha_fin else None,
                    "dias_solicitados": s.dias_solicitados,
                    "tipo_vacaciones": s.tipo_vacaciones,
                    "nivel_actual": s.nivel_actual,
                    "nivel_maximo": s.nivel_maximo
                })
            return result
        
        # Obtener información del usuario
        usuario = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if not usuario:
            raise HTTPException(status_code=403, detail="Usuario no encontrado")
        
        # Obtener solicitudes según nivel
        condiciones = []
        
        if "jefe_area" in current_user.roles:
            areas_jefatura = usuario.areas_que_jefatura or []
            if areas_jefatura:
                from sqlalchemy import and_
                condiciones.append(
                    and_(
                        Solicitud.estado == EstadoSolicitud.PENDIENTE,
                        Solicitud.nivel_actual == 2,
                        Personal.area.in_(areas_jefatura)
                    )
                )
        
        if "jefe_direccion" in current_user.roles:
            from sqlalchemy import and_
            condiciones.append(
                and_(
                    Solicitud.estado == EstadoSolicitud.PENDIENTE,
                    Solicitud.nivel_actual == 3,
                    Personal.area == usuario.area_que_jefatura_direccion
                )
            )
        
        if "oficina_central" in current_user.roles:
            condiciones.append(
                Solicitud.estado == EstadoSolicitud.PENDIENTE,
                Solicitud.nivel_actual == 4
            )
        
        if not condiciones:
            return []
        
        from sqlalchemy import or_
        query = db.query(Solicitud).join(
            Personal, Personal.id == Solicitud.empleado_id
        ).filter(or_(*condiciones))
        
        solicitudes = query.order_by(desc(Solicitud.created_at)).all()
        
        result = []
        for s in solicitudes:
            empleado = db.query(Personal).filter(Personal.id == s.empleado_id).first()
            result.append({
                "id": str(s.id),
                "tipo": s.tipo.value if s.tipo else None,
                "estado": s.estado.value,
                "fecha_cambio": s.fecha_cambio.isoformat() if s.fecha_cambio else None,
                "fecha_solicitud": s.fecha_solicitud.isoformat() if s.fecha_solicitud else None,
                "motivo": s.motivo,
                "empleado_id": str(s.empleado_id),
                "empleado_nombre": empleado.nombre if empleado else None,
                "area_nombre": empleado.area if empleado else None,
                "datos": s.datos,
                "fecha_inicio": s.fecha_inicio.isoformat() if s.fecha_inicio else None,
                "fecha_fin": s.fecha_fin.isoformat() if s.fecha_fin else None,
                "dias_solicitados": s.dias_solicitados,
                "tipo_vacaciones": s.tipo_vacaciones,
                "nivel_actual": s.nivel_actual,
                "nivel_maximo": s.nivel_maximo
            })
        
        return result
        
    except Exception as e:
        logger.error(f"Error en listar_pendientes_aprobacion: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{solicitud_id}/estado")
async def actualizar_estado(
    solicitud_id: str,
    update_data: dict,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "jefe_direccion", "oficina_central"]))
):
    """
    Aprueba o rechaza una solicitud
    """
    try:
        solicitud = db.query(Solicitud).filter(Solicitud.id == UUID(solicitud_id)).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        if solicitud.estado != EstadoSolicitud.PENDIENTE:
            raise HTTPException(status_code=400, detail=f"La solicitud ya está {solicitud.estado.value}")
        
        nuevo_estado = update_data.get("estado")
        comentario = update_data.get("comentario_revision")
        
        if nuevo_estado not in ["aprobada", "rechazada"]:
            raise HTTPException(status_code=400, detail="Estado debe ser 'aprobada' o 'rechazada'")
        
        if nuevo_estado == "aprobada":
            if solicitud.nivel_actual < solicitud.nivel_maximo:
                solicitud.nivel_actual += 1
                solicitud.estado = EstadoSolicitud.PENDIENTE
                mensaje = f"Solicitud aprobada. Pendiente nivel {solicitud.nivel_actual}"
            else:
                solicitud.estado = EstadoSolicitud.APROBADA
                solicitud.fecha_aprobacion = datetime.utcnow()
                solicitud.aprobado_por = current_user.id
                mensaje = "Solicitud completamente aprobada"
        else:
            solicitud.estado = EstadoSolicitud.RECHAZADA
            mensaje = "Solicitud rechazada"
        
        solicitud.fecha_revision = datetime.utcnow()
        solicitud.revisado_por = current_user.id
        solicitud.comentario_revision = comentario
        
        db.commit()
        db.refresh(solicitud)
        
        logger.info(f"✅ Solicitud {solicitud_id} - {nuevo_estado}")
        
        return {
            "id": str(solicitud.id),
            "estado": solicitud.estado.value,
            "nivel_actual": solicitud.nivel_actual,
            "mensaje": mensaje
        }
        
    except Exception as e:
        logger.error(f"Error en actualizar_estado: {e}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{solicitud_id}")
async def obtener_solicitud(
    solicitud_id: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "usuario"]))
):
    """
    Obtiene una solicitud por ID con todos sus datos
    """
    try:
        solicitud = db.query(Solicitud).filter(Solicitud.id == UUID(solicitud_id)).first()
        
        if not solicitud:
            raise HTTPException(status_code=404, detail="Solicitud no encontrada")
        
        # Verificar permisos
        if "usuario" in current_user.roles and "admin" not in current_user.roles:
            if str(current_user.personal_id) != str(solicitud.empleado_id):
                raise HTTPException(status_code=403, detail="No autorizado")
        
        empleado = db.query(Personal).filter(Personal.id == solicitud.empleado_id).first()
        
        return {
            "id": str(solicitud.id),
            "tipo": solicitud.tipo.value if solicitud.tipo else None,
            "estado": solicitud.estado.value if solicitud.estado else None,
            "fecha_cambio": solicitud.fecha_cambio.isoformat() if solicitud.fecha_cambio else None,
            "fecha_solicitud": solicitud.fecha_solicitud.isoformat() if solicitud.fecha_solicitud else None,
            "motivo": solicitud.motivo,
            "observaciones": solicitud.observaciones,
            "empleado_id": str(solicitud.empleado_id),
            "empleado_nombre": empleado.nombre if empleado else None,
            "empleado_grado": empleado.grado if empleado else None,
            "area_nombre": empleado.area if empleado else None,
            "datos": solicitud.datos,
            "fecha_inicio": solicitud.fecha_inicio.isoformat() if solicitud.fecha_inicio else None,
            "fecha_fin": solicitud.fecha_fin.isoformat() if solicitud.fecha_fin else None,
            "dias_solicitados": solicitud.dias_solicitados,
            "tipo_vacaciones": solicitud.tipo_vacaciones,
            "nivel_actual": solicitud.nivel_actual,
            "nivel_maximo": solicitud.nivel_maximo,
            "created_by": str(solicitud.created_by) if solicitud.created_by else None,
            "created_at": solicitud.created_at.isoformat() if solicitud.created_at else None,
            "fecha_revision": solicitud.fecha_revision.isoformat() if solicitud.fecha_revision else None,
            "comentario_revision": solicitud.comentario_revision,
            "fecha_aprobacion": solicitud.fecha_aprobacion.isoformat() if solicitud.fecha_aprobacion else None
        }
        
    except Exception as e:
        logger.error(f"Error en obtener_solicitud: {e}")
        raise HTTPException(status_code=500, detail=str(e))