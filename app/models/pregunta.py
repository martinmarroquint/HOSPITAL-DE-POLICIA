from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Text, ForeignKey
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime, timezone


class Pregunta(Base):
    __tablename__ = "preguntas"

    id = Column(String, primary_key=True)
    examen_id = Column(String, ForeignKey("examenes.id", ondelete="CASCADE"), nullable=False, index=True)
    tipo = Column(String(30), nullable=False)  # opcion_multiple, verdadero_falso, relacionar, ordenamiento, completar, respuesta_corta, ensayo
    enunciado = Column(Text, nullable=False)
    puntos = Column(Float, default=1.0)
    orden = Column(Integer, default=0)

    # Opción múltiple
    opcion_a = Column(Text, default="")
    opcion_b = Column(Text, default="")
    opcion_c = Column(Text, default="")
    opcion_d = Column(Text, default="")
    opcion_e = Column(Text, default="")
    respuesta_correcta = Column(Integer, nullable=True)  # índice 0-4 para opción múltiple

    # Verdadero/Falso
    afirmaciones = Column(JSON, nullable=True)  # [{id, texto, esVerdadero}]

    # Relacionar
    columna_a = Column(JSON, nullable=True)
    columna_b = Column(JSON, nullable=True)

    # Ordenamiento
    elementos = Column(JSON, nullable=True)

    # Completar espacios
    segmentos = Column(JSON, nullable=True)  # [{id, tipo: 'texto'|'espacio', texto?, respuesta?, puntos?}]

    # Respuesta corta
    respuesta_corta = Column(Text, default="")
    respuestas_alternativas = Column(JSON, nullable=True)

    # Ensayo
    longitud_minima = Column(Integer, default=100)
    rubrica = Column(Text, default="")

    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    # Relación
    examen = relationship("Examen", back_populates="preguntas")