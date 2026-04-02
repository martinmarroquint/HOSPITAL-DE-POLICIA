# D:\Centro de control Hospital PNP\back\app\api\descansos_medicos.py
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import and_, or_, func
from typing import List, Optional
from datetime import date, datetime, timedelta
from uuid import UUID
import json
import logging

from app.database import get_db
from app.core.dependencies import require_roles, get_current_user_id, get_current_personal_id
from app.models.descanso_medico import DescansoMedico
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.models.planificacion import Planificacion
from app.schemas.descanso_medico import (
    DescansoMedicoCreate, DescansoMedicoResponse, DescansoMedicoUpdate,
    Domicilio, Profesional
)
from app.utils.file_handler import save_upload_file
from app.utils.validators import validar_sin_duplicado_dm, validar_limite_dias_dm

router = APIRouter()
logger = logging.getLogger(__name__)

# =====================================================
# 🚀 CACHE EN MEMORIA PARA DESCANSOS MÉDICOS
# =====================================================
class DMCache:
    def __init__(self):
        self._cache = {}
        self._timestamps = {}
        self.timeout = 120  # 2 minutos
    
    def get(self, key: str):
        """Obtiene un valor del caché si no ha expirado"""
        if key in self._cache and key in self._timestamps:
            if datetime.now() - self._timestamps[key] < timedelta(seconds=self.timeout):
                return self._cache[key]
            else:
                del self._cache[key]
                del self._timestamps[key]
        return None
    
    def set(self, key: str, value: any):
        """Guarda un valor en el caché"""
        self._cache[key] = value
        self._timestamps[key] = datetime.now()
    
    def invalidate(self, key_pattern: str = None):
        """Invalida caché"""
        if key_pattern:
            keys_to_delete = [k for k in self._cache.keys() if key_pattern in k]
            for key in keys_to_delete:
                del self._cache[key]
                del self._timestamps[key]
        else:
            self._cache.clear()
            self._timestamps.clear()
            logger.info("🧹 Caché de DM limpiado")

dm_cache = DMCache()

@router.get("/", response_model=List[DescansoMedicoResponse])
async def listar_descansos_medicos(
    estado: Optional[str] = Query(None, description="pendiente, aprobado, rechazado"),
    empleado_id: Optional[UUID] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Lista todos los descansos médicos con filtros
    """
    query = db.query(DescansoMedico)
    
    if estado:
        query = query.filter(DescansoMedico.estado == estado)
    
    if empleado_id:
        query = query.filter(DescansoMedico.paciente_id == empleado_id)
    
    # Si es jefe de área, solo ver su área
    if "jefe_area" in current_user.roles and "admin" not in current_user.roles:
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            query = query.join(Personal, Personal.id == DescansoMedico.paciente_id).filter(Personal.area == jefe.area)
    
    descansos = query.order_by(DescansoMedico.created_at.desc()).all()
    
    # Agregar nombre del paciente
    result = []
    for d in descansos:
        d_dict = d.__dict__
        paciente = db.query(Personal).filter(Personal.id == d.paciente_id).first()
        if paciente:
            d_dict["paciente_nombre"] = paciente.nombre
        result.append(DescansoMedicoResponse.model_validate(d_dict))
    
    return result

@router.get("/activos", response_model=List[DescansoMedicoResponse])
async def listar_dm_activos(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "oficial_permanencia", "usuario"]))
):
    """
    Lista descansos médicos activos - VERSIÓN CORREGIDA CON PERMISOS AMPLIADOS
    """
    try:
        cache_key = f"dm_activos_{current_user.id}"
        cached = dm_cache.get(cache_key)
        if cached:
            logger.info(f"📦 Cache hit DM: {cache_key}")
            return cached
        
        start_time = datetime.now()
        hoy = date.today()
        
        # Construir query base
        query = db.query(
            DescansoMedico.id,
            DescansoMedico.paciente_id,
            DescansoMedico.fecha_inicio,
            DescansoMedico.fecha_fin,
            DescansoMedico.diagnostico_cie,
            DescansoMedico.diagnostico_desc,
            DescansoMedico.estado,
            Personal.nombre.label("paciente_nombre"),
            Personal.grado.label("paciente_grado"),
            Personal.area.label("paciente_area")
        ).join(
            Personal,
            Personal.id == DescansoMedico.paciente_id
        ).filter(
            DescansoMedico.fecha_inicio <= hoy,
            DescansoMedico.fecha_fin >= hoy,
            DescansoMedico.estado == "aprobado"
        )
        
        # Si es usuario normal, solo ver sus propios DM
        if "usuario" in current_user.roles and "admin" not in current_user.roles and "jefe_area" not in current_user.roles:
            query = query.filter(DescansoMedico.paciente_id == current_user.personal_id)
            logger.info(f"👤 Usuario viendo sus propios DM: {current_user.personal_id}")
        
        # Si es jefe de área, ver DM de su área
        elif "jefe_area" in current_user.roles and "admin" not in current_user.roles:
            jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if jefe and jefe.area:
                query = query.filter(Personal.area == jefe.area)
                logger.info(f"👥 Jefe viendo DM del área: {jefe.area}")
        
        # Si es admin, ve todos
        elif "admin" in current_user.roles:
            logger.info("👑 Admin viendo todos los DM")
        
        # Si es oficial de permanencia, ve DM de su área
        elif "oficial_permanencia" in current_user.roles:
            oficial = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if oficial and oficial.area:
                query = query.filter(Personal.area == oficial.area)
                logger.info(f"👮 Oficial viendo DM del área: {oficial.area}")
        
        # Ejecutar query con límite
        dms = query.order_by(DescansoMedico.fecha_inicio).limit(100).all()
        
        result = [
            {
                "id": str(dm.id),
                "paciente_id": str(dm.paciente_id),
                "fecha_inicio": dm.fecha_inicio.isoformat(),
                "fecha_fin": dm.fecha_fin.isoformat(),
                "diagnostico_cie": dm.diagnostico_cie,
                "diagnostico_desc": dm.diagnostico_desc,
                "estado": dm.estado,
                "paciente_nombre": dm.paciente_nombre,
                "paciente_grado": dm.paciente_grado,
                "paciente_area": dm.paciente_area
            }
            for dm in dms
        ]
        
        query_time = (datetime.now() - start_time).total_seconds() * 1000
        logger.info(f"✅ DM activos obtenidos en {query_time:.2f}ms - {len(result)} registros")
        
        # Cache por 2 minutos
        dm_cache.set(cache_key, result)
        
        return result
        
    except Exception as e:
        logger.error(f"❌ Error en listar_dm_activos: {e}")
        return []

@router.get("/empleado/{empleado_id}", response_model=List[DescansoMedicoResponse])
async def listar_dm_por_empleado(
    empleado_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Lista DM de un empleado específico
    """
    # Verificar permisos: usuarios solo pueden ver sus propios DM
    if "usuario" in current_user.roles and "admin" not in current_user.roles and "jefe_area" not in current_user.roles:
        if str(current_user.personal_id) != str(empleado_id):
            raise HTTPException(status_code=403, detail="No puede ver DM de otro empleado")
    
    descansos = db.query(DescansoMedico).filter(
        DescansoMedico.paciente_id == empleado_id
    ).order_by(DescansoMedico.created_at.desc()).all()
    
    # Agregar nombre del paciente
    result = []
    paciente = db.query(Personal).filter(Personal.id == empleado_id).first()
    for d in descansos:
        d_dict = d.__dict__
        if paciente:
            d_dict["paciente_nombre"] = paciente.nombre
        result.append(DescansoMedicoResponse.model_validate(d_dict))
    
    return result

@router.get("/{id}", response_model=DescansoMedicoResponse)
async def obtener_dm(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Obtiene un DM por ID
    """
    dm = db.query(DescansoMedico).filter(DescansoMedico.id == id).first()
    if not dm:
        raise HTTPException(status_code=404, detail="Descanso médico no encontrado")
    
    # Verificar permisos
    if "usuario" in current_user.roles and "admin" not in current_user.roles and "jefe_area" not in current_user.roles:
        if str(current_user.personal_id) != str(dm.paciente_id):
            raise HTTPException(status_code=403, detail="No puede ver DM de otro empleado")
    
    dm_dict = dm.__dict__
    paciente = db.query(Personal).filter(Personal.id == dm.paciente_id).first()
    if paciente:
        dm_dict["paciente_nombre"] = paciente.nombre
    
    return DescansoMedicoResponse.model_validate(dm_dict)

@router.post("/", response_model=DescansoMedicoResponse, status_code=201)
async def crear_dm(
    paciente: str = Form(...),
    diagnostico: str = Form(...),
    domicilio: str = Form(...),
    profesional: str = Form(...),
    fecha_inicio: date = Form(...),
    fecha_termino: date = Form(...),
    dias: int = Form(...),
    observaciones: str = Form(None),
    anotaciones: str = Form(None),
    imagen: UploadFile = File(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "usuario"]))
):
    """
    Crea un nuevo descanso médico con imagen
    """
    # Parsear JSONs
    try:
        paciente_data = json.loads(paciente)
        diagnostico_data = json.loads(diagnostico)
        domicilio_data = json.loads(domicilio)
        profesional_data = json.loads(profesional)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Error en formato de datos JSON")
    
    # Validar fechas
    if fecha_termino < fecha_inicio:
        raise HTTPException(status_code=400, detail="Fecha término debe ser mayor o igual a fecha inicio")
    
    # Validar límite de días
    valido, msg = validar_limite_dias_dm(dias)
    if not valido:
        raise HTTPException(status_code=400, detail=msg)
    
    # Validar que no haya DM duplicado
    valido, msg = validar_sin_duplicado_dm(db, paciente_data.get("id"), fecha_inicio, fecha_termino)
    if not valido:
        raise HTTPException(status_code=400, detail=msg)
    
    # Guardar imagen si se proporcionó
    imagen_url = None
    if imagen:
        imagen_url = await save_upload_file(imagen, subfolder="dm")
    
    # Crear DM
    dm = DescansoMedico(
        paciente_id=paciente_data.get("id"),
        diagnostico_cie=diagnostico_data.get("cie"),
        diagnostico_desc=diagnostico_data.get("descripcion"),
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_termino,
        dias=dias,
        domicilio=domicilio_data,
        profesional=profesional_data,
        observaciones=observaciones,
        anotaciones=anotaciones,
        imagen_url=imagen_url,
        created_by=current_user.id
    )
    
    db.add(dm)
    db.commit()
    db.refresh(dm)
    
    # Crear planificación de DM
    fecha_actual = fecha_inicio
    while fecha_actual <= fecha_termino:
        planificacion = Planificacion(
            personal_id=dm.paciente_id,
            fecha=fecha_actual,
            turno_codigo="DM",
            dm_info={
                "dm_id": str(dm.id),
                "diagnostico": diagnostico_data.get("descripcion")
            },
            created_by=current_user.id
        )
        db.add(planificacion)
        fecha_actual += timedelta(days=1)
    
    db.commit()
    
    # Invalidar caché
    dm_cache.invalidate()
    
    dm_dict = dm.__dict__
    paciente_obj = db.query(Personal).filter(Personal.id == dm.paciente_id).first()
    if paciente_obj:
        dm_dict["paciente_nombre"] = paciente_obj.nombre
    
    return DescansoMedicoResponse.model_validate(dm_dict)

@router.put("/{id}/recepcion", response_model=DescansoMedicoResponse)
async def recepcionar_dm(
    id: UUID,
    update_data: DescansoMedicoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Marca DM como recibido (cambia estado a pendiente de aprobación)
    """
    dm = db.query(DescansoMedico).filter(DescansoMedico.id == id).first()
    if not dm:
        raise HTTPException(status_code=404, detail="Descanso médico no encontrado")
    
    dm.estado = "pendiente"
    dm.observaciones = update_data.observaciones or dm.observaciones
    
    db.commit()
    db.refresh(dm)
    
    # Invalidar caché
    dm_cache.invalidate()
    
    dm_dict = dm.__dict__
    paciente = db.query(Personal).filter(Personal.id == dm.paciente_id).first()
    if paciente:
        dm_dict["paciente_nombre"] = paciente.nombre
    
    return DescansoMedicoResponse.model_validate(dm_dict)

@router.put("/{id}/aprobar", response_model=DescansoMedicoResponse)
async def aprobar_dm(
    id: UUID,
    update_data: DescansoMedicoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Aprueba un DM
    """
    dm = db.query(DescansoMedico).filter(DescansoMedico.id == id).first()
    if not dm:
        raise HTTPException(status_code=404, detail="Descanso médico no encontrado")
    
    dm.estado = "aprobado"
    dm.anotaciones = update_data.anotaciones or dm.anotaciones
    
    db.commit()
    db.refresh(dm)
    
    # Invalidar caché
    dm_cache.invalidate()
    
    dm_dict = dm.__dict__
    paciente = db.query(Personal).filter(Personal.id == dm.paciente_id).first()
    if paciente:
        dm_dict["paciente_nombre"] = paciente.nombre
    
    return DescansoMedicoResponse.model_validate(dm_dict)

@router.put("/{id}/rechazar", response_model=DescansoMedicoResponse)
async def rechazar_dm(
    id: UUID,
    update_data: DescansoMedicoUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """
    Rechaza un DM
    """
    dm = db.query(DescansoMedico).filter(DescansoMedico.id == id).first()
    if not dm:
        raise HTTPException(status_code=404, detail="Descanso médico no encontrado")
    
    dm.estado = "rechazado"
    dm.anotaciones = update_data.anotaciones or dm.anotaciones
    
    # Eliminar planificaciones de DM
    db.query(Planificacion).filter(
        Planificacion.personal_id == dm.paciente_id,
        Planificacion.fecha.between(dm.fecha_inicio, dm.fecha_fin),
        Planificacion.turno_codigo == "DM"
    ).delete(synchronize_session=False)
    
    db.commit()
    db.refresh(dm)
    
    # Invalidar caché
    dm_cache.invalidate()
    
    dm_dict = dm.__dict__
    paciente = db.query(Personal).filter(Personal.id == dm.paciente_id).first()
    if paciente:
        dm_dict["paciente_nombre"] = paciente.nombre
    
    return DescansoMedicoResponse.model_validate(dm_dict)

@router.get("/verificar/{empleado_id}")
async def verificar_dm_activo(
    empleado_id: UUID,
    fecha: date = Query(default_factory=date.today),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "oficial_permanencia", "jefe_area"]))
):
    """
    Verifica si un empleado tiene DM activo en una fecha
    """
    dm = db.query(DescansoMedico).filter(
        DescansoMedico.paciente_id == empleado_id,
        DescansoMedico.fecha_inicio <= fecha,
        DescansoMedico.fecha_fin >= fecha,
        DescansoMedico.estado == "aprobado"
    ).first()
    
    if dm:
        return {
            "activo": True,
            "dm_id": str(dm.id),
            "fecha_inicio": dm.fecha_inicio.isoformat(),
            "fecha_fin": dm.fecha_fin.isoformat(),
            "diagnostico": dm.diagnostico_desc
        }
    
    return {"activo": False}