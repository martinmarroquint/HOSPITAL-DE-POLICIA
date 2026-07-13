# app/main.py
# VERSION ACTUALIZADA - CON CARTERA DE SERVICIOS MEDICOS + GEOLOCALIZACION GPS + INVENTARIO LOGISTICO + EXAMENES ONLINE + GRUPOS

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import logging
import time
from datetime import datetime, timezone
import traceback
import os

from app.config import settings
from app.database import (
    get_db_status,
    startup_db_events,
    shutdown_db_events,
    check_db_connection
)
from app.api import api_router

# MIDDLEWARE MULTI-EMPRESA
from app.core.middleware_empresa import EmpresaContextMiddleware

# =====================================================
# CONFIGURACION DE LOGGING
# =====================================================

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# =====================================================
# CREACION DE LA APLICACION FASTAPI
# =====================================================

if settings.is_production:
    docs_url = None
    redoc_url = None
    openapi_url = None
else:
    docs_url = "/docs"
    redoc_url = "/redoc"
    openapi_url = f"{settings.API_V1_PREFIX}/openapi.json"

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="API para el Sistema de Gestion Multi-Empresa con jerarquia de roles, inventario logistico, geolocalizacion, Roles de Servicio PNP, Grupos de Clases y Examenes Online",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
    openapi_tags=[
        {"name": "Autenticacion", "description": "Endpoints para autenticacion y gestion de usuarios"},
        {"name": "Biometria", "description": "Autenticacion biometrica - Huella digital / Face ID"},
        {"name": "Personal", "description": "Gestion de personal"},
        {"name": "Planificacion", "description": "Planificacion de turnos y horarios"},
        {"name": "Asistencia", "description": "Registro y control de asistencia"},
        {"name": "Descansos Medicos", "description": "Gestion de descansos medicos"},
        {"name": "Solicitudes Unificadas", "description": "Solicitudes de vacaciones, permisos y cambios"},
        {"name": "Solicitudes de Cambio", "description": "Solicitudes de cambio de turno"},
        {"name": "QR", "description": "Generacion y validacion de codigos QR"},
        {"name": "Configuracion Mensual", "description": "Configuracion de parametros mensuales"},
        {"name": "Publicaciones", "description": "Canal interno de comunicaciones"},
        {"name": "Notificaciones", "description": "Centro de notificaciones y alertas"},
        {"name": "Configuracion", "description": "Configuracion dinamica del sistema"},
        {"name": "Clientes", "description": "Panel Super Admin - Gestion de clientes y organizaciones"},
        {"name": "Empresas", "description": "Panel Super Admin / Admin Cliente - Gestion de empresas"},
        {"name": "Sesiones", "description": "Gestion de sesiones, clases y eventos"},
        {"name": "Cartera de Servicios", "description": "Portal publico de cartera medica y carga de Excel"},
        {"name": "Pre-Registros", "description": "Pre-Registros de Personal - Formulario publico + Admin"},
        {"name": "Geolocalizacion", "description": "Registro de asistencia por GPS con validacion de coordenadas"},
        {"name": "Inventario", "description": "Gestion de inventario logistico - Catalogo maestro + unidades"},
        {"name": "Examenes", "description": "Sistema de examenes online - Creacion, publicacion, rendicion y resultados"},
        {"name": "Grupos", "description": "Gestion de grupos/clases - Alumnos, asistencias y materiales"},
        {"name": "Sistema", "description": "Endpoints de sistema y monitoreo"}
    ]
)

# =====================================================
# SERVIR ARCHIVOS ESTATICOS (LOGOS, FOTOS)
# =====================================================
app.mount("/static", StaticFiles(directory="static"), name="static")

# =====================================================
# CONFIGURACION CORS
# =====================================================

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "https://hospital-pnp.web.app",
    "https://hospital-pnp.firebaseapp.com",
]

if settings.BACKEND_CORS_ORIGINS:
    for origin in settings.BACKEND_CORS_ORIGINS:
        origin_str = str(origin)
        if settings.is_production and "*" in origin_str:
            logger.warning(f"Wildcard CORS ignorado en produccion: {origin_str}")
            continue
        ALLOWED_ORIGINS.append(origin_str)

ALLOWED_ORIGINS = list(dict.fromkeys(ALLOWED_ORIGINS))

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH", "HEAD"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept", "X-Empresa-ID", "X-Cliente-ID"],
    expose_headers=["X-Process-Time"],
    max_age=86400,
)

logger.info(f"CORS configurado con {len(ALLOWED_ORIGINS)} origenes")

# =====================================================
# OTROS MIDDLEWARES
# =====================================================

app.add_middleware(
    GZipMiddleware,
    minimum_size=500,
    compresslevel=6
)

# MIDDLEWARE MULTI-EMPRESA
app.add_middleware(EmpresaContextMiddleware)
logger.info("Middleware multi-empresa registrado")

# =====================================================
# MIDDLEWARE DE MONITOREO
# =====================================================

@app.middleware("http")
async def monitor_performance(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time * 1000:.2f}ms"
    return response

# =====================================================
# REGISTRO DE ROUTERS
# =====================================================

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

# Modulos cargados (para diagnostico)
modulos_existentes = [
    'auth',
    'biometric',
    'personal',
    'planificacion',
    'asistencia',
    'descansos_medicos',
    'solicitudes_cambio',
    'qr',
    'configuracion_mensual',
    'publicaciones',
    'notificaciones',
    'configuracion',
    'clientes',
    'empresas',
    'sesiones',
    'cartera_servicios',
    'pre_registros',
    'geolocalizacion',
    'inventario',
    'examenes',
    'grupos'
]

logger.info(f"Modulos cargados: {', '.join(modulos_existentes)}")

# =====================================================
# ENDPOINTS DE DIAGNOSTICO
# =====================================================

@app.api_route("/", methods=["GET", "HEAD"], tags=["Sistema"], summary="Informacion del sistema")
async def root():
    return {
        "message": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "operational",
        "jerarquia_roles": ["super_admin", "admin_cliente", "admin_empresa", "jefe_unidad", "usuario", "visitante"],
        "modulos": modulos_existentes,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

@app.get("/health", tags=["Sistema"], summary="Health check")
async def health_check():
    db_connected, db_message = check_db_connection()
    return {
        "status": "healthy" if db_connected else "degraded",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "components": {
            "database": {"status": "up" if db_connected else "down", "message": db_message},
            "api": {"status": "up", "modulos_cargados": len(modulos_existentes)}
        }
    }

@app.get("/db-check", tags=["Sistema"])
async def db_check():
    return {"database_status": get_db_status(), "timestamp": datetime.now(timezone.utc).isoformat()}

@app.get("/ready", tags=["Sistema"])
async def readiness_check():
    db_connected, db_message = check_db_connection()
    if not db_connected:
        return JSONResponse(status_code=503, content={"status": "not ready", "reason": db_message})
    return {"status": "ready"}

@app.get("/info", tags=["Sistema"])
async def system_info():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "jerarquia": {
            "roles": ["super_admin", "admin_cliente", "admin_empresa", "jefe_unidad", "usuario", "visitante"],
            "estructura": "super_admin -> clientes -> empresas -> unidades"
        },
        "cors_origins": ALLOWED_ORIGINS,
        "modulos": modulos_existentes,
        "biometria": "Disponible",
        "cartera_servicios": "Disponible",
        "pre_registros": "Disponible",
        "geolocalizacion": "Disponible",
        "inventario": "Disponible",
        "examenes_online": "Disponible",
        "grupos_clases": "Disponible",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

# =====================================================
# MANEJADORES DE ERRORES
# =====================================================

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    return JSONResponse(status_code=404, content={
        "error": "Not Found",
        "message": "El endpoint solicitado no existe",
        "url": str(request.url),
        "method": request.method,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

@app.exception_handler(500)
async def custom_500_handler(request: Request, exc):
    error_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    logger.error(f"Error 500 [{error_id}] en {request.method} {request.url.path}: {str(exc)}")
    logger.error(f"   Traceback: {traceback.format_exc()}")
    return JSONResponse(status_code=500, content={
        "error": "Internal Server Error",
        "message": str(exc) if settings.DEBUG else "Error interno del servidor",
        "error_id": error_id,
        "timestamp": datetime.now(timezone.utc).isoformat()
    })

# =====================================================
# EVENTOS DE INICIO Y FIN
# =====================================================

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info(f"INICIANDO {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info(f"Modo: {settings.ENVIRONMENT.upper()}")
    logger.info(f"CORS origenes: {len(ALLOWED_ORIGINS)}")
    logger.info(f"Middleware multi-empresa: ACTIVO")
    logger.info(f"Jerarquia: super_admin -> admin_cliente -> admin_empresa -> jefe_unidad -> usuario")
    logger.info(f"Biometria: DISPONIBLE")
    logger.info(f"Cartera de Servicios: DISPONIBLE")
    logger.info(f"Geolocalizacion GPS: DISPONIBLE")
    logger.info(f"Inventario Logistico: DISPONIBLE")
    logger.info(f"Pre-Registros: DISPONIBLE")
    logger.info(f"Examenes Online: DISPONIBLE")
    logger.info(f"Grupos de Clases: DISPONIBLE")
    logger.info("=" * 60)
    await startup_db_events()
    db_connected, _ = check_db_connection()
    if db_connected:
        logger.info("Sistema listo para recibir peticiones")
    else:
        logger.warning("Sistema iniciado SIN conexion a base de datos")
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"DETENIENDO {settings.PROJECT_NAME}")
    await shutdown_db_events()
    logger.info("Aplicacion detenida correctamente")

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "app.main.py",
        host="0.0.0.0",
        port=port,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug"
    )