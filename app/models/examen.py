from sqlalchemy import Column, String, Integer, Float, DateTime, JSON, Text
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime, timezone


class Examen(Base):
    __tablename__ = "examenes"

    id = Column(String, primary_key=True)
    codigo = Column(String(50), unique=True, nullable=False, index=True)
    titulo = Column(String(300), nullable=False)
    descripcion = Column(Text, default="")
    tiempo_limite = Column(Integer, nullable=False, default=60)  # minutos
    puntaje_aprobacion = Column(Float, default=60.0)
    estado = Column(String(20), default='BORRADOR')  # BORRADOR, PUBLICADO, CERRADO
    configuracion = Column(JSON, default=dict)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc))

    # Relaciones
    preguntas = relationship("Pregunta", back_populates="examen", cascade="all, delete-orphan", lazy="selectin")
    resultados = relationship("ResultadoExamen", back_populates="examen", cascade="all, delete-orphan", lazy="selectin")