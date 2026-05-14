# api/personal.py
# VERSIÓN FINAL - ALINEADO CON roles.py

from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional, Dict, Any
from uuid import UUID
from datetime import datetime, timedelta
import json
import unicodedata
import logging
import secrets
import base64
import hashlib
import hmac

from app.database import get_db
from app.core.dependencies import require_roles, get_current_user_id, get_current_empresa_id
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.models.planificacion import Planificacion
from app.models.asistencia import Asistencia
from app.models.descanso_medico import DescansoMedico
from app.models.solicitud_cambio import SolicitudCambio
from app.models.empresa import Empresa
from app.models.qr import QRRegistro
from app.schemas.personal import (
    PersonalCreate, PersonalUpdate, PersonalResponse, 
    CargaMasivaItem, CargaMasivaResponse,
    VerificarRelacionesResponse, VerificarDNIResponse,
    EliminarResponse, JefaturaResumen
)
from app.utils.roles import (
    ROLES_SISTEMA, 
    TODOS_LOS_ROLES, 
    ROLES_ADMIN, 
    ROLES_JEFE, 
    ROLES_JEFATURA,
    ROLES_PUEDEN_GESTIONAR_USUARIOS,
    ROLES_PUEDEN_VER_REPORTES,
    ROLES_SOLO_LECTURA,
    ROLES_SOLO_ESCANER
)

logger = logging.getLogger(__name__)

router = APIRouter()

# =====================================================
# CACHE EN MEMORIA (2 minutos)
# =====================================================
personal_cache = {}
cache_timeout = 120

def clear_personal_cache():
    global personal_cache
    personal_cache.clear()

def get_cache_key(user_id: str, area: Optional[str], grado: Optional[str], busqueda: Optional[str]) -> str:
    return f"{user_id}-{area}-{grado}-{busqueda}"

# =====================================================
# CONFIGURACIÓN QR
# =====================================================
QR_SECRET_KEY = getattr(__import__('app.config', fromlist=['settings']).settings, 'QR_SECRET_KEY', 'human-check-qr-secret')

def firmar_payload(payload: dict) -> str:
    campos = ['i', 'n', 'd', 't', 'v']
    mensaje = '|'.join(str(payload.get(c, '')) for c in campos)
    return hmac.new(QR_SECRET_KEY.encode(), mensaje.encode(), hashlib.sha256).hexdigest()[:12]

def generar_qr_estatico_para_visitante(db: Session, personal: Personal):
    """Genera QR estático automáticamente para un visitante"""
    id_corto = str(personal.id).replace('-', '')[-8:]
    nombre_corto = (personal.nombre or '').split(',')[0].strip()[:15]
    
    payload = {"i": id_corto, "n": nombre_corto, "t": "v", "v": "2"}
    payload["s"] = firmar_payload(payload)
    
    ahora = datetime.utcnow()
    qr_registro = QRRegistro(
        qr_id=f"qr-estatico-{personal.id}",
        empleado_id=personal.id,
        generado_en=ahora,
        expira_en=ahora + timedelta(days=365),
        usado=False,
        tipo="visitante",
        codigo=json.dumps(payload)
    )
    db.add(qr_registro)
    logger.info(f"QR estático auto-generado para visitante: {personal.nombre}")

# =====================================================
# LISTAS DE REFERENCIA
# =====================================================

GRADOS_VALIDOS = [
    'GENERAL PNP', 'GENERAL SPNP', 'CRNL PNP', 'CRNL SPNP',
    'CMDT PNP', 'CMDT SPNP', 'MAY PNP', 'MAY SPNP',
    'CAP PNP', 'CAP SPNP', 'SS PNP', 'SS SPNP',
    'SB PNP', 'SB SPNP', 'ST1 PNP', 'ST1 SPNP',
    'ST2 PNP', 'ST2 SPNP', 'ST3 PNP', 'ST3 SPNP',
    'S1 PNP', 'S1 SPNP', 'S2 PNP', 'S2 SPNP',
    'S3 PNP', 'S3 SPNP', 'EC. PC.', 'CIVIL', 'CAS',
    'MEDICO', 'SERUM', 'ENFERMERA', 'TECNICO', 'ADMINISTRATIVO', 'PENDIENTE'
]

# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def limpiar_valor_optional(valor: Optional[str]) -> Optional[str]:
    """Convierte cadenas vacías a None para campos opcionales"""
    if valor is None:
        return None
    if isinstance(valor, str) and not valor.strip():
        return None
    return valor.strip() if isinstance(valor, str) else valor

def es_visitante(roles: List[str]) -> bool:
    if not roles: return False
    return "visitante" in [r.lower() for r in roles if isinstance(r, str)]

def get_roles_normalizados(roles) -> List[str]:
    if not roles: return []
    if isinstance(roles, list): return [r.lower() for r in roles if isinstance(r, str)]
    if isinstance(roles, str):
        try:
            parsed = json.loads(roles)
            if isinstance(parsed, list): return [r.lower() for r in parsed if isinstance(r, str)]
        except: pass
    return []

def get_roles_usuario(user: Usuario) -> List[str]:
    return get_roles_normalizados(user.roles)

def es_admin(user: Usuario) -> bool:
    """Verifica si el usuario tiene rol de administrador"""
    roles = get_roles_usuario(user)
    return any(r in ROLES_ADMIN for r in roles)

def es_jefe(user: Usuario) -> bool:
    """Verifica si el usuario tiene rol de jefe"""
    roles = get_roles_usuario(user)
    return any(r in ROLES_JEFE for r in roles)

def tiene_acceso_global(user: Usuario) -> bool:
    """Verifica si el usuario tiene acceso global (admin o jefe)"""
    return es_admin(user) or es_jefe(user)

def generar_email_interno(nombre_completo: str, dni: str = None, dominio: str = None) -> str:
    dominio_final = dominio or "sistema.com"
    if not nombre_completo or nombre_completo == 'PENDIENTE':
        return f"pendiente{hash(dni) % 10000 if dni else 0}@{dominio_final}"
    nombre = nombre_completo.upper().strip().replace(',', ' ')
    palabras = [p for p in nombre.split() if p]
    if not palabras:
        return f"usuario{hash(dni) % 10000 if dni else 0}@{dominio_final}"
    primer_nombre = palabras[0]
    primer_apellido = palabras[-1] if len(palabras) > 1 else palabras[0]
    def quitar_tildes(texto):
        return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').lower()
    nombre_norm = quitar_tildes(primer_nombre)
    apellido_norm = quitar_tildes(primer_apellido)
    return f"{nombre_norm}.{apellido_norm}@{dominio_final}"

def obtener_dominio_empresa(db: Session, empresa_id: UUID) -> str:
    if not empresa_id: return "sistema.com"
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if empresa and empresa.subdominio:
        return empresa.dominio_email or empresa.subdominio
    return "sistema.com"

def get_areas_jefatura_from_data(personal_data) -> List[str]:
    """Extrae las áreas de jefatura de los datos de creación/actualización"""
    areas = []
    
    if hasattr(personal_data, 'areas_que_jefatura') and personal_data.areas_que_jefatura:
        if isinstance(personal_data.areas_que_jefatura, list):
            for item in personal_data.areas_que_jefatura:
                if isinstance(item, str):
                    if ':' in item:
                        areas.append(item.split(':', 1)[1])
                    else:
                        areas.append(item)
    
    if hasattr(personal_data, 'areas_jefatura') and personal_data.areas_jefatura:
        if isinstance(personal_data.areas_jefatura, dict):
            for tipo, areas_lista in personal_data.areas_jefatura.items():
                if isinstance(areas_lista, list):
                    areas.extend(areas_lista)
    
    # Si no hay áreas explícitas pero tiene área asignada
    if not areas and hasattr(personal_data, 'area') and personal_data.area:
        areas = [personal_data.area]
    
    return list(set(areas))

def get_areas_jefatura(jefe: Personal) -> List[str]:
    """
    Obtiene todas las áreas que están bajo la jefatura de una persona.
    Un jefe jefatura todo lo que está debajo de él en la jerarquía organizacional.
    """
    if not jefe:
        return []
    
    areas = []
    
    if jefe.areas_que_jefatura and isinstance(jefe.areas_que_jefatura, list):
        for item in jefe.areas_que_jefatura:
            if isinstance(item, str):
                if ':' in item:
                    areas.append(item.split(':', 1)[1])
                else:
                    areas.append(item)
    
    if jefe.areas_jefatura and isinstance(jefe.areas_jefatura, dict):
        for tipo, areas_lista in jefe.areas_jefatura.items():
            if isinstance(areas_lista, list):
                areas.extend(areas_lista)
    
    # Si no tiene áreas explícitas pero tiene un área asignada, jefatura esa área
    if not areas and jefe.area:
        areas = [jefe.area]
    
    return list(set(areas))

def get_subordinados(db: Session, jefe: Personal) -> List[Personal]:
    """
    Obtiene todos los subordinados de un jefe según la jerarquía.
    Un jefe jefatura todo lo que está debajo de él.
    """
    areas = get_areas_jefatura(jefe)
    
    if not areas:
        return []
    
    subordinados = db.query(Personal).filter(
        Personal.activo == True,
        Personal.area.in_(areas),
        Personal.id != jefe.id
    ).all()
    
    return subordinados

def puede_acceder_a_personal(current_user: Usuario, personal: Personal, db: Session) -> bool:
    """Verifica si el usuario actual puede acceder a un personal específico"""
    roles_usuario = get_roles_usuario(current_user)
    
    # Admin puede ver todo
    if any(r in ROLES_ADMIN for r in roles_usuario):
        return True
    
    # El usuario puede verse a sí mismo
    if str(current_user.personal_id) == str(personal.id):
        return True
    
    # Jefe puede ver a sus subordinados
    if any(r in ROLES_JEFE for r in roles_usuario):
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            areas = get_areas_jefatura(jefe)
            if personal.area in areas:
                return True
    
    return False

# =====================================================
# ENDPOINTS PRINCIPALES
# =====================================================

@router.get("/", response_model=List[PersonalResponse])
async def listar_personal(
    area: Optional[str] = Query(None),
    grado: Optional[str] = Query(None),
    busqueda: Optional[str] = Query(None),
    activo: Optional[bool] = Query(None),
    incluir_inactivos: Optional[bool] = Query(False),
    empresa_id: Optional[UUID] = Query(None),
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(TODOS_LOS_ROLES))
):
    cache_key = get_cache_key(str(current_user.id), area, grado, busqueda)
    if offset == 0 and limit == 100 and cache_key in personal_cache:
        cached_data, timestamp = personal_cache[cache_key]
        if datetime.now() - timestamp < timedelta(seconds=cache_timeout):
            return cached_data[:limit]
    
    query = db.query(Personal).filter(
    Personal.dni != '00000001',  # DNI del super admin
    Personal.dni != '00000000',  # DNI de respaldo
    ~Personal.nombre.ilike('%SUPER ADMINISTRADOR%')  # Por nombre
)
    
    # Filtro por empresa_id
    if empresa_id:
        query = query.filter(Personal.empresa_id == empresa_id)
    elif current_user.empresa_id:
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    
    roles_usuario = get_roles_usuario(current_user)
    
    # Usuario básico o visitante solo se ve a sí mismo
    if not tiene_acceso_global(current_user) and not any(r in ROLES_SOLO_LECTURA for r in roles_usuario if r not in ROLES_SOLO_ESCANER):
        if current_user.personal_id:
            personal = query.filter(Personal.id == current_user.personal_id).first()
            result = [personal] if personal else []
            personal_cache[cache_key] = (result, datetime.now())
            return result
        return []
    
    # Jefe ve a todos sus subordinados (y a sí mismo)
    if es_jefe(current_user) and not es_admin(current_user):
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            areas_jefatura = get_areas_jefatura(jefe)
            if areas_jefatura:
                query = query.filter(
                    or_(
                        Personal.id == jefe.id,
                        Personal.area.in_(areas_jefatura)
                    )
                )
    
    if area: query = query.filter(Personal.area == area)
    if grado: query = query.filter(Personal.grado == grado)
    if activo is not None: query = query.filter(Personal.activo == activo)
    elif not incluir_inactivos and not es_admin(current_user):
        query = query.filter(Personal.activo == True)
    if busqueda:
        busqueda_pattern = f"%{busqueda}%"
        query = query.filter(
            or_(
                Personal.nombre.ilike(busqueda_pattern),
                Personal.dni.ilike(busqueda_pattern),
                Personal.cip.ilike(busqueda_pattern)
            )
        )
    
    total = query.count()
    resultados = query.order_by(Personal.area, Personal.grado, Personal.nombre).offset(offset).limit(limit).all()
    if offset == 0: 
        personal_cache[cache_key] = (resultados, datetime.now())
    return resultados


@router.get("/me/jefatura", response_model=JefaturaResumen)
async def obtener_mi_jefatura(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(TODOS_LOS_ROLES))
):
    personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
    if not personal: 
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    areas_jefatura = get_areas_jefatura(personal) if es_jefe(current_user) else []
    roles_jefatura = ["jefe"] if es_jefe(current_user) else []
    
    return JefaturaResumen(
        tiene_acceso_global=tiene_acceso_global(current_user),
        roles_jefatura=roles_jefatura,
        areas_por_tipo={"area": areas_jefatura},
        todas_las_areas=areas_jefatura
    )


@router.get("/mis-subordinados", response_model=List[PersonalResponse])
async def listar_mis_subordinados(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN + ROLES_JEFE))
):
    """Endpoint específico para que un jefe vea sus subordinados directos"""
    personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    # Admin ve todo
    if es_admin(current_user):
        query = db.query(Personal).filter(Personal.activo == True)
        if current_user.empresa_id:
            query = query.filter(Personal.empresa_id == current_user.empresa_id)
        return query.order_by(Personal.area, Personal.nombre).all()
    
    # Jefe ve sus subordinados
    subordinados = get_subordinados(db, personal)
    return subordinados


@router.get("/jefes/por-area/{area}")
async def listar_jefes_por_area(
    area: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN + ROLES_JEFE))
):
    query = db.query(Personal).filter(
        Personal.activo == True,
        Personal.roles.op('&&')(ROLES_JEFE)
    )
    if current_user.empresa_id:
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    
    jefes = query.all()
    resultado = {'area': area, 'jefes': {'jefe': []}}
    
    for jefe in jefes:
        areas = get_areas_jefatura(jefe)
        if area in areas:
            resultado['jefes']['jefe'].append({
                'id': str(jefe.id),
                'nombre': jefe.nombre,
                'grado': jefe.grado,
                'email': jefe.email,
                'area_trabajo': jefe.area
            })
    
    return resultado


@router.get("/areas-sin-jefe")
async def listar_areas_sin_jefe(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    query = db.query(Personal).filter(
        Personal.activo == True,
        Personal.roles.op('&&')(ROLES_JEFE)
    )
    if current_user.empresa_id:
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    
    jefes = query.all()
    areas_con_jefe = set()
    for jefe in jefes:
        areas = get_areas_jefatura(jefe)
        areas_con_jefe.update(areas)
    
    areas_todas = db.query(Personal.area).filter(Personal.activo == True).distinct().all()
    areas_todas = [a[0] for a in areas_todas if a[0]]
    areas_sin_jefe = [a for a in areas_todas if a not in areas_con_jefe]
    
    return {
        'total_areas': len(areas_todas),
        'areas_con_jefe': len(areas_con_jefe),
        'areas_sin_jefe': len(areas_sin_jefe),
        'lista_areas_sin_jefe': areas_sin_jefe
    }


@router.get("/{id}", response_model=PersonalResponse)
async def obtener_personal(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(TODOS_LOS_ROLES))
):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    if current_user.empresa_id:
        if personal.empresa_id != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    # Verificar acceso
    if not puede_acceder_a_personal(current_user, personal, db):
        raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    return personal


@router.get("/area/{area}", response_model=List[PersonalResponse])
async def listar_por_area(
    area: str,
    activo: Optional[bool] = Query(True),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN + ROLES_JEFE))
):
    # Jefe solo puede ver sus áreas
    if es_jefe(current_user) and not es_admin(current_user):
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            areas = get_areas_jefatura(jefe)
            if area not in areas:
                raise HTTPException(status_code=403, detail="No tiene acceso a esta área")
    
    query = db.query(Personal).filter(Personal.area == area)
    if current_user.empresa_id:
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    if activo is not None:
        query = query.filter(Personal.activo == activo)
    return query.order_by(Personal.grado, Personal.nombre).all()


@router.get("/verificar-dni/{dni}")
async def verificar_dni(
    dni: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    query = db.query(Personal).filter(Personal.dni == dni)
    if current_user.empresa_id:
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    usuario = query.first()
    if not usuario:
        return {"disponible": True, "existe": False, "activo": False}
    return {
        "disponible": not usuario.activo,
        "existe": True,
        "activo": usuario.activo,
        "id": str(usuario.id),
        "nombre": usuario.nombre,
        "email": usuario.email
    }


@router.post("/", response_model=PersonalResponse, status_code=201)
async def crear_personal(
    personal_data: PersonalCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_PUEDEN_GESTIONAR_USUARIOS))
):
    """Crea un nuevo personal. Solo admin_empresa puede crear usuarios."""
    
    # Limpiar campos opcionales
    personal_data.cip = limpiar_valor_optional(personal_data.cip)
    personal_data.email = limpiar_valor_optional(personal_data.email)
    personal_data.telefono = limpiar_valor_optional(personal_data.telefono)
    personal_data.especialidad = limpiar_valor_optional(personal_data.especialidad)
    personal_data.numero_colegiatura = limpiar_valor_optional(personal_data.numero_colegiatura)
    personal_data.sexo = limpiar_valor_optional(personal_data.sexo) or 'No especificado'
    
    es_visitante_personal = 'visitante' in (personal_data.roles or [])
    
    if not es_visitante_personal and not personal_data.area:
        raise HTTPException(status_code=400, detail="El área de trabajo es obligatoria")
    
    if es_visitante_personal and not personal_data.area:
        personal_data.area = None
    
    # Validar que jefes tengan áreas asignadas
    if 'jefe' in (personal_data.roles or []):
        areas = get_areas_jefatura_from_data(personal_data)
        if not areas:
            raise HTTPException(status_code=400, detail="Los jefes deben tener al menos un área asignada para jefaturar")
    
    # Verificar DNI duplicado
    query = db.query(Personal).filter(Personal.dni == personal_data.dni)
    if current_user.empresa_id:
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    usuario_existente = query.first()
    if usuario_existente:
        if usuario_existente.activo:
            raise HTTPException(status_code=400, detail="DNI ya registrado y activo")
        else:
            for key, value in personal_data.model_dump().items():
                setattr(usuario_existente, key, value)
            usuario_existente.activo = True
            db.commit()
            db.refresh(usuario_existente)
            clear_personal_cache()
            return usuario_existente
    
    # Validar CIP duplicado
    if personal_data.cip and personal_data.cip.strip():
        query_cip = db.query(Personal).filter(
            Personal.cip == personal_data.cip,
            Personal.activo == True
        )
        if current_user.empresa_id:
            query_cip = query_cip.filter(Personal.empresa_id == current_user.empresa_id)
        if query_cip.first():
            raise HTTPException(status_code=400, detail="CIP ya registrado")
    
    # Validar email duplicado
    if personal_data.email and personal_data.email.strip():
        email_existente = db.query(Personal).filter(
            Personal.email == personal_data.email,
            Personal.activo == True
        ).first()
        if email_existente:
            raise HTTPException(status_code=400, detail="Email ya registrado")
    
    personal = Personal(**personal_data.model_dump())
    if current_user.empresa_id:
        personal.empresa_id = current_user.empresa_id
    
    db.add(personal)
    db.commit()
    db.refresh(personal)
    
    # Generar QR para visitantes
    if 'visitante' in (personal.roles or []):
        generar_qr_estatico_para_visitante(db, personal)
        db.commit()
    
    clear_personal_cache()
    return personal


@router.put("/{id}", response_model=PersonalResponse)
async def actualizar_personal(
    id: UUID,
    personal_data: PersonalUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_PUEDEN_GESTIONAR_USUARIOS))
):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id:
        if personal.empresa_id != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    # Limpiar campos opcionales
    if personal_data.cip is not None:
        personal_data.cip = limpiar_valor_optional(personal_data.cip)
    if personal_data.email is not None:
        personal_data.email = limpiar_valor_optional(personal_data.email)
    if personal_data.telefono is not None:
        personal_data.telefono = limpiar_valor_optional(personal_data.telefono)
    if personal_data.especialidad is not None:
        personal_data.especialidad = limpiar_valor_optional(personal_data.especialidad)
    if personal_data.numero_colegiatura is not None:
        personal_data.numero_colegiatura = limpiar_valor_optional(personal_data.numero_colegiatura)
    
    roles_actuales = personal_data.roles if personal_data.roles is not None else personal.roles
    es_visitante_actual = 'visitante' in (roles_actuales or [])
    
    # Validar que jefes tengan áreas asignadas
    if 'jefe' in (roles_actuales or []) and not es_visitante_actual:
        area_trabajo = personal_data.area if personal_data.area is not None else personal.area
        areas_que = personal_data.areas_que_jefatura if personal_data.areas_que_jefatura is not None else personal.areas_que_jefatura
        areas_obj = personal_data.areas_jefatura if personal_data.areas_jefatura is not None else personal.areas_jefatura
        
        class TempData:
            pass
        temp = TempData()
        temp.areas_que_jefatura = areas_que
        temp.areas_jefatura = areas_obj
        temp.area = area_trabajo
        
        areas = get_areas_jefatura_from_data(temp)
        if not areas:
            raise HTTPException(status_code=400, detail="Los jefes deben tener al menos un área asignada para jefaturar")
    
    # Validar DNI duplicado
    if personal_data.dni and personal_data.dni != personal.dni:
        query = db.query(Personal).filter(Personal.dni == personal_data.dni, Personal.activo == True)
        if current_user.empresa_id:
            query = query.filter(Personal.empresa_id == current_user.empresa_id)
        if query.first():
            raise HTTPException(status_code=400, detail="DNI ya registrado")
    
    # Validar CIP duplicado
    if personal_data.cip is not None and personal_data.cip != personal.cip:
        if personal_data.cip and personal_data.cip.strip():
            query = db.query(Personal).filter(
                Personal.cip == personal_data.cip,
                Personal.activo == True
            )
            if current_user.empresa_id:
                query = query.filter(Personal.empresa_id == current_user.empresa_id)
            if query.first():
                raise HTTPException(status_code=400, detail="CIP ya registrado")
    
    # Validar email duplicado
    if personal_data.email is not None and personal_data.email != personal.email:
        if personal_data.email and personal_data.email.strip():
            if db.query(Personal).filter(
                Personal.email == personal_data.email,
                Personal.activo == True
            ).first():
                raise HTTPException(status_code=400, detail="Email ya registrado")
    
    era_visitante = 'visitante' in (personal.roles or [])
    update_data = personal_data.model_dump(exclude_unset=True)
    
    for field, value in update_data.items():
        setattr(personal, field, value)
    
    db.commit()
    db.refresh(personal)
    
    es_visitante_ahora = 'visitante' in (personal.roles or [])
    if es_visitante_ahora and not era_visitante:
        qr_existente = db.query(QRRegistro).filter(
            QRRegistro.empleado_id == personal.id,
            QRRegistro.tipo == "visitante"
        ).first()
        if not qr_existente:
            generar_qr_estatico_para_visitante(db, personal)
            db.commit()
    
    clear_personal_cache()
    return personal


# =====================================================
# CARGA MASIVA
# =====================================================

@router.post("/carga-masiva-stream")
async def carga_masiva_stream(
    datos: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_PUEDEN_GESTIONAR_USUARIOS))
):
    dominio = obtener_dominio_empresa(db, current_user.empresa_id)
    
    async def generar_eventos():
        total = len(datos)
        exitosos = 0
        fallidos = 0
        detalles = []
        errores = []
        yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"
        
        for idx, item in enumerate(datos):
            fila = item.get('_fila', idx + 2)
            try:
                dni = str(item.get('DNI', '') or item.get('dni', '')).strip() or f"PEND{idx+1:04d}"
                cip = limpiar_valor_optional(str(item.get('CIP', '') or item.get('cip', '')).strip())
                grado = str(item.get('GRADO', '') or item.get('grado', '')).strip().upper() or "PENDIENTE"
                nombre = str(item.get('NOMBRE COMPLETO', '') or item.get('nombre', '')).strip().upper() or f"PERSONAL {idx+1}"
                email = limpiar_valor_optional(str(item.get('EMAIL', '') or item.get('email', '')).strip().lower())
                if not email or '@' not in email:
                    email = generar_email_interno(nombre, dni, dominio)
                
                area = str(item.get('ÁREA', '') or item.get('area', '')).strip().upper() or "PENDIENTE"
                roles_str = str(item.get('ROLES', '') or item.get('roles', '')).strip()
                roles = [r.strip().lower() for r in roles_str.split(',') if r.strip()] if roles_str else ['usuario']
                
                # Validar que los roles existan
                for rol in roles:
                    if rol not in TODOS_LOS_ROLES:
                        raise ValueError(f"Rol inválido: {rol}")
                
                telefono = limpiar_valor_optional(str(item.get('TELÉFONO', '') or item.get('telefono', '')).strip())
                if telefono and not telefono.isdigit():
                    telefono = ''.join(c for c in telefono if c.isdigit())
                
                especialidad = limpiar_valor_optional(str(item.get('ESPECIALIDAD', '') or item.get('especialidad', '')).strip())
                
                fecha_nac = item.get('FECHA NACIMIENTO (YYYY-MM-DD)') or item.get('fecha_nacimiento')
                if fecha_nac and isinstance(fecha_nac, str):
                    try:
                        fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                    except:
                        fecha_nac = None
                
                fecha_ingreso = item.get('FECHA INGRESO (YYYY-MM-DD)') or item.get('fecha_ingreso')
                if fecha_ingreso and isinstance(fecha_ingreso, str):
                    try:
                        fecha_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
                    except:
                        fecha_ingreso = datetime.now().date()
                else:
                    fecha_ingreso = datetime.now().date()
                
                num_colegiatura = limpiar_valor_optional(str(item.get('NÚMERO COLEGIATURA', '') or item.get('numero_colegiatura', '')).strip())
                observaciones = str(item.get('OBSERVACIONES', '') or item.get('observaciones', '')).strip()
                
                areas_jefatura_str = str(item.get('ÁREAS_JEFATURA', '') or item.get('area_jefatura', '')).strip()
                areas_jefatura = [a.strip().upper() for a in areas_jefatura_str.split(',') if a.strip()] if areas_jefatura_str else []
                
                if "jefe" in roles and not areas_jefatura:
                    raise ValueError("Los jefes deben tener al menos un área asignada")
                
                query = db.query(Personal)
                if current_user.empresa_id:
                    query = query.filter(Personal.empresa_id == current_user.empresa_id)
                
                if cip:
                    usuario_existente = query.filter(or_(Personal.dni == dni, Personal.cip == cip)).first()
                else:
                    usuario_existente = query.filter(Personal.dni == dni).first()
                
                if usuario_existente:
                    if usuario_existente.activo:
                        fallidos += 1
                        errores.append({"fila": fila, "errores": [f"Usuario ya existe (DNI: {dni})"]})
                    else:
                        for key, value in {
                            'grado': grado, 'nombre': nombre, 'email': email,
                            'telefono': telefono, 'fecha_nacimiento': fecha_nac,
                            'area': area, 'especialidad': especialidad,
                            'fecha_ingreso': fecha_ingreso, 'roles': roles,
                            'numero_colegiatura': num_colegiatura,
                            'observaciones': observaciones,
                            'areas_que_jefatura': areas_jefatura
                        }.items():
                            setattr(usuario_existente, key, value)
                        usuario_existente.activo = True
                        db.commit()
                        exitosos += 1
                        detalles.append({"fila": fila, "mensaje": f"Usuario reactivado: {nombre}"})
                else:
                    nuevo_personal = Personal(
                        dni=dni, cip=cip, grado=grado, nombre=nombre,
                        email=email, telefono=telefono,
                        fecha_nacimiento=fecha_nac, area=area,
                        especialidad=especialidad, fecha_ingreso=fecha_ingreso,
                        roles=roles, numero_colegiatura=num_colegiatura,
                        observaciones=observaciones,
                        areas_que_jefatura=areas_jefatura,
                        activo=True, condicion='Titular',
                        empresa_id=current_user.empresa_id
                    )
                    db.add(nuevo_personal)
                    db.commit()
                    db.refresh(nuevo_personal)
                    
                    if 'visitante' in roles:
                        generar_qr_estatico_para_visitante(db, nuevo_personal)
                        db.commit()
                    
                    exitosos += 1
                    detalles.append({"fila": fila, "mensaje": f"Usuario creado: {nombre}"})
                
                if (idx + 1) % 5 == 0 or idx + 1 == total:
                    yield f"data: {json.dumps({'type': 'progress', 'actual': idx + 1, 'total': total, 'exitosos': exitosos, 'fallidos': fallidos})}\n\n"
            except Exception as e:
                db.rollback()
                fallidos += 1
                errores.append({"fila": fila, "errores": [str(e)]})
        
        if exitosos > 0:
            clear_personal_cache()
        yield f"data: {json.dumps({'type': 'complete', 'exitosos': exitosos, 'fallidos': fallidos, 'detalles': detalles, 'errores': errores})}\n\n"
    
    return StreamingResponse(
        generar_eventos(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.post("/carga-masiva")
async def carga_masiva_personal(
    datos: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_PUEDEN_GESTIONAR_USUARIOS))
):
    dominio = obtener_dominio_empresa(db, current_user.empresa_id)
    resultados = {"exitosos": 0, "fallidos": 0, "detalles": [], "errores": []}
    
    for idx, item in enumerate(datos):
        fila = item.get('_fila', idx + 2)
        try:
            dni = str(item.get('DNI', '') or item.get('dni', '')).strip() or f"PEND{idx+1:04d}"
            cip = limpiar_valor_optional(str(item.get('CIP', '') or item.get('cip', '')).strip())
            grado = str(item.get('GRADO', '') or item.get('grado', '')).strip().upper() or "PENDIENTE"
            nombre = str(item.get('NOMBRE COMPLETO', '') or item.get('nombre', '')).strip().upper() or f"PERSONAL {idx+1}"
            email = limpiar_valor_optional(str(item.get('EMAIL', '') or item.get('email', '')).strip().lower())
            if not email or '@' not in email:
                email = generar_email_interno(nombre, dni, dominio)
            
            area = str(item.get('ÁREA', '') or item.get('area', '')).strip().upper() or "PENDIENTE"
            roles_str = str(item.get('ROLES', '') or item.get('roles', '')).strip()
            roles = [r.strip().lower() for r in roles_str.split(',') if r.strip()] if roles_str else ['usuario']
            
            for rol in roles:
                if rol not in TODOS_LOS_ROLES:
                    raise ValueError(f"Rol inválido: {rol}")
            
            telefono = limpiar_valor_optional(str(item.get('TELÉFONO', '') or item.get('telefono', '')).strip())
            if telefono and not telefono.isdigit():
                telefono = ''.join(c for c in telefono if c.isdigit())
            
            especialidad = limpiar_valor_optional(str(item.get('ESPECIALIDAD', '') or item.get('especialidad', '')).strip())
            
            fecha_nac = item.get('FECHA NACIMIENTO (YYYY-MM-DD)') or item.get('fecha_nacimiento')
            if fecha_nac and isinstance(fecha_nac, str):
                try:
                    fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                except:
                    fecha_nac = None
            
            fecha_ingreso = item.get('FECHA INGRESO (YYYY-MM-DD)') or item.get('fecha_ingreso')
            if fecha_ingreso and isinstance(fecha_ingreso, str):
                try:
                    fecha_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
                except:
                    fecha_ingreso = datetime.now().date()
            else:
                fecha_ingreso = datetime.now().date()
            
            num_colegiatura = limpiar_valor_optional(str(item.get('NÚMERO COLEGIATURA', '') or item.get('numero_colegiatura', '')).strip())
            observaciones = str(item.get('OBSERVACIONES', '') or item.get('observaciones', '')).strip()
            
            areas_jefatura_str = str(item.get('ÁREAS_JEFATURA', '') or item.get('area_jefatura', '')).strip()
            areas_jefatura = [a.strip().upper() for a in areas_jefatura_str.split(',') if a.strip()] if areas_jefatura_str else []
            
            if "jefe" in roles and not areas_jefatura:
                raise ValueError("Los jefes deben tener al menos un área asignada")
            
            query = db.query(Personal)
            if current_user.empresa_id:
                query = query.filter(Personal.empresa_id == current_user.empresa_id)
            
            if cip:
                usuario_existente = query.filter(or_(Personal.dni == dni, Personal.cip == cip)).first()
            else:
                usuario_existente = query.filter(Personal.dni == dni).first()
            
            if usuario_existente:
                if usuario_existente.activo:
                    resultados["fallidos"] += 1
                    resultados["errores"].append({"fila": fila, "errores": [f"Usuario ya existe (DNI: {dni})"]})
                    continue
                else:
                    for key, value in {
                        'grado': grado, 'nombre': nombre, 'email': email,
                        'telefono': telefono, 'fecha_nacimiento': fecha_nac,
                        'area': area, 'especialidad': especialidad,
                        'fecha_ingreso': fecha_ingreso, 'roles': roles,
                        'numero_colegiatura': num_colegiatura,
                        'observaciones': observaciones,
                        'areas_que_jefatura': areas_jefatura
                    }.items():
                        setattr(usuario_existente, key, value)
                    usuario_existente.activo = True
                    db.commit()
                    resultados["exitosos"] += 1
                    resultados["detalles"].append({"fila": fila, "mensaje": f"Usuario reactivado: {nombre}"})
                    continue
            
            nuevo_personal = Personal(
                dni=dni, cip=cip, grado=grado, nombre=nombre,
                email=email, telefono=telefono,
                fecha_nacimiento=fecha_nac, area=area,
                especialidad=especialidad, fecha_ingreso=fecha_ingreso,
                roles=roles, numero_colegiatura=num_colegiatura,
                observaciones=observaciones,
                areas_que_jefatura=areas_jefatura,
                activo=True, condicion='Titular',
                empresa_id=current_user.empresa_id
            )
            db.add(nuevo_personal)
            db.commit()
            db.refresh(nuevo_personal)
            
            if 'visitante' in roles:
                generar_qr_estatico_para_visitante(db, nuevo_personal)
                db.commit()
            
            resultados["exitosos"] += 1
            resultados["detalles"].append({"fila": fila, "mensaje": f"Usuario creado: {nombre}"})
        except Exception as e:
            db.rollback()
            resultados["fallidos"] += 1
            resultados["errores"].append({"fila": fila, "errores": [str(e)]})
    
    if resultados["exitosos"] > 0:
        clear_personal_cache()
    return resultados


# =====================================================
# ENDPOINTS DE RELACIONES Y ELIMINACIÓN
# =====================================================

@router.get("/{id}/tiene-relaciones")
async def verificar_relaciones(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id:
        if personal.empresa_id != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    tiene_planificacion = db.query(Planificacion.id).filter(Planificacion.personal_id == id).first() is not None
    tiene_asistencia = db.query(Asistencia.id).filter(Asistencia.personal_id == id).first() is not None
    tiene_dm = db.query(DescansoMedico.id).filter(DescansoMedico.paciente_id == id).first() is not None
    tiene_solicitudes = db.query(SolicitudCambio.id).filter(
        or_(SolicitudCambio.empleado_id == id, SolicitudCambio.empleado2_id == id)
    ).first() is not None
    tiene_usuario_auth = db.query(Usuario.id).filter(Usuario.personal_id == id).first() is not None
    
    return {
        "tiene_relaciones": tiene_planificacion or tiene_asistencia or tiene_dm or tiene_solicitudes or tiene_usuario_auth,
        "detalles": {
            "planificacion": tiene_planificacion,
            "asistencia": tiene_asistencia,
            "descansos_medicos": tiene_dm,
            "solicitudes": tiene_solicitudes,
            "usuario_auth": tiene_usuario_auth
        }
    }


@router.delete("/{id}/fisico")
async def eliminar_personal_fisico(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id:
        if personal.empresa_id != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    if db.query(Planificacion.id).filter(Planificacion.personal_id == id).first() or \
       db.query(Asistencia.id).filter(Asistencia.personal_id == id).first() or \
       db.query(DescansoMedico.id).filter(DescansoMedico.paciente_id == id).first() or \
       db.query(SolicitudCambio.id).filter(
           or_(SolicitudCambio.empleado_id == id, SolicitudCambio.empleado2_id == id)
       ).first() or \
       db.query(Usuario.id).filter(Usuario.personal_id == id).first():
        raise HTTPException(status_code=400, detail="No se puede eliminar físicamente. Use desactivación.")
    
    db.query(QRRegistro).filter(QRRegistro.empleado_id == id).delete()
    db.delete(personal)
    db.commit()
    clear_personal_cache()
    return {"success": True, "message": "Usuario eliminado físicamente", "id": str(id)}


@router.delete("/{id}")
async def desactivar_personal(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_PUEDEN_GESTIONAR_USUARIOS))
):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id:
        if personal.empresa_id != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    personal.activo = False
    db.commit()
    clear_personal_cache()
    return {"success": True, "message": "Usuario desactivado", "id": str(id), "soft_delete": True}


@router.post("/{id}/restaurar", response_model=PersonalResponse)
async def restaurar_personal(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_PUEDEN_GESTIONAR_USUARIOS))
):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id:
        if personal.empresa_id != current_user.empresa_id:
            raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    if personal.activo:
        raise HTTPException(status_code=400, detail="El usuario ya está activo")
    
    personal.activo = True
    db.commit()
    db.refresh(personal)
    clear_personal_cache()
    return personal


@router.get("/inactivos/lista", response_model=List[PersonalResponse])
async def listar_inactivos(
    limit: int = Query(100),
    offset: int = Query(0),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    query = db.query(Personal).filter(Personal.activo == False)
    if current_user.empresa_id:
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    return query.order_by(Personal.nombre).offset(offset).limit(limit).all()