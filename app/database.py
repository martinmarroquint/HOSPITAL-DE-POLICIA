from sqlalchemy import create_engine, text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from typing import Generator, Tuple
from app.config import settings

# Crear engine de base de datos
engine = create_engine(
    settings.SUPABASE_DATABASE_URL,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=settings.DEBUG  # Solo echo en desarrollo
)

# Sesión local
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Base para modelos
Base = declarative_base()

# =====================================================
# FUNCIÓN PARA VERIFICAR CONEXIÓN
# =====================================================
def check_db_connection() -> Tuple[bool, str]:
    """
    Verifica la conexión a la base de datos
    Returns: (success: bool, message: str)
    """
    try:
        with engine.connect() as conn:
            # Ejecutar consulta de prueba
            result = conn.execute(text("SELECT 1")).scalar()
            conn.commit()
            
            if result == 1:
                return True, "Conexión exitosa a la base de datos"
            else:
                return False, "Resultado inesperado en consulta de prueba"
    except Exception as e:
        return False, f"Error de conexión: {str(e)}"

# =====================================================
# FUNCIÓN PARA OBTENER ESTADÍSTICAS DEL POOL - CORREGIDA
# =====================================================
def get_pool_stats() -> dict:
    """
    Obtiene estadísticas del pool de conexiones
    """
    pool = engine.pool
    
    # Diferentes métodos según el tipo de pool
    stats = {
        "size": pool.size(),
        "checked_in_connections": pool.checkedin(),
        "overflow": pool.overflow(),
    }
    
    # Intentar obtener total si existe (no siempre disponible)
    try:
        stats["total"] = pool.total()
    except AttributeError:
        # Si no existe total, calcular aproximadamente
        stats["total"] = pool.size() + pool.overflow()
    
    return stats

# =====================================================
# DEPENDENCIA PRINCIPAL
# =====================================================
def get_db() -> Generator[Session, None, None]:
    """
    Dependencia para obtener sesión de base de datos
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# =====================================================
# FUNCIÓN PARA INICIALIZAR BASE DE DATOS (OPCIONAL)
# =====================================================
def init_db():
    """
    Crea las tablas si no existen
    """
    Base.metadata.create_all(bind=engine)

# =====================================================
# FUNCIÓN PARA CERRAR CONEXIONES (OPCIONAL)
# =====================================================
def close_db_connections():
    """
    Cierra todas las conexiones del pool
    """
    engine.dispose()