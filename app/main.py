from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
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

# =====================================================
# 📦 CONFIGURACIÓN DE LOGGING
# =====================================================

# Configurar logging estructurado
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler()  # Salida a consola para Render
    ]
)
logger = logging.getLogger(__name__)

# =====================================================
# 🚀 CREACIÓN DE LA APLICACIÓN FASTAPI
# =====================================================

# Configurar documentación según entorno
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
        {
            "name": "Autenticación",
            "description": "Endpoints para autenticación y gestión de usuarios"
        },
        {
            "name": "Personal",
            "description": "Gestión de personal policial"
        },
        {
            "name": "Planificación",
            "description": "Planificación de turnos y horarios"
        },
        {
            "name": "Asistencia",
            "description": "Registro y control de asistencia"
        },
        {
            "name": "Descansos Médicos",
            "description": "Gestión de descansos médicos"
        },
        {
            "name": "Solicitudes Unificadas",
            "description": "Solicitudes de vacaciones, permisos y cambios"
        },
        {
            "name": "Solicitudes de Cambio",
            "description": "Solicitudes de cambio de turno"
        },
        {
            "name": "QR",
            "description": "Generación y validación de códigos QR"
        },
        {
            "name": "Configuración Mensual",
            "description": "Configuración de parámetros mensuales"
        },
        {
            "name": "Sistema",
            "description": "Endpoints de sistema y monitoreo"
        }
    ]
)

# =====================================================
# 🚀 CONFIGURACIÓN CORS - ACTUALIZADA CON DOMINIOS DE FIREBASE
# =====================================================

# Orígenes permitidos (incluyendo Firebase y producción)
origins = [
    # Desarrollo local
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    # Render (backend)
    "https://*.onrender.com",
    # Firebase (frontend) - ¡AGREGADOS!
    "https://hospital-pnp.web.app",
    "https://hospital-pnp.firebaseapp.com",
    # Vercel y Netlify (alternativas)
    "https://*.vercel.app",
    "https://*.netlify.app",
]

# Agregar orígenes de configuración desde settings
if settings.BACKEND_CORS_ORIGINS:
    origins.extend([str(origin) for origin in settings.BACKEND_CORS_ORIGINS])

# Eliminar duplicados manteniendo orden
origins = list(dict.fromkeys(origins))

# Configuración CORS con FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

logger.info(f"✅ CORS configurado con {len(origins)} orígenes")
logger.info(f"📋 Orígenes permitidos: {origins}")

# =====================================================
# 🚀 MIDDLEWARE CORS MANUAL PARA PREFLIGHT (RESPUESTA RÁPIDA)
# =====================================================

@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    """
    Middleware manual para manejar CORS y preflight requests
    """
    # Manejar preflight OPTIONS
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
                "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With, Accept",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "3600",
            }
        )
    
    # Procesar la solicitud normal
    response = await call_next(request)
    
    # Obtener el origen de la solicitud para respuesta específica
    origin = request.headers.get("origin")
    
    # Si el origen está en nuestra lista, responder con ese origen específico
    if origin in origins:
        response.headers["Access-Control-Allow-Origin"] = origin
    else:
        # Fallback: permitir cualquier origen (solo para desarrollo)
        response.headers["Access-Control-Allow-Origin"] = "*"
    
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Requested-With, Accept"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    
    return response

# =====================================================
# 🚀 OTROS MIDDLEWARES
# =====================================================

# Compresión GZip para respuestas grandes
app.add_middleware(
    GZipMiddleware,
    minimum_size=500,  # Comprimir respuestas mayores a 500 bytes
    compresslevel=6    # Nivel de compresión
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
    
    # Procesar la solicitud
    response = await call_next(request)
    
    # Calcular tiempo de procesamiento
    process_time = time.time() - start_time
    process_time_ms = process_time * 1000
    
    # Agregar header con tiempo de procesamiento
    response.headers["X-Process-Time"] = f"{process_time_ms:.2f}ms"
    
    # Log de endpoints lentos
    if process_time > 0.5:  # Más de 500ms
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

# Lista de módulos a importar (solo los que existen en tu proyecto)
modulos_existentes = []

# Intentar importar y registrar cada módulo
modulos_a_importar = [
    ("auth", "Autenticación", "/auth"),
    ("personal", "Personal", "/personal"),
    ("planificacion", "Planificación", "/planificacion"),
    ("asistencia", "Asistencia", "/asistencia"),
    ("descansos_medicos", "Descansos Médicos", "/dm"),
    ("solicitudes_cambio", "Solicitudes de Cambio", "/solicitudes-cambio"),
    ("solicitudes", "Solicitudes Unificadas", "/solicitudes"),
    ("qr", "QR", "/qr"),
    ("configuracion_mensual", "Configuración Mensual", "/configuracion-mensual"),
]

logger.info("=" * 60)
logger.info("📡 REGISTRANDO ROUTERS")
logger.info("=" * 60)

for nombre_modulo, tag, prefijo_base in modulos_a_importar:
    try:
        modulo = __import__(f"app.api.{nombre_modulo}", fromlist=["router"])
        
        if hasattr(modulo, 'router'):
            prefijo = f"{settings.API_V1_PREFIX}{prefijo_base}"
            tags = [tag]
            
            app.include_router(modulo.router, prefix=prefijo, tags=tags)
            logger.info(f"✅ {nombre_modulo}: Registrado en {prefijo}")
            modulos_existentes.append(nombre_modulo)
        else:
            logger.warning(f"⚠️ {nombre_modulo}: No tiene router, omitiendo")
            
    except ImportError as e:
        logger.warning(f"⚠️ {nombre_modulo}: No encontrado - {e}")
    except Exception as e:
        logger.error(f"❌ {nombre_modulo}: Error al registrar - {e}")

logger.info(f"📦 Total módulos cargados: {len(modulos_existentes)}")
logger.info("=" * 60)

# =====================================================
# 🔍 ENDPOINTS DE DIAGNÓSTICO Y MONITOREO
# =====================================================

@app.get(
    "/",
    tags=["Sistema"],
    summary="Información del sistema",
    description="Retorna información básica de la API"
)
async def root():
    """Endpoint principal con información de la API"""
    return {
        "message": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
        "status": "operational",
        "modulos_cargados": modulos_existentes,
        "cors_origins": len(origins),
        "timestamp": datetime.utcnow().isoformat()
    }

@app.get(
    "/health",
    tags=["Sistema"],
    summary="Health check",
    description="Verifica el estado de salud de la API y sus dependencias"
)
async def health_check():
    """Endpoint de verificación de salud para monitoreo"""
    # Verificar conexión a base de datos
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
    summary="Verificación detallada de base de datos",
    description="Obtiene información detallada sobre el estado de la base de datos"
)
async def db_check():
    """Verificación detallada de la conexión a base de datos"""
    db_status = get_db_status()
    
    return {
        "database_status": db_status,
        "timestamp": datetime.utcnow().isoformat(),
        "environment": settings.ENVIRONMENT
    }

@app.get(
    "/ready",
    tags=["Sistema"],
    summary="Readiness probe",
    description="Verifica si la API está lista para recibir tráfico"
)
async def readiness_check():
    """
    Endpoint para readiness probe de Kubernetes/Render.
    Verifica que todos los componentes estén listos.
    """
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
    summary="Información detallada del sistema",
    description="Obtiene información detallada sobre la configuración del sistema"
)
async def system_info():
    """Información detallada del sistema (excluye datos sensibles)"""
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
        "api_prefix": settings.API_V1_PREFIX,
        "cors_origins_count": len(origins),
        "cors_origins": origins,
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
    """Manejo personalizado de errores 404"""
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
    """Manejo personalizado de errores 500 con logging"""
    error_id = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")
    
    # Log detallado del error
    logger.error(f"❌ Error 500 [{error_id}] en {request.method} {request.url.path}")
    logger.error(f"Error: {str(exc)}")
    
    if settings.DEBUG:
        logger.error(f"Stacktrace:\n{traceback.format_exc()}")
    
    # Respuesta según entorno
    if settings.DEBUG:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": str(exc),
                "error_id": error_id,
                "timestamp": datetime.utcnow().isoformat(),
                "traceback": traceback.format_exc().split("\n") if settings.DEBUG else None
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
    """Manejador global de excepciones no capturadas"""
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
    """Evento ejecutado al iniciar la aplicación"""
    logger.info("=" * 60)
    logger.info(f"🚀 INICIANDO {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info(f"🔧 Modo: {settings.ENVIRONMENT.upper()}")
    logger.info(f"📡 API Prefix: {settings.API_V1_PREFIX}")
    logger.info(f"📦 Módulos cargados: {len(modulos_existentes)}")
    logger.info(f"🌐 CORS orígenes: {len(origins)}")
    logger.info("=" * 60)
    
    # Inicializar conexión a base de datos
    await startup_db_events()
    
    # Verificar estado final
    db_connected, _ = check_db_connection()
    if db_connected:
        logger.info("✅ Sistema listo para recibir peticiones")
    else:
        logger.warning("⚠️ Sistema iniciado SIN conexión a base de datos")
    
    logger.info("=" * 60)

@app.on_event("shutdown")
async def shutdown_event():
    """Evento ejecutado al cerrar la aplicación"""
    logger.info("=" * 60)
    logger.info(f"🛑 DETENIENDO {settings.PROJECT_NAME}")
    logger.info("=" * 60)
    
    # Cerrar conexiones de base de datos
    await shutdown_db_events()
    
    logger.info("✅ Aplicación detenida correctamente")

# =====================================================
# 📊 INFORMACIÓN DE INICIALIZACIÓN
# =====================================================

if __name__ == "__main__":
    import uvicorn
    
    logger.info("🚀 Iniciando servidor de desarrollo...")
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info" if not settings.DEBUG else "debug"
    )