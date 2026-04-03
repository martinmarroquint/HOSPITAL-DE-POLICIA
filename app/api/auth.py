from fastapi import APIRouter, Depends, HTTPException, status, Body
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session
from datetime import timedelta, datetime
from typing import Any, List, Optional
from uuid import UUID

from app.database import get_db
from app.core.security import create_access_token, verify_password, get_password_hash
from app.core.dependencies import get_current_user, get_current_active_user, require_roles
from app.models.usuario import Usuario
from app.models.personal import Personal
from app.schemas.auth import Token, LoginRequest, UserProfile, PasswordChange, UsuarioCreate
from app.config import settings

router = APIRouter()


# =====================================================
# FUNCIÓN AUXILIAR PARA OBTENER DATOS DE PERSONAL
# =====================================================
def obtener_datos_personal(db: Session, personal_id: UUID):
    """Obtiene los datos de personal incluyendo roles y áreas que jefatura"""
    personal = db.query(Personal).filter(Personal.id == personal_id).first()
    if not personal:
        return None
    return {
        "nombre": personal.nombre,
        "grado": personal.grado,
        "area": personal.area,
        "dni": personal.dni,
        "cip": personal.cip,
        "roles": personal.roles or [],
        "areas_que_jefatura": personal.areas_que_jefatura or []
    }


# =====================================================
# ✅ LOGIN CON VERIFICACIÓN NORMAL (SIN BYPASS)
# =====================================================
@router.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: Session = Depends(get_db)
) -> Any:
    """
    OAuth2 compatible token login
    Los roles se toman de la tabla PERSONAL, no de USUARIO
    """
    print(f"🔐 Intentando login para: {form_data.username}")
    
    # Buscar usuario por email
    user = db.query(Usuario).filter(Usuario.email == form_data.username).first()
    
    if not user:
        print(f"❌ Usuario no encontrado: {form_data.username}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    print(f"✅ Usuario encontrado: {user.email}")
    print(f"🔑 Hash en BD: {user.password_hash[:30]}..." if user.password_hash else "🔑 Hash es NULL")
    
    # ✅ VERIFICACIÓN NORMAL (SIN BYPASS)
    if not verify_password(form_data.password, user.password_hash):
        print(f"❌ Contraseña incorrecta para: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    print(f"✅ Contraseña correcta para: {user.email}")
    
    if not user.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )
    
    # ✅ OBTENER ROLES DE LA TABLA PERSONAL
    personal_data = obtener_datos_personal(db, user.personal_id)
    roles = personal_data["roles"] if personal_data else user.roles
    
    # Actualizar último acceso
    user.ultimo_acceso = datetime.utcnow()
    db.commit()
    
    # Crear token con roles de personal
    access_token_expires = timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": user.email, "user_id": str(user.id), "roles": roles},
        expires_delta=access_token_expires
    )
    
    print(f"🎉 Login exitoso para: {user.email}")
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "expires_in": settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60
    }


# =====================================================
# 🔍 ENDPOINT DE DIAGNÓSTICO - SOLO PARA PRUEBAS
# =====================================================
@router.get("/check-user")
async def check_user(
    email: str,
    db: Session = Depends(get_db)
):
    """Verifica si un usuario existe y muestra su estado (SOLO DIAGNÓSTICO)"""
    user = db.query(Usuario).filter(Usuario.email == email).first()
    
    if not user:
        return {"exists": False, "email": email}
    
    # Determinar tipo de hash
    if user.password_hash.startswith("$2b$"):
        hash_type = "bcrypt"
    elif user.password_hash.startswith("$argon2"):
        hash_type = "argon2"
    else:
        hash_type = "desconocido"
    
    return {
        "exists": True,
        "email": user.email,
        "username": user.username,
        "personal_id": str(user.personal_id),
        "hash_type": hash_type,
        "hash_prefix": user.password_hash[:30] if user.password_hash else None,
        "is_active": user.activo,
        "has_personal": user.personal_id is not None
    }


@router.post("/logout")
async def logout(current_user: Usuario = Depends(get_current_active_user)):
    """
    Logout (en cliente debe eliminar el token)
    """
    return {"message": "Sesión cerrada exitosamente"}


@router.get("/perfil", response_model=UserProfile)
async def get_perfil(
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Obtiene perfil del usuario autenticado con datos de personal
    Incluye roles correctos desde la tabla PERSONAL
    """
    personal_data = obtener_datos_personal(db, current_user.personal_id)
    
    if personal_data:
        return {
            "id": current_user.id,
            "email": current_user.email,
            "personal_id": current_user.personal_id,
            "roles": personal_data["roles"],
            "activo": current_user.activo,
            "ultimo_acceso": current_user.ultimo_acceso,
            "nombre": personal_data["nombre"],
            "grado": personal_data["grado"],
            "area": personal_data["area"],
            "dni": personal_data["dni"],
            "cip": personal_data["cip"],
            "areas_que_jefatura": personal_data["areas_que_jefatura"]
        }
    else:
        return {
            "id": current_user.id,
            "email": current_user.email,
            "personal_id": current_user.personal_id,
            "roles": current_user.roles,
            "activo": current_user.activo,
            "ultimo_acceso": current_user.ultimo_acceso,
            "nombre": None,
            "grado": None,
            "area": None,
            "dni": None,
            "cip": None,
            "areas_que_jefatura": []
        }


@router.get("/verificar")
async def verificar_token(
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Verifica si el token es válido
    """
    return {
        "valid": True,
        "user_id": str(current_user.id),
        "email": current_user.email,
        "roles": current_user.roles
    }


@router.post("/cambiar-password")
async def cambiar_password(
    password_data: PasswordChange,
    current_user: Usuario = Depends(get_current_active_user),
    db: Session = Depends(get_db)
):
    """
    Cambia la contraseña del usuario
    """
    if not verify_password(password_data.current_password, current_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contraseña actual incorrecta"
        )
    
    current_user.password_hash = get_password_hash(password_data.new_password)
    db.commit()
    
    return {"message": "Contraseña actualizada exitosamente"}


# =====================================================
# ENDPOINTS PARA GESTIÓN DE USUARIOS DE AUTENTICACIÓN
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
    """Crea un usuario de autenticación para un personal existente"""
    personal = db.query(Personal).filter(Personal.id == personal_id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    existente = db.query(Usuario).filter(Usuario.email == email).first()
    if existente:
        raise HTTPException(status_code=400, detail="Email ya registrado")
    
    usuario_existente = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    if usuario_existente:
        raise HTTPException(status_code=400, detail="Este personal ya tiene un usuario")
    
    usuario = Usuario(
        personal_id=personal_id,
        email=email,
        password_hash=get_password_hash(password),
        roles=roles,
        activo=True
    )
    
    db.add(usuario)
    personal.roles = roles
    db.commit()
    db.refresh(usuario)
    
    return {
        "id": usuario.id,
        "email": usuario.email,
        "personal_id": usuario.personal_id,
        "roles": usuario.roles,
        "activo": usuario.activo,
        "ultimo_acceso": usuario.ultimo_acceso,
        "nombre": personal.nombre,
        "grado": personal.grado,
        "area": personal.area,
        "dni": personal.dni,
        "cip": personal.cip,
        "areas_que_jefatura": personal.areas_que_jefatura or []
    }


@router.get("/usuarios", response_model=List[UserProfile])
async def listar_usuarios_auth(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Lista todos los usuarios de autenticación"""
    usuarios = db.query(Usuario).all()
    resultados = []
    
    for usuario in usuarios:
        personal_data = obtener_datos_personal(db, usuario.personal_id)
        resultados.append({
            "id": usuario.id,
            "email": usuario.email,
            "personal_id": usuario.personal_id,
            "roles": personal_data["roles"] if personal_data else usuario.roles,
            "activo": usuario.activo,
            "ultimo_acceso": usuario.ultimo_acceso,
            "nombre": personal_data["nombre"] if personal_data else None,
            "grado": personal_data["grado"] if personal_data else None,
            "area": personal_data["area"] if personal_data else None,
            "dni": personal_data["dni"] if personal_data else None,
            "cip": personal_data["cip"] if personal_data else None,
            "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else []
        })
    
    return resultados


@router.get("/usuarios/{usuario_id}", response_model=UserProfile)
async def obtener_usuario_auth(
    usuario_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Obtiene un usuario de autenticación por ID"""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    personal_data = obtener_datos_personal(db, usuario.personal_id)
    
    return {
        "id": usuario.id,
        "email": usuario.email,
        "personal_id": usuario.personal_id,
        "roles": personal_data["roles"] if personal_data else usuario.roles,
        "activo": usuario.activo,
        "ultimo_acceso": usuario.ultimo_acceso,
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
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Actualiza un usuario de autenticación"""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    personal = db.query(Personal).filter(Personal.id == usuario.personal_id).first()
    
    if email is not None and email != usuario.email:
        existente = db.query(Usuario).filter(Usuario.email == email).first()
        if existente:
            raise HTTPException(status_code=400, detail="Email ya registrado")
        usuario.email = email
    
    if activo is not None:
        usuario.activo = activo
    
    if roles is not None:
        usuario.roles = roles
        if personal:
            personal.roles = roles
            db.commit()
    
    db.commit()
    db.refresh(usuario)
    
    personal_data = obtener_datos_personal(db, usuario.personal_id)
    
    return {
        "id": usuario.id,
        "email": usuario.email,
        "personal_id": usuario.personal_id,
        "roles": personal_data["roles"] if personal_data else usuario.roles,
        "activo": usuario.activo,
        "ultimo_acceso": usuario.ultimo_acceso,
        "nombre": personal_data["nombre"] if personal_data else None,
        "grado": personal_data["grado"] if personal_data else None,
        "area": personal_data["area"] if personal_data else None,
        "dni": personal_data["dni"] if personal_data else None,
        "cip": personal_data["cip"] if personal_data else None,
        "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else []
    }


# =====================================================
# ENDPOINT PARA RESETEAR CONTRASEÑA
# =====================================================
@router.post("/reset-password")
@router.post("/usuarios/{usuario_id}/reset-password")
async def reset_password_usuario(
    usuario_id: Optional[UUID] = None,
    personal_id: Optional[UUID] = Body(None, embed=True),
    nueva_password: str = Body(..., embed=True),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Resetea la contraseña de un usuario"""
    usuario = None
    
    if usuario_id:
        usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    
    if not usuario and personal_id:
        usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    usuario.password_hash = get_password_hash(nueva_password)
    db.commit()
    
    return {
        "message": "Contraseña restablecida exitosamente",
        "usuario_id": str(usuario.id),
        "personal_id": str(usuario.personal_id),
        "email": usuario.email
    }


@router.get("/personal/{personal_id}/auth-id")
async def obtener_auth_id_por_personal(
    personal_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Obtiene el ID de autenticación a partir del ID de personal"""
    usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Este personal no tiene usuario")
    
    personal_data = obtener_datos_personal(db, personal_id)
    
    return {
        "usuario_id": usuario.id,
        "personal_id": usuario.personal_id,
        "email": usuario.email,
        "roles": personal_data["roles"] if personal_data else usuario.roles,
        "activo": usuario.activo
    }


@router.post("/generar-password-temporal")
async def generar_password_temporal(
    personal_id: UUID = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Genera una contraseña temporal para un usuario"""
    personal = db.query(Personal).filter(Personal.id == personal_id).first()
    if not personal:
        raise HTTPException(status_code=404, detail="Personal no encontrado")
    
    usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Este personal no tiene usuario")
    
    import random
    import string
    sufijo = ''.join(random.choices(string.ascii_uppercase + string.digits, k=2))
    password_temporal = f"{personal.dni}{sufijo}" if personal.dni else f"temp{random.randint(1000, 9999)}"
    
    usuario.password_hash = get_password_hash(password_temporal)
    db.commit()
    
    return {
        "message": "Contraseña temporal generada",
        "password_temporal": password_temporal,
        "usuario_id": usuario.id,
        "email": usuario.email
    }


@router.get("/personal/{personal_id}/tiene-auth")
async def verificar_tiene_auth(
    personal_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Verifica si un personal tiene usuario"""
    usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    
    return {
        "tiene_auth": usuario is not None,
        "personal_id": personal_id,
        "usuario_id": str(usuario.id) if usuario else None,
        "email": usuario.email if usuario else None
    }


@router.delete("/usuarios/{usuario_id}", status_code=status.HTTP_204_NO_CONTENT)
async def eliminar_usuario_auth(
    usuario_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina un usuario de autenticación"""
    usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Usuario no encontrado")
    
    if usuario.id == current_user.id:
        raise HTTPException(status_code=400, detail="No puedes eliminar tu propio usuario")
    
    db.delete(usuario)
    db.commit()
    
    return None


@router.get("/personal/{personal_id}/usuario", response_model=UserProfile)
async def obtener_usuario_por_personal(
    personal_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "jefe_area"]))
):
    """Obtiene el usuario asociado a un personal"""
    usuario = db.query(Usuario).filter(Usuario.personal_id == personal_id).first()
    if not usuario:
        raise HTTPException(status_code=404, detail="Este personal no tiene usuario")
    
    personal_data = obtener_datos_personal(db, personal_id)
    
    return {
        "id": usuario.id,
        "email": usuario.email,
        "personal_id": usuario.personal_id,
        "roles": personal_data["roles"] if personal_data else usuario.roles,
        "activo": usuario.activo,
        "ultimo_acceso": usuario.ultimo_acceso,
        "nombre": personal_data["nombre"] if personal_data else None,
        "grado": personal_data["grado"] if personal_data else None,
        "area": personal_data["area"] if personal_data else None,
        "dni": personal_data["dni"] if personal_data else None,
        "cip": personal_data["cip"] if personal_data else None,
        "areas_que_jefatura": personal_data["areas_que_jefatura"] if personal_data else []
    }