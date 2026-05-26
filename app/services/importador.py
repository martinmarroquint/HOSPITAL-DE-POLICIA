# backend/app/services/importador.py
import json
from datetime import date
from typing import Dict, Any, List, Optional  # ← Optional agregado
from uuid import UUID
from sqlalchemy.orm import Session

from app.core.logger import setup_logger
from app.models.cartera import Especialidad, Programacion, CargaExcel
from app.services.dto import ResumenImportacionDTO

logger = setup_logger(__name__)


class ImportadorServicio:
    """Servicio para importar programaciones a la base de datos"""
    
    def __init__(self, db: Session):
        self.db = db
    
    def importar(
        self,
        programaciones: List[Dict[str, Any]],
        especialidades_list: List[str],
        nombre_archivo: str,
        mes: int,
        anio: int,
        total_medicos: int,
        total_especialidades: int,
        total_registros: int,
        total_errores: int,
        errores: List[Dict[str, Any]],
        usuario_id: Optional[UUID] = None
    ) -> ResumenImportacionDTO:
        """Importa programaciones a la base de datos"""
        
        try:
            # Eliminar programaciones del mes
            registros_eliminados = self._eliminar_programaciones_mes(mes, anio)
            
            # Crear registro de carga
            carga = self._crear_carga(
                nombre_archivo, mes, anio,
                total_medicos, total_especialidades,
                total_registros, total_errores,
                errores, usuario_id
            )
            
            # Procesar especialidades
            especialidades_map = self._procesar_especialidades(especialidades_list)
            
            # Insertar programaciones
            registros_guardados = self._insertar_programaciones(
                programaciones, especialidades_map, carga.id
            )
            
            self.db.commit()
            
            logger.info(
                f"Importacion completada: {registros_guardados} registros, "
                f"{len(especialidades_map)} especialidades"
            )
            
            return ResumenImportacionDTO(
                carga_id=str(carga.id),
                registros_guardados=registros_guardados,
                registros_eliminados=registros_eliminados
            )
            
        except Exception as e:
            self.db.rollback()
            logger.exception(f"Error en importacion: {e}")
            raise
    
    def _eliminar_programaciones_mes(self, mes: int, anio: int) -> int:
        """Elimina programaciones existentes del mes"""
        inicio_mes = date(anio, mes, 1)
        if mes < 12:
            fin_mes = date(anio, mes + 1, 1)
        else:
            fin_mes = date(anio + 1, 1, 1)
        
        eliminados = self.db.query(Programacion).filter(
            Programacion.fecha >= inicio_mes,
            Programacion.fecha < fin_mes
        ).delete()
        
        logger.info(f"Eliminadas {eliminados} programaciones de {mes}/{anio}")
        return eliminados
    
    def _crear_carga(
        self, nombre_archivo: str, mes: int, anio: int,
        total_medicos: int, total_especialidades: int,
        total_registros: int, total_errores: int,
        errores: List[Dict[str, Any]],
        usuario_id: Optional[UUID] = None
    ) -> CargaExcel:
        """Crea registro de carga en el historial"""
        carga = CargaExcel(
            nombre_archivo=nombre_archivo,
            mes=mes,
            anio=anio,
            total_medicos=total_medicos,
            total_especialidades=total_especialidades,
            total_registros=total_registros,
            total_errores=total_errores,
            errores=errores,
            estado="completado",
            usuario_id=usuario_id
        )
        self.db.add(carga)
        self.db.flush()
        return carga
    
    def _procesar_especialidades(self, especialidades_list: List[str]) -> Dict[str, UUID]:
        """Procesa especialidades: crea nuevas o usa existentes"""
        especialidades_map = {}
        
        for nombre in especialidades_list:
            esp = self.db.query(Especialidad).filter(
                Especialidad.nombre == nombre
            ).first()
            
            if not esp:
                esp = Especialidad(nombre=nombre)
                self.db.add(esp)
                self.db.flush()
                logger.debug(f"Nueva especialidad: {nombre}")
            
            especialidades_map[nombre] = esp.id
        
        return especialidades_map
    
    def _insertar_programaciones(
        self, programaciones: List[Dict[str, Any]],
        especialidades_map: Dict[str, UUID],
        carga_id: UUID
    ) -> int:
        """Inserta programaciones en lote"""
        registros = []
        
        for prog in programaciones:
            fecha_str = prog.get('fecha', '')
            fecha_val = date.fromisoformat(fecha_str) if fecha_str else date.today()
            
            esp_id = especialidades_map.get(prog.get('especialidad', ''))
            if not esp_id:
                logger.warning(f"Especialidad no encontrada: {prog.get('especialidad')}")
                continue
            
            registros.append(Programacion(
                especialidad_id=esp_id,
                medico_dni=prog.get('medico_dni', ''),
                medico_nombre=prog.get('medico_nombre', ''),
                fecha=fecha_val,
                dia=int(prog.get('dia', 0)),
                dia_semana=prog.get('dia_semana', ''),
                turno=prog.get('turno', ''),
                turno_texto=prog.get('turno_texto', ''),
                carga_id=carga_id
            ))
        
        self.db.bulk_save_objects(registros)
        return len(registros)