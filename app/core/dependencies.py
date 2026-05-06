"""
DEPENDENCIAS MULTI-EMPRESA
Autenticación, autorización y control de acceso por empresa_id y rol_global
CORREGIDO: Super admin NO puede acceder a datos de empresas
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
        detail="Credenciales invalidas. Inicie sesion nuevamente.",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    
    user = db.query(Usuario).filter(Usuario.email.ilike(username)).first()
    if user is None:
        raise credentials_exception
    
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
    """Verifica que el usuario este autenticado y activo."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado. Inicie sesion."
        )
    if not current_user.activo:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Usuario inactivo"
        )
    return current_user


# =====================================================
# ROLES GLOBALES
# =====================================================

async def get_current_super_admin(
    current_user: Usuario = Depends(get_current_active_user),
) -> Usuario:
    """
    Verifica que el usuario sea super_admin.
    SOLO para dashboard de monitoreo multi-empresa.
    NO puede acceder a datos de empresas especificas.
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
    Verifica que el usuario sea admin_empresa EXCLUSIVAMENTE.
    El super_admin NO tiene acceso a datos de empresas.
    Debe usar impersonation si necesita acceder.
    """
    # Super admin NO puede acceder a datos de empresas
    if current_user.rol_global == "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Super admin no tiene acceso a datos de empresas. "
                   "Use el dashboard de monitoreo o active impersonation."
        )
    
    # Debe ser admin_empresa o tener rol 'admin' interno
    roles = current_user.roles or []
    is_admin_global = current_user.rol_global == "admin_empresa"
    is_admin_interno = "admin" in [r.lower() for r in roles if isinstance(r, str)]
    
    if not is_admin_global and not is_admin_interno:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Se requiere rol de administrador de empresa."
        )
    
    if not current_user.empresa_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario sin empresa asignada."
        )
    
    return current_user


def require_roles(required_roles: List[str]):
    """
    Verifica que el usuario tenga al menos uno de los roles internos requeridos.
    El rol 'admin' tiene acceso automatico a todo.
    El super_admin NO tiene acceso a endpoints de empresa.
    """
    async def role_checker(
        current_user: Usuario = Depends(get_current_active_user),
    ) -> Usuario:
        # Si es super_admin, DENEGAR acceso a endpoints de empresa
        if current_user.rol_global == "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Super admin no tiene acceso a esta funcion. "
                       "Use el dashboard de monitoreo."
            )
        
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
    super_admin SIEMPRE tiene acceso a endpoints de super_admin.
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
require_admin_empresa = require_rol_global(["admin_empresa"])


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
    """Obtiene informacion completa del usuario actual"""
    return {
        "id": str(current_user.id),
        "email": current_user.email,
        "username": current_user.username,
        "roles": current_user.roles,
        "personal_id": str(current_user.personal_id) if current_user.personal_id else None,
        "empresa_id": str(current_user.empresa_id) if current_user.empresa_id else None,
        "rol_global": current_user.rol_global,
        "activo": current_user.activo
    }


async def get_current_user_or_none(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[Usuario]:
    """
    Obtiene el usuario actual o None si no hay token.
    Para endpoints que pueden ser publicos o privados.
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
    """Verifica si un token es valido sin obtener el usuario"""
    if not token:
        return False
    
    payload = decode_token(token)
    return payload is not None