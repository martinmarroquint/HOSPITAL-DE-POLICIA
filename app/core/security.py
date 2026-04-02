from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings

# =====================================================
# ✅ CONFIGURACIÓN CORREGIDA: SOPORTE PARA BCRYPT Y ARGON2
# =====================================================
# Ahora puede verificar contraseñas en AMBOS formatos:
# - BCRYPT (para usuarios nuevos como jesus@administracion.com)
# - ARGON2 (para usuarios existentes de la base de datos original)
# =====================================================

pwd_context = CryptContext(
    schemes=["bcrypt", "argon2"],  # ← CAMBIADO: primero bcrypt, luego argon2
    deprecated="auto",
    # Configuración para bcrypt
    bcrypt__rounds=12,
    # Configuración para argon2
    argon2__rounds=4,
    argon2__memory_cost=65536,
    argon2__parallelism=4
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si la contraseña plana coincide con el hash
    AHORA SOPORTA TANTO BCRYPT COMO ARGON2
    
    Args:
        plain_password: Contraseña en texto plano
        hashed_password: Hash almacenado en la base de datos
    
    Returns:
        bool: True si la contraseña es correcta, False en caso contrario
    """
    try:
        # passlib detecta automáticamente el tipo de hash
        # y usa el esquema correcto (bcrypt o argon2)
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"Error verificando password: {e}")
        return False

def get_password_hash(password: str) -> str:
    """
    Genera hash de contraseña usando bcrypt (más compatible)
    
    Args:
        password: Contraseña en texto plano
    
    Returns:
        str: Hash de la contraseña en formato bcrypt
    """
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """
    Crea token JWT para autenticación
    
    Args:
        data: Datos a incluir en el token (ej: {"sub": email, "user_id": id})
        expires_delta: Tiempo de expiración personalizado (opcional)
    
    Returns:
        str: Token JWT codificado
    """
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
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
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None

def has_role(user_roles: List[str], required_roles: List[str]) -> bool:
    """
    Verifica si el usuario tiene alguno de los roles requeridos
    
    Args:
        user_roles: Lista de roles del usuario
        required_roles: Lista de roles requeridos
    
    Returns:
        bool: True si el usuario tiene al menos un rol requerido o es admin
    """
    if "admin" in user_roles:
        return True
    return any(role in user_roles for role in required_roles)