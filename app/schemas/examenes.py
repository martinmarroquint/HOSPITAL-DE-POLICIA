from pydantic import BaseModel, Field
from typing import Optional, List, Any, Dict
from datetime import datetime


# ========== PREGUNTA ==========
class AfirmacionVF(BaseModel):
    id: str
    texto: str
    esVerdadero: bool

class SegmentoCompletar(BaseModel):
    id: str
    tipo: str  # 'texto' o 'espacio'
    texto: Optional[str] = ""
    respuesta: Optional[str] = ""
    puntos: Optional[float] = 1.0

class PreguntaBase(BaseModel):
    tipo: str
    enunciado: str
    puntos: float = 1.0
    orden: int = 0
    # Opción múltiple
    opcion_a: Optional[str] = ""
    opcion_b: Optional[str] = ""
    opcion_c: Optional[str] = ""
    opcion_d: Optional[str] = ""
    opcion_e: Optional[str] = ""
    respuesta_correcta: Optional[int] = None
    # Verdadero/Falso
    afirmaciones: Optional[List[AfirmacionVF]] = None
    # Relacionar
    columna_a: Optional[List[str]] = None
    columna_b: Optional[List[str]] = None
    # Ordenamiento
    elementos: Optional[List[str]] = None
    # Completar
    segmentos: Optional[List[SegmentoCompletar]] = None
    # Respuesta corta
    respuesta_corta: Optional[str] = ""
    respuestas_alternativas: Optional[List[str]] = None
    # Ensayo
    longitud_minima: Optional[int] = 100
    rubrica: Optional[str] = ""

class PreguntaCreate(PreguntaBase):
    pass

class PreguntaResponse(PreguntaBase):
    id: str
    examen_id: str
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== EXAMEN ==========
class ConfiguracionExamen(BaseModel):
    aleatorizarPreguntas: bool = False
    aleatorizarOpciones: bool = False
    preguntasPorExamen: int = 0
    mostrarUnaSolaPregunta: bool = False

class ExamenCreate(BaseModel):
    titulo: str
    descripcion: str = ""
    tiempo_limite: int = 60
    puntaje_aprobacion: float = 60.0
    configuracion: ConfiguracionExamen = ConfiguracionExamen()
    preguntas: List[PreguntaCreate] = []

class ExamenUpdate(BaseModel):
    titulo: Optional[str] = None
    descripcion: Optional[str] = None
    tiempo_limite: Optional[int] = None
    puntaje_aprobacion: Optional[float] = None
    estado: Optional[str] = None
    configuracion: Optional[ConfiguracionExamen] = None

class ExamenResponse(BaseModel):
    id: str
    codigo: str
    titulo: str
    descripcion: str
    tiempo_limite: int
    puntaje_aprobacion: float
    estado: str
    configuracion: Optional[Dict] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ExamenDetailResponse(ExamenResponse):
    preguntas: List[PreguntaResponse] = []


# ========== RESULTADO ==========
class ResultadoCreate(BaseModel):
    examen_id: str
    alumno_id: str
    alumno_nombre: str = ""
    alumno_grado: str = ""
    alumno_dni: str = ""
    respuestas: Dict[str, Any]
    calificacion: float = 0.0
    correctas: int = 0
    total_preguntas: int = 0
    puntos_obtenidos: float = 0.0
    total_puntos: float = 0.0
    tiempo_usado: int = 0
    tiempo_restante: int = 0
    violaciones: int = 0
    eventos_seguridad: Optional[List[Dict]] = None
    entregado_por_tiempo: bool = False
    estado: str = 'COMPLETADO'

class ResultadoResponse(BaseModel):
    id: str
    examen_id: str
    alumno_id: str
    alumno_nombre: str
    alumno_grado: str
    alumno_dni: str
    respuestas: Dict
    calificacion: float
    correctas: int
    total_preguntas: int
    puntos_obtenidos: float
    total_puntos: float
    tiempo_usado: int
    violaciones: int
    estado: str
    entregado_en: Optional[datetime] = None

    class Config:
        from_attributes = True


# ========== RESPUESTAS GENÉRICAS ==========
class MensajeResponse(BaseModel):
    mensaje: str
    ok: bool = True