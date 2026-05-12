# app/core/dependencies.py
"""
DEPENDENCIAS MULTI-EMPRESA CON JERARQUÍA DE ROLES
Autenticación, autorización y control de acceso por empresa_id, cliente_id y rol_global
Soporta: super_admin → admin_cliente → admin_empresa → jefe_unidad → usuario
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
from app.utils.roles import ROLES_ADMIN, ROLES_JEFE, ROLES_SOLO_ESCANER

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
    Sincroniza empresa_id, cliente_id y rol_global desde el token si es necesario.
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
    
    # Sincronizar empresa_id desde el token
    token_empresa_id = payload.get("empresa_id")
    if token_empresa_id and str(user.empresa_id) != token_empresa_id:
        try:
            user.empresa_id = UUID(token_empresa_id)
            db.commit()
        except (ValueError, TypeError):
            pass
    
    # Sincronizar cliente_id desde el token
    token_cliente_id = payload.get("cliente_id")
    if token_cliente_id and str(user.cliente_id) != token_cliente_id:
        try:
            user.cliente_id = UUID(token_cliente_id)
            db.commit()
        except (ValueError, TypeError):
            pass
    
    # Sincronizar rol_global desde el token
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
# DEPENDENCIAS POR ROL GLOBAL
# =====================================================

async def get_current_super_admin(
    current_user: Usuario = Depends(get_current_active_user),
) -> Usuario:
    """
    Verifica que el usuario sea super_admin.
    Acceso al panel global de monitoreo y gestión de clientes.
    """
    if current_user.rol_global != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Se requiere rol super_admin."
        )
    return current_user


async def get_current_admin_cliente(
    current_user: Usuario = Depends(get_current_active_user),
) -> Usuario:
    """
    Verifica que el usuario sea admin_cliente o superior.
    Acceso a gestión de empresas de su cliente.
    """
    if current_user.rol_global not in ["super_admin", "admin_cliente"]:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido. Se requiere rol admin_cliente o superior."
        )
    return current_user


async def get_current_admin_empresa(
    current_user: Usuario = Depends(get_current_active_user),
) -> Usuario:
    """
    Verifica que el usuario sea admin_empresa o superior.
    Super admin y admin_cliente también tienen acceso.
    """
    # Super admin y admin_cliente pueden acceder como admin_empresa
    if current_user.rol_global in ["super_admin", "admin_cliente"]:
        return current_user
    
    # admin_empresa o rol 'admin' interno
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
    Los roles admin (super_admin, admin_cliente, admin_empresa) tienen acceso automático.
    """
    async def role_checker(
        current_user: Usuario = Depends(get_current_active_user),
    ) -> Usuario:
        # Admins tienen acceso total
        if current_user.rol_global in ["super_admin", "admin_cliente", "admin_empresa"]:
            return current_user
        
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
    super_admin SIEMPRE tiene acceso.
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


# =====================================================
# DEPENDENCIAS PREDEFINIDAS
# =====================================================

require_admin = require_roles(ROLES_ADMIN)
require_jefe_area = require_roles(ROLES_ADMIN + ROLES_JEFE)
require_oficial_permanencia = require_roles(ROLES_ADMIN + ROLES_JEFE)
require_control_qr = require_roles(ROLES_ADMIN + ROLES_JEFE + ROLES_SOLO_ESCANER)
require_super_admin = require_rol_global(["super_admin"])
require_admin_cliente = require_rol_global(["super_admin", "admin_cliente"])
require_admin_empresa = require_rol_global(["super_admin", "admin_cliente", "admin_empresa"])


# =====================================================
# UTILITARIOS
# =====================================================

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


def get_current_cliente_id(
    current_user: Usuario = Depends(get_current_active_user)
) -> Optional[UUID]:
    """Obtiene el ID del cliente del usuario actual"""
    return current_user.cliente_id


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
        "cliente_id": str(current_user.cliente_id) if current_user.cliente_id else None,
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