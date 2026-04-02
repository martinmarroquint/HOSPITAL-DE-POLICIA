# app/core/security.py
from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings

# Configurar CryptContext para usar argon2 (el que funciona)
pwd_context = CryptContext(
    schemes=["argon2"],  # ← Cambiado de bcrypt a argon2
    deprecated="auto",
    argon2__rounds=4,  # Parámetros óptimos para argon2
    argon2__memory_cost=65536,
    argon2__parallelism=4
)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verifica si la contraseña plana coincide con el hash"""
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except Exception as e:
        print(f"Error verificando password: {e}")
        return False

def get_password_hash(password: str) -> str:
    """Genera hash de contraseña usando argon2"""
    return pwd_context.hash(password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Crea token JWT"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt

def decode_token(token: str) -> Optional[dict]:
    """Decodifica token JWT"""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        return None

def has_role(user_roles: List[str], required_roles: List[str]) -> bool:
    """Verifica si el usuario tiene alguno de los roles requeridos"""
    if "admin" in user_roles:
        return True
    return any(role in user_roles for role in required_roles)