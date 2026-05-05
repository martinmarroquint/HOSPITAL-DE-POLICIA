"""
MIDDLEWARE DE CONTEXTO MULTI-EMPRESA
Extrae empresa_id y rol_global del JWT y lo inyecta en request.state
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.security import decode_token
from typing import List

# Endpoints que NO requieren contexto de empresa
EXCLUDED_PATHS: List[str] = [
    "/api/v1/auth/login",
    "/api/v1/auth/check-user",
    "/api/v1/auth/verificar",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/ready",
    "/db-check",
    "/info",
    "/",
]


class EmpresaContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware que extrae la información de empresa del JWT
    y la almacena en request.state para uso en toda la aplicación.
    
    Esto permite que cualquier endpoint acceda a:
    - request.state.empresa_id
    - request.state.rol_global
    - request.state.user_id
    - request.state.roles
    
    Sin necesidad de consultar la base de datos en cada request.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Inicializar valores por defecto
        request.state.empresa_id = None
        request.state.rol_global = "usuario"
        request.state.user_id = None
        request.state.roles = []
        
        # Excluir endpoints públicos
        path = request.url.path
        if any(path.startswith(excluded) for excluded in EXCLUDED_PATHS):
            return await call_next(request)
        
        # Extraer token del header Authorization
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            payload = decode_token(token)
            
            if payload:
                # Inyectar datos en request.state
                request.state.empresa_id = payload.get("empresa_id")
                request.state.rol_global = payload.get("rol_global", "usuario")
                request.state.user_id = payload.get("user_id")
                request.state.personal_id = payload.get("personal_id")
                request.state.roles = payload.get("roles", [])
                request.state.area = payload.get("area")
        
        # Continuar con la cadena de middlewares
        return await call_next(request)


def get_empresa_id_from_request(request: Request) -> str:
    """
    Función auxiliar para obtener empresa_id desde request.state
    Útil para inyectar en servicios que necesitan el contexto.
    """
    return getattr(request.state, "empresa_id", None)


def get_rol_global_from_request(request: Request) -> str:
    """
    Función auxiliar para obtener rol_global desde request.state
    """
    return getattr(request.state, "rol_global", "usuario")


def get_current_context(request: Request) -> dict:
    """
    Obtiene todo el contexto del usuario actual desde request.state
    """
    return {
        "empresa_id": getattr(request.state, "empresa_id", None),
        "rol_global": getattr(request.state, "rol_global", "usuario"),
        "user_id": getattr(request.state, "user_id", None),
        "personal_id": getattr(request.state, "personal_id", None),
        "roles": getattr(request.state, "roles", []),
        "area": getattr(request.state, "area", None),
    }