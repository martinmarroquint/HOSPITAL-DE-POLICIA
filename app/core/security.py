"""
CORE DE SEGURIDAD - ARGON2 EXCLUSIVO
Sistema multi-empresa con JWT enriquecido
"""

from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings

# =====================================================
# CONFIGURACIÓN ARGON2 EXCLUSIVO
# - Solo Argon2 para generar y verificar
# - Máxima seguridad para datos sensibles
# - Sin compatibilidad con bcrypt (más limpio, más seguro)
# =====================================================

pwd_context = CryptContext(
    schemes=["argon2"],
    deprecated="auto",
    argon2__rounds=4,
    argon2__memory_cost=65536,
    argon2__parallelism=4,
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si la contraseña plana coincide con el hash.
    Usa exclusivamente Argon2 para máxima seguridad.
    
    Args:
        plain_password: Contraseña en texto plano
        hashed_password: Hash almacenado en la base de datos
    
    Returns:
        bool: True si la contraseña es correcta, False en caso contrario
    """
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"❌ Error verificando password: {e}")
        return False

def get_password_hash(password: str) -> str:
    """
    Genera hash de contraseña usando ARGON2
    
    Args:
        password: Contraseña en texto plano
    
    Returns:
        str: Hash de la contraseña en formato Argon2
    """
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea token JWT enriquecido para autenticación multi-empresa
    
    Args:
        data: Datos a incluir en el token:
              - sub: email del usuario
              - user_id: UUID del usuario
              - personal_id: UUID del personal asociado
              - roles: lista de roles internos
              - empresa_id: UUID de la empresa
              - rol_global: super_admin, admin_empresa, usuario
              - area: área del personal
              - username: nombre de usuario
        expires_delta: Tiempo de expiración personalizado (opcional)
    
    Returns:
        str: Token JWT codificado
    """
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({
        "exp": expire,
        "iat": datetime.utcnow(),
        "type": "access"
    })
    
    encoded_jwt = jwt.encode(
        to_encode, 
        settings.JWT_SECRET_KEY, 
        algorithm=settings.JWT_ALGORITHM
    )
    return encoded_jwt

def decode_token(token: str) -> Optional[dict]:
    """
    Decodifica y valida un token JWT
    
    Args:
        token: Token JWT a decodificar
    
    Returns:
        Optional[dict]: Payload del token si es válido, None en caso contrario
    """
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError as e:
        print(f"❌ Error decodificando token: {e}")
        return None

def has_role(user_roles: List[str], required_roles: List[str]) -> bool:
    """
    Verifica si el usuario tiene alguno de los roles requeridos.
    El rol 'admin' tiene acceso automático a todo.
    
    Args:
        user_roles: Lista de roles del usuario
        required_roles: Lista de roles requeridos
    
    Returns:
        bool: True si el usuario tiene al menos un rol requerido o es admin
    """
    if not user_roles:
        return False
    
    # Admin tiene acceso total
    if "admin" in [r.lower() for r in user_roles]:
        return True
    
    # Verificar si tiene alguno de los roles requeridos
    return any(
        role.lower() in [r.lower() for r in user_roles] 
        for role in required_roles
    )

def has_rol_global(user_rol_global: str, allowed_roles: List[str]) -> bool:
    """
    Verifica si el usuario tiene un rol global permitido.
    super_admin tiene acceso automático a todo.
    
    Args:
        user_rol_global: Rol global del usuario
        allowed_roles: Lista de roles globales permitidos
    
    Returns:
        bool: True si el usuario tiene acceso
    """
    if user_rol_global == "super_admin":
        return True
    
    return user_rol_global in allowed_roles