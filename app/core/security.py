"""
CORE DE SEGURIDAD - ARGON2 EXCLUSIVO
Sistema multi-empresa con JWT enriquecido
Soporte para jerarquía: super_admin → admin_cliente → admin_empresa → usuario
"""

from datetime import datetime, timedelta
from typing import Optional, List
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.config import settings

# =====================================================
# ROLES DEL SISTEMA (JERARQUÍA)
# =====================================================
ROLES_SISTEMA = [
    'super_admin',       # Nivel 0: Dueño del sistema
    'admin_cliente',     # Nivel 10: Dueño de la organización
    'admin_empresa',     # Nivel 20: Administrador de empresa
    'jefe_unidad',       # Nivel 30: Jefe de unidad/departamento
    'usuario',           # Nivel 100: Usuario regular
    'visitante',         # Nivel 110: Visitante temporal
]

ROLES_ADMIN = ['super_admin', 'admin_cliente', 'admin_empresa']
ROLES_GESTION = ['admin_cliente', 'admin_empresa', 'jefe_unidad']

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
              - empresa_id: UUID de la empresa (puede ser null para admin_cliente)
              - cliente_id: UUID del cliente (para admin_cliente)
              - rol_global: super_admin, admin_cliente, admin_empresa, usuario, visitante
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
    Los roles admin (super_admin, admin_cliente, admin_empresa) tienen acceso a todo.
    
    Args:
        user_roles: Lista de roles del usuario
        required_roles: Lista de roles requeridos
    
    Returns:
        bool: True si el usuario tiene al menos un rol requerido o es admin
    """
    if not user_roles:
        return False
    
    user_roles_lower = [r.lower() for r in user_roles]
    
    # Admins tienen acceso total
    if any(admin_role in user_roles_lower for admin_role in ['super_admin', 'admin_cliente', 'admin']):
        return True
    
    # Verificar si tiene alguno de los roles requeridos
    return any(
        role.lower() in user_roles_lower 
        for role in required_roles
    )

def has_rol_global(user_rol_global: str, allowed_roles: List[str]) -> bool:
    """
    Verifica si el usuario tiene un rol global permitido.
    Jerarquía de acceso:
    - super_admin: acceso a TODO
    - admin_cliente: acceso a sus empresas
    - admin_empresa: acceso a su empresa
    - usuario: acceso limitado
    
    Args:
        user_rol_global: Rol global del usuario
        allowed_roles: Lista de roles globales permitidos
    
    Returns:
        bool: True si el usuario tiene acceso
    """
    if not user_rol_global:
        return False
    
    # super_admin tiene acceso total
    if user_rol_global == "super_admin":
        return True
    
    # admin_cliente tiene acceso a funciones de gestión
    if user_rol_global == "admin_cliente" and any(r in allowed_roles for r in ROLES_ADMIN + ROLES_GESTION):
        return True
    
    # Verificar rol específico
    return user_rol_global in allowed_roles

def is_admin(user_rol_global: str) -> bool:
    """
    Verifica si el usuario tiene rol de administrador (cualquier nivel)
    
    Args:
        user_rol_global: Rol global del usuario
    
    Returns:
        bool: True si es super_admin, admin_cliente o admin_empresa
    """
    return user_rol_global in ROLES_ADMIN

def is_super_admin(user_rol_global: str) -> bool:
    """
    Verifica si el usuario es super_admin
    
    Args:
        user_rol_global: Rol global del usuario
    
    Returns:
        bool: True si es super_admin
    """
    return user_rol_global == "super_admin"

def is_admin_cliente(user_rol_global: str) -> bool:
    """
    Verifica si el usuario es admin_cliente
    
    Args:
        user_rol_global: Rol global del usuario
    
    Returns:
        bool: True si es admin_cliente
    """
    return user_rol_global == "admin_cliente"

def is_admin_empresa(user_rol_global: str) -> bool:
    """
    Verifica si el usuario es admin_empresa
    
    Args:
        user_rol_global: Rol global del usuario
    
    Returns:
        bool: True si es admin_empresa
    """
    return user_rol_global == "admin_empresa"

def get_role_level(user_rol_global: str) -> int:
    """
    Retorna el nivel jerárquico del rol
    
    Args:
        user_rol_global: Rol global del usuario
    
    Returns:
        int: Nivel jerárquico (menor = más poder)
    """
    niveles = {
        'super_admin': 0,
        'admin_cliente': 10,
        'admin_empresa': 20,
        'jefe_unidad': 30,
        'usuario': 100,
        'visitante': 110,
    }
    return niveles.get(user_rol_global, 999)

def can_manage_role(user_rol_global: str, target_rol_global: str) -> bool:
    """
    Verifica si un usuario puede gestionar a otro basado en su rol
    
    Args:
        user_rol_global: Rol del usuario que intenta gestionar
        target_rol_global: Rol del usuario a gestionar
    
    Returns:
        bool: True si puede gestionarlo
    """
    user_level = get_role_level(user_rol_global)
    target_level = get_role_level(target_rol_global)
    
    # Solo puede gestionar roles de nivel inferior
    return user_level < target_level