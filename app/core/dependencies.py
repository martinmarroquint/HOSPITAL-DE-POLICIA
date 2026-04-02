# D:\Centro de control Hospital PNP\back\app\core\dependencies.py

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session
from typing import List, Optional, Union
from uuid import UUID

from app.database import get_db
from app.models.usuario import Usuario
from app.core.security import decode_token, has_role
from app.schemas.auth import TokenData

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[Usuario]:
    """Obtiene el usuario actual desde el token JWT"""
    if not token:
        return None
        
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
    
    username: str = payload.get("sub")
    if username is None:
        raise credentials_exception
    
    user = db.query(Usuario).filter(Usuario.email == username).first()
    if user is None:
        raise credentials_exception
    
    if not user.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )
    
    return user

async def get_current_active_user(
    current_user: Usuario = Depends(get_current_user),
) -> Usuario:
    """Verifica que el usuario esté activo"""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    if not current_user.activo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Usuario inactivo"
        )
    return current_user

# ✅ NUEVA DEPENDENCIA: get_current_admin_user
async def get_current_admin_user(
    current_user: Usuario = Depends(get_current_active_user),
) -> Usuario:
    """Verifica que el usuario actual sea administrador"""
    
    # Verificar si tiene rol admin
    if not has_role(current_user.roles, ["admin"]):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="No tiene permisos de administrador para acceder a este recurso"
        )
    
    return current_user

def require_roles(required_roles: List[str]):
    """Decorator para requerir roles específicos"""
    async def role_checker(
        current_user: Usuario = Depends(get_current_active_user),
    ) -> Usuario:
        if not has_role(current_user.roles, required_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"No tiene permisos para acceder a este recurso. Roles requeridos: {', '.join(required_roles)}"
            )
        return current_user
    return role_checker

# ✅ NUEVA: Dependencias predefinidas para roles comunes
require_admin = require_roles(["admin"])
require_jefe_area = require_roles(["admin", "jefe_area"])
require_oficial_permanencia = require_roles(["admin", "oficial_permanencia"])
require_control_qr = require_roles(["admin", "control_qr", "oficial_permanencia"])

def get_current_user_id(current_user: Usuario = Depends(get_current_active_user)) -> UUID:
    """Obtiene el ID del usuario actual"""
    return current_user.id

def get_current_personal_id(current_user: Usuario = Depends(get_current_active_user)) -> Optional[UUID]:
    """Obtiene el ID del personal asociado al usuario actual"""
    return current_user.personal_id

# ✅ NUEVA: get_current_user_info - Información completa del usuario
def get_current_user_info(current_user: Usuario = Depends(get_current_active_user)) -> dict:
    """Obtiene información completa del usuario actual"""
    return {
        "id": current_user.id,
        "email": current_user.email,
        "nombre": current_user.nombre,
        "roles": current_user.roles,
        "personal_id": current_user.personal_id,
        "activo": current_user.activo
    }

# ✅ NUEVA: get_current_user_or_none - Para endpoints que pueden ser públicos
async def get_current_user_or_none(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db)
) -> Optional[Usuario]:
    """Obtiene el usuario actual o None si no hay token (para endpoints públicos)"""
    if not token:
        return None
    
    try:
        user = await get_current_user(token, db)
        return user
    except HTTPException:
        return None
    except Exception:
        return None

# ✅ NUEVA: verify_token - Para verificar tokens sin obtener usuario
async def verify_token(
    token: str = Depends(oauth2_scheme)
) -> bool:
    """Verifica si un token es válido sin obtener el usuario"""
    if not token:
        return False
    
    payload = decode_token(token)
    return payload is not None

# =====================================================
# 📊 ALIAS DE FUNCIONES PARA COMPATIBILIDAD
# =====================================================
# Mantener nombres originales para no romper código existente
get_current_admin_user_dep = get_current_admin_user
get_current_user_optional = get_current_user_or_none