from sqlalchemy import Column, String, DateTime, Boolean, JSON, Date, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class Personal(Base):
    __tablename__ = "personal"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dni = Column(String(8), unique=True, nullable=False, index=True)
    cip = Column(String(20), unique=True, nullable=False)
    grado = Column(String(50), nullable=False)
    nombre = Column(String(200), nullable=False)
    sexo = Column(String(20), nullable=True, default='No especificado')
    email = Column(String(100), unique=True, nullable=False)
    telefono = Column(String(20))
    fecha_nacimiento = Column(Date)
    area = Column(String(100), nullable=False, index=True)
    especialidad = Column(String(100))
    roles = Column(JSON, default=["usuario"])
    numero_colegiatura = Column(String(50), nullable=True)
    activo = Column(Boolean, default=True)
    fecha_ingreso = Column(Date)
    condicion = Column(String(50))
    observaciones = Column(Text)
    
    # ✅ CAMPO ACTUALIZADO: Ahora es un array JSON para múltiples áreas que jefatura
    # Ejemplo: ["FARMACIA", "RECURSOS HUMANOS", "ADMINISTRACION"]
    areas_que_jefatura = Column(JSON, default=[])  # Lista de áreas que jefatura
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<Personal {self.nombre}>"