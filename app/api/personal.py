from fastapi import APIRouter, Depends, HTTPException, status, Query, UploadFile, File
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from typing import List, Optional, Dict, Any
from uuid import UUID
from functools import lru_cache
from datetime import datetime, timedelta
import pandas as pd
import io
import json
import unicodedata
import asyncio

from app.database import get_db
from app.core.dependencies import require_roles, get_current_user_id
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.models.planificacion import Planificacion
from app.models.asistencia import Asistencia
from app.models.descanso_medico import DescansoMedico
from app.models.solicitud_cambio import SolicitudCambio
from app.schemas.personal import PersonalCreate, PersonalUpdate, PersonalResponse, CargaMasivaItem

router = APIRouter()

# =====================================================
# CACHE EN MEMORIA (2 minutos)
# =====================================================
personal_cache = {}
cache_timeout = 120  # 2 minutos

def clear_personal_cache():
    """Limpia todo el caché de personal"""
    global personal_cache
    personal_cache.clear()

def get_cache_key(user_id: str, area: Optional[str], grado: Optional[str], busqueda: Optional[str]) -> str:
    """Genera clave única para caché"""
    return f"{user_id}-{area}-{grado}-{busqueda}"

# =====================================================
# LISTAS COMPLETAS DE GRADOS Y ÁREAS
# =====================================================

GRADOS_VALIDOS = [
    # Oficiales Generales
    'GENERAL PNP', 'GENERAL SPNP',
    # Oficiales Superiores
    'CRNL PNP', 'CRNL SPNP',
    'CMDT PNP', 'CMDT SPNP',
    # Oficiales Subalternos
    'MAY PNP', 'MAY SPNP',
    'CAP PNP', 'CAP SPNP',
    # Suboficiales
    'SS PNP', 'SS SPNP',
    'SB PNP', 'SB SPNP',
    # Técnicos
    'ST1 PNP', 'ST1 SPNP',
    'ST2 PNP', 'ST2 SPNP',
    'ST3 PNP', 'ST3 SPNP',
    # Suboficiales de 1ra, 2da, 3ra
    'S1 PNP', 'S1 SPNP',
    'S2 PNP', 'S2 SPNP',
    'S3 PNP', 'S3 SPNP',
    # Personal Civil y CAS
    'EC. PC.',
    'CIVIL',
    'CAS',
    # Personal de Salud
    'MEDICO',
    'SERUM',
    'ENFERMERA',
    'TECNICO',
    'ADMINISTRATIVO',
    'PENDIENTE'
]

AREAS_VALIDAS = [
    # Dirección y Administración General
    'DIRECTOR DEL HOSPITAL REGIONAL AREQUIPA',
    'SECRETARIA',
    'UNIDAD DE PLANEAMIENTO Y EDUCACION',
    'AREA DE PLANEAMIENTO',
    'AREA DE EDUCACION',
    'OFICINA DE ADMINISTRACION',
    'AREA DE RECURSOS HUMANOS',
    'AREA DE LOGISTICA',
    'AREA DE CONTABILIDAD',
    'AREA DE BIENESTAR Y APOYO AL POLICIA',
    'UNIDAD DE SEGURIDAD DE INSTALACIONES',
    
    # Atención al Usuario y Comunicaciones
    'UNIDAD DE RELACIONES PUBLICAS Y ATENCION AL USUARIO',
    'AREA DE RELACIONES PÚBLICAS',
    'AREA DE ATENCIÓN AL USUARIO',
    'UNIDAD DE TRAMITE DOCUMENTARIO',
    
    # Gestión de Calidad y Estadística
    'UNIDAD DE GESTION DE LA CALIDAD',
    'UNIDAD DE ADMISION Y REGISTROS MEDICOS',
    'UNIDAD DE INTELIGENCIA SANITARIA',
    'AREA DE ESTADISTICA',
    'AREA DE EPIDEMIOLOGIA',
    'AREA DE PROGRAMAS Y ESTRATEGIAS SANITARIAS',
    'UNIDAD DE TECNOLOGIA DE LA INFORMACION Y COMUNICACIONES',
    
    # Jefaturas y Divisiones Médicas
    'JEFATURA DE ORDENES',
    'DIVISION DE MEDICINA Y ESPECIALIDADES MEDICAS',
    'DEPARTAMENTO DE MEDICINA',
    'AREA DE SALUD OCUPACIONAL',
    'AREA DE FICHA MEDICA',
    'OFICINA DE REFERENCIAS Y CONTRAREFERENCIAS',
    'JUNTA MEDICA',
    
    # Especialidades Médicas
    'DEPARTAMENTO DE CARDIOLOGIA',
    'DEPARTAMENTO DE NEFROLOGIA',
    'DEPARTAMENTO DE NEUROLOGIA',
    'DEPARTAMENTO DE ALERGIA E INMUNOLOGIA',
    'DEPARTAMENTO DE DERMATOLOGIA',
    'DEPARTAMENTO DE ENDOCRINOLOGIA',
    'DEPARTAMENTO DE GASTROENTEROLOGIA',
    'DEPARTAMENTO DE MEDICINA INTERNA',
    'DEPARTAMENTO DE NEUMOLOGIA',
    'DEPARTAMENTO DE PSIQUIATRIA',
    'DEPARTAMENTO DE REUMATOLOGIA',
    
    # Especialidades Quirúrgicas
    'DIVISION DE CIRUGIA Y ESPECIALIDADES QUIRURGICAS',
    'DEPARTAMENTO DE CIRUGIA PLASTICA REPARADORA Y QUEMADOS',
    'DEPARTAMENTO DE CIRUGIA GENERAL',
    'DEPARTAMENTO DE OFTALMOLOGIA',
    'DEPARTAMENTO DE ANESTESIOLOGÍA Y CENTRO QUIRURGICO',
    'DEPARTAMENTO DE NEUROCIRUGIA',
    'DEPARTAMENTO DE ORTOPEDIA Y TRAUMATOLOGIA',
    'DEPARTAMENTO DE OTORRINOLARINGOLOGIA Y CIRUGIA DE CABEZA Y CUELLO',
    'DEPARTAMENTO DE UROLOGIA',
    
    # Área Materno Infantil
    'DIVISION MATERNO INFANTIL',
    'DEPARTAMENTO DE OBSTETRICIA',
    'DEPARTAMENTO DE GINECOLOGIA',
    'DEPARTAMENTO DE MEDICINA PEDIATRICA',
    'DEPARTAMENTO DE NEONATOLOGIA',
    
    # Emergencia y Áreas Críticas
    'DIVISION DE EMERGENCIA Y AREAS CRITICAS',
    'DEPARTAMENTO DE EMERGENCIA',
    
    # Diagnóstico y Tratamiento
    'DIVISION DE AYUDA AL DIAGNOSTICO Y TRATAMIENTO',
    'DEPARTAMENTO DE ASISTENCIA SOCIAL',
    'DEPARTAMENTO DE DIAGNOSTICO POR IMAGENES',
    'DEPARTAMENTO HEMOTERAPIA Y BANCO DE SANGRE',
    'DEPARTAMENTO DE MEDICINA FISICA Y REHABILITACION',
    'DEPARTAMENTO DE NUTRICION',
    'DEPARTAMENTO DE ODONTOESTOMATOLOGIA',
    'DEPARTAMENTO DE PATOLOGIA CLINICA',
    'DEPARTAMENTO DE PSICOLOGIA',
    'DEPARTAMENTO DE FARMACIA',
    
    # Enfermería
    'DIVISION DE ENFERMERIA',
    'DEPARTAMENTO DE ATENCION HOSPITALARIA Y AMBULATORIA',
    
    # Áreas Operativas
    'ÁREA DE MEDICINA Y ESPECIALIDADES MÉDICAS',
    'ÁREA DE CIRUGÍA Y ESPECIALIDADES QUIRÚRGICAS',
    'ANESTESIOLOGÍA Y CENTRO QUIRÚRGICO',
    'ÁREA MATERNO INFANTIL',
    'ÁREA DE EMERGENCIA Y ÁREAS CRÍTICAS',
    'ÁREA DE ATENCIÓN AMBULATORIA',
    
    # Oficiales de Permanencia
    'OFICIAL DE PERMANENCIA',
    
    # Postas Médicas
    'POSTA MEDICA POLICIAL SAN MARTIN DE PORRES',
    'POSTA MEDICA POLICIAL CAMANA',
    'POSTA MEDICA POLICIAL ISLAY',
    
    # Otras Áreas
    'CONSULTORIOS EXTERNOS',
    'LICENCIA',
    'ESCUELA DE EDUCACION SUPERIOR TECNICO PROFESIONAL',
    'UNIDAD DESCONCENTRADA DE DOSAJE ETILICO',
    'PENDIENTE'
]

ROLES_VALIDOS = ['admin', 'jefe_area', 'oficial_permanencia', 'control_qr', 'usuario']

# =====================================================
# FUNCIÓN AUXILIAR PARA GENERAR EMAIL
# =====================================================
def generar_email_interno(nombre_completo: str, dni: str = None) -> str:
    """Genera un email institucional basado en el nombre"""
    if not nombre_completo or nombre_completo == 'PENDIENTE':
        return f"pendiente{hash(dni) % 10000 if dni else 0}@hospital.arequipa.pnp.com"
    
    # Limpiar el nombre
    nombre = nombre_completo.upper().strip()
    nombre = nombre.replace(',', ' ')
    
    # Dividir en palabras
    palabras = [p for p in nombre.split() if p]
    
    if not palabras:
        return f"usuario{hash(dni) % 10000 if dni else 0}@hospital.arequipa.pnp.com"
    
    # Extraer primer nombre y primer apellido
    primer_nombre = palabras[0]
    primer_apellido = palabras[-1] if len(palabras) > 1 else palabras[0]
    
    # Quitar tildes
    def quitar_tildes(texto):
        return ''.join(
            c for c in unicodedata.normalize('NFD', texto)
            if unicodedata.category(c) != 'Mn'
        ).lower()
    
    nombre_norm = quitar_tildes(primer_nombre)
    apellido_norm = quitar_tildes(primer_apellido)
    
    return f"{nombre_norm}.{apellido_norm}@hospital.arequipa.pnp.com"

# =====================================================
# ENDPOINTS PRINCIPALES
# =====================================================

@router.get("/", response_model=List[PersonalResponse])
async def listar_personal(
    area: Optional[str] = Query(None, description="Filtrar por área"),
    grado: Optional[str] = Query(None, description="Filtrar por grado"),
    busqueda: Optional[str] = Query(None, description="Búsqueda por nombre, DNI o CIP"),
    activo: Optional[bool] = Query(None, description="Filtrar por estado activo"),
    incluir_inactivos: Optional[bool] = Query(False, description="Incluir usuarios inactivos"),
    limit: int = Query(100, description="Límite de resultados"),
    offset: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """
    Lista todo el personal con filtros opcionales
    """
    # Verificar caché
    cache_key = get_cache_key(str(current_user.id), area, grado, busqueda)
    
    if offset == 0 and limit == 100 and cache_key in personal_cache:
        cached_data, timestamp = personal_cache[cache_key]
        if datetime.now() - timestamp < timedelta(seconds=cache_timeout):
            print(f"📦 Cache hit: {cache_key}")
            start = offset
            end = offset + limit
            return cached_data[start:end] if start < len(cached_data) else []
    
    print(f"🔄 Cache miss: {cache_key} - Consultando BD...")
    
    query = db.query(Personal)
    
    # Usuario normal solo ve sus datos
    if "usuario" in current_user.roles and "admin" not in current_user.roles and "jefe_area" not in current_user.roles:
        if current_user.personal_id:
            personal = query.filter(Personal.id == current_user.personal_id).first()
            result = [personal] if personal else []
            personal_cache[cache_key] = (result, datetime.now())
            return result
        return []
    
    # Aplicar filtros
    if area:
        query = query.filter(Personal.area == area)
    
    if grado:
        query = query.filter(Personal.grado == grado)
    
    if activo is not None:
        query = query.filter(Personal.activo == activo)
    elif not incluir_inactivos and "admin" not in current_user.roles:
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
    
    # Si es jefe de área, solo ver su área
    if "jefe_area" in current_user.roles and "admin" not in current_user.roles:
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe and jefe.area:
            query = query.filter(Personal.area == jefe.area)
    
    # Obtener total y resultados
    total = query.count()
    resultados = query.order_by(
        Personal.area,
        Personal.grado,
        Personal.nombre
    ).offset(offset).limit(limit).all()
    
    # Guardar en caché
    if offset == 0:
        personal_cache[cache_key] = (resultados, datetime.now())
    
    print(f"✅ Consulta completada: {len(resultados)} registros (total: {total})")
    return resultados


@router.get("/{id}", response_model=PersonalResponse)
async def obtener_personal(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area", "usuario"]))
):
    """Obtiene un personal por ID"""
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    # Verificar permisos
    if "usuario" in current_user.roles and "admin" not in current_user.roles and "jefe_area" not in current_user.roles:
        if str(current_user.personal_id) != str(id):
            raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
        return personal
    
    if "jefe_area" in current_user.roles and "admin" not in current_user.roles:
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe and jefe.area != personal.area:
            raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    return personal


@router.get("/area/{area}", response_model=List[PersonalResponse])
async def listar_por_area(
    area: str,
    activo: Optional[bool] = Query(True, description="Filtrar por estado activo"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """Lista personal por área"""
    if "jefe_area" in current_user.roles and "admin" not in current_user.roles:
        jefe = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if jefe and jefe.area != area:
            raise HTTPException(status_code=403, detail="No tiene acceso a esta área")
    
    query = db.query(Personal).filter(Personal.area == area)
    
    if activo is not None:
        query = query.filter(Personal.activo == activo)
    
    return query.order_by(Personal.grado, Personal.nombre).all()


@router.get("/verificar-dni/{dni}")
async def verificar_dni(
    dni: str,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Verifica si un DNI está disponible"""
    usuario = db.query(Personal).filter(Personal.dni == dni).first()
    
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


# =====================================================
# ✅ FUNCIÓN AUXILIAR PARA VALIDAR ÁREAS DE JEFATURA
# =====================================================
def validar_areas_jefatura(areas: List[str], area_trabajo: str) -> None:
    """Valida que las áreas de jefatura existan en la lista de áreas válidas"""
    from app.api.personal import AREAS_VALIDAS
    
    for area in areas:
        if area not in AREAS_VALIDAS:
            raise HTTPException(
                status_code=400,
                detail=f"El área '{area}' no es válida. Seleccione de la lista de áreas disponibles."
            )


@router.post("/", response_model=PersonalResponse, status_code=201)
async def crear_personal(
    personal_data: PersonalCreate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea un nuevo personal con validación de áreas de jefatura"""
    
    # ✅ VALIDACIÓN 1: Área de trabajo es obligatoria
    if not personal_data.area or personal_data.area == "":
        raise HTTPException(status_code=400, detail="El área de trabajo es obligatoria")
    
    # ✅ VALIDACIÓN 2: Si tiene rol jefe_area, debe tener al menos un área que jefatura
    if "jefe_area" in personal_data.roles:
        if not personal_data.areas_que_jefatura or len(personal_data.areas_que_jefatura) == 0:
            raise HTTPException(
                status_code=400,
                detail="Los jefes de área deben tener al menos un área asignada"
            )
        
        # ✅ VALIDACIÓN 3: Verificar que las áreas que jefatura existen
        validar_areas_jefatura(personal_data.areas_que_jefatura, personal_data.area)
    
    # Verificar DNI
    usuario_existente = db.query(Personal).filter(
        Personal.dni == personal_data.dni
    ).first()
    
    if usuario_existente:
        if usuario_existente.activo:
            raise HTTPException(status_code=400, detail="DNI ya registrado y activo")
        else:
            # Reactivar usuario existente
            for key, value in personal_data.model_dump().items():
                setattr(usuario_existente, key, value)
            usuario_existente.activo = True
            db.commit()
            db.refresh(usuario_existente)
            clear_personal_cache()
            return usuario_existente
    
    # Verificar CIP único
    if personal_data.cip:
        cip_existente = db.query(Personal).filter(
            Personal.cip == personal_data.cip,
            Personal.activo == True
        ).first()
        if cip_existente:
            raise HTTPException(status_code=400, detail="CIP ya registrado")
    
    # Verificar email único
    email_existente = db.query(Personal).filter(
        Personal.email == personal_data.email,
        Personal.activo == True
    ).first()
    if email_existente:
        raise HTTPException(status_code=400, detail="Email ya registrado")
    
    # Crear nuevo usuario
    personal = Personal(**personal_data.model_dump())
    db.add(personal)
    db.commit()
    db.refresh(personal)
    
    clear_personal_cache()
    return personal


# =====================================================
# 🆕 ENDPOINT PARA ACTUALIZAR PERSONAL (CON VALIDACIONES)
# =====================================================

@router.put("/{id}", response_model=PersonalResponse)
async def actualizar_personal(
    id: UUID,
    personal_data: PersonalUpdate,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    Actualiza un personal existente con validación de áreas de jefatura
    Solo accesible para administradores
    """
    # Buscar el personal
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    # ✅ VALIDACIÓN DE ÁREAS DE JEFATURA si se está actualizando
    roles_actuales = personal_data.roles if personal_data.roles is not None else personal.roles
    areas_jefatura_actuales = personal_data.areas_que_jefatura if personal_data.areas_que_jefatura is not None else personal.areas_que_jefatura
    
    if "jefe_area" in roles_actuales:
        if not areas_jefatura_actuales or len(areas_jefatura_actuales) == 0:
            raise HTTPException(
                status_code=400,
                detail="Los jefes de área deben tener al menos un área asignada"
            )
        
        # Obtener el área de trabajo (actual o nueva)
        area_trabajo = personal_data.area if personal_data.area is not None else personal.area
        
        # Validar que las áreas existen
        validar_areas_jefatura(areas_jefatura_actuales, area_trabajo)
    
    # Verificar unicidad de campos si se actualizan
    if personal_data.dni and personal_data.dni != personal.dni:
        dni_existente = db.query(Personal).filter(
            Personal.dni == personal_data.dni,
            Personal.activo == True
        ).first()
        if dni_existente:
            raise HTTPException(status_code=400, detail="DNI ya registrado")
    
    if personal_data.cip and personal_data.cip != personal.cip:
        cip_existente = db.query(Personal).filter(
            Personal.cip == personal_data.cip,
            Personal.activo == True
        ).first()
        if cip_existente:
            raise HTTPException(status_code=400, detail="CIP ya registrado")
    
    if personal_data.email and personal_data.email != personal.email:
        email_existente = db.query(Personal).filter(
            Personal.email == personal_data.email,
            Personal.activo == True
        ).first()
        if email_existente:
            raise HTTPException(status_code=400, detail="Email ya registrado")
    
    # Actualizar solo los campos proporcionados
    update_data = personal_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(personal, field, value)
    
    db.commit()
    db.refresh(personal)
    
    # Limpiar caché
    clear_personal_cache()
    
    return personal


# =====================================================
# ENDPOINT DE CARGA MASIVA CON STREAMING DE PROGRESO (ACTUALIZADO)
# =====================================================

@router.post("/carga-masiva-stream")
async def carga_masiva_stream(
    datos: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    Carga masiva con streaming de progreso
    Soporta múltiples áreas que jefatura separadas por comas
    """
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
                # Procesar registro
                dni = str(item.get('DNI', '') or item.get('dni', '')).strip()
                if not dni:
                    dni = f"PEND{idx+1:04d}"
                
                cip = str(item.get('CIP', '') or item.get('cip', '')).strip()
                if not cip:
                    cip = f"CIP{idx+1:04d}"
                
                grado = str(item.get('GRADO', '') or item.get('grado', '')).strip().upper()
                if not grado:
                    grado = "PENDIENTE"
                
                nombre = str(item.get('NOMBRE COMPLETO', '') or item.get('nombre', '') or item.get('NOMBRE', '')).strip().upper()
                if not nombre:
                    nombre = f"PERSONAL {idx+1}"
                
                email = str(item.get('EMAIL', '') or item.get('email', '')).strip().lower()
                if not email or '@' not in email:
                    email = generar_email_interno(nombre, dni)
                
                area = str(item.get('ÁREA', '') or item.get('AREA', '') or item.get('area', '')).strip().upper()
                if not area:
                    area = "PENDIENTE"
                
                roles_str = str(item.get('ROLES', '') or item.get('roles', '')).strip()
                roles = [r.strip().lower() for r in roles_str.split(',') if r.strip()] if roles_str else ['usuario']
                
                telefono = str(item.get('TELÉFONO', '') or item.get('telefono', '')).strip()
                if telefono and not telefono.isdigit():
                    telefono = ''.join(c for c in telefono if c.isdigit())
                
                especialidad = str(item.get('ESPECIALIDAD', '') or item.get('especialidad', '')).strip()
                
                fecha_nac = item.get('FECHA NACIMIENTO (YYYY-MM-DD)') or item.get('fecha_nacimiento')
                if fecha_nac:
                    try:
                        if isinstance(fecha_nac, str):
                            fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                    except:
                        fecha_nac = None
                
                fecha_ingreso = item.get('FECHA INGRESO (YYYY-MM-DD)') or item.get('fecha_ingreso')
                if fecha_ingreso:
                    try:
                        if isinstance(fecha_ingreso, str):
                            fecha_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
                    except:
                        fecha_ingreso = datetime.now().date()
                else:
                    fecha_ingreso = datetime.now().date()
                
                num_colegiatura = str(item.get('NÚMERO COLEGIATURA', '') or 
                                      item.get('NUMERO_COLEGIATURA', '') or 
                                      item.get('numero_colegiatura', '')).strip()
                if not num_colegiatura:
                    num_colegiatura = None
                
                observaciones = str(item.get('OBSERVACIONES', '') or item.get('observaciones', '')).strip()
                
                # ✅ PROCESAR ÁREAS QUE JEFATURA (pueden ser múltiples separadas por comas)
                areas_jefatura_str = str(item.get('ÁREAS_JEFATURA', '') or 
                                         item.get('AREA_JEFATURA', '') or 
                                         item.get('area_jefatura', '')).strip()
                areas_jefatura = []
                if areas_jefatura_str:
                    areas_jefatura = [a.strip().upper() for a in areas_jefatura_str.split(',') if a.strip()]
                
                # ✅ VALIDACIÓN: Si es jefe de área, debe tener áreas asignadas
                if "jefe_area" in roles and not areas_jefatura:
                    raise ValueError("Los jefes de área deben tener al menos un área asignada en la columna ÁREAS_JEFATURA")
                
                # Verificar si ya existe
                usuario_existente = None
                if dni and not dni.startswith('PEND'):
                    usuario_existente = db.query(Personal).filter(
                        or_(
                            Personal.dni == dni,
                            Personal.cip == cip if not cip.startswith('CIP') else False
                        )
                    ).first()
                
                if usuario_existente:
                    if usuario_existente.activo:
                        fallidos += 1
                        errores.append({
                            "fila": fila,
                            "errores": [f"Usuario ya existe y está activo (DNI: {dni})"]
                        })
                    else:
                        # Reactivar
                        usuario_existente.grado = grado
                        usuario_existente.nombre = nombre
                        usuario_existente.email = email
                        usuario_existente.telefono = telefono or None
                        if fecha_nac:
                            usuario_existente.fecha_nacimiento = fecha_nac
                        usuario_existente.area = area
                        usuario_existente.especialidad = especialidad
                        if fecha_ingreso:
                            usuario_existente.fecha_ingreso = fecha_ingreso
                        usuario_existente.roles = roles
                        usuario_existente.numero_colegiatura = num_colegiatura
                        usuario_existente.observaciones = observaciones
                        usuario_existente.areas_que_jefatura = areas_jefatura  # ✅ NUEVO
                        usuario_existente.activo = True
                        
                        db.commit()
                        exitosos += 1
                        detalles.append({
                            "fila": fila,
                            "mensaje": f"Usuario reactivado: {nombre}",
                            "id": str(usuario_existente.id),
                            "areas_jefatura": areas_jefatura
                        })
                else:
                    # Crear nuevo
                    nuevo_personal = Personal(
                        dni=dni,
                        cip=cip,
                        grado=grado,
                        nombre=nombre,
                        email=email,
                        telefono=telefono or None,
                        fecha_nacimiento=fecha_nac,
                        area=area,
                        especialidad=especialidad,
                        fecha_ingreso=fecha_ingreso,
                        roles=roles,
                        numero_colegiatura=num_colegiatura,
                        observaciones=observaciones,
                        areas_que_jefatura=areas_jefatura,  # ✅ NUEVO
                        activo=True,
                        condicion='Titular'
                    )
                    
                    db.add(nuevo_personal)
                    db.commit()
                    db.refresh(nuevo_personal)
                    
                    exitosos += 1
                    detalles.append({
                        "fila": fila,
                        "mensaje": f"Usuario creado: {nombre}",
                        "id": str(nuevo_personal.id),
                        "areas_jefatura": areas_jefatura
                    })
                
                # Enviar progreso cada 5 registros o al final
                if (idx + 1) % 5 == 0 or idx + 1 == total:
                    progreso = {
                        'type': 'progress',
                        'actual': idx + 1,
                        'total': total,
                        'exitosos': exitosos,
                        'fallidos': fallidos
                    }
                    yield f"data: {json.dumps(progreso)}\n\n"
                
            except Exception as e:
                db.rollback()
                fallidos += 1
                errores.append({
                    "fila": fila,
                    "errores": [f"Error: {str(e)}"]
                })
                print(f"❌ Error en fila {fila}: {str(e)}")
        
        # Resultado final
        if exitosos > 0:
            clear_personal_cache()
        
        resultado_final = {
            'type': 'complete',
            'exitosos': exitosos,
            'fallidos': fallidos,
            'detalles': detalles,
            'errores': errores
        }
        yield f"data: {json.dumps(resultado_final)}\n\n"
    
    return StreamingResponse(
        generar_eventos(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


# =====================================================
# ENDPOINT DE CARGA MASIVA TRADICIONAL (ACTUALIZADO)
# =====================================================

@router.post("/carga-masiva")
async def carga_masiva_personal(
    datos: List[Dict[str, Any]],
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    Carga masiva de personal - Versión tradicional
    Soporta múltiples áreas que jefatura separadas por comas
    """
    resultados = {
        "exitosos": 0,
        "fallidos": 0,
        "detalles": [],
        "errores": []
    }
    
    print(f"📥 Recibidos {len(datos)} registros para carga masiva")
    
    for idx, item in enumerate(datos):
        fila = item.get('_fila', idx + 2)
        
        try:
            # DNI
            dni = str(item.get('DNI', '') or item.get('dni', '')).strip()
            if not dni:
                dni = f"PEND{idx+1:04d}"
            
            cip = str(item.get('CIP', '') or item.get('cip', '')).strip()
            if not cip:
                cip = f"CIP{idx+1:04d}"
            
            grado = str(item.get('GRADO', '') or item.get('grado', '')).strip().upper()
            if not grado:
                grado = "PENDIENTE"
            
            nombre = str(item.get('NOMBRE COMPLETO', '') or item.get('nombre', '') or item.get('NOMBRE', '')).strip().upper()
            if not nombre:
                nombre = f"PERSONAL {idx+1}"
            
            email = str(item.get('EMAIL', '') or item.get('email', '')).strip().lower()
            if not email or '@' not in email:
                email = generar_email_interno(nombre, dni)
            
            area = str(item.get('ÁREA', '') or item.get('AREA', '') or item.get('area', '')).strip().upper()
            if not area:
                area = "PENDIENTE"
            
            roles_str = str(item.get('ROLES', '') or item.get('roles', '')).strip()
            roles = [r.strip().lower() for r in roles_str.split(',') if r.strip()] if roles_str else ['usuario']
            
            telefono = str(item.get('TELÉFONO', '') or item.get('telefono', '')).strip()
            if telefono and not telefono.isdigit():
                telefono = ''.join(c for c in telefono if c.isdigit())
            
            especialidad = str(item.get('ESPECIALIDAD', '') or item.get('especialidad', '')).strip()
            
            fecha_nac = item.get('FECHA NACIMIENTO (YYYY-MM-DD)') or item.get('fecha_nacimiento')
            if fecha_nac:
                try:
                    if isinstance(fecha_nac, str):
                        fecha_nac = datetime.strptime(fecha_nac, '%Y-%m-%d').date()
                except:
                    fecha_nac = None
            
            fecha_ingreso = item.get('FECHA INGRESO (YYYY-MM-DD)') or item.get('fecha_ingreso')
            if fecha_ingreso:
                try:
                    if isinstance(fecha_ingreso, str):
                        fecha_ingreso = datetime.strptime(fecha_ingreso, '%Y-%m-%d').date()
                except:
                    fecha_ingreso = datetime.now().date()
            else:
                fecha_ingreso = datetime.now().date()
            
            num_colegiatura = str(item.get('NÚMERO COLEGIATURA', '') or 
                                  item.get('NUMERO_COLEGIATURA', '') or 
                                  item.get('numero_colegiatura', '')).strip()
            if not num_colegiatura:
                num_colegiatura = None
            
            observaciones = str(item.get('OBSERVACIONES', '') or item.get('observaciones', '')).strip()
            
            # ✅ PROCESAR ÁREAS QUE JEFATURA
            areas_jefatura_str = str(item.get('ÁREAS_JEFATURA', '') or 
                                     item.get('AREA_JEFATURA', '') or 
                                     item.get('area_jefatura', '')).strip()
            areas_jefatura = []
            if areas_jefatura_str:
                areas_jefatura = [a.strip().upper() for a in areas_jefatura_str.split(',') if a.strip()]
            
            # ✅ VALIDACIÓN: Si es jefe de área, debe tener áreas asignadas
            if "jefe_area" in roles and not areas_jefatura:
                raise ValueError("Los jefes de área deben tener al menos un área asignada en la columna ÁREAS_JEFATURA")
            
            # Verificar existencia
            usuario_existente = None
            if dni and not dni.startswith('PEND'):
                usuario_existente = db.query(Personal).filter(
                    or_(
                        Personal.dni == dni,
                        Personal.cip == cip if not cip.startswith('CIP') else False
                    )
                ).first()
            
            if usuario_existente:
                if usuario_existente.activo:
                    resultados["fallidos"] += 1
                    resultados["errores"].append({
                        "fila": fila,
                        "errores": [f"Usuario ya existe y está activo (DNI: {dni})"],
                        "datos": item
                    })
                    continue
                else:
                    # Reactivar
                    for key, value in {
                        'grado': grado, 'nombre': nombre, 'email': email,
                        'telefono': telefono or None, 'fecha_nacimiento': fecha_nac,
                        'area': area, 'especialidad': especialidad,
                        'fecha_ingreso': fecha_ingreso, 'roles': roles,
                        'numero_colegiatura': num_colegiatura,
                        'observaciones': observaciones,
                        'areas_que_jefatura': areas_jefatura  # ✅ NUEVO
                    }.items():
                        setattr(usuario_existente, key, value)
                    usuario_existente.activo = True
                    
                    db.commit()
                    resultados["exitosos"] += 1
                    resultados["detalles"].append({
                        "fila": fila,
                        "mensaje": f"Usuario reactivado: {nombre}",
                        "id": str(usuario_existente.id),
                        "areas_jefatura": areas_jefatura
                    })
                    continue
            
            # Crear nuevo
            nuevo_personal = Personal(
                dni=dni, cip=cip, grado=grado, nombre=nombre, email=email,
                telefono=telefono or None, fecha_nacimiento=fecha_nac,
                area=area, especialidad=especialidad, fecha_ingreso=fecha_ingreso,
                roles=roles, numero_colegiatura=num_colegiatura,
                observaciones=observaciones, areas_que_jefatura=areas_jefatura,  # ✅ NUEVO
                activo=True, condicion='Titular'
            )
            
            db.add(nuevo_personal)
            db.commit()
            db.refresh(nuevo_personal)
            
            resultados["exitosos"] += 1
            resultados["detalles"].append({
                "fila": fila,
                "mensaje": f"Usuario creado: {nombre}",
                "id": str(nuevo_personal.id),
                "areas_jefatura": areas_jefatura
            })
            
        except Exception as e:
            db.rollback()
            resultados["fallidos"] += 1
            resultados["errores"].append({
                "fila": fila,
                "errores": [f"Error: {str(e)}"],
                "datos": item
            })
            print(f"❌ Error en fila {fila}: {str(e)}")
    
    if resultados["exitosos"] > 0:
        clear_personal_cache()
    
    print(f"✅ Carga masiva completada: {resultados['exitosos']} exitosos, {resultados['fallidos']} fallidos")
    return resultados


# =====================================================
# ENDPOINTS PARA RELACIONES Y ELIMINACIÓN
# =====================================================

@router.get("/{id}/tiene-relaciones")
async def verificar_relaciones(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Verifica si un usuario tiene datos relacionados"""
    tiene_planificacion = db.query(Planificacion.id).filter(Planificacion.personal_id == id).first() is not None
    tiene_asistencia = db.query(Asistencia.id).filter(Asistencia.personal_id == id).first() is not None
    tiene_dm = db.query(DescansoMedico.id).filter(DescansoMedico.paciente_id == id).first() is not None
    tiene_solicitudes = db.query(SolicitudCambio.id).filter(
        or_(
            SolicitudCambio.empleado_id == id,
            SolicitudCambio.empleado2_id == id
        )
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
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina físicamente un personal"""
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    # Verificar relaciones
    tiene_planificacion = db.query(Planificacion.id).filter(Planificacion.personal_id == id).first() is not None
    tiene_asistencia = db.query(Asistencia.id).filter(Asistencia.personal_id == id).first() is not None
    tiene_dm = db.query(DescansoMedico.id).filter(DescansoMedico.paciente_id == id).first() is not None
    tiene_solicitudes = db.query(SolicitudCambio.id).filter(
        or_(
            SolicitudCambio.empleado_id == id,
            SolicitudCambio.empleado2_id == id
        )
    ).first() is not None
    tiene_usuario_auth = db.query(Usuario.id).filter(Usuario.personal_id == id).first() is not None
    
    if tiene_planificacion or tiene_asistencia or tiene_dm or tiene_solicitudes or tiene_usuario_auth:
        raise HTTPException(
            status_code=400, 
            detail="No se puede eliminar físicamente porque tiene datos relacionados. Use desactivación en su lugar."
        )
    
    db.delete(personal)
    db.commit()
    clear_personal_cache()
    
    return {
        "success": True,
        "message": "Usuario eliminado físicamente",
        "id": str(id)
    }


@router.delete("/{id}")
async def desactivar_personal(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Desactiva un personal (soft delete)"""
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    personal.activo = False
    db.commit()
    clear_personal_cache()
    
    return {
        "success": True,
        "message": "Usuario desactivado correctamente",
        "id": str(id),
        "soft_delete": True
    }


@router.post("/{id}/restaurar", response_model=PersonalResponse)
async def restaurar_personal(
    id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Restaura un personal previamente desactivado"""
    personal = db.query(Personal).filter(Personal.id == id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    if personal.activo:
        raise HTTPException(status_code=400, detail="El usuario ya está activo")
    
    personal.activo = True
    db.commit()
    db.refresh(personal)
    clear_personal_cache()
    
    return personal


@router.get("/inactivos/lista", response_model=List[PersonalResponse])
async def listar_inactivos(
    limit: int = Query(100, description="Límite de resultados"),
    offset: int = Query(0, description="Offset para paginación"),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Lista solo usuarios inactivos"""
    return db.query(Personal).filter(
        Personal.activo == False
    ).order_by(
        Personal.nombre
    ).offset(offset).limit(limit).all()