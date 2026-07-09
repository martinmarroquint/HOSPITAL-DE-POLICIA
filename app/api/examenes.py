# back/app/api/examenes.py
# VERSION COMPLETA - CON EDITAR PREGUNTAS + total_preguntas + intentos_permitidos

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import datetime, timezone

from app.database import get_db
from app.models.examen import Examen
from app.models.pregunta import Pregunta
from app.models.resultado_examen import ResultadoExamen
from app.models.alumno_examen import AlumnoExamen
from app.schemas.examenes import (
    ExamenCreate, ExamenUpdate, ExamenResponse, ExamenDetailResponse,
    PreguntaCreate, PreguntaResponse,
    ResultadoCreate, ResultadoResponse,
    MensajeResponse
)

router = APIRouter()


# =============================================
# UTILIDAD
# =============================================
def generar_codigo():
    ahora = datetime.now(timezone.utc)
    r = str(uuid.uuid4().int)[:4]
    return f"EXA-{ahora.year}{str(ahora.month).zfill(2)}{str(ahora.day).zfill(2)}-{r.zfill(4)}"


# =============================================
# ALUMNOS
# =============================================

@router.get("/alumnos")
def listar_alumnos(
    busqueda: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Lista todos los alumnos registrados"""
    query = db.query(AlumnoExamen)
    if busqueda:
        query = query.filter(
            (AlumnoExamen.nombres.ilike(f"%{busqueda}%")) |
            (AlumnoExamen.apellidos.ilike(f"%{busqueda}%")) |
            (AlumnoExamen.dni.ilike(f"%{busqueda}%"))
        )
    return query.order_by(AlumnoExamen.apellidos.asc()).all()


@router.get("/alumnos/buscar")
def buscar_alumnos(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_db)
):
    """Busca alumnos por nombre, apellido o DNI (para dropdown en tiempo real)"""
    return db.query(AlumnoExamen).filter(
        (AlumnoExamen.nombres.ilike(f"%{q}%")) |
        (AlumnoExamen.apellidos.ilike(f"%{q}%")) |
        (AlumnoExamen.dni.ilike(f"%{q}%")) |
        (AlumnoExamen.grado.ilike(f"%{q}%"))
    ).limit(10).all()


@router.post("/alumnos", status_code=201)
def guardar_alumnos(data: List[dict], db: Session = Depends(get_db)):
    """Reemplaza todos los alumnos con la nueva lista"""
    db.query(AlumnoExamen).delete()
    
    for alumno in data:
        nuevo = AlumnoExamen(
            id=str(uuid.uuid4()),
            dni=alumno.get('dni', ''),
            grado=alumno.get('grado', ''),
            nombres=alumno.get('nombres', ''),
            apellidos=alumno.get('apellidos', ''),
            email=alumno.get('email', ''),
            grupo=alumno.get('grupo', '')
        )
        db.add(nuevo)
    
    db.commit()
    return {"mensaje": f"{len(data)} alumnos guardados correctamente", "ok": True}


@router.delete("/alumnos", response_model=MensajeResponse)
def eliminar_todos_alumnos(db: Session = Depends(get_db)):
    """Elimina todos los alumnos"""
    db.query(AlumnoExamen).delete()
    db.commit()
    return {"mensaje": "Todos los alumnos eliminados", "ok": True}


# =============================================
# EXÁMENES
# =============================================

@router.get("/", response_model=List[ExamenResponse])
def listar_examenes(
    estado: Optional[str] = Query(None),
    busqueda: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Lista todos los exámenes con filtros opcionales"""
    query = db.query(Examen)
    
    if estado:
        query = query.filter(Examen.estado == estado)
    
    if busqueda:
        query = query.filter(
            (Examen.titulo.ilike(f"%{busqueda}%")) |
            (Examen.codigo.ilike(f"%{busqueda}%"))
        )
    
    return query.order_by(Examen.created_at.desc()).all()


@router.get("/publicados", response_model=List[ExamenResponse])
def listar_examenes_publicados(db: Session = Depends(get_db)):
    """Lista solo exámenes publicados (para alumnos)"""
    return db.query(Examen).filter(Examen.estado == 'PUBLICADO').order_by(Examen.created_at.desc()).all()


@router.get("/{examen_id}", response_model=ExamenDetailResponse)
def obtener_examen(examen_id: str, db: Session = Depends(get_db)):
    """Obtiene un examen con todas sus preguntas"""
    examen = db.query(Examen).filter(Examen.id == examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    return examen


@router.post("/", response_model=ExamenDetailResponse, status_code=201)
def crear_examen(data: ExamenCreate, db: Session = Depends(get_db)):
    """Crea un nuevo examen con sus preguntas"""
    examen_id = str(uuid.uuid4())
    codigo = generar_codigo()
    
    examen = Examen(
        id=examen_id,
        codigo=codigo,
        titulo=data.titulo,
        descripcion=data.descripcion,
        tiempo_limite=data.tiempo_limite,
        puntaje_aprobacion=data.puntaje_aprobacion,
        configuracion=data.configuracion.model_dump() if data.configuracion else {},
        intentos_permitidos=data.intentos_permitidos,
        estado='BORRADOR'
    )
    db.add(examen)
    
    for i, pregunta_data in enumerate(data.preguntas):
        pregunta = Pregunta(
            id=str(uuid.uuid4()),
            examen_id=examen_id,
            tipo=pregunta_data.tipo,
            enunciado=pregunta_data.enunciado,
            puntos=pregunta_data.puntos,
            orden=pregunta_data.orden or i,
            opcion_a=pregunta_data.opcion_a,
            opcion_b=pregunta_data.opcion_b,
            opcion_c=pregunta_data.opcion_c,
            opcion_d=pregunta_data.opcion_d,
            opcion_e=pregunta_data.opcion_e,
            respuesta_correcta=pregunta_data.respuesta_correcta,
            afirmaciones=[a.model_dump() for a in pregunta_data.afirmaciones] if pregunta_data.afirmaciones else None,
            columna_a=pregunta_data.columna_a,
            columna_b=pregunta_data.columna_b,
            elementos=pregunta_data.elementos,
            segmentos=[s.model_dump() for s in pregunta_data.segmentos] if pregunta_data.segmentos else None,
            frases=[f.model_dump() for f in pregunta_data.frases] if pregunta_data.frases else None,
            respuesta_corta=pregunta_data.respuesta_corta,
            respuestas_alternativas=pregunta_data.respuestas_alternativas,
            longitud_minima=pregunta_data.longitud_minima,
            rubrica=pregunta_data.rubrica,
        )
        db.add(pregunta)
    
    db.commit()
    db.refresh(examen)
    return examen


@router.put("/{examen_id}", response_model=ExamenDetailResponse)
def actualizar_examen(examen_id: str, data: ExamenCreate, db: Session = Depends(get_db)):
    """Actualiza un examen existente Y sus preguntas (elimina y recrea)"""
    examen = db.query(Examen).filter(Examen.id == examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    
    # Actualizar datos básicos del examen
    examen.titulo = data.titulo
    examen.descripcion = data.descripcion
    examen.tiempo_limite = data.tiempo_limite
    examen.puntaje_aprobacion = data.puntaje_aprobacion
    if data.configuracion:
        examen.configuracion = data.configuracion.model_dump()
    if data.intentos_permitidos is not None:
        examen.intentos_permitidos = data.intentos_permitidos
    examen.updated_at = datetime.now(timezone.utc)
    
    # Eliminar preguntas existentes
    db.query(Pregunta).filter(Pregunta.examen_id == examen_id).delete()
    
    # Crear nuevas preguntas
    for i, pregunta_data in enumerate(data.preguntas):
        pregunta = Pregunta(
            id=str(uuid.uuid4()),
            examen_id=examen_id,
            tipo=pregunta_data.tipo,
            enunciado=pregunta_data.enunciado,
            puntos=pregunta_data.puntos,
            orden=pregunta_data.orden or i,
            opcion_a=pregunta_data.opcion_a,
            opcion_b=pregunta_data.opcion_b,
            opcion_c=pregunta_data.opcion_c,
            opcion_d=pregunta_data.opcion_d,
            opcion_e=pregunta_data.opcion_e,
            respuesta_correcta=pregunta_data.respuesta_correcta,
            afirmaciones=[a.model_dump() for a in pregunta_data.afirmaciones] if pregunta_data.afirmaciones else None,
            columna_a=pregunta_data.columna_a,
            columna_b=pregunta_data.columna_b,
            elementos=pregunta_data.elementos,
            segmentos=[s.model_dump() for s in pregunta_data.segmentos] if pregunta_data.segmentos else None,
            frases=[f.model_dump() for f in pregunta_data.frases] if pregunta_data.frases else None,
            respuesta_corta=pregunta_data.respuesta_corta,
            respuestas_alternativas=pregunta_data.respuestas_alternativas,
            longitud_minima=pregunta_data.longitud_minima,
            rubrica=pregunta_data.rubrica,
        )
        db.add(pregunta)
    
    db.commit()
    db.refresh(examen)
    return examen


@router.delete("/{examen_id}", response_model=MensajeResponse)
def eliminar_examen(examen_id: str, db: Session = Depends(get_db)):
    """Elimina un examen y sus preguntas asociadas"""
    examen = db.query(Examen).filter(Examen.id == examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    
    db.delete(examen)
    db.commit()
    return {"mensaje": "Examen eliminado correctamente", "ok": True}


@router.put("/{examen_id}/estado", response_model=MensajeResponse)
def cambiar_estado_examen(
    examen_id: str,
    estado: str = Query(..., regex="^(BORRADOR|PUBLICADO|CERRADO)$"),
    db: Session = Depends(get_db)
):
    """Cambia el estado de un examen"""
    examen = db.query(Examen).filter(Examen.id == examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    
    examen.estado = estado
    examen.updated_at = datetime.now(timezone.utc)
    db.commit()
    
    mensajes = {
        'PUBLICADO': 'Examen publicado correctamente',
        'CERRADO': 'Examen cerrado correctamente',
        'BORRADOR': 'Examen vuelto a borrador'
    }
    return {"mensaje": mensajes.get(estado, 'Estado actualizado'), "ok": True}


# =============================================
# RESULTADOS
# =============================================

@router.post("/resultados", response_model=ResultadoResponse, status_code=201)
def guardar_resultado(data: ResultadoCreate, db: Session = Depends(get_db)):
    """Guarda el resultado de un examen rendido"""
    examen = db.query(Examen).filter(Examen.id == data.examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    
    # Verificar intentos del alumno
    if examen.intentos_permitidos > 0:
        intentos_actuales = db.query(ResultadoExamen).filter(
            ResultadoExamen.examen_id == data.examen_id,
            ResultadoExamen.alumno_id == data.alumno_id
        ).count()
        
        if intentos_actuales >= examen.intentos_permitidos:
            raise HTTPException(status_code=400, detail="Ya alcanzó el límite de intentos permitidos")
    
    resultado = ResultadoExamen(
        id=str(uuid.uuid4()),
        examen_id=data.examen_id,
        alumno_id=data.alumno_id,
        alumno_nombre=data.alumno_nombre,
        alumno_grado=data.alumno_grado,
        alumno_dni=data.alumno_dni,
        respuestas=data.respuestas,
        calificacion=data.calificacion,
        correctas=data.correctas,
        total_preguntas=data.total_preguntas,
        puntos_obtenidos=data.puntos_obtenidos,
        total_puntos=data.total_puntos,
        tiempo_usado=data.tiempo_usado,
        tiempo_restante=data.tiempo_restante,
        violaciones=data.violaciones,
        eventos_seguridad=data.eventos_seguridad,
        entregado_por_tiempo=data.entregado_por_tiempo,
        estado=data.estado
    )
    db.add(resultado)
    db.commit()
    db.refresh(resultado)
    return resultado


@router.get("/resultados/{examen_id}", response_model=List[ResultadoResponse])
def listar_resultados(examen_id: str, db: Session = Depends(get_db)):
    """Lista todos los resultados de un examen"""
    return db.query(ResultadoExamen).filter(
        ResultadoExamen.examen_id == examen_id
    ).order_by(ResultadoExamen.entregado_en.desc()).all()


@router.delete("/resultados/{examen_id}", response_model=MensajeResponse)
def limpiar_resultados(examen_id: str, db: Session = Depends(get_db)):
    """Elimina todos los resultados de un examen"""
    db.query(ResultadoExamen).filter(ResultadoExamen.examen_id == examen_id).delete()
    db.commit()
    return {"mensaje": "Resultados eliminados correctamente", "ok": True}