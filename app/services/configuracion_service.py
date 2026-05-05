"""
Servicio de Configuración Dinámica
Lógica de negocio para la configuración del sistema
"""

from sqlalchemy.orm import Session
from typing import Optional, List, Dict, Any
from uuid import UUID
import logging

from app.models.configuracion import (
    ConfigTurno, ConfigRegla, ConfigNivelJerarquico, ConfigUnidad,
    ConfigRol, ConfigCampoPersonal, ConfigCatalogo
)

logger = logging.getLogger(__name__)


class ConfiguracionService:
    """Servicio central de configuración"""
    
    def __init__(self, db: Session):
        self.db = db
    
    # =====================================================
    # ESTADO DE CONFIGURACIÓN
    # =====================================================
    
    def get_estado(self) -> Dict[str, Any]:
        """Retorna el estado de completitud de la configuración"""
        completado = {
            "turnos": self.db.query(ConfigTurno).filter(ConfigTurno.activo == True).count() > 0,
            "reglas": self.db.query(ConfigRegla).filter(ConfigRegla.activo == True).count() > 0,
            "organigrama": self.db.query(ConfigUnidad).filter(ConfigUnidad.activo == True).count() > 0,
            "roles": self.db.query(ConfigRol).filter(ConfigRol.activo == True).count() > 0,
            "campos": self.db.query(ConfigCampoPersonal).filter(ConfigCampoPersonal.habilitado == True).count() > 0,
            "usuarios": False  # Se completa cuando hay personal cargado
        }
        
        total = len(completado)
        completados = sum(1 for v in completado.values() if v)
        porcentaje = round((completados / total) * 100)
        
        return {"completado": completado, "porcentaje": porcentaje}
    
    # =====================================================
    # TURNOS
    # =====================================================
    
    def get_turnos(self, incluir_inactivos: bool = False) -> List[ConfigTurno]:
        query = self.db.query(ConfigTurno).order_by(ConfigTurno.orden, ConfigTurno.nombre)
        if not incluir_inactivos:
            query = query.filter(ConfigTurno.activo == True)
        return query.all()
    
    def get_turno_by_codigo(self, codigo: str) -> Optional[ConfigTurno]:
        return self.db.query(ConfigTurno).filter(ConfigTurno.codigo == codigo).first()
    
    def crear_turno(self, data: Dict[str, Any]) -> ConfigTurno:
        turno = ConfigTurno(**data)
        self.db.add(turno)
        self.db.commit()
        self.db.refresh(turno)
        logger.info(f"✅ Turno creado: {turno.codigo} - {turno.nombre}")
        return turno
    
    def actualizar_turno(self, turno_id: UUID, data: Dict[str, Any]) -> ConfigTurno:
        turno = self.db.query(ConfigTurno).filter(ConfigTurno.id == turno_id).first()
        if not turno:
            raise ValueError(f"Turno {turno_id} no encontrado")
        
        for key, value in data.items():
            if hasattr(turno, key) and value is not None:
                setattr(turno, key, value)
        
        self.db.commit()
        self.db.refresh(turno)
        logger.info(f"✅ Turno actualizado: {turno.codigo}")
        return turno
    
    def eliminar_turno(self, turno_id: UUID) -> bool:
        turno = self.db.query(ConfigTurno).filter(ConfigTurno.id == turno_id).first()
        if not turno:
            raise ValueError(f"Turno {turno_id} no encontrado")
        if turno.sistema:
            raise ValueError("No se puede eliminar un turno del sistema")
        
        self.db.delete(turno)
        self.db.commit()
        logger.info(f"🗑️ Turno eliminado: {turno.codigo}")
        return True
    
    def crear_turnos_masivo(self, turnos_data: List[Dict[str, Any]]) -> List[ConfigTurno]:
        creados = []
        for data in turnos_data:
            turno = ConfigTurno(**data)
            self.db.add(turno)
            creados.append(turno)
        self.db.commit()
        logger.info(f"✅ {len(creados)} turnos creados masivamente")
        return creados
    
    # =====================================================
    # REGLAS
    # =====================================================
    
    def get_reglas(self) -> Optional[ConfigRegla]:
        return self.db.query(ConfigRegla).filter(ConfigRegla.activo == True).first()
    
    def guardar_reglas(self, data: Dict[str, Any]) -> ConfigRegla:
        regla_existente = self.db.query(ConfigRegla).first()
        
        if regla_existente:
            for key, value in data.items():
                if hasattr(regla_existente, key):
                    setattr(regla_existente, key, value)
            self.db.commit()
            self.db.refresh(regla_existente)
            logger.info("✅ Reglas actualizadas")
            return regla_existente
        else:
            regla = ConfigRegla(**data)
            self.db.add(regla)
            self.db.commit()
            self.db.refresh(regla)
            logger.info("✅ Reglas creadas")
            return regla
    
    # =====================================================
    # ORGANIGRAMA - NIVELES
    # =====================================================
    
    def get_niveles(self) -> List[ConfigNivelJerarquico]:
        return self.db.query(ConfigNivelJerarquico).filter(
            ConfigNivelJerarquico.activo == True
        ).order_by(ConfigNivelJerarquico.orden).all()
    
    def guardar_niveles(self, niveles_data: List[Dict[str, Any]]) -> List[ConfigNivelJerarquico]:
        # Eliminar existentes
        self.db.query(ConfigNivelJerarquico).delete()
        
        creados = []
        for data in niveles_data:
            nivel = ConfigNivelJerarquico(**data)
            self.db.add(nivel)
            creados.append(nivel)
        
        self.db.commit()
        logger.info(f"✅ {len(creados)} niveles jerárquicos guardados")
        return creados
    
    # =====================================================
    # ORGANIGRAMA - UNIDADES
    # =====================================================
    
    def get_unidades(self) -> List[ConfigUnidad]:
        return self.db.query(ConfigUnidad).filter(
            ConfigUnidad.activo == True
        ).order_by(ConfigUnidad.orden).all()
    
    def get_organigrama(self) -> Dict[str, Any]:
        return {
            "niveles": [n.to_dict() for n in self.get_niveles()],
            "unidades": [u.to_dict() for u in self.get_unidades()]
        }
    
    def crear_unidad(self, data: Dict[str, Any]) -> ConfigUnidad:
        unidad = ConfigUnidad(**data)
        self.db.add(unidad)
        self.db.commit()
        self.db.refresh(unidad)
        logger.info(f"✅ Unidad creada: {unidad.nombre}")
        return unidad
    
    def actualizar_unidad(self, unidad_id: UUID, data: Dict[str, Any]) -> ConfigUnidad:
        unidad = self.db.query(ConfigUnidad).filter(ConfigUnidad.id == unidad_id).first()
        if not unidad:
            raise ValueError(f"Unidad {unidad_id} no encontrada")
        
        for key, value in data.items():
            if hasattr(unidad, key) and value is not None:
                setattr(unidad, key, value)
        
        self.db.commit()
        self.db.refresh(unidad)
        logger.info(f"✅ Unidad actualizada: {unidad.nombre}")
        return unidad
    
    def eliminar_unidad(self, unidad_id: UUID) -> bool:
        unidad = self.db.query(ConfigUnidad).filter(ConfigUnidad.id == unidad_id).first()
        if not unidad:
            raise ValueError(f"Unidad {unidad_id} no encontrada")
        
        # Desactivar unidades hijas
        hijas = self.db.query(ConfigUnidad).filter(ConfigUnidad.padre_id == unidad_id).all()
        for hija in hijas:
            hija.activo = False
        
        self.db.delete(unidad)
        self.db.commit()
        logger.info(f"🗑️ Unidad eliminada: {unidad.nombre}")
        return True
    
    # =====================================================
    # ROLES
    # =====================================================
    
    def get_roles(self) -> List[ConfigRol]:
        return self.db.query(ConfigRol).filter(
            ConfigRol.activo == True
        ).order_by(ConfigRol.nivel.desc()).all()
    
    def crear_rol(self, data: Dict[str, Any]) -> ConfigRol:
        rol = ConfigRol(**data)
        self.db.add(rol)
        self.db.commit()
        self.db.refresh(rol)
        logger.info(f"✅ Rol creado: {rol.nombre}")
        return rol
    
    def actualizar_rol(self, rol_id: UUID, data: Dict[str, Any]) -> ConfigRol:
        rol = self.db.query(ConfigRol).filter(ConfigRol.id == rol_id).first()
        if not rol:
            raise ValueError(f"Rol {rol_id} no encontrado")
        
        for key, value in data.items():
            if hasattr(rol, key) and value is not None:
                setattr(rol, key, value)
        
        self.db.commit()
        self.db.refresh(rol)
        logger.info(f"✅ Rol actualizado: {rol.nombre}")
        return rol
    
    def eliminar_rol(self, rol_id: UUID) -> bool:
        rol = self.db.query(ConfigRol).filter(ConfigRol.id == rol_id).first()
        if not rol:
            raise ValueError(f"Rol {rol_id} no encontrado")
        if rol.sistema:
            raise ValueError("No se puede eliminar un rol del sistema")
        
        self.db.delete(rol)
        self.db.commit()
        logger.info(f"🗑️ Rol eliminado: {rol.nombre}")
        return True
    
    # =====================================================
    # CAMPOS DEL PERSONAL
    # =====================================================
    
    def get_campos_personal(self) -> List[ConfigCampoPersonal]:
        return self.db.query(ConfigCampoPersonal).order_by(ConfigCampoPersonal.orden).all()
    
    def guardar_campos_personal(self, campos_data: List[Dict[str, Any]]) -> List[ConfigCampoPersonal]:
        # Eliminar existentes no-sistema
        self.db.query(ConfigCampoPersonal).filter(ConfigCampoPersonal.sistema == False).delete()
        
        creados = []
        for data in campos_data:
            # Verificar si ya existe (por campo_id)
            existente = self.db.query(ConfigCampoPersonal).filter(
                ConfigCampoPersonal.campo_id == data.get("campo_id")
            ).first()
            
            if existente:
                for key, value in data.items():
                    if hasattr(existente, key):
                        setattr(existente, key, value)
                creados.append(existente)
            else:
                campo = ConfigCampoPersonal(**data)
                self.db.add(campo)
                creados.append(campo)
        
        self.db.commit()
        logger.info(f"✅ {len(creados)} campos de personal guardados")
        return creados
    
    # =====================================================
    # CATÁLOGOS
    # =====================================================
    
    def get_catalogos(self, tipo: Optional[str] = None) -> List[ConfigCatalogo]:
        query = self.db.query(ConfigCatalogo).filter(ConfigCatalogo.activo == True)
        if tipo:
            query = query.filter(ConfigCatalogo.tipo == tipo)
        return query.order_by(ConfigCatalogo.orden).all()
    
    def crear_catalogo(self, data: Dict[str, Any]) -> ConfigCatalogo:
        catalogo = ConfigCatalogo(**data)
        self.db.add(catalogo)
        self.db.commit()
        self.db.refresh(catalogo)
        return catalogo
    
    def eliminar_catalogo(self, catalogo_id: UUID) -> bool:
        catalogo = self.db.query(ConfigCatalogo).filter(ConfigCatalogo.id == catalogo_id).first()
        if not catalogo:
            raise ValueError(f"Catálogo {catalogo_id} no encontrado")
        self.db.delete(catalogo)
        self.db.commit()
        return True