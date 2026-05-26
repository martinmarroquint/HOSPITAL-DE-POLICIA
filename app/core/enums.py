# backend/app/core/enums.py
from enum import Enum

class Turno(str, Enum):
    MANANA = "M"
    TARDE = "T"
    MANANA_TARDE = "MT"

class EstadoCarga(str, Enum):
    PROCESANDO = "procesando"
    COMPLETADO = "completado"
    ERROR = "error"

class DiaSemana(str, Enum):
    LUNES = "LUNES"
    MARTES = "MARTES"
    MIERCOLES = "MIERCOLES"
    JUEVES = "JUEVES"
    VIERNES = "VIERNES"
    SABADO = "SABADO"
    DOMINGO = "DOMINGO"