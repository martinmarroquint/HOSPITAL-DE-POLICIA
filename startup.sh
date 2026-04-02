#!/bin/bash

echo "=============================================="
echo "🚀 INICIANDO DESPLIEGUE EN RENDER"
echo "=============================================="
echo "📦 Entorno: ${ENVIRONMENT:-production}"
echo "🐍 Python: $(python --version 2>&1)"
echo "📂 Directorio: $(pwd)"
echo "=============================================="

# Verificar variables de entorno requeridas
REQUIRED_VARS="SUPABASE_DATABASE_URL SUPABASE_DB_HOST SUPABASE_DB_PORT SUPABASE_DB_NAME SUPABASE_DB_USER SUPABASE_DB_PASSWORD JWT_SECRET_KEY"

echo "🔍 Verificando variables de entorno..."
MISSING_VARS=0
for VAR in $REQUIRED_VARS; do
    if [ -z "${!VAR}" ]; then
        echo "❌ Variable faltante: $VAR"
        MISSING_VARS=$((MISSING_VARS + 1))
    else
        # Mostrar solo los primeros caracteres por seguridad
        case "$VAR" in
            SUPABASE_DATABASE_URL|SUPABASE_DB_PASSWORD|JWT_SECRET_KEY)
                VALUE="${!VAR}"
                if [ ${#VALUE} -gt 4 ]; then
                    echo "✅ $VAR: ****${VALUE: -4}"
                else
                    echo "✅ $VAR: ****"
                fi
                ;;
            *)
                echo "✅ $VAR: ${!VAR}"
                ;;
        esac
    fi
done

if [ $MISSING_VARS -gt 0 ]; then
    echo "❌ Faltan $MISSING_VARS variables de entorno requeridas"
    exit 1
fi

echo "✅ Todas las variables de entorno verificadas"

# Ejecutar migraciones de Alembic (si existe)
echo ""
echo "🔄 Ejecutando migraciones de base de datos..."
if command -v alembic > /dev/null 2>&1; then
    alembic upgrade head
    if [ $? -eq 0 ]; then
        echo "✅ Migraciones ejecutadas correctamente"
    else
        echo "⚠️  Error en migraciones, continuando con la aplicación..."
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