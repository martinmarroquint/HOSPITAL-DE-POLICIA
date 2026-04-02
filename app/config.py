from typing import List, Optional
from pydantic_settings import BaseSettings
from pydantic import ConfigDict, field_validator
import json

class Settings(BaseSettings):
    # =====================================================
    # SUPABASE DATABASE
    # =====================================================
    SUPABASE_DATABASE_URL: str
    SUPABASE_DB_HOST: str
    SUPABASE_DB_PORT: int
    SUPABASE_DB_NAME: str
    SUPABASE_DB_USER: str
    SUPABASE_DB_PASSWORD: str

    # =====================================================
    # JWT
    # =====================================================
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440  # 24 horas

    # =====================================================
    # API
    # =====================================================
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Hospital PNP API"
    VERSION: str = "1.0.0"
    ENVIRONMENT: str = "development"  # ← NUEVO: development, staging, production
    DEBUG: bool = True  # ← NUEVO: modo debug

    # =====================================================
    # CORS
    # =====================================================
    BACKEND_CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000"
    ]

    @field_validator("BACKEND_CORS_ORIGINS", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        if isinstance(v, str):
            try:
                # Intentar parsear como JSON
                return json.loads(v)
            except json.JSONDecodeError:
                # Si no es JSON, dividir por comas
                return [origin.strip() for origin in v.split(",") if origin.strip()]
        return v or []  # ← CORREGIDO: asegurar que no sea None

    # =====================================================
    # FILE UPLOAD
    # =====================================================
    MAX_UPLOAD_SIZE: int = 5 * 1024 * 1024  # 5MB (más claro así)
    UPLOAD_PATH: str = "uploads"  # ← CORREGIDO: sin / al inicio para rutas relativas
    ALLOWED_EXTENSIONS: List[str] = [".jpg", ".jpeg", ".png", ".pdf", ".doc", ".docx"]

    # =====================================================
    # AWS S3 (opcional)
    # =====================================================
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_REGION: Optional[str] = "us-east-1"
    AWS_S3_BUCKET: Optional[str] = None

    # =====================================================
    # SEGURIDAD
    # =====================================================
    PASSWORD_MIN_LENGTH: int = 8  # ← NUEVO
    MAX_LOGIN_ATTEMPTS: int = 5   # ← NUEVO
    LOGIN_TIMEOUT_MINUTES: int = 15  # ← NUEVO

    # =====================================================
    # REDIS (opcional para caché)
    # =====================================================
    REDIS_URL: Optional[str] = None  # ← NUEVO
    REDIS_ENABLED: bool = False  # ← NUEVO

    model_config = ConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"  # Ignorar campos extra en el .env
    )

    # =====================================================
    # PROPIEDADES CALCULADAS
    # =====================================================
    @property
    def is_development(self) -> bool:
        """Retorna True si estamos en entorno de desarrollo"""
        return self.ENVIRONMENT.lower() == "development"

    @property
    def is_production(self) -> bool:
        """Retorna True si estamos en entorno de producción"""
        return self.ENVIRONMENT.lower() == "production"

    @property
    def is_staging(self) -> bool:
        """Retorna True si estamos en entorno de staging"""
        return self.ENVIRONMENT.lower() == "staging"

    @property
    def database_url(self) -> str:
        """Retorna la URL de la base de datos (compatibilidad con código existente)"""
        return self.SUPABASE_DATABASE_URL

# Instancia global de settings
settings = Settings()