# api/personal.py
# VERSIÓN CORREGIDA - SOPORTE PARA admin_empresa Y admin_cliente

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

ROLES_VALIDOS = [
    'admin', 'admin_empresa', 'admin_cliente',
    'jefe_grupo', 'jefe_area', 'jefe_departamento',
    'jefe_direccion', 'recursos_humanos', 'oficina_central',
    'oficial_permanencia', 'control_qr', 'usuario', 'visitante'
]

ROLES_JEFATURA = ['jefe_grupo', 'jefe_area', 'jefe_departamento', 'jefe_direccion']
ROLES_ACCESO_GLOBAL = ['admin', 'admin_empresa', 'admin_cliente', 'recursos_humanos', 'oficina_central', 'oficial_permanencia', 'control_qr']
ROLES_ADMIN = ['admin', 'admin_empresa', 'admin_cliente']

# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

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

def procesar_areas_jefatura(areas_que_jefatura: Optional[List], areas_jefatura: Optional[Dict]) -> Dict[str, List[str]]:
    resultado = {'grupo': [], 'area': [], 'departamento': [], 'direccion': []}
    if areas_jefatura and isinstance(areas_jefatura, dict):
        for tipo in resultado.keys():
            if tipo in areas_jefatura and isinstance(areas_jefatura[tipo], list):
                resultado[tipo].extend(areas_jefatura[tipo])
    if areas_que_jefatura and isinstance(areas_que_jefatura, list):
        prefijo_map = {'grupo': 'grupo:', 'area': 'area:', 'departamento': 'depto:', 'direccion': 'direccion:'}
        for tipo, prefijo in prefijo_map.items():
            for item in areas_que_jefatura:
                if isinstance(item, str):
                    if item.startswith(prefijo): resultado[tipo].append(item.replace(prefijo, ''))
                    elif ':' not in item and tipo == 'area': resultado[tipo].append(item)
    for tipo in resultado: resultado[tipo] = list(set(resultado[tipo]))
    return resultado

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
    current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente", "jefe_area", "usuario", "visitante"]))
):
    cache_key = get_cache_key(str(current_user.id), area, grado, busqueda)
    if offset == 0 and limit == 100 and cache_key in personal_cache:
        cached_data, timestamp = personal_cache[cache_key]
        if datetime.now() - timestamp < timedelta(seconds=cache_timeout):
            return cached_data[:limit]
    
    query = db.query(Personal)
    
    # 🆕 Filtro por empresa_id (parámetro explícito o del usuario)
    if empresa_id:
        query = query.filter(Personal.empresa_id == empresa_id)
    elif current_user.empresa_id and current_user.rol_global != "super_admin":
        query = query.filter(Personal.empresa_id == current_user.empresa_id)
    
    roles_usuario = get_roles_usuario(current_user)
    es_usuario_basico = "usuario" in roles_usuario
    es_visitante_user = es_visitante(roles_usuario)
    
    # 🆕 CORREGIDO: incluye admin_empresa y admin_cliente como roles elevados
    tiene_rol_elevado = any(r in roles_usuario for r in ROLES_ACCESO_GLOBAL + ROLES_JEFATURA)
    
    if (es_usuario_basico or es_visitante_user) and not tiene_rol_elevado:
        if current_user.personal_id:
            personal = query.filter(Personal.id == current_user.personal_id).first()
            result = [personal] if personal else []
            personal_cache[cache_key] = (result, datetime.now())
            return result
        return []
    
    if area: query = query.filter(Personal.area == area)
    if grado: query = query.filter(Personal.grado == grado)
    if activo is not None: query = query.filter(Personal.activo == activo)
    elif not incluir_inactivos and not any(r in roles_usuario for r in ROLES_ADMIN):
        query = query.filter(Personal.activo == True)
    if busqueda:
        busqueda_pattern = f"%{busqueda}%"
        query = query.filter(or_(Personal.nombre.ilike(busqueda_pattern), Personal.dni.ilike(busqueda_pattern), Personal.cip.ilike(busqueda_pattern)))
    
    # 🆕 CORREGIDO: no filtrar por jefatura si es admin_empresa o admin_cliente
    if any(r in roles_usuario for r in ROLES_JEFATURA) and not any(r in roles_usuario for r in ROLES_ADMIN):
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            areas_jefatura = procesar_areas_jefatura(jefe.areas_que_jefatura, jefe.areas_jefatura)
            todas_areas = []
            for areas in areas_jefatura.values(): todas_areas.extend(areas)
            if jefe.area and not todas_areas: todas_areas = [jefe.area]
            if todas_areas: query = query.filter(Personal.area.in_(todas_areas))
    
    total = query.count()
    resultados = query.order_by(Personal.area, Personal.grado, Personal.nombre).offset(offset).limit(limit).all()
    if offset == 0: personal_cache[cache_key] = (resultados, datetime.now())
    return resultados


@router.get("/me/jefatura", response_model=JefaturaResumen)
async def obtener_mi_jefatura(db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente", "jefe_area", "jefe_grupo", "jefe_departamento", "jefe_direccion", "recursos_humanos", "oficina_central", "oficial_permanencia", "control_qr", "usuario", "visitante"]))):
    personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
    if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
    tiene_acceso_global = any(rol in personal.roles for rol in ROLES_ACCESO_GLOBAL)
    roles_jefatura = [rol for rol in personal.roles if rol in ROLES_JEFATURA]
    areas_por_tipo = procesar_areas_jefatura(personal.areas_que_jefatura, personal.areas_jefatura)
    if 'jefe_area' in roles_jefatura and not areas_por_tipo.get('area') and personal.area: areas_por_tipo['area'] = [personal.area]
    todas_las_areas = list(set([a for areas in areas_por_tipo.values() for a in areas]))
    return JefaturaResumen(tiene_acceso_global=tiene_acceso_global, roles_jefatura=roles_jefatura, areas_por_tipo=areas_por_tipo, todas_las_areas=todas_las_areas)


@router.get("/jefes/por-area/{area}")
async def listar_jefes_por_area(area: str, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente", "recursos_humanos"]))):
    query = db.query(Personal).filter(Personal.activo == True, Personal.roles.op('&&')(ROLES_JEFATURA))
    if current_user.empresa_id and current_user.rol_global != "super_admin": query = query.filter(Personal.empresa_id == current_user.empresa_id)
    jefes = query.all()
    resultado = {'area': area, 'jefes': {r: [] for r in ROLES_JEFATURA}}
    for jefe in jefes:
        areas_procesadas = procesar_areas_jefatura(jefe.areas_que_jefatura, jefe.areas_jefatura)
        for rol in ROLES_JEFATURA:
            if rol in jefe.roles:
                tipo = rol.replace('jefe_', '')
                if area in areas_procesadas.get(tipo, []):
                    resultado['jefes'][rol].append({'id': str(jefe.id), 'nombre': jefe.nombre, 'grado': jefe.grado, 'email': jefe.email, 'area_trabajo': jefe.area})
                if rol == 'jefe_area' and not areas_procesadas.get('area') and jefe.area == area:
                    resultado['jefes'][rol].append({'id': str(jefe.id), 'nombre': jefe.nombre, 'grado': jefe.grado, 'email': jefe.email, 'area_trabajo': jefe.area})
    return resultado


@router.get("/areas-sin-jefe")
async def listar_areas_sin_jefe(db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente", "recursos_humanos"]))):
    query = db.query(Personal).filter(Personal.activo == True, Personal.roles.op('&&')(ROLES_JEFATURA))
    if current_user.empresa_id and current_user.rol_global != "super_admin": query = query.filter(Personal.empresa_id == current_user.empresa_id)
    jefes = query.all()
    areas_con_jefe = set()
    for jefe in jefes:
        areas_procesadas = procesar_areas_jefatura(jefe.areas_que_jefatura, jefe.areas_jefatura)
        for areas in areas_procesadas.values(): areas_con_jefe.update(areas)
        if 'jefe_area' in jefe.roles and not any(areas_procesadas.values()) and jefe.area: areas_con_jefe.add(jefe.area)
    
    # Usar áreas del organigrama real
    areas_todas = db.query(Personal.area).filter(Personal.activo == True).distinct().all()
    areas_todas = [a[0] for a in areas_todas if a[0]]
    areas_sin_jefe = [a for a in areas_todas if a not in areas_con_jefe]
    return {'total_areas': len(areas_todas), 'areas_con_jefe': len(areas_con_jefe), 'areas_sin_jefe': len(areas_sin_jefe), 'lista_areas_sin_jefe': areas_sin_jefe}


@router.get("/{id}", response_model=PersonalResponse)
async def obtener_personal(id: UUID, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente", "jefe_area", "jefe_grupo", "jefe_departamento", "jefe_direccion", "usuario", "visitante"]))):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if personal.empresa_id != current_user.empresa_id: raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    roles_usuario = get_roles_usuario(current_user)
    es_visitante_user = es_visitante(roles_usuario)
    es_usuario_basico = "usuario" in roles_usuario
    tiene_rol_elevado = any(r in roles_usuario for r in ROLES_ACCESO_GLOBAL + ROLES_JEFATURA)
    
    if (es_usuario_basico or es_visitante_user) and not tiene_rol_elevado:
        if str(current_user.personal_id) != str(id): raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
        return personal
    
    if any(r in roles_usuario for r in ROLES_JEFATURA) and not any(r in roles_usuario for r in ROLES_ADMIN):
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            areas_jefatura = procesar_areas_jefatura(jefe.areas_que_jefatura, jefe.areas_jefatura)
            todas_areas = []
            for areas in areas_jefatura.values(): todas_areas.extend(areas)
            if jefe.area and not todas_areas: todas_areas = [jefe.area]
            if personal.area not in todas_areas: raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    return personal


@router.get("/area/{area}", response_model=List[PersonalResponse])
async def listar_por_area(area: str, activo: Optional[bool] = Query(True), db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente", "jefe_area", "jefe_grupo", "jefe_departamento", "jefe_direccion"]))):
    roles_usuario = get_roles_usuario(current_user)
    if not any(r in roles_usuario for r in ROLES_ADMIN):
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe:
            areas_jefatura = procesar_areas_jefatura(jefe.areas_que_jefatura, jefe.areas_jefatura)
            todas_areas = []
            for areas in areas_jefatura.values(): todas_areas.extend(areas)
            if jefe.area and not todas_areas: todas_areas = [jefe.area]
            if area not in todas_areas: raise HTTPException(status_code=403, detail="No tiene acceso a esta área")
    query = db.query(Personal).filter(Personal.area == area)
    if current_user.empresa_id and current_user.rol_global != "super_admin": query = query.filter(Personal.empresa_id == current_user.empresa_id)
    if activo is not None: query = query.filter(Personal.activo == activo)
    return query.order_by(Personal.grado, Personal.nombre).all()


@router.get("/verificar-dni/{dni}")
async def verificar_dni(dni: str, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    query = db.query(Personal).filter(Personal.dni == dni)
    if current_user.empresa_id and current_user.rol_global != "super_admin": query = query.filter(Personal.empresa_id == current_user.empresa_id)
    usuario = query.first()
    if not usuario: return {"disponible": True, "existe": False, "activo": False}
    return {"disponible": not usuario.activo, "existe": True, "activo": usuario.activo, "id": str(usuario.id), "nombre": usuario.nombre, "email": usuario.email}


@router.post("/", response_model=PersonalResponse, status_code=201)
async def crear_personal(personal_data: PersonalCreate, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    """Crea un nuevo personal. Si es visitante, genera QR estático automáticamente."""
    
    es_visitante_personal = 'visitante' in (personal_data.roles or [])
    
    if not es_visitante_personal and not personal_data.area:
        raise HTTPException(status_code=400, detail="El área de trabajo es obligatoria")
    
    if es_visitante_personal and not personal_data.area:
        personal_data.area = None
    
    areas_procesadas = procesar_areas_jefatura(personal_data.areas_que_jefatura, personal_data.areas_jefatura)
    for rol in ROLES_JEFATURA:
        if rol in personal_data.roles:
            tipo = rol.replace('jefe_', '')
            areas = areas_procesadas.get(tipo, [])
            if rol == 'jefe_area' and not areas and personal_data.area: areas = [personal_data.area]
            if not areas:
                nombres = {'jefe_grupo': 'Jefe de Grupo', 'jefe_area': 'Jefe de Área', 'jefe_departamento': 'Jefe de Departamento', 'jefe_direccion': 'Jefe de Dirección'}
                raise HTTPException(status_code=400, detail=f"Los {nombres[rol]} deben tener al menos un área asignada")
    
    query = db.query(Personal).filter(Personal.dni == personal_data.dni)
    if current_user.empresa_id: query = query.filter(Personal.empresa_id == current_user.empresa_id)
    usuario_existente = query.first()
    if usuario_existente:
        if usuario_existente.activo: raise HTTPException(status_code=400, detail="DNI ya registrado y activo")
        else:
            for key, value in personal_data.model_dump().items(): setattr(usuario_existente, key, value)
            usuario_existente.activo = True
            db.commit(); db.refresh(usuario_existente); clear_personal_cache()
            return usuario_existente
    
    if personal_data.cip is not None:
        query_cip = db.query(Personal).filter(Personal.cip == personal_data.cip, Personal.activo == True)
        if current_user.empresa_id: query_cip = query_cip.filter(Personal.empresa_id == current_user.empresa_id)
        if query_cip.first(): raise HTTPException(status_code=400, detail="CIP ya registrado")
    
    email_existente = db.query(Personal).filter(Personal.email == personal_data.email, Personal.activo == True).first()
    if email_existente: raise HTTPException(status_code=400, detail="Email ya registrado")
    
    personal = Personal(**personal_data.model_dump())
    if current_user.empresa_id: personal.empresa_id = current_user.empresa_id
    
    db.add(personal)
    db.commit()
    db.refresh(personal)
    
    if 'visitante' in (personal.roles or []):
        generar_qr_estatico_para_visitante(db, personal)
        db.commit()
    
    clear_personal_cache()
    return personal


@router.put("/{id}", response_model=PersonalResponse)
async def actualizar_personal(id: UUID, personal_data: PersonalUpdate, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if personal.empresa_id != current_user.empresa_id: raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    roles_actuales = personal_data.roles if personal_data.roles is not None else personal.roles
    es_visitante_actual = 'visitante' in (roles_actuales or [])
    
    areas_que = personal_data.areas_que_jefatura if personal_data.areas_que_jefatura is not None else personal.areas_que_jefatura
    areas_obj = personal_data.areas_jefatura if personal_data.areas_jefatura is not None else personal.areas_jefatura
    area_trabajo = personal_data.area if personal_data.area is not None else personal.area
    areas_procesadas = procesar_areas_jefatura(areas_que, areas_obj)
    
    if not es_visitante_actual:
        for rol in ROLES_JEFATURA:
            if rol in roles_actuales:
                tipo = rol.replace('jefe_', '')
                areas = areas_procesadas.get(tipo, [])
                if rol == 'jefe_area' and not areas and area_trabajo: areas = [area_trabajo]
                if not areas:
                    nombres = {'jefe_grupo': 'Jefe de Grupo', 'jefe_area': 'Jefe de Área', 'jefe_departamento': 'Jefe de Departamento', 'jefe_direccion': 'Jefe de Dirección'}
                    raise HTTPException(status_code=400, detail=f"Los {nombres[rol]} deben tener al menos un área asignada")
    
    if personal_data.dni and personal_data.dni != personal.dni:
        query = db.query(Personal).filter(Personal.dni == personal_data.dni, Personal.activo == True)
        if current_user.empresa_id: query = query.filter(Personal.empresa_id == current_user.empresa_id)
        if query.first(): raise HTTPException(status_code=400, detail="DNI ya registrado")
    
    if personal_data.cip is not None and personal_data.cip != personal.cip:
        query = db.query(Personal).filter(Personal.cip == personal_data.cip, Personal.activo == True)
        if current_user.empresa_id: query = query.filter(Personal.empresa_id == current_user.empresa_id)
        if query.first(): raise HTTPException(status_code=400, detail="CIP ya registrado")
    
    if personal_data.email and personal_data.email != personal.email:
        if db.query(Personal).filter(Personal.email == personal_data.email, Personal.activo == True).first(): raise HTTPException(status_code=400, detail="Email ya registrado")
    
    era_visitante = 'visitante' in (personal.roles or [])
    update_data = personal_data.model_dump(exclude_unset=True)
    for field, value in update_data.items(): setattr(personal, field, value)
    db.commit()
    db.refresh(personal)
    
    es_visitante_ahora = 'visitante' in (personal.roles or [])
    if es_visitante_ahora and not era_visitante:
        qr_existente = db.query(QRRegistro).filter(QRRegistro.empleado_id == personal.id, QRRegistro.tipo == "visitante").first()
        if not qr_existente:
            generar_qr_estatico_para_visitante(db, personal)
            db.commit()
    
    clear_personal_cache()
    return personal


# =====================================================
# CARGA MASIVA
# =====================================================

@router.post("/carga-masiva-stream")
async def carga_masiva_stream(datos: List[Dict[str, Any]], db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    dominio = obtener_dominio_empresa(db, current_user.empresa_id)
    async def generar_eventos():
        total = len(datos); exitosos = 0; fallidos = 0; detalles = []; errores = []
        yield f"data: {json.dumps({'type': 'start', 'total': total})}\n\n"
        for idx, item in enumerate(datos):
            fila = item.get('_fila', idx + 2)
            try:
                dni = str(item.get('DNI', '') or item.get('dni', '')).strip() or f"PEND{idx+1:04d}"
                cip = str(item.get('CIP', '') or item.get('cip', '')).strip() or f"CIP{idx+1:04d}"
                grado = str(item.get('GRADO', '') or item.get('grado', '')).strip().upper() or "PENDIENTE"
                nombre = str(item.get('NOMBRE COMPLETO', '') or item.get('nombre', '')).strip().upper() or f"PERSONAL {idx+1}"
                email = str(item.get('EMAIL', '') or item.get('email', '')).strip().lower()
                if not email or '@' not in email: email = generar_email_interno(nombre, dni, dominio)
                area = str(item.get('ÁREA', '') or item.get('area', '')).strip().upper() or "PENDIENTE"
                roles_str = str(item.get('ROLES', '') or item.get('roles', '')).strip()
                roles = [r.strip().lower() for r in roles_str.split(',') if r.strip()] if roles_str else ['usuario']
                telefono = str(item.get('TELÉFONO', '') or item.get('telefono', '')).strip()
                if telefono and not telefono.isdigit(): telefono = ''.join(c for c in telefono if c.isdigit())
                especialidad = str(item.get('ESPECIALIDAD', '') or item.get('especialidad', '')).strip()
                fecha_nac = item.get('FECHA NACIMIENTO (YYYY-MM-DD)') or item.get('fecha_nacimiento')
                if fecha_nac and isinstance(fecha_nac, str):
                    try: fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                    except: fecha_nac = None
                fecha_ingreso = item.get('FECHA INGRESO (YYYY-MM-DD)') or item.get('fecha_ingreso')
                if fecha_ingreso and isinstance(fecha_ingreso, str):
                    try: fecha_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
                    except: fecha_ingreso = datetime.now().date()
                else: fecha_ingreso = datetime.now().date()
                num_colegiatura = str(item.get('NÚMERO COLEGIATURA', '') or item.get('numero_colegiatura', '')).strip() or None
                observaciones = str(item.get('OBSERVACIONES', '') or item.get('observaciones', '')).strip()
                areas_jefatura_str = str(item.get('ÁREAS_JEFATURA', '') or item.get('area_jefatura', '')).strip()
                areas_jefatura = [a.strip().upper() for a in areas_jefatura_str.split(',') if a.strip()] if areas_jefatura_str else []
                if "jefe_area" in roles and not areas_jefatura: raise ValueError("Los jefes de área deben tener al menos un área asignada")
                
                query = db.query(Personal)
                if current_user.empresa_id: query = query.filter(Personal.empresa_id == current_user.empresa_id)
                usuario_existente = query.filter(or_(Personal.dni == dni, Personal.cip == cip if not cip.startswith('CIP') else False)).first()
                
                if usuario_existente:
                    if usuario_existente.activo:
                        fallidos += 1; errores.append({"fila": fila, "errores": [f"Usuario ya existe (DNI: {dni})"]})
                    else:
                        for key, value in {'grado': grado, 'nombre': nombre, 'email': email, 'telefono': telefono or None, 'fecha_nacimiento': fecha_nac, 'area': area, 'especialidad': especialidad, 'fecha_ingreso': fecha_ingreso, 'roles': roles, 'numero_colegiatura': num_colegiatura, 'observaciones': observaciones, 'areas_que_jefatura': areas_jefatura}.items(): setattr(usuario_existente, key, value)
                        usuario_existente.activo = True; db.commit()
                        exitosos += 1; detalles.append({"fila": fila, "mensaje": f"Usuario reactivado: {nombre}"})
                else:
                    nuevo_personal = Personal(dni=dni, cip=cip, grado=grado, nombre=nombre, email=email, telefono=telefono or None, fecha_nacimiento=fecha_nac, area=area, especialidad=especialidad, fecha_ingreso=fecha_ingreso, roles=roles, numero_colegiatura=num_colegiatura, observaciones=observaciones, areas_que_jefatura=areas_jefatura, activo=True, condicion='Titular', empresa_id=current_user.empresa_id)
                    db.add(nuevo_personal); db.commit(); db.refresh(nuevo_personal)
                    if 'visitante' in roles: generar_qr_estatico_para_visitante(db, nuevo_personal); db.commit()
                    exitosos += 1; detalles.append({"fila": fila, "mensaje": f"Usuario creado: {nombre}"})
                if (idx + 1) % 5 == 0 or idx + 1 == total: yield f"data: {json.dumps({'type': 'progress', 'actual': idx + 1, 'total': total, 'exitosos': exitosos, 'fallidos': fallidos})}\n\n"
            except Exception as e: db.rollback(); fallidos += 1; errores.append({"fila": fila, "errores": [str(e)]})
        if exitosos > 0: clear_personal_cache()
        yield f"data: {json.dumps({'type': 'complete', 'exitosos': exitosos, 'fallidos': fallidos, 'detalles': detalles, 'errores': errores})}\n\n"
    return StreamingResponse(generar_eventos(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"})


@router.post("/carga-masiva")
async def carga_masiva_personal(datos: List[Dict[str, Any]], db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    dominio = obtener_dominio_empresa(db, current_user.empresa_id)
    resultados = {"exitosos": 0, "fallidos": 0, "detalles": [], "errores": []}
    for idx, item in enumerate(datos):
        fila = item.get('_fila', idx + 2)
        try:
            dni = str(item.get('DNI', '') or item.get('dni', '')).strip() or f"PEND{idx+1:04d}"
            cip = str(item.get('CIP', '') or item.get('cip', '')).strip() or f"CIP{idx+1:04d}"
            grado = str(item.get('GRADO', '') or item.get('grado', '')).strip().upper() or "PENDIENTE"
            nombre = str(item.get('NOMBRE COMPLETO', '') or item.get('nombre', '')).strip().upper() or f"PERSONAL {idx+1}"
            email = str(item.get('EMAIL', '') or item.get('email', '')).strip().lower()
            if not email or '@' not in email: email = generar_email_interno(nombre, dni, dominio)
            area = str(item.get('ÁREA', '') or item.get('area', '')).strip().upper() or "PENDIENTE"
            roles_str = str(item.get('ROLES', '') or item.get('roles', '')).strip()
            roles = [r.strip().lower() for r in roles_str.split(',') if r.strip()] if roles_str else ['usuario']
            telefono = str(item.get('TELÉFONO', '') or item.get('telefono', '')).strip()
            if telefono and not telefono.isdigit(): telefono = ''.join(c for c in telefono if c.isdigit())
            especialidad = str(item.get('ESPECIALIDAD', '') or item.get('especialidad', '')).strip()
            fecha_nac = item.get('FECHA NACIMIENTO (YYYY-MM-DD)') or item.get('fecha_nacimiento')
            if fecha_nac and isinstance(fecha_nac, str):
                try: fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                except: fecha_nac = None
            fecha_ingreso = item.get('FECHA INGRESO (YYYY-MM-DD)') or item.get('fecha_ingreso')
            if fecha_ingreso and isinstance(fecha_ingreso, str):
                try: fecha_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
                except: fecha_ingreso = datetime.now().date()
            else: fecha_ingreso = datetime.now().date()
            num_colegiatura = str(item.get('NÚMERO COLEGIATURA', '') or item.get('numero_colegiatura', '')).strip() or None
            observaciones = str(item.get('OBSERVACIONES', '') or item.get('observaciones', '')).strip()
            areas_jefatura_str = str(item.get('ÁREAS_JEFATURA', '') or item.get('area_jefatura', '')).strip()
            areas_jefatura = [a.strip().upper() for a in areas_jefatura_str.split(',') if a.strip()] if areas_jefatura_str else []
            if "jefe_area" in roles and not areas_jefatura: raise ValueError("Los jefes de área deben tener al menos un área asignada")
            
            query = db.query(Personal)
            if current_user.empresa_id: query = query.filter(Personal.empresa_id == current_user.empresa_id)
            usuario_existente = query.filter(or_(Personal.dni == dni, Personal.cip == cip if not cip.startswith('CIP') else False)).first()
            if usuario_existente:
                if usuario_existente.activo: resultados["fallidos"] += 1; resultados["errores"].append({"fila": fila, "errores": [f"Usuario ya existe (DNI: {dni})"]}); continue
                else:
                    for key, value in {'grado': grado, 'nombre': nombre, 'email': email, 'telefono': telefono or None, 'fecha_nacimiento': fecha_nac, 'area': area, 'especialidad': especialidad, 'fecha_ingreso': fecha_ingreso, 'roles': roles, 'numero_colegiatura': num_colegiatura, 'observaciones': observaciones, 'areas_que_jefatura': areas_jefatura}.items(): setattr(usuario_existente, key, value)
                    usuario_existente.activo = True; db.commit()
                    resultados["exitosos"] += 1; resultados["detalles"].append({"fila": fila, "mensaje": f"Usuario reactivado: {nombre}"}); continue
            nuevo_personal = Personal(dni=dni, cip=cip, grado=grado, nombre=nombre, email=email, telefono=telefono or None, fecha_nacimiento=fecha_nac, area=area, especialidad=especialidad, fecha_ingreso=fecha_ingreso, roles=roles, numero_colegiatura=num_colegiatura, observaciones=observaciones, areas_que_jefatura=areas_jefatura, activo=True, condicion='Titular', empresa_id=current_user.empresa_id)
            db.add(nuevo_personal); db.commit(); db.refresh(nuevo_personal)
            if 'visitante' in roles: generar_qr_estatico_para_visitante(db, nuevo_personal); db.commit()
            resultados["exitosos"] += 1; resultados["detalles"].append({"fila": fila, "mensaje": f"Usuario creado: {nombre}"})
        except Exception as e: db.rollback(); resultados["fallidos"] += 1; resultados["errores"].append({"fila": fila, "errores": [str(e)]})
    if resultados["exitosos"] > 0: clear_personal_cache()
    return resultados


# =====================================================
# ENDPOINTS DE RELACIONES Y ELIMINACIÓN
# =====================================================

@router.get("/{id}/tiene-relaciones")
async def verificar_relaciones(id: UUID, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if personal.empresa_id != current_user.empresa_id: raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    tiene_planificacion = db.query(Planificacion.id).filter(Planificacion.personal_id == id).first() is not None
    tiene_asistencia = db.query(Asistencia.id).filter(Asistencia.personal_id == id).first() is not None
    tiene_dm = db.query(DescansoMedico.id).filter(DescansoMedico.paciente_id == id).first() is not None
    tiene_solicitudes = db.query(SolicitudCambio.id).filter(or_(SolicitudCambio.empleado_id == id, SolicitudCambio.empleado2_id == id)).first() is not None
    tiene_usuario_auth = db.query(Usuario.id).filter(Usuario.personal_id == id).first() is not None
    return {"tiene_relaciones": tiene_planificacion or tiene_asistencia or tiene_dm or tiene_solicitudes or tiene_usuario_auth, "detalles": {"planificacion": tiene_planificacion, "asistencia": tiene_asistencia, "descansos_medicos": tiene_dm, "solicitudes": tiene_solicitudes, "usuario_auth": tiene_usuario_auth}}


@router.delete("/{id}/fisico")
async def eliminar_personal_fisico(id: UUID, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin"]))):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if personal.empresa_id != current_user.empresa_id: raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    if db.query(Planificacion.id).filter(Planificacion.personal_id == id).first() or db.query(Asistencia.id).filter(Asistencia.personal_id == id).first() or db.query(DescansoMedico.id).filter(DescansoMedico.paciente_id == id).first() or db.query(SolicitudCambio.id).filter(or_(SolicitudCambio.empleado_id == id, SolicitudCambio.empleado2_id == id)).first() or db.query(Usuario.id).filter(Usuario.personal_id == id).first(): raise HTTPException(status_code=400, detail="No se puede eliminar físicamente. Use desactivación.")
    
    db.query(QRRegistro).filter(QRRegistro.empleado_id == id).delete()
    db.delete(personal); db.commit(); clear_personal_cache()
    return {"success": True, "message": "Usuario eliminado físicamente", "id": str(id)}


@router.delete("/{id}")
async def desactivar_personal(id: UUID, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if personal.empresa_id != current_user.empresa_id: raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    personal.activo = False; db.commit(); clear_personal_cache()
    return {"success": True, "message": "Usuario desactivado", "id": str(id), "soft_delete": True}


@router.post("/{id}/restaurar", response_model=PersonalResponse)
async def restaurar_personal(id: UUID, db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal: raise HTTPException(status_code=404, detail="Personal no encontrado")
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if personal.empresa_id != current_user.empresa_id: raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    if personal.activo: raise HTTPException(status_code=400, detail="El usuario ya está activo")
    personal.activo = True; db.commit(); db.refresh(personal); clear_personal_cache()
    return personal


@router.get("/inactivos/lista", response_model=List[PersonalResponse])
async def listar_inactivos(limit: int = Query(100), offset: int = Query(0), db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(["admin", "admin_empresa", "admin_cliente"]))):
    query = db.query(Personal).filter(Personal.activo == False)
    if current_user.empresa_id and current_user.rol_global != "super_admin": query = query.filter(Personal.empresa_id == current_user.empresa_id)
    return query.order_by(Personal.nombre).offset(offset).limit(limit).all()