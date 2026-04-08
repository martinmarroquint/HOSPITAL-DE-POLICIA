from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
import logging
import time
from datetime import datetime
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

# =====================================================
# 📦 CONFIGURACIÓN DE LOGGING
# =====================================================

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# =====================================================
# 🚀 CREACIÓN DE LA APLICACIÓN FASTAPI
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
    description="API para el Sistema de Gestión del Hospital de Policía",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=openapi_url,
    openapi_tags=[
        {"name": "Autenticación", "description": "Endpoints para autenticación y gestión de usuarios"},
        {"name": "Personal", "description": "Gestión de personal policial"},
        {"name": "Planificación", "description": "Planificación de turnos y horarios"},
        {"name": "Asistencia", "description": "Registro y control de asistencia"},
        {"name": "Descansos Médicos", "description": "Gestión de descansos médicos"},
        {"name": "Solicitudes Unificadas", "description": "Solicitudes de vacaciones, permisos y cambios"},
        {"name": "Solicitudes de Cambio", "description": "Solicitudes de cambio de turno"},
        {"name": "QR", "description": "Generación y validación de códigos QR"},
        {"name": "Configuración Mensual", "description": "Configuración de parámetros mensuales"},
        {"name": "Sistema", "description": "Endpoints de sistema y monitoreo"}
    ]
)

# =====================================================
# 🚀 CONFIGURACIÓN CORS - CORREGIDA PARA PRODUCCIÓN
# =====================================================
# ✅ SOLO dominios específicos (sin wildcards inseguros)
# ✅ Sin middleware manual redundante
# ✅ Compatible con Firebase Hosting

ALLOWED_ORIGINS = [
    # Desarrollo local
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    # Firebase (frontend en producción)
    "https://hospital-pnp.web.app",
    "https://hospital-pnp.firebaseapp.com",
]

# Agregar orígenes adicionales desde settings si existen
if settings.BACKEND_CORS_ORIGINS:
    for origin in settings.BACKEND_CORS_ORIGINS:
        origin_str = str(origin)
        # Evitar wildcards inseguros en producción
        if settings.is_production and "*" in origin_str:
            logger.warning(f"⚠️ Wildcard CORS ignorado en producción: {origin_str}")
            continue
        ALLOWED_ORIGINS.append(origin_str)

# Eliminar duplicados
ALLOWED_ORIGINS = list(dict.fromkeys(ALLOWED_ORIGINS))

# ✅ ELIMINADO: middleware CORS manual (redundante y problemático)
# ✅ ELIMINADO: wildcards como "*.onrender.com"
# ✅ ELIMINADO: combinación de "*" con allow_credentials=True

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    expose_headers=["X-Process-Time"],
    max_age=86400,  # 24 horas para preflight
)

logger.info(f"✅ CORS configurado con {len(ALLOWED_ORIGINS)} orígenes")
logger.info(f"📋 Orígenes permitidos: {ALLOWED_ORIGINS}")

# =====================================================
# 🚀 OTROS MIDDLEWARES
# =====================================================

app.add_middleware(
    GZipMiddleware,
    minimum_size=500,
    compresslevel=6
)

# =====================================================
# 📊 MIDDLEWARE DE MONITOREO Y RENDIMIENTO
# =====================================================

@app.middleware("http")
async def monitor_performance(request: Request, call_next):
    """
    Middleware para monitorear rendimiento y tiempos de respuesta
    """
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    process_time_ms = process_time * 1000
    
    response.headers["X-Process-Time"] = f"{process_time_ms:.2f}ms"
    
    if process_time > 0.5:
        logger.warning(
            f"⚠️ Endpoint lento: {request.method} {request.url.path} - "
            f"{process_time_ms:.2f}ms"
        )
    elif settings.DEBUG and process_time > 0.1:
        logger.debug(
            f"⏱️ {request.method} {request.url.path} - {process_time_ms:.2f}ms"
        )
    
    return response

# =====================================================
# 📡 REGISTRO DE ROUTERS
# =====================================================

app.include_router(api_router, prefix=settings.API_V1_PREFIX)

modulos_existentes = [
    'auth', 'personal', 'planificacion', 'asistencia',
    'descansos_medicos', 'solicitudes_cambio', 'qr', 'configuracion_mensual'
]

logger.info("=" * 60)
logger.info("📡 REGISTRANDO ROUTERS")
logger.info("=" * 60)
logger.info(f"✅ Router principal registrado en {settings.API_V1_PREFIX}")
logger.info(f"📦 Módulos incluidos: {modulos_existentes}")
logger.info("=" * 60)

# =====================================================
# 🔍 ENDPOINTS DE DIAGNÓSTICO Y MONITOREO
# =====================================================

@app.get(
    "/",
    tags=["Sistema"],
    summary="Información del sistema"
)
async def root():
    return {
        "message": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
        "status": "operational",
        "modulos_cargados": modulos_existentes,
        "cors_origins": len(ALLOWED_ORIGINS),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get(
    "/health",
    tags=["Sistema"],
    summary="Health check"
)
async def health_check():
    db_connected, db_message = check_db_connection()
    
    return {
        "status": "healthy" if db_connected else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "components": {
            "database": {
                "status": "up" if db_connected else "down",
                "message": db_message
            },
            "api": {
                "status": "up",
                "modulos_cargados": len(modulos_existentes)
            }
        }
    }

@app.get(
    "/db-check",
    tags=["Sistema"],
    summary="Verificación detallada de base de datos"
)
async def db_check():
    db_status = get_db_status()
    
    return {
        "database_status": db_status,
        "timestamp": datetime.utcnow().isoformat(),
        "environment": settings.ENVIRONMENT
    }

@app.get(
    "/ready",
    tags=["Sistema"],
    summary="Readiness probe"
)
async def readiness_check():
    db_connected, db_message = check_db_connection()
    
    if not db_connected:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not ready",
                "reason": f"Database not ready: {db_message}",
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    
    return {
        "status": "ready",
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get(
    "/info",
    tags=["Sistema"],
    summary="Información detallada del sistema"
)
async def system_info():
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
        "api_prefix": settings.API_V1_PREFIX,
        "cors_origins_count": len(ALLOWED_ORIGINS),
        "cors_origins": ALLOWED_ORIGINS,
        "modules": modulos_existentes,
        "database": {
            "host": settings.SUPABASE_DB_HOST,
            "name": settings.SUPABASE_DB_NAME,
            "connected": check_db_connection()[0]
        },
        "timestamp": datetime.utcnow().isoformat()
    }

# =====================================================
# 🛡️ MANEJO DE ERRORES GLOBAL
# =====================================================

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "error": "Not Found",
            "message": "El endpoint solicitado no existe",
            "url": str(request.url),
            "method": request.method,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(500)
async def custom_500_handler(request: Request, exc):
    error_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    
    logger.error(f"❌ Error 500 [{error_id}] en {request.method} {request.url.path}")
    logger.error(f"Error: {str(exc)}")
    
    if settings.DEBUG:
        logger.error(f"Stacktrace:\n{traceback.format_exc()}")
    
    if settings.DEBUG:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": str(exc),
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat(),
                "traceback": traceback.format_exc().split("\n")
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "Ha ocurrido un error interno en el servidor",
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat()
            }
        )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    error_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    
    logger.error(f"❌ Excepción no manejada [{error_id}]: {str(exc)}")
    
    if settings.DEBUG:
        logger.error(f"Stacktrace:\n{traceback.format_exc()}")
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal Server Error",
            "message": str(exc) if settings.DEBUG else "Error interno del servidor",
            "error_id": error_id,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# =====================================================
# 🔥 EVENTOS DE CICLO DE VIDA
# =====================================================

@app.on_event("startup")
async def startup_event():
    logger.info("=" * 60)
    logger.info(f"🚀 INICIANDO {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info(f"🔧 Modo: {settings.ENVIRONMENT.upper()}")
    logger.info(f"📡 API Prefix: {settings.API_V1_PREFIX}")
    logger.info(f"📦 Módulos cargados: {len(modulos_existentes)}")
    logger.info(f"🌐 CORS orígenes: {len(ALLOWED_ORIGINS)}")
    logger.info("=" * 60)
    
    await startup_db_events()
    
    db_connected, _ = check_db_connection()
    if db_connected:
        logger.info("✅ Sistema listo para recibir peticiones")
    else:
        logger.warning("⚠️ Sistema iniciado SIN conexión a base de datos")
    
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("=" * 60)
    logger.info(f"🛑 DETENIENDO {settings.PROJECT_NAME}")
    logger.info("=" * 60)
    
    await shutdown_db_events()
    
    logger.info("✅ Aplicación detenida correctamente")

# =====================================================
# 📊 INFORMACIÓN DE INICIALIZACIÓN
# =====================================================

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.environ.get("PORT", 8000))
    
    logger.info("🚀 Iniciando servidor...")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=port,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug"
    )