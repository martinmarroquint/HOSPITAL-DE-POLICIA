# back/app/models/examen.py
from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Text
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from app.database import Base
from datetime import datetime, timezone


class Examen(Base):
    __tablename__ = "examenes"

    id = Column(String, primary_key=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    titulo = Column(String(300), nullable=False)
    descripcion = Column(Text, default="")
    tiempo_limite = Column(Integer, nullable=False, default=60)
    puntaje_aprobacion = Column(Float, default=60.0)
    estado = Column(String(20), default='BORRADOR')
    configuracion = Column(JSON, default=dict)
    intentos_permitidos = Column(Integer, default=1)
    grupo_id = Column(String(100), nullable=True)  # ← AGREGAR ESTA LINEA
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relaciones
    preguntas = relationship("Pregunta", back_populates="examen", cascade="all, delete-orphan", lazy="selectin")
    resultados = relationship("ResultadoExamen", back_populates="examen", cascade="all, delete-orphan", lazy="selectin")

    @hybrid_property
    def total_preguntas(self):
        return len(self.preguntas) if self.preguntas else 0