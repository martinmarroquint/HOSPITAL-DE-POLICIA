# api/personal.py
# VERSIÓN FINAL - JERARQUÍA RECURSIVA - CARGA MASIVA FUNCIONAL

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
    roles = get_roles_usuario(user)
    return any(r in ROLES_ADMIN for r in roles)

def es_jefe(user: Usuario) -> bool:
    roles = get_roles_usuario(user)
    return any(r in ROLES_JEFE for r in roles)

def tiene_acceso_global(user: Usuario) -> bool:
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
    if not areas and hasattr(personal_data, 'area') and personal_data.area:
        areas = [personal_data.area]
    return list(set(areas))

def get_areas_jefatura(jefe: Personal) -> List[str]:
    """Obtiene las áreas directas que jefatura una persona"""
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
    if not areas and jefe.area:
        areas = [jefe.area]
    return list(set(areas))

# =====================================================
# 🆕 FUNCIÓN: Obtener áreas hijas del organigrama
# =====================================================

def _obtener_areas_hijas_organigrama(db: Session, empresa_id: UUID) -> Dict[str, List[str]]:
    """
    Consulta el organigrama y devuelve un diccionario:
    { nombre_padre: [nombre_hija1, nombre_hija2, ...] }
    """
    try:
        from app.models.configuracion import UnidadOrganigrama
        
        unidades = db.query(UnidadOrganigrama).filter(
            UnidadOrganigrama.empresa_id == empresa_id
        ).all()
        
        if not unidades:
            return {}
        
        unidad_map = {u.id: u for u in unidades}
        hijos_por_padre = {}
        
        for u in unidades:
            if u.padre_id and u.padre_id in unidad_map:
                padre_nombre = unidad_map[u.padre_id].nombre
                if padre_nombre not in hijos_por_padre:
                    hijos_por_padre[padre_nombre] = []
                hijos_por_padre[padre_nombre].append(u.nombre)
        
        return hijos_por_padre
    except Exception as e:
        logger.warning(f"No se pudo cargar organigrama: {e}")
        return {}


def _expandir_areas_con_hijas(areas_directas: List[str], hijos_por_padre: Dict[str, List[str]]) -> List[str]:
    """
    Dado un conjunto de áreas directas, obtiene recursivamente todas las áreas hijas.
    Ej: ['INICIAL'] -> ['INICIAL', '3 AÑOS', '4 AÑOS', '5 AÑOS']
    """
    todas = set(areas_directas)
    visitados = set()
    
    def obtener_recursivo(nombre_area):
        if nombre_area in visitados:
            return
        visitados.add(nombre_area)
        hijas = hijos_por_padre.get(nombre_area, [])
        for hija in hijas:
            todas.add(hija)
            obtener_recursivo(hija)
    
    for area in areas_directas:
        obtener_recursivo(area)
    
    return list(todas)


# =====================================================
# 🆕 get_subordinados CORREGIDO - CON JERARQUÍA RECURSIVA
# =====================================================

def get_subordinados(db: Session, jefe: Personal) -> List[Personal]:
    """
    Obtiene todos los subordinados de un jefe según la jerarquía.
    Busca en las áreas directas Y en las áreas hijas del organigrama.
    """
    areas_directas = get_areas_jefatura(jefe)
    
    if not areas_directas:
        return []
    
    # 🆕 Expandir áreas con las hijas del organigrama
    hijos_por_padre = _obtener_areas_hijas_organigrama(db, jefe.empresa_id)
    
    if hijos_por_padre:
        todas_las_areas = _expandir_areas_con_hijas(areas_directas, hijos_por_padre)
    else:
        todas_las_areas = areas_directas
    
    logger.info(f"Jefe {jefe.nombre}: áreas directas={areas_directas}, total con hijas={todas_las_areas}")
    
    # Buscar subordinados en TODAS las áreas (directas + hijas)
    subordinados = db.query(Personal).filter(
        Personal.activo == True,
        Personal.area.in_(todas_las_areas),
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
    
    # 🆕 Jefe puede ver a sus subordinados (incluye áreas hijas)
    if any(r in ROLES_JEFE for r in roles_usuario):
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            subordinados = get_subordinados(db, jefe)
            sub_ids = [str(s.id) for s in subordinados]
            if str(personal.id) in sub_ids:
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
        Personal.dni != '00000001',
        Personal.dni != '00000000',
        ~Personal.nombre.ilike('%SUPER ADMINISTRADOR%')
    )
    
    if empresa_id:
        query = query.filter(Personal.empresa_id == empresa_id)
    elif current_user.empresa_id:
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    
    roles_usuario = get_roles_usuario(current_user)
    
    if not tiene_acceso_global(current_user) and not any(r in ROLES_SOLO_LECTURA for r in roles_usuario if r not in ROLES_SOLO_ESCANER):
        if current_user.personal_id:
            personal = query.filter(Personal.id == current_user.personal_id).first()
            result = [personal] if personal else []
            personal_cache[cache_key] = (result, datetime.now())
            return result
        return []
    
    # 🆕 Jefe ve a sus subordinados (áreas directas + hijas del organigrama)
    if es_jefe(current_user) and not es_admin(current_user):
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            subordinados = get_subordinados(db, jefe)
            sub_ids = [s.id for s in subordinados]
            sub_ids.append(jefe.id)  # Incluirse a sí mismo
            query = query.filter(Personal.id.in_(sub_ids))
    
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
    
    # 🆕 Obtener áreas expandidas con hijas
    areas_directas = get_areas_jefatura(personal) if es_jefe(current_user) else []
    hijos_por_padre = _obtener_areas_hijas_organigrama(db, personal.empresa_id)
    
    if hijos_por_padre:
        todas_las_areas = _expandir_areas_con_hijas(areas_directas, hijos_por_padre)
    else:
        todas_las_areas = areas_directas
    
    roles_jefatura = ["jefe"] if es_jefe(current_user) else []
    
    return JefaturaResumen(
        tiene_acceso_global=tiene_acceso_global(current_user),
        roles_jefatura=roles_jefatura,
        areas_por_tipo={"area": todas_las_areas},
        todas_las_areas=todas_las_areas
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
    
    # 🆕 Jefe ve sus subordinados (con áreas hijas)
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
    
    if 'jefe' in (personal_data.roles or []):
        areas = get_areas_jefatura_from_data(personal_data)
        if not areas:
            raise HTTPException(status_code=400, detail="Los jefes deben tener al menos un área asignada para jefaturar")
    
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
    
    if personal_data.cip and personal_data.cip.strip():
        query_cip = db.query(Personal).filter(
            Personal.cip == personal_data.cip,
            Personal.activo == True
        )
        if current_user.empresa_id:
            query_cip = query_cip.filter(Personal.empresa_id == current_user.empresa_id)
        if query_cip.first():
            raise HTTPException(status_code=400, detail="CIP ya registrado")
    
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
    
    if personal_data.dni and personal_data.dni != personal.dni:
        query = db.query(Personal).filter(Personal.dni == personal_data.dni, Personal.activo == True)
        if current_user.empresa_id:
            query = query.filter(Personal.empresa_id == current_user.empresa_id)
        if query.first():
            raise HTTPException(status_code=400, detail="DNI ya registrado")
    
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
    empresa_id = current_user.empresa_id
    
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
                dni = str(item.get('dni', '') or item.get('DNI', '')).strip() or f"PEND{idx+1:04d}"
                cip = limpiar_valor_optional(str(item.get('cip', '') or item.get('CIP', '')).strip())
                grado = str(item.get('grado', '') or item.get('GRADO', '')).strip().upper() or "PENDIENTE"
                nombre = str(item.get('nombre', '') or item.get('NOMBRE COMPLETO', '') or item.get('NOMBRE', '')).strip().upper() or f"PERSONAL {idx+1}"
                email = limpiar_valor_optional(str(item.get('email', '') or item.get('EMAIL', '')).strip().lower())
                if not email or '@' not in email:
                    email = generar_email_interno(nombre, dni, dominio)
                
                area = str(item.get('area', '') or item.get('ÁREA', '') or item.get('AREA', '')).strip().upper() or "PENDIENTE"
                
                roles_val = item.get('roles') or item.get('ROLES') or ''
                if isinstance(roles_val, list):
                    roles_str = ','.join(roles_val)
                else:
                    roles_str = str(roles_val).strip()
                roles = [r.strip().lower() for r in roles_str.split(',') if r.strip()] if roles_str else ['usuario']
                
                for rol in roles:
                    if rol not in TODOS_LOS_ROLES:
                        raise ValueError(f"Rol inválido: {rol}")
                
                telefono = limpiar_valor_optional(str(item.get('telefono', '') or item.get('TELÉFONO', '') or item.get('TELEFONO', '')).strip())
                if telefono and not telefono.isdigit():
                    telefono = ''.join(c for c in telefono if c.isdigit())
                
                especialidad = limpiar_valor_optional(str(item.get('especialidad', '') or item.get('ESPECIALIDAD', '')).strip())
                sexo = str(item.get('sexo', '') or item.get('SEXO', '') or 'No especificado').strip()
                
                fecha_nac = item.get('fecha_nacimiento') or item.get('FECHA NACIMIENTO (YYYY-MM-DD)') or item.get('FECHA NACIMIENTO')
                if fecha_nac and isinstance(fecha_nac, str):
                    try:
                        fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                    except:
                        fecha_nac = None
                
                fecha_ingreso = item.get('fecha_ingreso') or item.get('FECHA INGRESO (YYYY-MM-DD)') or item.get('FECHA INGRESO')
                if fecha_ingreso and isinstance(fecha_ingreso, str):
                    try:
                        fecha_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
                    except:
                        fecha_ingreso = datetime.now().date()
                else:
                    fecha_ingreso = datetime.now().date()
                
                num_colegiatura = limpiar_valor_optional(str(item.get('numero_colegiatura', '') or item.get('NÚMERO COLEGIATURA', '') or item.get('NUMERO COLEGIATURA', '')).strip())
                observaciones = str(item.get('observaciones', '') or item.get('OBSERVACIONES', '')).strip()
                
                areas_jefatura_str = str(item.get('area_jefatura', '') or item.get('ÁREAS_JEFATURA', '') or item.get('AREAS_JEFATURA', '')).strip()
                areas_jefatura = [a.strip().upper() for a in areas_jefatura_str.split(',') if a.strip()] if areas_jefatura_str else []
                
                if "jefe" in roles and not areas_jefatura:
                    raise ValueError("Los jefes deben tener al menos un área asignada")
                
                usuario_existente = db.query(Personal).filter(
                    Personal.dni == dni,
                    Personal.activo == True,
                    Personal.empresa_id == empresa_id
                ).first()
                
                if not usuario_existente and cip:
                    usuario_existente = db.query(Personal).filter(
                        Personal.cip == cip,
                        Personal.activo == True,
                        Personal.empresa_id == empresa_id
                    ).first()
                
                if usuario_existente:
                    fallidos += 1
                    errores.append({"fila": fila, "errores": [f"Usuario ya existe (DNI: {dni})"]})
                else:
                    nuevo_personal = Personal(
                        dni=dni, cip=cip, grado=grado, nombre=nombre,
                        email=email, telefono=telefono, sexo=sexo,
                        fecha_nacimiento=fecha_nac, area=area,
                        especialidad=especialidad, fecha_ingreso=fecha_ingreso,
                        roles=roles, numero_colegiatura=num_colegiatura,
                        observaciones=observaciones,
                        areas_que_jefatura=areas_jefatura,
                        activo=True, condicion='Titular',
                        empresa_id=empresa_id
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
    empresa_id = current_user.empresa_id
    resultados = {"exitosos": 0, "fallidos": 0, "detalles": [], "errores": []}
    
    for idx, item in enumerate(datos):
        fila = item.get('_fila', idx + 2)
        try:
            dni = str(item.get('dni', '') or item.get('DNI', '')).strip() or f"PEND{idx+1:04d}"
            cip = limpiar_valor_optional(str(item.get('cip', '') or item.get('CIP', '')).strip())
            grado = str(item.get('grado', '') or item.get('GRADO', '')).strip().upper() or "PENDIENTE"
            nombre = str(item.get('nombre', '') or item.get('NOMBRE COMPLETO', '')).strip().upper() or f"PERSONAL {idx+1}"
            email = limpiar_valor_optional(str(item.get('email', '') or item.get('EMAIL', '')).strip().lower())
            if not email or '@' not in email:
                email = generar_email_interno(nombre, dni, dominio)
            
            area = str(item.get('area', '') or item.get('ÁREA', '')).strip().upper() or "PENDIENTE"
            
            roles_val = item.get('roles') or item.get('ROLES') or ''
            if isinstance(roles_val, list):
                roles_str = ','.join(roles_val)
            else:
                roles_str = str(roles_val).strip()
            roles = [r.strip().lower() for r in roles_str.split(',') if r.strip()] if roles_str else ['usuario']
            
            for rol in roles:
                if rol not in TODOS_LOS_ROLES:
                    raise ValueError(f"Rol inválido: {rol}")
            
            telefono = limpiar_valor_optional(str(item.get('telefono', '') or item.get('TELÉFONO', '')).strip())
            if telefono and not telefono.isdigit():
                telefono = ''.join(c for c in telefono if c.isdigit())
            
            especialidad = limpiar_valor_optional(str(item.get('especialidad', '') or item.get('ESPECIALIDAD', '')).strip())
            sexo = str(item.get('sexo', '') or item.get('SEXO', '') or 'No especificado').strip()
            
            fecha_nac = item.get('fecha_nacimiento') or item.get('FECHA NACIMIENTO (YYYY-MM-DD)')
            if fecha_nac and isinstance(fecha_nac, str):
                try:
                    fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                except:
                    fecha_nac = None
            
            fecha_ingreso = item.get('fecha_ingreso') or item.get('FECHA INGRESO (YYYY-MM-DD)')
            if fecha_ingreso and isinstance(fecha_ingreso, str):
                try:
                    fecha_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
                except:
                    fecha_ingreso = datetime.now().date()
            else:
                fecha_ingreso = datetime.now().date()
            
            num_colegiatura = limpiar_valor_optional(str(item.get('numero_colegiatura', '') or item.get('NÚMERO COLEGIATURA', '')).strip())
            observaciones = str(item.get('observaciones', '') or item.get('OBSERVACIONES', '')).strip()
            
            areas_jefatura_str = str(item.get('area_jefatura', '') or item.get('ÁREAS_JEFATURA', '')).strip()
            areas_jefatura = [a.strip().upper() for a in areas_jefatura_str.split(',') if a.strip()] if areas_jefatura_str else []
            
            if "jefe" in roles and not areas_jefatura:
                raise ValueError("Los jefes deben tener al menos un área asignada")
            
            usuario_existente = db.query(Personal).filter(
                Personal.dni == dni,
                Personal.activo == True,
                Personal.empresa_id == empresa_id
            ).first()
            
            if not usuario_existente and cip:
                usuario_existente = db.query(Personal).filter(
                    Personal.cip == cip,
                    Personal.activo == True,
                    Personal.empresa_id == empresa_id
                ).first()
            
            if usuario_existente:
                resultados["fallidos"] += 1
                resultados["errores"].append({"fila": fila, "errores": [f"Usuario ya existe (DNI: {dni})"]})
                continue
            
            nuevo_personal = Personal(
                dni=dni, cip=cip, grado=grado, nombre=nombre,
                email=email, telefono=telefono, sexo=sexo,
                fecha_nacimiento=fecha_nac, area=area,
                especialidad=especialidad, fecha_ingreso=fecha_ingreso,
                roles=roles, numero_colegiatura=num_colegiatura,
                observaciones=observaciones,
                areas_que_jefatura=areas_jefatura,
                activo=True, condicion='Titular',
                empresa_id=empresa_id
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
# HABILITAR LOTE
# =====================================================

def hash_password(password: str) -> str:
    """Hash simple de contraseña (ajustar según tu sistema)"""
    import hashlib
    return hashlib.sha256(password.encode()).hexdigest()


@router.post("/habilitar-lote")
async def habilitar_lote_usuarios(
    datos: Dict[str, Any],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_PUEDEN_GESTIONAR_USUARIOS))
):
    """
    Habilita múltiples usuarios generando credenciales.
    """
    ids = datos.get('usuarios', [])
    dominio = datos.get('dominio') or obtener_dominio_empresa(db, current_user.empresa_id)
    
    credenciales = []
    errores = []
    
    for user_id in ids:
        try:
            personal = db.query(Personal).filter(
                Personal.id == UUID(user_id),
                Personal.activo == True,
                Personal.empresa_id == current_user.empresa_id
            ).first()
            
            if not personal:
                errores.append({"id": user_id, "error": "No encontrado"})
                continue
            
            usuario_existente = db.query(Usuario).filter(
                Usuario.personal_id == personal.id
            ).first()
            
            if usuario_existente and usuario_existente.activo:
                credenciales.append({
                    "id": str(personal.id),
                    "nombre": personal.nombre,
                    "email": personal.email or generar_email_interno(personal.nombre, personal.dni, dominio),
                    "password": "***YA ACTIVO***",
                    "area": personal.area,
                    "estado": "ya_activo"
                })
                continue
            
            email = personal.email
            if not email or '@' not in email or (email.endswith('@sistema.com') and dominio != 'sistema.com'):
                email = generar_email_interno(personal.nombre, personal.dni, dominio)
                personal.email = email
            
            password = secrets.token_urlsafe(8)[:10]
            
            if usuario_existente:
                usuario_existente.activo = True
                usuario_existente.email = email
                usuario_existente.password_hash = hash_password(password)
            else:
                nuevo_usuario = Usuario(
                    personal_id=personal.id,
                    email=email,
                    password_hash=hash_password(password),
                    roles=[r for r in (personal.roles or []) if r != 'visitante'] or ['usuario'],
                    activo=True,
                    empresa_id=current_user.empresa_id
                )
                db.add(nuevo_usuario)
            
            db.commit()
            
            credenciales.append({
                "id": str(personal.id),
                "nombre": personal.nombre,
                "email": email,
                "password": password,
                "area": personal.area or '',
                "estado": "creado"
            })
            
        except Exception as e:
            db.rollback()
            errores.append({"id": user_id, "error": str(e)})
    
    return {
        "total": len(credenciales),
        "credenciales": credenciales,
        "errores": errores
    }


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