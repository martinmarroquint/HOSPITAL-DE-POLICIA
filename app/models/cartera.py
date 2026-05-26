from sqlalchemy import Column, String, Integer, Date, DateTime, Boolean, ForeignKey, JSON
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid
from app.database import Base

class Especialidad(Base):
    __tablename__ = "cartera_especialidades"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    nombre = Column(String(200), nullable=False)
    activo = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.now)
    
    programaciones = relationship("Programacion", back_populates="especialidad")


class Programacion(Base):
    __tablename__ = "cartera_programaciones"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    especialidad_id = Column(UUID(as_uuid=True), ForeignKey("cartera_especialidades.id"), nullable=False)
    
    medico_dni = Column(String(20), nullable=False)
    medico_nombre = Column(String(300), nullable=False)
    
    fecha = Column(Date, nullable=False)
    dia = Column(Integer, nullable=False)
    dia_semana = Column(String(20), nullable=False)
    turno = Column(String(5), nullable=False)
    turno_texto = Column(String(30), nullable=False)
    
    carga_id = Column(UUID(as_uuid=True), ForeignKey("cartera_cargas.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.now)
    
    especialidad = relationship("Especialidad", back_populates="programaciones")
    carga = relationship("CargaExcel", back_populates="programaciones")


class CargaExcel(Base):
    __tablename__ = "cartera_cargas"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    empresa_id = Column(UUID(as_uuid=True), ForeignKey("empresas.id"), nullable=True)
    usuario_id = Column(UUID(as_uuid=True), ForeignKey("usuarios.id"), nullable=True)
    
    nombre_archivo = Column(String(255), nullable=False)
    mes = Column(Integer, nullable=False)
    anio = Column(Integer, nullable=False)
    
    total_medicos = Column(Integer, default=0)
    total_especialidades = Column(Integer, default=0)
    total_registros = Column(Integer, default=0)
    total_errores = Column(Integer, default=0)
    errores = Column(JSON, default=[])
    
    estado = Column(String(20), default="completado")
    created_at = Column(DateTime, default=datetime.now)
    
    programaciones = relationship("Programacion", back_populates="carga")