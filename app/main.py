# D:\Centro de control Hospital PNP\back\app\main.py
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
import logging
import time
from datetime import datetime
from sqlalchemy import text

from app.config import settings

# =====================================================
# 📦 IMPORTACIONES - SOLO MÓDULOS EXISTENTES Y NECESARIOS
# =====================================================
print("\n" + "="*60)
print("🚀 DIAGNÓSTICO DE IMPORTACIONES")
print("="*60)

# Lista de módulos que existen en tu proyecto
modulos_existentes = []

# Módulos necesarios y activos
try:
    from app.api import auth
    print("✅ auth: Importado correctamente")
    modulos_existentes.append(("auth", auth))
except ImportError as e:
    print(f"❌ auth: {e}")

try:
    from app.api import personal
    print("✅ personal: Importado correctamente")
    modulos_existentes.append(("personal", personal))
except ImportError as e:
    print(f"❌ personal: {e}")

try:
    from app.api import planificacion
    print("✅ planificacion: Importado correctamente")
    modulos_existentes.append(("planificacion", planificacion))
except ImportError as e:
    print(f"❌ planificacion: {e}")

try:
    from app.api import asistencia
    print("✅ asistencia: Importado correctamente")
    modulos_existentes.append(("asistencia", asistencia))
except ImportError as e:
    print(f"❌ asistencia: {e}")

try:
    from app.api import descansos_medicos
    print("✅ descansos_medicos: Importado correctamente")
    modulos_existentes.append(("descansos_medicos", descansos_medicos))
except ImportError as e:
    print(f"❌ descansos_medicos: {e}")

try:
    from app.api import solicitudes_cambio
    print("✅ solicitudes_cambio: Importado correctamente")
    modulos_existentes.append(("solicitudes_cambio", solicitudes_cambio))
except ImportError as e:
    print(f"❌ solicitudes_cambio: {e}")

try:
    from app.api import qr
    print("✅ qr: Importado correctamente")
    modulos_existentes.append(("qr", qr))
except ImportError as e:
    print(f"❌ qr: {e}")

try:
    from app.api import configuracion_mensual
    print("✅ configuracion_mensual: Importado correctamente")
    modulos_existentes.append(("configuracion_mensual", configuracion_mensual))
except ImportError as e:
    print(f"❌ configuracion_mensual: {e}")

# 🆕 NUEVO: Router unificado para solicitudes (vacaciones, permisos, etc.)
try:
    from app.api import solicitudes
    print("✅ solicitudes: Importado correctamente (nuevo router unificado)")
    modulos_existentes.append(("solicitudes", solicitudes))
except ImportError as e:
    print(f"❌ solicitudes: {e} - Es necesario crear este archivo")

# =====================================================
# 🚫 MÓDULOS NO NECESARIOS (COMENTADOS O ELIMINADOS)
# =====================================================
# token_validacion - NO ESTÁ EN USO, causa errores
# try:
#     from app.api import token_validacion
#     print("✅ token_validacion: Importado correctamente")
#     modulos_existentes.append(("token_validacion", token_validacion))
# except ImportError as e:
#     print(f"⚠️ token_validacion: {e} (opcional - no necesario)")

# trazabilidad - NO ESTÁ EN USO actualmente
# try:
#     from app.api import trazabilidad
#     print("✅ trazabilidad: Importado correctamente")
#     modulos_existentes.append(("trazabilidad", trazabilidad))
# except ImportError as e:
#     print(f"⚠️ trazabilidad: {e} (opcional)")

print(f"\n📦 Total módulos cargados: {len(modulos_existentes)}")

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url=f"{settings.API_V1_PREFIX}/openapi.json" if settings.DEBUG else None,
)

# =====================================================
# 🚀 1. MIDDLEWARE CORS MANUAL (MÁS ROBUSTO)
# =====================================================

# Middleware CORS manual para manejar TODAS las peticiones
@app.middleware("http")
async def cors_middleware(request: Request, call_next):
    # Manejar preflight OPTIONS
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS, PATCH",
                "Access-Control-Allow-Headers": "Content-Type, Authorization",
                "Access-Control-Allow-Credentials": "true",
                "Access-Control-Max-Age": "3600",
            }
        )
    
    response = await call_next(request)
    
    # Agregar headers CORS a todas las respuestas
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Credentials"] = "true"
    
    return response

# =====================================================
# 🚀 2. CONFIGURACIÓN CORS ADICIONAL (por si acaso)
# =====================================================
logger.info(f"🔧 Configurando CORS adicional con orígenes: {settings.BACKEND_CORS_ORIGINS}")

# Orígenes permitidos (incluyendo puerto 5173 de Vite y producción)
origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8000",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:8000",
    "https://*.onrender.com",  # Para producción en Render
    "https://*.vercel.app",    # Para producción en Vercel
]

# Si hay orígenes configurados en settings, agregarlos también
if settings.BACKEND_CORS_ORIGINS:
    origins.extend([str(origin) for origin in settings.BACKEND_CORS_ORIGINS])

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=3600,
)

logger.info(f"✅ CORS configurado con orígenes: {origins}")

# =====================================================
# 🚀 3. OTROS MIDDLEWARES
# =====================================================
app.add_middleware(
    GZipMiddleware,
    minimum_size=500,
    compresslevel=6
)

# =====================================================
# 📊 MIDDLEWARE DE MONITOREO
# =====================================================
@app.middleware("http")
async def monitor_performance(request: Request, call_next):
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
    elif settings.DEBUG:
        logger.debug(
            f"✅ {request.method} {request.url.path} - {process_time_ms:.2f}ms"
        )
    
    return response

# =====================================================
# 📡 REGISTRO DE ROUTERS - COMPLETO Y CORREGIDO
# =====================================================

print("\n" + "="*60)
print("📡 REGISTRANDO ROUTERS")
print("="*60)

api_v1_prefix = settings.API_V1_PREFIX

for nombre_modulo, modulo in modulos_existentes:
    try:
        if hasattr(modulo, 'router'):
            # Determinar prefijo según el módulo
            if nombre_modulo == "auth":
                prefijo = f"{api_v1_prefix}/auth"
                tags = ["Autenticación"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ auth: Registrado en {prefijo}")
                
            elif nombre_modulo == "personal":
                prefijo = f"{api_v1_prefix}/personal"
                tags = ["Personal"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ personal: Registrado en {prefijo}")
                
            elif nombre_modulo == "planificacion":
                prefijo = f"{api_v1_prefix}/planificacion"
                tags = ["Planificación"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ planificacion: Registrado en {prefijo}")
                
            elif nombre_modulo == "asistencia":
                prefijo = f"{api_v1_prefix}/asistencia"
                tags = ["Asistencia"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ asistencia: Registrado en {prefijo}")
                
            elif nombre_modulo == "descansos_medicos":
                prefijo = f"{api_v1_prefix}/dm"
                tags = ["Descansos Médicos"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ descansos_medicos: Registrado en {prefijo}")
                
            elif nombre_modulo == "solicitudes_cambio":
                prefijo = f"{api_v1_prefix}/solicitudes-cambio"
                tags = ["Solicitudes de Cambio"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ solicitudes_cambio: Registrado en {prefijo}")
                
            elif nombre_modulo == "solicitudes":
                prefijo = f"{api_v1_prefix}/solicitudes"
                tags = ["Solicitudes Unificadas"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ solicitudes: Registrado en {prefijo}")
                print(f"      └─ Endpoints disponibles:")
                print(f"         • POST {prefijo}/ - Crear solicitud (vacaciones/permisos/cambios)")
                print(f"         • GET {prefijo}/ - Listar solicitudes")
                print(f"         • GET {prefijo}/pendientes - Solicitudes pendientes de aprobación")
                print(f"         • GET {prefijo}/{{id}} - Obtener solicitud")
                print(f"         • PATCH {prefijo}/{{id}}/estado - Aprobar/Rechazar")
                
            elif nombre_modulo == "qr":
                # El router ya tiene prefix="/qr"
                prefijo = api_v1_prefix
                tags = ["QR"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ qr: Registrado en {prefijo}")
                print(f"      └─ Endpoints resultantes:")
                print(f"         • {prefijo}/qr/generar")
                print(f"         • {prefijo}/qr/validar")
                print(f"         • {prefijo}/qr/empleado/{{id}}/activo")
                print(f"         • {prefijo}/qr/generar-token/{{id}}")
                print(f"         • {prefijo}/qr/validar-token")
                
            elif nombre_modulo == "configuracion_mensual":
                prefijo = f"{api_v1_prefix}/configuracion-mensual"
                tags = ["Configuración Mensual"]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ configuracion_mensual: Registrado en {prefijo}")
                
            else:
                prefijo = f"{api_v1_prefix}/{nombre_modulo}"
                tags = [nombre_modulo.capitalize()]
                app.include_router(modulo.router, prefix=prefijo, tags=tags)
                print(f"   ✅ {nombre_modulo}: Registrado en {prefijo}")
            
            # Mostrar algunas rutas
            if hasattr(modulo.router, 'routes') and modulo.router.routes:
                print(f"      └─ {len(modulo.router.routes)} rutas disponibles")
        else:
            print(f"   ⚠️ {nombre_modulo}: No tiene router, omitiendo")
    except Exception as e:
        print(f"   ❌ {nombre_modulo}: Error al registrar - {e}")

# =====================================================
# 🔍 ENDPOINTS DE DIAGNÓSTICO (ACTUALIZADOS)
# =====================================================

@app.get("/")
async def root():
    return {
        "message": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "debug": settings.DEBUG,
        "modulos_cargados": len(modulos_existentes),
        "endpoints_disponibles": [
            f"{api_v1_prefix}/auth",
            f"{api_v1_prefix}/personal",
            f"{api_v1_prefix}/planificacion",
            f"{api_v1_prefix}/asistencia",
            f"{api_v1_prefix}/dm",
            f"{api_v1_prefix}/solicitudes-cambio",
            f"{api_v1_prefix}/solicitudes",  # 🆕 NUEVO ENDPOINT UNIFICADO
            f"{api_v1_prefix}/qr",
            f"{api_v1_prefix}/configuracion-mensual",
            "/health",
            "/db-check"
        ]
    }

@app.get("/health")
async def health_check():
    """Endpoint de verificación de salud - útil para monitoreo"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "database_connected": _check_db_connection(),
        "modulos_cargados": len(modulos_existentes)
    }

@app.get("/db-check")
async def db_check():
    """Verifica conexión a base de datos"""
    try:
        from app.database import check_db_connection
        success, message = check_db_connection()
        
        return {
            "database": {
                "connected": success,
                "message": message
            },
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        return {
            "database": {
                "connected": False,
                "error": str(e)
            },
            "timestamp": datetime.utcnow().isoformat()
        }

def _check_db_connection() -> bool:
    """Función auxiliar para verificar conexión a DB"""
    try:
        from app.database import check_db_connection
        success, _ = check_db_connection()
        return success
    except:
        return False

# =====================================================
# 🛡️ MANEJO DE ERRORES
# =====================================================

@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    return JSONResponse(
        status_code=404,
        content={
            "message": "Endpoint no encontrado",
            "url": str(request.url),
            "method": request.method,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

@app.exception_handler(500)
async def custom_500_handler(request: Request, exc):
    logger.error(f"❌ Error 500 en {request.method} {request.url.path}: {str(exc)}")
    
    if settings.DEBUG:
        logger.exception("Stacktrace completo:")
        return JSONResponse(
            status_code=500,
            content={
                "message": "Error interno del servidor",
                "error": str(exc),
                "timestamp": datetime.utcnow().isoformat()
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "message": "Error interno del servidor",
                "timestamp": datetime.utcnow().isoformat()
            }
        )

# =====================================================
# 🔥 EVENTOS DE INICIO
# =====================================================

@app.on_event("startup")
async def startup_event():
    logger.info(f"🚀 Iniciando {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info(f"🔧 Modo: {settings.ENVIRONMENT}")
    logger.info(f"📦 Módulos cargados: {len(modulos_existentes)}")
    
    try:
        from app.database import check_db_connection
        success, message = check_db_connection()
        
        if success:
            logger.info(f"✅ Conexión a base de datos establecida")
        else:
            logger.error(f"❌ Error conectando a base de datos: {message}")
            
    except Exception as e:
        logger.error(f"❌ Error en startup: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    logger.info(f"🛑 Deteniendo {settings.PROJECT_NAME}")

# =====================================================
# 📊 RESUMEN FINAL
# =====================================================

print("\n" + "="*60)
print("✅ INICIALIZACIÓN COMPLETADA")
print("="*60)
print(f"📦 Total módulos cargados: {len(modulos_existentes)}")
print(f"🚀 API disponible en: http://localhost:8000")
print(f"📚 Documentación: http://localhost:8000/docs")
print("")
print("📋 ENDPOINTS PRINCIPALES:")
print(f"   • Vacaciones: POST {api_v1_prefix}/solicitudes (tipo='vacaciones')")
print(f"   • Permisos:   POST {api_v1_prefix}/solicitudes (tipo='permiso')")
print(f"   • Cambio turno: POST {api_v1_prefix}/solicitudes-cambio")
print("="*60 + "\n")