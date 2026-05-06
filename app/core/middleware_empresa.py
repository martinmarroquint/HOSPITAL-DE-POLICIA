"""
MIDDLEWARE DE CONTEXTO MULTI-EMPRESA
Extrae empresa_id y rol_global del JWT y lo inyecta en request.state
CORREGIDO: Bloquea super_admin de acceder a endpoints de empresa
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
    "/api/v1/config/cliente/publico",
    "/docs",
    "/redoc",
    "/openapi.json",
    "/health",
    "/ready",
    "/db-check",
    "/info",
    "/",
]

# Endpoints EXCLUSIVOS del super admin (monitoreo)
SUPER_ADMIN_PATHS: List[str] = [
    "/api/v1/super-admin/",
    "/api/v1/admin/empresas",
]

# Endpoints donde el super admin NO puede acceder
RESTRICTED_FOR_SUPER_ADMIN: List[str] = [
    "/api/v1/personal/",
    "/api/v1/asistencia/",
    "/api/v1/planificacion/",
    "/api/v1/qr/",
    "/api/v1/solicitudes/",
    "/api/v1/notificaciones/",
    "/api/v1/config/turnos",
    "/api/v1/config/organigrama",
    "/api/v1/config/reglas",
    "/api/v1/config/roles",
    "/api/v1/config/campos-personal",
    "/api/v1/config/catalogos",
]


class EmpresaContextMiddleware(BaseHTTPMiddleware):
    """
    Middleware que extrae la informacion de empresa del JWT
    y la almacena en request.state para uso en toda la aplicacion.
    
    BLOQUEA al super_admin de acceder a datos de empresas.
    """
    
    async def dispatch(self, request: Request, call_next):
        # Inicializar valores por defecto
        request.state.empresa_id = None
        request.state.rol_global = "usuario"
        request.state.user_id = None
        request.state.roles = []
        
        # Excluir endpoints publicos
        path = request.url.path
        if any(path.startswith(excluded) for excluded in EXCLUDED_PATHS):
            return await call_next(request)
        
        # Extraer token del header Authorization
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.replace("Bearer ", "")
            payload = decode_token(token)
            
            if payload:
                rol_global = payload.get("rol_global", "usuario")
                
                # BLOQUEAR super_admin de acceder a endpoints de empresa
                if rol_global == "super_admin":
                    # Verificar si es un endpoint restringido
                    if any(path.startswith(restricted) for restricted in RESTRICTED_FOR_SUPER_ADMIN):
                        from fastapi.responses import JSONResponse
                        return JSONResponse(
                            status_code=403,
                            content={
                                "detail": "Super admin no tiene acceso a datos de empresas. "
                                         "Use el dashboard de monitoreo.",
                                "code": "SUPER_ADMIN_RESTRICTED"
                            }
                        )
                
                # Inyectar datos en request.state
                request.state.empresa_id = payload.get("empresa_id")
                request.state.rol_global = rol_global
                request.state.user_id = payload.get("user_id")
                request.state.personal_id = payload.get("personal_id")
                request.state.roles = payload.get("roles", [])
                request.state.area = payload.get("area")
        
        return await call_next(request)


def get_empresa_id_from_request(request: Request) -> str:
    """Funcion auxiliar para obtener empresa_id desde request.state"""
    return getattr(request.state, "empresa_id", None)


def get_rol_global_from_request(request: Request) -> str:
    """Funcion auxiliar para obtener rol_global desde request.state"""
    return getattr(request.state, "rol_global", "usuario")


def get_current_context(request: Request) -> dict:
    """Obtiene todo el contexto del usuario actual desde request.state"""
    return {
        "empresa_id": getattr(request.state, "empresa_id", None),
        "rol_global": getattr(request.state, "rol_global", "usuario"),
        "user_id": getattr(request.state, "user_id", None),
        "personal_id": getattr(request.state, "personal_id", None),
        "roles": getattr(request.state, "roles", []),
        "area": getattr(request.state, "area", None),
    }