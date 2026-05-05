"""
DEPENDENCIAS MULTI-EMPRESA
Autenticación, autorización y control de acceso por empresa_id y rol_global
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session
from typing import List, Optional, Union
from uuid import UUID

from app.database import get_db
from app.models.usuario import Usuario
from app.models.empresa import Empresa
from app.core.security import decode_token, has_role, has_rol_global

oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    auto_error=False
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[Usuario]:
    """
    Obtiene el usuario actual desde el token JWT con soporte multi-empresa.
    Sincroniza empresa_id y rol_global desde el token si es necesario.
    """
    if not token:
        return None
        
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas. Inicie sesión nuevamente.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    # Decodificar token
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    
    # Obtener email del token
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    
    # Buscar usuario en base de datos
    user = db.query(Usuario).filter(Usuario.email.ilike(username)).first()
    if user is None:
        raise credentials_exception
    
    # Verificar que el usuario esté activo
    if not user.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo. Contacte al administrador."
        )
    
    # Sincronizar empresa_id desde el token si es necesario
    token_empresa_id = payload.get("empresa_id")
    if token_empresa_id and str(user.empresa_id) != token_empresa_id:
        try:
            user.empresa_id = UUID(token_empresa_id)
            db.commit()
        except (ValueError, TypeError):
            pass
    
    # Sincronizar rol_global desde el token si es necesario
    token_rol_global = payload.get("rol_global")
    if token_rol_global and user.rol_global != token_rol_global:
        user.rol_global = token_rol_global
        db.commit()
    
    return user


async def get_current_active_user(
    current_user: Usuario = Depends(get_current_user),
) -> Usuario:
    """
    Verifica que el usuario esté autenticado y activo.
    """
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Inicie sesión."
        )
    if not current_user.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo"
        )
    return current_user


async def get_current_super_admin(
    current_user: Usuario = Depends(get_current_active_user),
) -> Usuario:
    """
    Verifica que el usuario sea super_admin.
    Solo el dueño del sistema tiene este rol.
    """
    if current_user.rol_global != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Se requiere rol super_admin."
        )
    return current_user


async def get_current_admin_empresa(
    current_user: Usuario = Depends(get_current_active_user),
) -> Usuario:
    """
    Verifica que el usuario sea admin_empresa o super_admin.
    """
    if current_user.rol_global not in ["super_admin", "admin_empresa"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Se requiere rol admin_empresa."
        )
    return current_user


def require_roles(required_roles: List[str]):
    """
    Verifica que el usuario tenga al menos uno de los roles internos requeridos.
    El rol 'admin' tiene acceso automático a todo.
    """
    async def role_checker(
        current_user: Usuario = Depends(get_current_active_user),
    ) -> Usuario:
        if not has_role(current_user.roles or [], required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permisos insuficientes. Roles requeridos: {', '.join(required_roles)}"
            )
        return current_user
    return role_checker


def require_rol_global(allowed_roles: List[str]):
    """
    Verifica que el usuario tenga un rol global permitido.
    super_admin siempre tiene acceso.
    """
    async def rol_global_checker(
        current_user: Usuario = Depends(get_current_active_user),
    ) -> Usuario:
        if not has_rol_global(current_user.rol_global or "usuario", allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Acceso restringido. Rol global requerido: {', '.join(allowed_roles)}"
            )
        return current_user
    return rol_global_checker


# Dependencias predefinidas para roles comunes
require_admin = require_roles(["admin"])
require_jefe_area = require_roles(["admin", "jefe_area"])
require_oficial_permanencia = require_roles(["admin", "oficial_permanencia"])
require_control_qr = require_roles(["admin", "control_qr", "oficial_permanencia"])
require_super_admin = require_rol_global(["super_admin"])
require_admin_empresa = require_rol_global(["super_admin", "admin_empresa"])


def get_current_user_id(
    current_user: Usuario = Depends(get_current_active_user)
) -> UUID:
    """Obtiene el ID del usuario actual"""
    return current_user.id


def get_current_personal_id(
    current_user: Usuario = Depends(get_current_active_user)
) -> Optional[UUID]:
    """Obtiene el ID del personal asociado al usuario actual"""
    return current_user.personal_id


def get_current_empresa_id(
    current_user: Usuario = Depends(get_current_active_user)
) -> Optional[UUID]:
    """Obtiene el ID de la empresa del usuario actual"""
    return current_user.empresa_id


def get_current_user_info(
    current_user: Usuario = Depends(get_current_active_user)
) -> dict:
    """Obtiene información completa del usuario actual"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "username": current_user.username,
        "roles": current_user.roles,
        "personal_id": current_user.personal_id,
        "empresa_id": current_user.empresa_id,
        "rol_global": current_user.rol_global,
        "activo": current_user.activo
    }


async def get_current_user_or_none(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[Usuario]:
    """
    Obtiene el usuario actual o None si no hay token.
    Para endpoints que pueden ser públicos o privados.
    """
    if not token:
        return None
    
    try:
        user = await get_current_user(token, db)
        return user
    except HTTPException:
        return None
    except Exception:
        return None


async def verify_token(
    token: str = Depends(oauth2_scheme)
) -> bool:
    """Verifica si un token es válido sin obtener el usuario"""
    if not token:
        return False
    
    payload = decode_token(token)
    return payload is not None