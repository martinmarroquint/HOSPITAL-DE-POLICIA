# api/sesiones.py
from fastapi import APIRouter, Depends, HTTPException, status, Body, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import datetime, date, timezone

from app.database import get_db
from app.core.dependencies import get_current_active_user, require_roles
from app.models.sesion import Sesion, SesionAsistente
from app.models.usuario import Usuario
from app.models.personal import Personal

router = APIRouter()


def ahora_utc():
    return datetime.now(timezone.utc)


# =====================================================
# CRUD DE SESIONES
# =====================================================

@router.get("/")
async def listar_sesiones(
    fecha: Optional[date] = Query(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Lista sesiones, opcionalmente filtradas por fecha"""
    query = db.query(Sesion)
    
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        query = query.filter(Sesion.empresa_id == current_user.empresa_id)
    
    if fecha:
        query = query.filter(Sesion.fecha == fecha)
    
    sesiones = query.order_by(Sesion.fecha.desc(), Sesion.hora_inicio).all()
    
    result = []
    for s in sesiones:
        asistentes = db.query(SesionAsistente).filter(SesionAsistente.sesion_id == s.id).all()
        instructor = db.query(Personal).filter(Personal.id == s.instructor_id).first()
        
        result.append({
            **s.to_dict(),
            "total_asistentes": len(asistentes),
            "asistieron": sum(1 for a in asistentes if a.asistio),
            "instructor_nombre": instructor.nombre if instructor else None,
        })
    
    return result


@router.post("/", status_code=201)
async def crear_sesion(
    nombre: str = Body(...),
    fecha: date = Body(...),
    hora_inicio: str = Body(...),
    hora_fin: str = Body(...),
    turno_codigo: Optional[str] = Body(None),
    descripcion: Optional[str] = Body(None),
    instructor_id: Optional[UUID] = Body(None),
    max_participantes: int = Body(20),
    color: str = Body("#8B5CF6"),
    asistentes_ids: List[UUID] = Body([]),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Crea una sesión con sus asistentes"""
    
    sesion = Sesion(
        empresa_id=current_user.empresa_id,
        nombre=nombre,
        descripcion=descripcion,
        fecha=fecha,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        turno_codigo=turno_codigo,
        instructor_id=instructor_id,
        max_participantes=max_participantes,
        color=color,
    )
    db.add(sesion)
    db.flush()
    
    # Agregar asistentes
    for pid in asistentes_ids:
        asistente = SesionAsistente(
            sesion_id=sesion.id,
            personal_id=pid,
        )
        db.add(asistente)
    
    db.commit()
    db.refresh(sesion)
    
    return {**sesion.to_dict(), "message": "Sesión creada exitosamente"}


@router.put("/{sesion_id}")
async def actualizar_sesion(
    sesion_id: UUID,
    nombre: Optional[str] = Body(None),
    fecha: Optional[date] = Body(None),
    hora_inicio: Optional[str] = Body(None),
    hora_fin: Optional[str] = Body(None),
    activo: Optional[bool] = Body(None),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Actualiza una sesión"""
    sesion = db.query(Sesion).filter(Sesion.id == sesion_id).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    
    if nombre is not None: sesion.nombre = nombre
    if fecha is not None: sesion.fecha = fecha
    if hora_inicio is not None: sesion.hora_inicio = hora_inicio
    if hora_fin is not None: sesion.hora_fin = hora_fin
    if activo is not None: sesion.activo = activo
    
    db.commit()
    return {**sesion.to_dict(), "message": "Sesión actualizada"}


@router.delete("/{sesion_id}")
async def eliminar_sesion(
    sesion_id: UUID,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin"]))
):
    """Elimina una sesión y sus asistentes"""
    sesion = db.query(Sesion).filter(Sesion.id == sesion_id).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    
    db.delete(sesion)
    db.commit()
    return {"message": "Sesión eliminada"}


# =====================================================
# CHECK-IN
# =====================================================

@router.post("/checkin")
async def registrar_checkin(
    sesion_id: UUID = Body(...),
    personal_id: UUID = Body(...),
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(["admin", "control_qr"]))
):
    """Registra check-in de un asistente a una sesión"""
    
    sesion = db.query(Sesion).filter(Sesion.id == sesion_id).first()
    if not sesion:
        raise HTTPException(status_code=404, detail="Sesión no encontrada")
    
    asistente = db.query(SesionAsistente).filter(
        SesionAsistente.sesion_id == sesion_id,
        SesionAsistente.personal_id == personal_id
    ).first()
    
    if not asistente:
        raise HTTPException(status_code=404, detail="Asistente no registrado en esta sesión")
    
    ahora = ahora_utc()
    asistente.asistio = True
    asistente.hora_llegada = ahora
    
    # Calcular tardanza/temprano
    hora_inicio_dt = datetime.combine(sesion.fecha, sesion.hora_inicio)
    if hora_inicio_dt.tzinfo is None:
        hora_inicio_dt = hora_inicio_dt.replace(tzinfo=timezone.utc)
    
    diferencia = (ahora - hora_inicio_dt).total_seconds() / 60
    
    if diferencia > 0:
        asistente.minutos_tardanza = int(diferencia)
        asistente.minutos_temprano = 0
    else:
        asistente.minutos_tardanza = 0
        asistente.minutos_temprano = int(abs(diferencia))
    
    db.commit()
    
    return {
        "message": "Check-in registrado",
        "personal_id": str(personal_id),
        "asistio": True,
        "minutos_tardanza": asistente.minutos_tardanza,
        "minutos_temprano": asistente.minutos_temprano,
    }


# =====================================================
# REPORTE DEL DÍA
# =====================================================

@router.get("/reporte/{fecha}")
async def reporte_dia(
    fecha: date,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Reporte de asistencia para un día específico"""
    
    query = db.query(Sesion)
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        query = query.filter(Sesion.empresa_id == current_user.empresa_id)
    
    sesiones = query.filter(Sesion.fecha == fecha).order_by(Sesion.hora_inicio).all()
    
    resultado = []
    for sesion in sesiones:
        asistentes = db.query(SesionAsistente).filter(
            SesionAsistente.sesion_id == sesion.id
        ).all()
        
        asistentes_detalle = []
        for a in asistentes:
            personal = db.query(Personal).filter(Personal.id == a.personal_id).first()
            asistentes_detalle.append({
                "personal_id": str(a.personal_id),
                "nombre": personal.nombre if personal else "Desconocido",
                "asistio": a.asistio,
                "hora_llegada": a.hora_llegada.isoformat() if a.hora_llegada else None,
                "minutos_tardanza": a.minutos_tardanza,
                "minutos_temprano": a.minutos_temprano,
            })
        
        resultado.append({
            **sesion.to_dict(),
            "asistentes": asistentes_detalle,
            "total": len(asistentes),
            "presentes": sum(1 for a in asistentes if a.asistio),
            "ausentes": sum(1 for a in asistentes if not a.asistio),
        })
    
    return resultado