# models/personal.py
# VERSIÓN COMPLETA - CON SOPORTE PARA MÚLTIPLES TIPOS DE JEFATURA
# Compatible con formato legacy (array) y nuevo (objeto)

from sqlalchemy import Column, String, DateTime, Boolean, JSON, Date, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class Personal(Base):
    __tablename__ = "personal"

    # =====================================================
    # CAMPOS DE IDENTIFICACIÓN
    # =====================================================
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dni = Column(String(8), unique=True, nullable=False, index=True)
    cip = Column(String(20), unique=True, nullable=False)
    
    # =====================================================
    # CAMPOS PERSONALES
    # =====================================================
    grado = Column(String(50), nullable=False)
    nombre = Column(String(200), nullable=False)
    sexo = Column(String(20), nullable=True, default='No especificado')
    fecha_nacimiento = Column(Date)
    
    # =====================================================
    # CAMPOS DE CONTACTO
    # =====================================================
    email = Column(String(100), unique=True, nullable=False)
    telefono = Column(String(20))
    
    # =====================================================
    # CAMPOS LABORALES
    # =====================================================
    area = Column(String(100), nullable=False, index=True)
    especialidad = Column(String(100))
    numero_colegiatura = Column(String(50), nullable=True)
    fecha_ingreso = Column(Date)
    condicion = Column(String(50))
    
    # =====================================================
    # ROLES Y PERMISOS
    # =====================================================
    roles = Column(JSON, default=["usuario"])
    
    # =====================================================
    # CAMPOS DE JEFATURA (COMPATIBILIDAD DUAL)
    # =====================================================
    
    # FORMATO LEGACY (ACTUAL - SIGUE FUNCIONANDO)
    # Array plano de áreas que jefatura
    # Ejemplo: ["FARMACIA", "RECURSOS HUMANOS", "ADMINISTRACION"]
    # También puede contener prefijos: ["area:EMERGENCIA", "depto:CARDIOLOGIA"]
    areas_que_jefatura = Column(JSON, default=[])
    
    # FORMATO NUEVO (ESTRUCTURADO POR TIPO DE JEFATURA)
    # Objeto con arrays por tipo de jefatura
    # Ejemplo: {
    #   "grupo": ["EMERGENCIA", "UCI"],
    #   "area": ["CARDIOLOGIA", "PEDIATRIA"],
    #   "departamento": ["MEDICINA"],
    #   "direccion": ["SALUD"]
    # }
    areas_jefatura = Column(JSON, default={})
    
    # =====================================================
    # CAMPOS DE ESTADO
    # =====================================================
    activo = Column(Boolean, default=True)
    observaciones = Column(Text)
    
    # =====================================================
    # CAMPOS DE AUDITORÍA
    # =====================================================
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # =====================================================
    # MÉTODOS AUXILIARES PARA JEFATURAS
    # =====================================================
    
    def get_areas_jefatura_por_tipo(self, tipo: str) -> list:
        """
        Obtiene las áreas que jefatura para un tipo específico.
        
        Args:
            tipo: 'grupo', 'area', 'departamento', 'direccion'
            
        Returns:
            Lista de áreas para ese tipo de jefatura
        """
        areas = []
        
        # 1. Intentar obtener del formato nuevo (estructurado)
        if self.areas_jefatura and isinstance(self.areas_jefatura, dict):
            if tipo in self.areas_jefatura:
                areas_tipo = self.areas_jefatura[tipo]
                if isinstance(areas_tipo, list):
                    areas.extend(areas_tipo)
        
        # 2. Intentar obtener del formato legacy (array con prefijos)
        if self.areas_que_jefatura and isinstance(self.areas_que_jefatura, list):
            prefijo_map = {
                'grupo': 'grupo:',
                'area': 'area:',
                'departamento': 'depto:',
                'direccion': 'direccion:'
            }
            prefijo = prefijo_map.get(tipo, f"{tipo}:")
            
            for item in self.areas_que_jefatura:
                if isinstance(item, str):
                    if item.startswith(prefijo):
                        areas.append(item.replace(prefijo, ''))
                    elif ':' not in item and tipo == 'area':
                        # Sin prefijo = área (legacy puro)
                        areas.append(item)
        
        # 3. Caso especial: jefe_area sin áreas asignadas -> su propia área
        if tipo == 'area' and not areas and 'jefe_area' in (self.roles or []):
            if self.area:
                areas = [self.area]
        
        return list(set(areas))  # Eliminar duplicados
    
    def get_all_areas_jefatura(self) -> list:
        """
        Obtiene TODAS las áreas que jefatura (todos los tipos combinados).
        
        Returns:
            Lista de todas las áreas que jefatura
        """
        all_areas = []
        tipos = ['grupo', 'area', 'departamento', 'direccion']
        
        for tipo in tipos:
            all_areas.extend(self.get_areas_jefatura_por_tipo(tipo))
        
        return list(set(all_areas))  # Eliminar duplicados
    
    def tiene_acceso_global(self) -> bool:
        """
        Verifica si el usuario tiene acceso global a todas las áreas.
        
        Returns:
            True si es admin, recursos_humanos u oficina_central
        """
        roles_globales = ['admin', 'recursos_humanos', 'oficina_central']
        return any(rol in (self.roles or []) for rol in roles_globales)
    
    def puede_aprobar_nivel(self, nivel: str, area_solicitud: str = None) -> bool:
        """
        Verifica si el usuario puede aprobar solicitudes de un nivel específico
        para un área determinada.
        
        Args:
            nivel: 'jefe_grupo', 'jefe_area', 'jefe_departamento', 'jefe_direccion'
            area_solicitud: Área de la solicitud a aprobar
            
        Returns:
            True si puede aprobar
        """
        # Acceso global puede aprobar todo
        if self.tiene_acceso_global():
            return True
        
        # Verificar si tiene el rol correspondiente
        if nivel not in (self.roles or []):
            return False
        
        # Si no se especifica área, solo verificamos el rol
        if not area_solicitud:
            return True
        
        # Mapear nivel a tipo de jefatura
        nivel_a_tipo = {
            'jefe_grupo': 'grupo',
            'jefe_area': 'area',
            'jefe_departamento': 'departamento',
            'jefe_direccion': 'direccion'
        }
        
        tipo = nivel_a_tipo.get(nivel)
        if not tipo:
            return False
        
        # Verificar si el área está en sus áreas que jefatura
        areas_permitidas = self.get_areas_jefatura_por_tipo(tipo)
        return area_solicitud in areas_permitidas

    def __repr__(self):
        return f"<Personal {self.nombre} (ID: {self.id})>"