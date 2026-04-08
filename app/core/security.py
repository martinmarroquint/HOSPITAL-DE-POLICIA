from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings

# =====================================================
# ✅ CONFIGURACIÓN HÍBRIDA (RECOMENDADA)
# =====================================================
# - VERIFICA: Ambos formatos (bcrypt y Argon2)
# - GENERA: SOLO Argon2 (evita el bug de bcrypt en reseteos)
#
# Beneficios:
# ✅ Usuarios existentes con bcrypt: Siguen funcionando
# ✅ Nuevos passwords/reseteos: Usan Argon2 (sin errores)
# ✅ Migración gradual y transparente
# =====================================================

pwd_context = CryptContext(
    schemes=["argon2", "bcrypt"],  # ← Argon2 PRIMERO = default para generar
    deprecated="auto",
    # Configuración para Argon2 (usado para NUEVOS hashes)
    argon2__rounds=4,
    argon2__memory_cost=65536,
    argon2__parallelism=4,
    # Configuración para bcrypt (SOLO para verificar hashes antiguos)
    bcrypt__rounds=12
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifica si la contraseña plana coincide con el hash.
    SOPORTA TANTO BCRYPT COMO ARGON2
    
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
        print(f"❌ Error verificando password: {e}")
        return False

def get_password_hash(password: str) -> str:
    """
    Genera hash de contraseña usando ARGON2 (evita el bug de bcrypt)
    
    Args:
        password: Contraseña en texto plano
    
    Returns:
        str: Hash de la contraseña en formato Argon2
    """
    # Forzar explícitamente Argon2 para evitar problemas con bcrypt
    return pwd_context.hash(password, scheme="argon2")

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