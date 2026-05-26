# backend/app/services/dto.py
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict, Any

@dataclass
class MedicoDTO:
    dni: str
    nombre: str
    especialidad: str

@dataclass
class ProgramacionDTO:
    medico_dni: str
    medico_nombre: str
    especialidad: str
    fecha: str
    dia: int
    dia_semana: str
    turno: str
    turno_texto: str

@dataclass
class ErrorValidacionDTO:
    tipo: str
    mensaje: str
    medico: Optional[str] = None
    dia: Optional[int] = None
    valor: Optional[str] = None
    fila: Optional[int] = None
    columna: Optional[int] = None

@dataclass
class ResultadoParserDTO:
    especialidades: List[str] = field(default_factory=list)
    total_medicos: int = 0
    total_especialidades: int = 0
    total_registros: int = 0
    total_errores: int = 0
    errores: List[Dict[str, Any]] = field(default_factory=list)
    advertencias: List[Dict[str, Any]] = field(default_factory=list)
    programaciones: List[Dict[str, Any]] = field(default_factory=list)

@dataclass
class ResumenImportacionDTO:
    carga_id: str
    especialidades_nuevas: int = 0
    especialidades_existentes: int = 0
    registros_guardados: int = 0
    registros_eliminados: int = 0