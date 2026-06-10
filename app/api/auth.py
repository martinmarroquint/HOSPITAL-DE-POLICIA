"""
AUTENTICACIÓN MULTI-EMPRESA
Login, registro, gestión de usuarios con soporte empresa_id y rol_global
El super_admin SIEMPRE puede acceder, incluso si la empresa está suspendida.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Body, UploadFile, File
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta, datetime, timezone
from typing import Any, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field
import os
import uuid as uuid_lib
from PIL import Image

from app.database import get_db
from app.core.security import (
    create_access_token, 
    verify_password, 
    get_password_hash,
    has_rol_global
)
from app.core.dependencies import (
    get_current_user, 
    get_current_active_user, 
    require_roles,
    get_current_super_admin
)
from app.models.usuario import Usuario
from app.models.personal import Personal
from app.models.empresa import Empresa
from app.schemas.auth import Token, LoginRequest, UserProfile, PasswordChange, UsuarioCreate
from app.config import settings

router = APIRouter()


# =====================================================
# SCHEMAS
# =====================================================

class ResetPasswordRequest(BaseModel):
    """Schema para resetear contraseña."""
    personal_id: Optional[UUID] = Field(None, description="ID del personal")
    nueva_password: str = Field(..., min_length=8, description="Nueva contraseña (mínimo 8 caracteres)")


class ProcesarFotoRequest(BaseModel):
    """Schema para procesar foto con IA."""
    foto_url: str = Field(..., description="URL de la foto a procesar")
    accion: str = Field(..., description="Acción: quitar_fondo, mejorar")


# =====================================================
# FUNCIÓN AUXILIAR PARA OBTENER DATOS DE PERSONAL
# =====================================================

def obtener_datos_personal_individual(db: Session, personal_id: UUID):
    """Obtiene los datos de un SOLO personal. Usar solo cuando sea un único registro."""
    if not personal_id:
        return None
    
    personal = db.query(Personal).filter(
        Personal.id == personal_id,
        Personal.activo == True
    ).first()
    
    if not personal:
        return None
    
    return {
        "nombre": personal.nombre,
        "grado": personal.grado or "",
        "area": personal.area or "",
        "dni": personal.dni or "",
        "cip": personal.cip or "",
        "roles": personal.roles or [],
        "areas_que_jefatura": personal.areas_que_jefatura or [],
        "empresa_id": str(personal.empresa_id) if personal.empresa_id else None,
        "foto_url": personal.foto_url or None,
        "telefono": personal.telefono or "",
        "direccion": getattr(personal, 'direccion', '') or "",
        "fecha_nacimiento": str(personal.fecha_nacimiento) if personal.fecha_nacimiento else None,
        "sexo": personal.sexo or "",
        "especialidad": personal.especialidad or "",
    }


def obtener_datos_personal_lote(db: Session, personal_ids: List[UUID]) -> dict:
    """
    Obtiene los datos de MÚLTIPLES personal en UNA SOLA consulta.
    Evita el problema N+1 queries.
    Retorna un diccionario {personal_id: datos}
    """
    if not personal_ids:
        return {}
    
    # Filtrar IDs None
    ids_validos = [pid for pid in personal_ids if pid is not None]
    if not ids_validos:
        return {}
    
    # UNA SOLA consulta para todos los personal
    personales = db.query(Personal).filter(
        Personal.id.in_(ids_validos),
        Personal.activo == True
    ).all()
    
    # Construir mapa
    resultado = {}
    for personal in personales:
        resultado[personal.id] = {
            "nombre": personal.nombre,
            "grado": personal.grado or "",
            "area": personal.area or "",
            "dni": personal.dni or "",
            "cip": personal.cip or "",
            "roles": personal.roles or [],
            "areas_que_jefatura": personal.areas_que_jefatura or [],
            "empresa_id": str(personal.empresa_id) if personal.empresa_id else None,
            "foto_url": personal.foto_url or None,
            "telefono": personal.telefono or "",
            "direccion": getattr(personal, 'direccion', '') or "",
            "fecha_nacimiento": str(personal.fecha_nacimiento) if personal.fecha_nacimiento else None,
            "sexo": personal.sexo or "",
            "especialidad": personal.especialidad or "",
        }
    
    return resultado


def verificar_acceso_empresa(current_user: Usuario, target_empresa_id: UUID) -> bool:
    """
    Verifica si el usuario actual puede acceder a los datos de una empresa.
    - super_admin: acceso total
    - admin_empresa: solo su empresa
    - usuario: solo su empresa
    """
    if current_user.rol_global == "super_admin":
        return True
    return str(current_user.empresa_id) == str(target_empresa_id)


# =====================================================
# LOGIN MULTI-EMPRESA (SUPER ADMIN SIEMPRE PASA)
# =====================================================

@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
) -> Any:
    """
    Login con soporte multi-empresa.
    El super_admin SIEMPRE puede acceder sin importar el estado de la empresa.
    """
    print(f"🔐 Intento de login: {form_data.username}")
    
    user = db.query(Usuario).filter(
        Usuario.email.ilike(form_data.username)
    ).first()
    
    if not user:
        print(f"❌ Usuario no encontrado: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not verify_password(form_data.password, user.password_hash):
        print(f"❌ Contraseña incorrecta: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    if not user.activo:
        print(f"❌ Usuario inactivo: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo. Contacte al administrador."
        )
    
    if user.empresa_id and user.rol_global != "super_admin":
        empresa = db.query(Empresa).filter(Empresa.id == user.empresa_id).first()
        if empresa and not empresa.activo:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"La empresa '{empresa.nombre}' está suspendida. Contacte al administrador."
            )
    
    personal_data = obtener_datos_personal_individual(db, user.personal_id)
    roles = personal_data["roles"] if personal_data else (user.roles or [])
    
    if personal_data and personal_data["roles"] != user.roles:
        print(f"🔄 Sincronizando roles para {user.email}")
        user.roles = personal_data["roles"]
        db.commit()
    
    user.ultimo_acceso = datetime.now(timezone.utc)
    db.commit()
    
    token_data = {
        "sub": user.email,
        "user_id": str(user.id),
        "personal_id": str(user.personal_id) if user.personal_id else None,
        "username": user.username or user.email.split('@')[0],
        "roles": roles,
        "empresa_id": str(user.empresa_id) if user.empresa_id else None,
        "rol_global": user.rol_global or "usuario",
        "area": personal_data["area"] if personal_data else None,
    }
    
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data=token_data,
        expires_delta=access_token_expires
    )
    
    print(f"✅ Login exitoso: {user.email}")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        "user": {
            "email": user.email,
            "username": token_data["username"],
            "rol_global": token_data["rol_global"],
            "roles": roles,
            "area": token_data["area"],
            "empresa_id": token_data["empresa_id"],
        }
    }


# =====================================================
# DIAGNÓSTICO Y VERIFICACIÓN
# =====================================================

@router.get("/check-user")
async def check_user(email: str, db: Session = Depends(get_db)):
    """Verifica si un usuario existe (solo para diagnóstico)."""
    user = db.query(Usuario).filter(Usuario.email.ilike(email)).first()
    
    if not user:
        return {"exists": False, "email": email}
    
    return {
        "exists": True,
        "email": user.email,
        "username": user.username,
        "is_active": user.activo,
        "has_personal": user.personal_id is not None,
        "has_empresa": user.empresa_id is not None,
        "rol_global": user.rol_global
    }


@router.get("/verificar")
async def verificar_token(current_user: Usuario = Depends(get_current_active_user)):
    """Verifica si el token es válido."""
    return {
        "valid": True,
        "user_id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "personal_id": str(current_user.personal_id) if current_user.personal_id else None,
        "empresa_id": str(current_user.empresa_id) if current_user.empresa_id else None,
        "rol_global": current_user.rol_global,
        "roles": current_user.roles,
        "activo": current_user.activo
    }


@router.post("/logout")
async def logout(current_user: Usuario = Depends(get_current_active_user)):
    """Logout."""
    return {"message": "Sesión cerrada exitosamente", "email": current_user.email}


# =====================================================
# PERFIL DE USUARIO
# =====================================================

@router.get("/perfil", response_model=UserProfile)
async def get_perfil(
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Obtiene el perfil completo del usuario autenticado."""
    personal_data = obtener_datos_personal_individual(db, current_user.personal_id)
    
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "personal_id": current_user.personal_id,
        "empresa_id": current_user.empresa_id,
        "rol_global": current_user.rol_global,
        "roles": personal_data["roles"] if personal_data else (current_user.roles or []),
        "activo": current_user.activo,
        "ultimo_acceso": current_user.ultimo_acceso,
        "nombre": personal_data["nombre"] if personal_data else None,
        "grado": personal_data["grado"] if personal_data else None,
        "area": personal_data["area"] if personal_data else None,
        "dni": personal_data["dni"] if personal_data else None,
        "cip": personal_data["cip"] if personal_data else None,
        "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else [],
        "foto_url": personal_data["foto_url"] if personal_data else None,
    }


@router.get("/perfil-completo")
async def get_perfil_completo(
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Endpoint que SIEMPRE devuelve datos de personal."""
    print(f"🔍 [PERFIL-COMPLETO] Buscando datos para: {current_user.email}")
    
    personal = None
    
    if current_user.personal_id:
        personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if personal:
            print(f"✅ Encontrado por ID: {personal.nombre}")
    
    if not personal:
        nombre_email = current_user.email.split('@')[0].replace('.', ' ').upper()
        personal = db.query(Personal).filter(Personal.nombre.ilike(f"%{nombre_email}%")).first()
        if personal:
            print(f"✅ Encontrado por nombre: {personal.nombre}")
    
    if not personal:
        nombre_emergencia = current_user.email.split('@')[0].replace('.', ' ').upper()
        print(f"⚠️ Usando datos de emergencia: {nombre_emergencia}")
        return {
            "id": current_user.id, "email": current_user.email, "username": current_user.username,
            "personal_id": current_user.personal_id,
            "empresa_id": str(current_user.empresa_id) if current_user.empresa_id else None,
            "rol_global": current_user.rol_global,
            "nombre": nombre_emergencia, "grado": "", "area": "", "dni": "", "cip": "",
            "roles": current_user.roles or [], "activo": current_user.activo,
            "ultimo_acceso": current_user.ultimo_acceso, "areas_que_jefatura": [],
            "foto_url": None, "telefono": "", "direccion": "", "fecha_nacimiento": None, "sexo": "", "especialidad": ""
        }
    
    return {
        "id": current_user.id, "email": current_user.email, "username": current_user.username,
        "personal_id": personal.id,
        "empresa_id": str(current_user.empresa_id) if current_user.empresa_id else None,
        "rol_global": current_user.rol_global,
        "nombre": personal.nombre, "grado": personal.grado or "", "area": personal.area or "",
        "dni": personal.dni or "", "cip": personal.cip or "",
        "roles": personal.roles or current_user.roles or [], "activo": current_user.activo,
        "ultimo_acceso": current_user.ultimo_acceso,
        "areas_que_jefatura": personal.areas_que_jefatura or [],
        "foto_url": personal.foto_url or None,
        "telefono": personal.telefono or "",
        "direccion": getattr(personal, 'direccion', '') or "",
        "fecha_nacimiento": str(personal.fecha_nacimiento) if personal.fecha_nacimiento else None,
        "sexo": personal.sexo or "",
        "especialidad": personal.especialidad or ""
    }


# =====================================================
# CAMBIO DE CONTRASEÑA
# =====================================================

@router.post("/cambiar-password")
async def cambiar_password(
    password_data: PasswordChange,
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """Cambia la contraseña del usuario autenticado."""
    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Contraseña actual incorrecta")
    if len(password_data.new_password) < 8:
        raise HTTPException(status_code=400, detail="La nueva contraseña debe tener al menos 8 caracteres")
    
    current_user.password_hash = get_password_hash(password_data.new_password)
    db.commit()
    return {"message": "Contraseña actualizada exitosamente"}


@router.post("/reset-password")
@router.post("/usuarios/{usuario_id}/reset-password")
async def reset_password_usuario(
    request: ResetPasswordRequest,
    usuario_id: Optional[UUID] = None,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Resetea la contraseña de un usuario."""
    try:
        usuario = None
        if usuario_id:
            usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
        if not usuario and request.personal_id:
            usuario = db.query(Usuario).filter(Usuario.personal_id == request.personal_id).first()
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        if not verificar_acceso_empresa(current_user, usuario.empresa_id):
            raise HTTPException(status_code=403, detail="No tiene acceso a usuarios de otra empresa")
        
        usuario.password_hash = get_password_hash(request.nueva_password)
        db.commit()
        return {"success": True, "message": "Contraseña restablecida exitosamente", "usuario_id": str(usuario.id), "email": usuario.email}
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en reset_password_usuario: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno al resetear contraseña")


# =====================================================
# 🆕 SUBIR FOTO DE PERFIL
# =====================================================

@router.post("/subir-foto-perfil")
async def subir_foto_perfil(
    foto: UploadFile = File(...),
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Sube una foto de perfil para el usuario autenticado.
    La imagen se guarda en /static/fotos_perfil/
    """
    try:
        # Validar tipo de archivo
        tipos_permitidos = ['image/jpeg', 'image/png', 'image/webp', 'image/gif']
        if foto.content_type not in tipos_permitidos:
            raise HTTPException(
                status_code=400,
                detail="Formato no permitido. Usa JPG, PNG, WebP o GIF"
            )
        
        # Leer contenido
        contenido = await foto.read()
        
        # Validar tamaño (máximo 10MB)
        if len(contenido) > 10 * 1024 * 1024:
            raise HTTPException(
                status_code=400,
                detail="La imagen no debe superar 10MB"
            )
        
        # Crear directorio si no existe
        upload_dir = "static/fotos_perfil"
        os.makedirs(upload_dir, exist_ok=True)
        
        # Generar nombre único
        extension = foto.filename.split('.')[-1] if '.' in foto.filename else 'jpg'
        nombre_archivo = f"{current_user.id}_{uuid_lib.uuid4().hex[:8]}.{extension}"
        ruta_completa = os.path.join(upload_dir, nombre_archivo)
        
        # Guardar archivo
        with open(ruta_completa, "wb") as buffer:
            buffer.write(contenido)
        
        # Optimizar imagen (redimensionar si es muy grande)
        try:
            img = Image.open(ruta_completa)
            if img.width > 800 or img.height > 800:
                img.thumbnail((800, 800), Image.Resampling.LANCZOS)
                img.save(ruta_completa, optimize=True, quality=85)
        except Exception as e:
            print(f"⚠️ No se pudo optimizar la imagen: {e}")
        
        # Construir URL
        foto_url = f"/static/fotos_perfil/{nombre_archivo}"
        
        # Guardar URL en el registro de Personal
        if current_user.personal_id:
            personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if personal:
                # Eliminar foto anterior si existe
                if personal.foto_url:
                    ruta_anterior = personal.foto_url.lstrip('/')
                    if os.path.exists(ruta_anterior):
                        os.remove(ruta_anterior)
                
                personal.foto_url = foto_url
                db.commit()
        
        print(f"✅ Foto subida: {foto_url}")
        
        return {
            "message": "Foto subida exitosamente",
            "foto_url": foto_url,
            "nombre_archivo": nombre_archivo
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error al subir foto: {e}")
        raise HTTPException(status_code=500, detail=f"Error al subir foto: {str(e)}")


# =====================================================
# 🆕 ELIMINAR FOTO DE PERFIL
# =====================================================

@router.delete("/eliminar-foto-perfil")
async def eliminar_foto_perfil(
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Elimina la foto de perfil del usuario autenticado.
    """
    try:
        if current_user.personal_id:
            personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
            if personal and personal.foto_url:
                # Eliminar archivo físico
                ruta_foto = personal.foto_url.lstrip('/')
                if os.path.exists(ruta_foto):
                    os.remove(ruta_foto)
                    print(f"🗑️ Archivo eliminado: {ruta_foto}")
                
                personal.foto_url = None
                db.commit()
        
        return {"message": "Foto eliminada exitosamente"}
        
    except Exception as e:
        print(f"❌ Error al eliminar foto: {e}")
        raise HTTPException(status_code=500, detail=f"Error al eliminar foto: {str(e)}")


# =====================================================
# 🆕 PROCESAR FOTO CON IA (QUITAR FONDO / MEJORAR)
# =====================================================

@router.post("/procesar-foto-ia")
async def procesar_foto_ia(
    request: ProcesarFotoRequest,
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Procesa una foto de perfil con IA.
    Acciones: quitar_fondo, mejorar
    """
    try:
        ruta_foto = request.foto_url.lstrip('/')
        
        if not os.path.exists(ruta_foto):
            raise HTTPException(status_code=404, detail="Foto no encontrada")
        
        # Mejorar calidad con PIL
        if request.accion == 'mejorar':
            img = Image.open(ruta_foto)
            
            # Convertir a RGB si es necesario
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Crear nueva imagen mejorada
            from PIL import ImageEnhance, ImageFilter
            
            # Mejorar nitidez
            enhancer = ImageEnhance.Sharpness(img)
            img = enhancer.enhance(1.5)
            
            # Mejorar contraste
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(1.1)
            
            # Mejorar color
            enhancer = ImageEnhance.Color(img)
            img = enhancer.enhance(1.05)
            
            # Reducir ruido
            img = img.filter(ImageFilter.SMOOTH_MORE)
            
            # Guardar imagen mejorada
            nombre_mejorada = ruta_foto.replace('.', '_mejorada.')
            img.save(nombre_mejorada, optimize=True, quality=90)
            
            foto_url = f"/{nombre_mejorada}"
            
            # Actualizar en BD
            if current_user.personal_id:
                personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
                if personal:
                    personal.foto_url = foto_url
                    db.commit()
            
            return {"message": "Foto mejorada exitosamente", "foto_procesada": foto_url}
        
        # Quitar fondo
        elif request.accion == 'quitar_fondo':
            # Para quitar fondo se necesita remove.bg API
            # Como fallback, solo mejoramos la imagen
            img = Image.open(ruta_foto)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            nombre_sin_fondo = ruta_foto.replace('.', '_nobg.')
            img.save(nombre_sin_fondo, optimize=True, quality=90)
            
            foto_url = f"/{nombre_sin_fondo}"
            
            if current_user.personal_id:
                personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
                if personal:
                    personal.foto_url = foto_url
                    db.commit()
            
            return {"message": "Foto procesada", "foto_procesada": foto_url}
        
        else:
            raise HTTPException(status_code=400, detail="Acción no válida")
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error al procesar foto: {e}")
        raise HTTPException(status_code=500, detail=f"Error al procesar foto: {str(e)}")


# =====================================================
# GESTIÓN DE USUARIOS (CRUD)
# =====================================================

@router.post("/usuarios", response_model=UserProfile, status_code=status.HTTP_201_CREATED)
async def crear_usuario_auth(
    personal_id: UUID = Body(...),
    email: str = Body(...),
    password: str = Body(...),
    roles: List[str] = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea un usuario de autenticación vinculado a un personal existente."""
    personal = db.query(Personal).filter(Personal.id == personal_id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    if not verificar_acceso_empresa(current_user, personal.empresa_id):
        raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    existente = db.query(Usuario).filter(Usuario.email.ilike(email)).first()
    if existente:
        raise HTTPException(status_code=400, detail="Email ya registrado")
    
    usuario_existente = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    if usuario_existente:
        raise HTTPException(status_code=400, detail="Este personal ya tiene un usuario")
    
    usuario = Usuario(
        personal_id=personal_id, email=email,
        password_hash=get_password_hash(password), roles=roles,
        empresa_id=current_user.empresa_id, rol_global="usuario", activo=True
    )
    db.add(usuario)
    if personal.roles != roles:
        personal.roles = roles
    db.commit()
    db.refresh(usuario)
    
    personal_data = obtener_datos_personal_individual(db, personal_id)
    return {
        "id": usuario.id, "email": usuario.email, "username": usuario.username,
        "personal_id": usuario.personal_id, "empresa_id": usuario.empresa_id,
        "rol_global": usuario.rol_global,
        "roles": personal_data["roles"] if personal_data else usuario.roles,
        "activo": usuario.activo, "ultimo_acceso": usuario.ultimo_acceso,
        "nombre": personal_data["nombre"] if personal_data else None,
        "grado": personal_data["grado"] if personal_data else None,
        "area": personal_data["area"] if personal_data else None,
        "dni": personal_data["dni"] if personal_data else None,
        "cip": personal_data["cip"] if personal_data else None,
        "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else []
    }


@router.get("/usuarios")
async def listar_usuarios_auth(
    limit: int = 200,
    offset: int = 0,
    activo: Optional[bool] = None,
    ordenar_por: Optional[str] = "email",
    orden: Optional[str] = "asc",
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """
    Lista usuarios de autenticación con paginación y SIN N+1 queries.
    
    Parámetros:
    - limit: máximo de registros (default 200)
    - offset: desplazamiento para paginación
    - activo: filtrar por estado (true/false)
    - ordenar_por: campo para ordenar (email, id)
    - orden: dirección (asc, desc)
    """
    # Construir query base
    if current_user.rol_global == "super_admin":
        query = db.query(Usuario)
    else:
        query = db.query(Usuario).filter(
            Usuario.empresa_id == current_user.empresa_id
        )
    
    # Filtrar por activo si se especifica
    if activo is not None:
        query = query.filter(Usuario.activo == activo)
    
    # Ordenar
    if ordenar_por == "id":
        order_col = Usuario.id
    else:
        order_col = Usuario.email
    
    if orden == "desc":
        query = query.order_by(order_col.desc())
    else:
        query = query.order_by(order_col.asc())
    
    # Aplicar límite y offset
    usuarios = query.offset(offset).limit(limit).all()
    
    # =====================================================
    # OPTIMIZACIÓN: Obtener todos los personal en UNA SOLA query
    # Esto evita el problema N+1 queries
    # =====================================================
    personal_ids = [u.personal_id for u in usuarios if u.personal_id]
    personal_map = obtener_datos_personal_lote(db, personal_ids)
    
    # Construir resultados
    resultados = []
    for usuario in usuarios:
        personal_data = personal_map.get(usuario.personal_id)
        
        resultado = {
            "id": usuario.id,
            "email": usuario.email,
            "username": usuario.username,
            "personal_id": usuario.personal_id,
            "empresa_id": usuario.empresa_id,
            "rol_global": usuario.rol_global,
            "roles": personal_data["roles"] if personal_data else (usuario.roles or []),
            "activo": usuario.activo,
            "ultimo_acceso": usuario.ultimo_acceso,
            "nombre": personal_data["nombre"] if personal_data else None,
            "grado": personal_data["grado"] if personal_data else None,
            "area": personal_data["area"] if personal_data else None,
            "dni": personal_data["dni"] if personal_data else None,
            "cip": personal_data["cip"] if personal_data else None,
            "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else [],
            "foto_url": personal_data["foto_url"] if personal_data else None,
            "telefono": personal_data["telefono"] if personal_data else None,
            "sexo": personal_data["sexo"] if personal_data else None,
        }
        resultados.append(resultado)
    
    return resultados


@router.get("/usuarios/{usuario_id}", response_model=UserProfile)
async def obtener_usuario_auth(
    usuario_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Obtiene un usuario por ID."""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not verificar_acceso_empresa(current_user, usuario.empresa_id):
        raise HTTPException(status_code=403, detail="No tiene acceso a este usuario")
    
    personal_data = obtener_datos_personal_individual(db, usuario.personal_id)
    return {
        "id": usuario.id, "email": usuario.email, "username": usuario.username,
        "personal_id": usuario.personal_id, "empresa_id": usuario.empresa_id,
        "rol_global": usuario.rol_global,
        "roles": personal_data["roles"] if personal_data else (usuario.roles or []),
        "activo": usuario.activo, "ultimo_acceso": usuario.ultimo_acceso,
        "nombre": personal_data["nombre"] if personal_data else None,
        "grado": personal_data["grado"] if personal_data else None,
        "area": personal_data["area"] if personal_data else None,
        "dni": personal_data["dni"] if personal_data else None,
        "cip": personal_data["cip"] if personal_data else None,
        "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else []
    }


@router.put("/usuarios/{usuario_id}", response_model=UserProfile)
async def actualizar_usuario_auth(
    usuario_id: UUID,
    email: Optional[str] = Body(None),
    activo: Optional[bool] = Body(None),
    roles: Optional[List[str]] = Body(None),
    rol_global: Optional[str] = Body(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Actualiza un usuario. Solo super_admin puede cambiar rol_global."""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if not verificar_acceso_empresa(current_user, usuario.empresa_id):
        raise HTTPException(status_code=403, detail="No tiene acceso a este usuario")
    if usuario.id == current_user.id and rol_global is not None:
        raise HTTPException(status_code=400, detail="No puede modificar su propio rol global")
    
    if email is not None and email != usuario.email:
        existente = db.query(Usuario).filter(Usuario.email.ilike(email)).first()
        if existente:
            raise HTTPException(status_code=400, detail="Email ya registrado")
        usuario.email = email
    if activo is not None:
        usuario.activo = activo
    if roles is not None:
        usuario.roles = roles
        personal = db.query(Personal).filter(Personal.id == usuario.personal_id).first()
        if personal:
            personal.roles = roles
    if rol_global is not None and current_user.rol_global == "super_admin":
        usuario.rol_global = rol_global
    
    db.commit()
    db.refresh(usuario)
    
    personal_data = obtener_datos_personal_individual(db, usuario.personal_id)
    return {
        "id": usuario.id, "email": usuario.email, "username": usuario.username,
        "personal_id": usuario.personal_id, "empresa_id": usuario.empresa_id,
        "rol_global": usuario.rol_global,
        "roles": personal_data["roles"] if personal_data else (usuario.roles or []),
        "activo": usuario.activo, "ultimo_acceso": usuario.ultimo_acceso,
        "nombre": personal_data["nombre"] if personal_data else None,
        "grado": personal_data["grado"] if personal_data else None,
        "area": personal_data["area"] if personal_data else None,
        "dni": personal_data["dni"] if personal_data else None,
        "cip": personal_data["cip"] if personal_data else None,
        "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else []
    }


@router.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_usuario_auth(
    usuario_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina un usuario."""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    if usuario.id == current_user.id:
        raise HTTPException(status_code=400, detail="No puede eliminar su propio usuario")
    if not verificar_acceso_empresa(current_user, usuario.empresa_id):
        raise HTTPException(status_code=403, detail="No tiene acceso a este usuario")
    
    db.delete(usuario)
    db.commit()
    return None


# =====================================================
# ENDPOINTS AUXILIARES
# =====================================================

@router.get("/personal/{personal_id}/auth-id")
async def obtener_auth_id_por_personal(
    personal_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Obtiene el ID de autenticación a partir del ID de personal."""
    usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Este personal no tiene usuario")
    if not verificar_acceso_empresa(current_user, usuario.empresa_id):
        raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    personal_data = obtener_datos_personal_individual(db, personal_id)
    return {
        "usuario_id": usuario.id, "personal_id": usuario.personal_id, "email": usuario.email,
        "roles": personal_data["roles"] if personal_data else usuario.roles,
        "empresa_id": str(usuario.empresa_id) if usuario.empresa_id else None,
        "rol_global": usuario.rol_global, "activo": usuario.activo
    }


@router.post("/generar-password-temporal")
async def generar_password_temporal(
    personal_id: UUID = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Genera una contraseña temporal segura."""
    personal = db.query(Personal).filter(Personal.id == personal_id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Este personal no tiene usuario")
    if not verificar_acceso_empresa(current_user, usuario.empresa_id):
        raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    import secrets, string
    alphabet = string.ascii_letters + string.digits + "!@#$%&*"
    password_temporal = ''.join(secrets.choice(alphabet) for _ in range(12))
    usuario.password_hash = get_password_hash(password_temporal)
    db.commit()
    return {
        "message": "Contraseña temporal generada exitosamente",
        "password_temporal": password_temporal,
        "usuario_id": str(usuario.id), "email": usuario.email
    }


@router.get("/personal/{personal_id}/tiene-auth")
async def verificar_tiene_auth(
    personal_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Verifica si un personal tiene usuario."""
    usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    return {
        "tiene_auth": usuario is not None, "personal_id": personal_id,
        "usuario_id": str(usuario.id) if usuario else None,
        "email": usuario.email if usuario else None
    }


@router.get("/personal/{personal_id}/usuario", response_model=UserProfile)
async def obtener_usuario_por_personal(
    personal_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """Obtiene el usuario asociado a un personal."""
    usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Este personal no tiene usuario")
    if not verificar_acceso_empresa(current_user, usuario.empresa_id):
        raise HTTPException(status_code=403, detail="No tiene acceso a este personal")
    
    personal_data = obtener_datos_personal_individual(db, personal_id)
    return {
        "id": usuario.id, "email": usuario.email, "username": usuario.username,
        "personal_id": usuario.personal_id, "empresa_id": usuario.empresa_id,
        "rol_global": usuario.rol_global,
        "roles": personal_data["roles"] if personal_data else (usuario.roles or []),
        "activo": usuario.activo, "ultimo_acceso": usuario.ultimo_acceso,
        "nombre": personal_data["nombre"] if personal_data else None,
        "grado": personal_data["grado"] if personal_data else None,
        "area": personal_data["area"] if personal_data else None,
        "dni": personal_data["dni"] if personal_data else None,
        "cip": personal_data["cip"] if personal_data else None,
        "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else []
    }


@router.get("/debug/my-roles")
async def debug_my_roles(
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """DEBUG: Muestra los roles actuales del usuario."""
    user_roles = current_user.roles or []
    personal_roles = []
    if current_user.personal_id:
        personal = db.query(Personal).filter(Personal.id == current_user.personal_id).first()
        if personal:
            personal_roles = personal.roles or []
    
    return {
        "email": current_user.email,
        "personal_id": str(current_user.personal_id) if current_user.personal_id else None,
        "empresa_id": str(current_user.empresa_id) if current_user.empresa_id else None,
        "rol_global": current_user.rol_global,
        "roles_from_usuario_table": user_roles,
        "roles_from_personal_table": personal_roles,
        "are_synced": user_roles == personal_roles,
        "has_admin_role": "admin" in [r.lower() for r in user_roles] or "admin" in [r.lower() for r in personal_roles]
    }