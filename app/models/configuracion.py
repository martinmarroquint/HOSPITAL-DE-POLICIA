"""
Modelos de Configuración Dinámica
Tablas que almacenan la configuración personalizada de cada cliente
CADA EMPRESA TIENE SU PROPIA CONFIGURACIÓN
"""

from sqlalchemy import Column, String, Integer, Float, Boolean, JSON, DateTime, ForeignKey, Text, Enum
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
import enum
from app.database import Base


# =====================================================
# ENUMERACIONES
# =====================================================

class TipoTurno(str, enum.Enum):
    PRODUCTIVO = "productivo"
    NO_PRODUCTIVO = "no_productivo"
    ESPECIAL = "especial"


class UnidadMedida(str, enum.Enum):
    TURNOS = "turnos"
    HORAS = "horas"


class Periodicidad(str, enum.Enum):
    MENSUAL = "mensual"
    QUINCENAL = "quincenal"
    SEMANAL = "semanal"


class TipoMeta(str, enum.Enum):
    FIJA = "fija"
    DINAMICA = "dinamica"
    PERSONALIZADA = "personalizada"


class MetodoRedondeo(str, enum.Enum):
    PISO = "piso"
    TECHO = "techo"
    UMBRAL = "umbral"


class AlcanceRegla(str, enum.Enum):
    GLOBAL = "global"
    POR_AREA = "por_area"


class TipoCampo(str, enum.Enum):
    TEXTO = "texto"
    NUMERO = "numero"
    EMAIL = "email"
    TELEFONO = "telefono"
    FECHA = "fecha"
    SELECTOR = "selector"
    CATALOGO = "catalogo"
    ORGANIGRAMA = "organigrama"
    TEXTAREA = "textarea"
    MONEDA = "moneda"
    BOOLEAN = "boolean"


# =====================================================
# TABLA: config_turnos
# =====================================================

class ConfigTurno(Base):
    """Tipos de turno configurables por el cliente"""
    __tablename__ = "config_turnos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    nombre = Column(String(100), nullable=False)
    codigo = Column(String(10), nullable=False, unique=True, index=True)
    hora_inicio = Column(String(5), nullable=True)
    hora_fin = Column(String(5), nullable=True)
    duracion = Column(Float, default=0)
    color = Column(String(7), default="#3FB4B4")
    color_texto = Column(String(7), default="#FFFFFF")
    tipo = Column(Enum(TipoTurno), default=TipoTurno.PRODUCTIVO)
    valor_computo = Column(Float, default=1.0)
    sistema = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)
    orden = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "nombre": self.nombre,
            "codigo": self.codigo,
            "hora_inicio": self.hora_inicio,
            "hora_fin": self.hora_fin,
            "duracion": self.duracion,
            "color": self.color,
            "color_texto": self.color_texto,
            "tipo": self.tipo.value if self.tipo else None,
            "valor_computo": self.valor_computo,
            "sistema": self.sistema,
            "activo": self.activo,
            "orden": self.orden
        }

    def __repr__(self):
        return f"<ConfigTurno {self.codigo} - {self.nombre}>"


# =====================================================
# TABLA: config_reglas
# =====================================================

class ConfigRegla(Base):
    """Reglas de cumplimiento configurables"""
    __tablename__ = "config_reglas"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    unidad_medida = Column(Enum(UnidadMedida), default=UnidadMedida.TURNOS)
    periodicidad = Column(Enum(Periodicidad), default=Periodicidad.MENSUAL)
    meta_tipo = Column(Enum(TipoMeta), default=TipoMeta.FIJA)
    meta_valor = Column(Float, default=25.0)
    meta_factor = Column(Float, default=0.83)
    meta_formula = Column(Text, nullable=True)
    minimo_cumplimiento = Column(Float, default=80.0)
    minimo_tipo = Column(String(20), default="porcentaje")
    tope_maximo = Column(Float, nullable=True)
    redondeo_metodo = Column(Enum(MetodoRedondeo), default=MetodoRedondeo.UMBRAL)
    redondeo_valor = Column(Float, default=0.3)
    francos_descuentan = Column(Boolean, default=False)
    max_francos_consecutivos = Column(Integer, default=2)
    exclusiones = Column(JSON, default=[])
    alcance = Column(Enum(AlcanceRegla), default=AlcanceRegla.GLOBAL)
    tolerancia_tardanza = Column(Integer, default=15)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "unidad_medida": self.unidad_medida.value if self.unidad_medida else None,
            "periodicidad": self.periodicidad.value if self.periodicidad else None,
            "meta_tipo": self.meta_tipo.value if self.meta_tipo else None,
            "meta_valor": self.meta_valor,
            "meta_factor": self.meta_factor,
            "meta_formula": self.meta_formula,
            "minimo_cumplimiento": self.minimo_cumplimiento,
            "minimo_tipo": self.minimo_tipo,
            "tope_maximo": self.tope_maximo,
            "redondeo_metodo": self.redondeo_metodo.value if self.redondeo_metodo else None,
            "redondeo_valor": self.redondeo_valor,
            "francos_descuentan": self.francos_descuentan,
            "max_francos_consecutivos": self.max_francos_consecutivos,
            "exclusiones": self.exclusiones or [],
            "alcance": self.alcance.value if self.alcance else None,
            "tolerancia_tardanza": self.tolerancia_tardanza,
            "activo": self.activo
        }

    def __repr__(self):
        return f"<ConfigRegla {self.id}>"


# =====================================================
# TABLA: config_organigrama_niveles
# =====================================================

class ConfigNivelJerarquico(Base):
    """Niveles jerárquicos configurables"""
    __tablename__ = "config_organigrama_niveles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    nombre = Column(String(100), nullable=False)
    color = Column(String(7), default="#3FB4B4")
    orden = Column(Integer, default=0)
    requiere_jefe = Column(Boolean, default=True)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "nombre": self.nombre,
            "color": self.color,
            "orden": self.orden,
            "requiere_jefe": self.requiere_jefe,
            "activo": self.activo
        }

    def __repr__(self):
        return f"<ConfigNivelJerarquico {self.nombre} (orden: {self.orden})>"


# =====================================================
# TABLA: config_organigrama_unidades
# =====================================================

class ConfigUnidad(Base):
    """Unidades organizacionales configurables"""
    __tablename__ = "config_organigrama_unidades"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    nombre = Column(String(200), nullable=False)
    codigo = Column(String(50), nullable=True)
    padre_id = Column(UUID(as_uuid=True), ForeignKey("config_organigrama_unidades.id"), nullable=True)
    nivel_id = Column(UUID(as_uuid=True), ForeignKey("config_organigrama_niveles.id"), nullable=True)
    activo = Column(Boolean, default=True)
    orden = Column(Integer, default=0)
    metadata_extra = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "nombre": self.nombre,
            "codigo": self.codigo,
            "padre_id": str(self.padre_id) if self.padre_id else None,
            "nivel_id": str(self.nivel_id) if self.nivel_id else None,
            "activo": self.activo,
            "orden": self.orden,
            "metadata_extra": self.metadata_extra or {}
        }

    def __repr__(self):
        return f"<ConfigUnidad {self.nombre}>"


# =====================================================
# TABLA: config_roles
# =====================================================

class ConfigRol(Base):
    """Roles y permisos configurables"""
    __tablename__ = "config_roles"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    nombre = Column(String(100), nullable=False, unique=True)
    nivel = Column(Integer, default=10)
    color = Column(String(7), default="#6B7280")
    descripcion = Column(Text, nullable=True)
    permisos = Column(JSON, default=[])
    es_jefatura = Column(Boolean, default=False)
    alcance_global = Column(Boolean, default=False)
    sistema = Column(Boolean, default=False)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "nombre": self.nombre,
            "nivel": self.nivel,
            "color": self.color,
            "descripcion": self.descripcion,
            "permisos": self.permisos or [],
            "es_jefatura": self.es_jefatura,
            "alcance_global": self.alcance_global,
            "sistema": self.sistema,
            "activo": self.activo
        }

    def __repr__(self):
        return f"<ConfigRol {self.nombre} (nivel: {self.nivel})>"


# =====================================================
# TABLA: config_campos_personal
# =====================================================

class ConfigCampoPersonal(Base):
    """Campos habilitados para el formulario de personal"""
    __tablename__ = "config_campos_personal"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    campo_id = Column(String(50), nullable=False)
    nombre = Column(String(100), nullable=False)
    tipo = Column(Enum(TipoCampo), default=TipoCampo.TEXTO)
    obligatorio = Column(Boolean, default=False)
    habilitado = Column(Boolean, default=True)
    sistema = Column(Boolean, default=False)
    seccion = Column(String(20), default="adicional")
    aplica_a = Column(JSON, default={"personal": True, "visitante": False})
    descripcion = Column(String(200), nullable=True)
    etiqueta = Column(String(100), nullable=True)
    opciones = Column(JSON, default=[])
    catalogo = Column(String(50), nullable=True)
    orden = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        tipo_valor = self.tipo
        if hasattr(tipo_valor, 'value'):
            tipo_valor = tipo_valor.value
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "campo_id": self.campo_id,
            "nombre": self.nombre,
            "tipo": str(tipo_valor) if tipo_valor else "texto",
            "obligatorio": self.obligatorio,
            "habilitado": self.habilitado,
            "sistema": self.sistema,
            "seccion": self.seccion or "adicional",
            "aplica_a": self.aplica_a or {"personal": True, "visitante": False},
            "descripcion": self.descripcion,
            "etiqueta": self.etiqueta,
            "opciones": self.opciones or [],
            "catalogo": self.catalogo,
            "orden": self.orden
        }

    def __repr__(self):
        return f"<ConfigCampoPersonal {self.campo_id}>"


# =====================================================
# TABLA: config_catalogos
# =====================================================

class ConfigCatalogo(Base):
    """Catálogos personalizables"""
    __tablename__ = "config_catalogos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    tipo = Column(String(50), nullable=False, index=True)
    valor = Column(String(200), nullable=False)
    orden = Column(Integer, default=0)
    activo = Column(Boolean, default=True)
    metadata_extra = Column(JSON, default={})
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "tipo": self.tipo,
            "valor": self.valor,
            "orden": self.orden,
            "activo": self.activo,
            "metadata_extra": self.metadata_extra or {}
        }

    def __repr__(self):
        return f"<ConfigCatalogo {self.tipo}: {self.valor}>"


# =====================================================
# TABLA: config_cliente
# =====================================================

class ConfigCliente(Base):
    """Configuración personalizada del cliente - UNA POR EMPRESA"""
    __tablename__ = "config_cliente"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    nombre_organizacion = Column(String(200), default='Hospital PNP')
    nombre_corto = Column(String(50), default='Hospital PNP')
    logo_url = Column(Text, nullable=True)
    color_primario = Column(String(7), default='#3FB4B4')
    color_secundario = Column(String(7), default='#2C8C8C')
    color_fondo = Column(String(7), default='#F1F5F9')
    color_texto = Column(String(7), default='#1F2937')
    pie_pagina = Column(String(200), default='Sistema de Gestión de Personal')
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def to_dict(self):
        return {
            "id": str(self.id),
            "empresa_id": str(self.empresa_id) if self.empresa_id else None,
            "nombre_organizacion": self.nombre_organizacion,
            "nombre_corto": self.nombre_corto,
            "logo_url": self.logo_url,
            "color_primario": self.color_primario,
            "color_secundario": self.color_secundario,
            "color_fondo": self.color_fondo,
            "color_texto": self.color_texto,
            "pie_pagina": self.pie_pagina,
        }