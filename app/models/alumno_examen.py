from sqlalchemy import Column, String, DateTime, Text
from app.database import Base
from datetime import datetime, timezone

class AlumnoExamen(Base):
    __tablename__ = "alumnos_examenes"
    
    id = Column(String, primary_key=True)
    dni = Column(String(20), default="")
    grado = Column(String(50), default="")
    nombres = Column(Text, nullable=False)
    apellidos = Column(Text, nullable=False)
    email = Column(String(100), default="")
    grupo = Column(String(50), default="")
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))