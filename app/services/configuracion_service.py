"""
Servicio de Configuración Dinámica
Lógica de negocio para la configuración del sistema
CORREGIDO: guardar_niveles ahora actualiza sin borrar unidades asociadas
           guardar_campos_personal convierte tipos a minúsculas
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
            "usuarios": False
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
        logger.info(f"Turno creado: {turno.codigo} - {turno.nombre}")
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
        logger.info(f"Turno actualizado: {turno.codigo}")
        return turno
    
    def eliminar_turno(self, turno_id: UUID) -> bool:
        turno = self.db.query(ConfigTurno).filter(ConfigTurno.id == turno_id).first()
        if not turno:
            raise ValueError(f"Turno {turno_id} no encontrado")
        if turno.sistema:
            raise ValueError("No se puede eliminar un turno del sistema")
        
        self.db.delete(turno)
        self.db.commit()
        logger.info(f"Turno eliminado: {turno.codigo}")
        return True
    
    def crear_turnos_masivo(self, turnos_data: List[Dict[str, Any]]) -> List[ConfigTurno]:
        creados = []
        for data in turnos_data:
            turno = ConfigTurno(**data)
            self.db.add(turno)
            creados.append(turno)
        self.db.commit()
        logger.info(f"{len(creados)} turnos creados masivamente")
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
            logger.info("Reglas actualizadas")
            return regla_existente
        else:
            regla = ConfigRegla(**data)
            self.db.add(regla)
            self.db.commit()
            self.db.refresh(regla)
            logger.info("Reglas creadas")
            return regla
    
    # =====================================================
    # ORGANIGRAMA - NIVELES
    # =====================================================
    
    def get_niveles(self) -> List[ConfigNivelJerarquico]:
        """Obtiene todos los niveles jerárquicos activos"""
        return self.db.query(ConfigNivelJerarquico).filter(
            ConfigNivelJerarquico.activo == True
        ).order_by(ConfigNivelJerarquico.orden).all()
    
    def guardar_niveles(self, niveles_data: List[Dict[str, Any]]) -> List[ConfigNivelJerarquico]:
        """
        Guarda los niveles jerárquicos.
        - Si el nivel tiene ID, lo actualiza
        - Si no tiene ID, lo crea nuevo
        - NO elimina niveles que tengan unidades asociadas
        """
        creados = []
        ids_procesados = []
        
        for data in niveles_data:
            nivel_id = data.get('id')
            
            if nivel_id:
                try:
                    nivel_id_uuid = UUID(str(nivel_id))
                    nivel = self.db.query(ConfigNivelJerarquico).filter(
                        ConfigNivelJerarquico.id == nivel_id_uuid
                    ).first()
                    
                    if nivel:
                        for key, value in data.items():
                            if hasattr(nivel, key) and key not in ['id', 'created_at', 'updated_at']:
                                setattr(nivel, key, value)
                        nivel.activo = True
                        creados.append(nivel)
                        ids_procesados.append(nivel_id_uuid)
                        logger.info(f"Nivel actualizado: {nivel.nombre} (ID: {nivel_id})")
                        continue
                except (ValueError, AttributeError):
                    pass
            
            data_copy = {k: v for k, v in data.items() if k not in ['id', 'created_at', 'updated_at']}
            data_copy.setdefault('activo', True)
            nuevo_nivel = ConfigNivelJerarquico(**data_copy)
            self.db.add(nuevo_nivel)
            self.db.flush()
            creados.append(nuevo_nivel)
            ids_procesados.append(nuevo_nivel.id)
            logger.info(f"Nivel creado: {nuevo_nivel.nombre}")
        
        niveles_existentes = self.db.query(ConfigNivelJerarquico).filter(
            ConfigNivelJerarquico.activo == True
        ).all()
        
        for nivel_existente in niveles_existentes:
            if nivel_existente.id not in ids_procesados:
                unidades_count = self.db.query(ConfigUnidad).filter(
                    ConfigUnidad.nivel_id == nivel_existente.id,
                    ConfigUnidad.activo == True
                ).count()
                
                if unidades_count == 0:
                    self.db.delete(nivel_existente)
                    logger.info(f"Nivel eliminado: {nivel_existente.nombre} (sin unidades)")
                else:
                    nivel_existente.activo = False
                    logger.warning(
                        f"Nivel '{nivel_existente.nombre}' marcado como inactivo: "
                        f"tiene {unidades_count} unidades asociadas"
                    )
        
        self.db.commit()
        logger.info(f"Total niveles guardados: {len(creados)}")
        return creados
    
    # =====================================================
    # ORGANIGRAMA - UNIDADES
    # =====================================================
    
    def get_unidades(self) -> List[ConfigUnidad]:
        """Obtiene todas las unidades activas"""
        return self.db.query(ConfigUnidad).filter(
            ConfigUnidad.activo == True
        ).order_by(ConfigUnidad.orden).all()
    
    def get_organigrama(self) -> Dict[str, Any]:
        """Obtiene el organigrama completo (niveles + unidades)"""
        return {
            "niveles": [n.to_dict() for n in self.get_niveles()],
            "unidades": [u.to_dict() for u in self.get_unidades()]
        }
    
    def crear_unidad(self, data: Dict[str, Any]) -> ConfigUnidad:
        """Crea una nueva unidad organizacional"""
        unidad = ConfigUnidad(**data)
        self.db.add(unidad)
        self.db.commit()
        self.db.refresh(unidad)
        logger.info(f"Unidad creada: {unidad.nombre}")
        return unidad
    
    def actualizar_unidad(self, unidad_id: UUID, data: Dict[str, Any]) -> ConfigUnidad:
        """Actualiza una unidad existente"""
        unidad = self.db.query(ConfigUnidad).filter(ConfigUnidad.id == unidad_id).first()
        if not unidad:
            raise ValueError(f"Unidad {unidad_id} no encontrada")
        
        for key, value in data.items():
            if hasattr(unidad, key) and value is not None:
                setattr(unidad, key, value)
        
        self.db.commit()
        self.db.refresh(unidad)
        logger.info(f"Unidad actualizada: {unidad.nombre}")
        return unidad
    
    def eliminar_unidad(self, unidad_id: UUID) -> bool:
        """Elimina una unidad y desactiva sus hijas"""
        unidad = self.db.query(ConfigUnidad).filter(ConfigUnidad.id == unidad_id).first()
        if not unidad:
            raise ValueError(f"Unidad {unidad_id} no encontrada")
        
        hijas = self.db.query(ConfigUnidad).filter(ConfigUnidad.padre_id == unidad_id).all()
        for hija in hijas:
            hija.activo = False
            logger.info(f"Unidad hija desactivada: {hija.nombre}")
        
        self.db.delete(unidad)
        self.db.commit()
        logger.info(f"Unidad eliminada: {unidad.nombre}")
        return True
    
    # =====================================================
    # ROLES
    # =====================================================
    
    def get_roles(self) -> List[ConfigRol]:
        """Obtiene todos los roles activos"""
        return self.db.query(ConfigRol).filter(
            ConfigRol.activo == True
        ).order_by(ConfigRol.nivel.desc()).all()
    
    def crear_rol(self, data: Dict[str, Any]) -> ConfigRol:
        """Crea un nuevo rol"""
        rol = ConfigRol(**data)
        self.db.add(rol)
        self.db.commit()
        self.db.refresh(rol)
        logger.info(f"Rol creado: {rol.nombre}")
        return rol
    
    def actualizar_rol(self, rol_id: UUID, data: Dict[str, Any]) -> ConfigRol:
        """Actualiza un rol existente"""
        rol = self.db.query(ConfigRol).filter(ConfigRol.id == rol_id).first()
        if not rol:
            raise ValueError(f"Rol {rol_id} no encontrado")
        
        for key, value in data.items():
            if hasattr(rol, key) and value is not None:
                setattr(rol, key, value)
        
        self.db.commit()
        self.db.refresh(rol)
        logger.info(f"Rol actualizado: {rol.nombre}")
        return rol
    
    def eliminar_rol(self, rol_id: UUID) -> bool:
        """Elimina un rol (no permite eliminar roles del sistema)"""
        rol = self.db.query(ConfigRol).filter(ConfigRol.id == rol_id).first()
        if not rol:
            raise ValueError(f"Rol {rol_id} no encontrado")
        if rol.sistema:
            raise ValueError("No se puede eliminar un rol del sistema")
        
        self.db.delete(rol)
        self.db.commit()
        logger.info(f"Rol eliminado: {rol.nombre}")
        return True
    
    # =====================================================
    # CAMPOS DEL PERSONAL (CORREGIDO - CONVERSIÓN A MINÚSCULAS)
    # =====================================================
    
    def get_campos_personal(self, empresa_id: Optional[UUID] = None) -> List[ConfigCampoPersonal]:
        """Obtiene campos del personal filtrados por empresa_id"""
        query = self.db.query(ConfigCampoPersonal)
        if empresa_id:
            query = query.filter(
                (ConfigCampoPersonal.empresa_id == empresa_id) | 
                (ConfigCampoPersonal.empresa_id == None)
            )
        return query.order_by(ConfigCampoPersonal.orden).all()
    
    def guardar_campos_personal(self, campos_data: List[Dict[str, Any]], empresa_id: Optional[UUID] = None) -> List[ConfigCampoPersonal]:
        """Guarda los campos del personal para una empresa especifica"""
        # Eliminar existentes no-sistema de esta empresa
        query = self.db.query(ConfigCampoPersonal).filter(ConfigCampoPersonal.sistema == False)
        if empresa_id:
            query = query.filter(ConfigCampoPersonal.empresa_id == empresa_id)
        query.delete()
        
        creados = []
        for data in campos_data:
            campo_id = data.get("campo_id")
            
            # 🎯 CORRECCIÓN: Convertir tipo a minúsculas para cumplir con CHECK constraint
            if data.get("tipo"):
                data["tipo"] = data["tipo"].lower()
            
            # Buscar existente
            existente_query = self.db.query(ConfigCampoPersonal).filter(
                ConfigCampoPersonal.campo_id == campo_id
            )
            if empresa_id:
                existente_query = existente_query.filter(
                    (ConfigCampoPersonal.empresa_id == empresa_id) | 
                    (ConfigCampoPersonal.empresa_id == None)
                )
            existente = existente_query.first()
            
            if existente:
                # Si ya existe, actualizar sus campos
                for key, value in data.items():
                    if hasattr(existente, key) and key not in ['id', 'empresa_id', 'created_at']:
                        setattr(existente, key, value)
                existente.empresa_id = empresa_id
                creados.append(existente)
            else:
                # Si no existe, crear nuevo
                data_copy = {k: v for k, v in data.items() if k not in ['id', 'created_at']}
                data_copy['empresa_id'] = empresa_id
                campo = ConfigCampoPersonal(**data_copy)
                self.db.add(campo)
                creados.append(campo)
        
        self.db.commit()
        logger.info(f"{len(creados)} campos de personal guardados para empresa {empresa_id}")
        return creados
    
    # =====================================================
    # CATÁLOGOS
    # =====================================================
    
    def get_catalogos(self, tipo: Optional[str] = None) -> List[ConfigCatalogo]:
        """Obtiene catálogos, opcionalmente filtrados por tipo"""
        query = self.db.query(ConfigCatalogo).filter(ConfigCatalogo.activo == True)
        if tipo:
            query = query.filter(ConfigCatalogo.tipo == tipo)
        return query.order_by(ConfigCatalogo.orden).all()
    
    def crear_catalogo(self, data: Dict[str, Any]) -> ConfigCatalogo:
        """Crea una nueva entrada de catálogo"""
        catalogo = ConfigCatalogo(**data)
        self.db.add(catalogo)
        self.db.commit()
        self.db.refresh(catalogo)
        logger.info(f"Catálogo creado: {catalogo.nombre} ({catalogo.tipo})")
        return catalogo
    
    def eliminar_catalogo(self, catalogo_id: UUID) -> bool:
        """Elimina una entrada de catálogo"""
        catalogo = self.db.query(ConfigCatalogo).filter(ConfigCatalogo.id == catalogo_id).first()
        if not catalogo:
            raise ValueError(f"Catálogo {catalogo_id} no encontrado")
        self.db.delete(catalogo)
        self.db.commit()
        logger.info(f"Catálogo eliminado: {catalogo.nombre}")
        return True