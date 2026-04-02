#!/bin/sh

echo "=============================================="
echo "🚀 INICIANDO DESPLIEGUE EN RENDER"
echo "=============================================="
echo "📦 Entorno: ${ENVIRONMENT:-production}"
echo "🐍 Python: $(python --version 2>&1)"
echo "📂 Directorio: $(pwd)"
echo "=============================================="

# Lista de variables requeridas
REQUIRED_VARS="SUPABASE_DATABASE_URL SUPABASE_DB_HOST SUPABASE_DB_PORT SUPABASE_DB_NAME SUPABASE_DB_USER SUPABASE_DB_PASSWORD JWT_SECRET_KEY"

echo "🔍 Verificando variables de entorno..."
MISSING_VARS=0

for VAR in $REQUIRED_VARS; do
    eval VALUE=\$$VAR
    if [ -z "$VALUE" ]; then
        echo "❌ Variable faltante: $VAR"
        MISSING_VARS=$((MISSING_VARS + 1))
    else
        echo "✅ $VAR: Configurada"
    fi
done

if [ $MISSING_VARS -gt 0 ]; then
    echo "❌ Faltan $MISSING_VARS variables de entorno requeridas"
    exit 1
fi

echo "✅ Todas las variables de entorno verificadas"

# Ejecutar migraciones de Alembic
echo ""
echo "🔄 Ejecutando migraciones de base de datos..."
if command -v alembic > /dev/null 2>&1; then
    alembic upgrade head
    if [ $? -eq 0 ]; then
        echo "✅ Migraciones ejecutadas correctamente"
    else
        echo "⚠️  Error en migraciones, continuando..."
    fi
else
    echo "⚠️  Alembic no encontrado, omitiendo migraciones"
fi

# Mostrar información del sistema
echo ""
echo "=============================================="
echo "📊 INFORMACIÓN DEL SISTEMA"
echo "=============================================="
echo "🌍 Entorno: ${ENVIRONMENT:-production}"
echo "🔧 Debug: ${DEBUG:-false}"
echo "🗄️  Base de datos: ${SUPABASE_DB_NAME}@${SUPABASE_DB_HOST}:${SUPABASE_DB_PORT}"
echo "=============================================="

# Iniciar la aplicación
echo ""
echo "🚀 Iniciando aplicación FastAPI..."
echo "=============================================="

# Ejecutar con uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1 --log-level ${LOG_LEVEL:-info} --proxy-headers --forwarded-allow-ips '*'