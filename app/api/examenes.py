# back/app/api/examenes.py
# VERSION COMPLETA FINAL - CON GRUPOS + SINCRONIZACION QR + FILTRO GRUPO_ID + BACKEND CALCULA LA NOTA

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
import uuid
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.models.examen import Examen
from app.models.pregunta import Pregunta
from app.models.resultado_examen import ResultadoExamen
from app.models.alumno_examen import AlumnoExamen
from app.models.grupo import Grupo
from app.schemas.examenes import (
    ExamenCreate, ExamenUpdate, ExamenResponse, ExamenDetailResponse,
    PreguntaCreate, PreguntaResponse,
    ResultadoCreate, ResultadoResponse,
    MensajeResponse,
    AlumnoGrupoSchema, AsistenciaGrupoSchema, GrupoCreate, GrupoUpdate, GrupoResponse
)

router = APIRouter()

# Constante para expiración del QR
QR_EXPIRATION_SECONDS = 30


# =============================================
# UTILIDAD
# =============================================
def generar_codigo():
    ahora = datetime.now(timezone.utc)
    r = str(uuid.uuid4().int)[:4]
    return f"EXA-{ahora.year}{str(ahora.month).zfill(2)}{str(ahora.day).zfill(2)}-{r.zfill(4)}"


# =============================================
# GRUPOS
# =============================================

@router.get("/grupos", response_model=List[GrupoResponse])
def listar_grupos(
    docente_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Lista todos los grupos"""
    query = db.query(Grupo)
    if docente_id:
        query = query.filter(Grupo.docente_id == docente_id)
    return query.order_by(Grupo.created_at.desc()).all()


@router.post("/grupos", response_model=GrupoResponse, status_code=201)
def crear_grupo(data: GrupoCreate, db: Session = Depends(get_db)):
    """Crea un nuevo grupo"""
    grupo = Grupo(
        id=str(uuid.uuid4()),
        nombre=data.nombre,
        docente_id=data.docente_id,
        alumnos=[],
        asistencias=[],
        recursos=[]
    )
    db.add(grupo)
    db.commit()
    db.refresh(grupo)
    return grupo


@router.get("/grupos/{grupo_id}", response_model=GrupoResponse)
def obtener_grupo(grupo_id: str, db: Session = Depends(get_db)):
    """Obtiene un grupo específico"""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return grupo


@router.put("/grupos/{grupo_id}", response_model=GrupoResponse)
def actualizar_grupo(grupo_id: str, data: GrupoUpdate, db: Session = Depends(get_db)):
    """Actualiza un grupo (alumnos, asistencias, recursos, etc.)"""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    if data.nombre is not None:
        grupo.nombre = data.nombre
    if data.alumnos is not None:
        grupo.alumnos = data.alumnos
    if data.asistencias is not None:
        grupo.asistencias = data.asistencias
    if data.recursos is not None:
        grupo.recursos = data.recursos
    
    grupo.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(grupo)
    return grupo


@router.delete("/grupos/{grupo_id}", response_model=MensajeResponse)
def eliminar_grupo(grupo_id: str, db: Session = Depends(get_db)):
    """Elimina un grupo"""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    db.delete(grupo)
    db.commit()
    return {"mensaje": "Grupo eliminado", "ok": True}


@router.post("/grupos/{grupo_id}/asistencia", response_model=MensajeResponse)
def guardar_asistencia(grupo_id: str, data: List[AsistenciaGrupoSchema], db: Session = Depends(get_db)):
    """Guarda la asistencia de un grupo para una fecha"""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    fecha_actual = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    asistencias_actuales = grupo.asistencias or []
    asistencias_actuales = [a for a in asistencias_actuales if a.get('fecha') != fecha_actual]
    
    nuevas = [a.model_dump() for a in data]
    grupo.asistencias = asistencias_actuales + nuevas
    grupo.updated_at = datetime.now(timezone.utc)
    
    db.commit()
    return {"mensaje": "Asistencia guardada", "total": len(nuevas), "ok": True}


# =============================================
# RECURSOS DEL GRUPO (CARPETA DOCENTE)
# =============================================

@router.post("/grupos/{grupo_id}/recursos")
def agregar_recurso_grupo(grupo_id: str, data: dict, db: Session = Depends(get_db)):
    """Agrega un recurso (link, PDF, etc.) a la carpeta del grupo"""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    recurso = {
        "id": str(uuid.uuid4()),
        "nombre": data.get("nombre", "Sin nombre"),
        "tipo": data.get("tipo", "link"),
        "url": data.get("url", ""),
        "descripcion": data.get("descripcion", ""),
        "fecha": datetime.now(timezone.utc).isoformat()
    }
    
    recursos = grupo.recursos or []
    recursos.append(recurso)
    grupo.recursos = recursos
    grupo.updated_at = datetime.now(timezone.utc)
    db.commit()
    
    return {"mensaje": "Recurso agregado", "recurso": recurso, "ok": True}


@router.get("/grupos/{grupo_id}/recursos")
def listar_recursos_grupo(grupo_id: str, db: Session = Depends(get_db)):
    """Lista los recursos de un grupo"""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    return grupo.recursos or []


@router.delete("/grupos/{grupo_id}/recursos/{recurso_id}")
def eliminar_recurso_grupo(grupo_id: str, recurso_id: str, db: Session = Depends(get_db)):
    """Elimina un recurso de un grupo"""
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    recursos = grupo.recursos or []
    grupo.recursos = [r for r in recursos if r.get("id") != recurso_id]
    grupo.updated_at = datetime.now(timezone.utc)
    db.commit()
    
    return {"mensaje": "Recurso eliminado", "ok": True}


# =============================================
# SINCRONIZACIÓN CARPETA DOCENTE (QR)
# =============================================

@router.post("/sincronizar/iniciar")
def iniciar_sesion_carpeta(data: dict, db: Session = Depends(get_db)):
    """PC inicia sesión de Carpeta Docente"""
    session_id = data.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id requerido")
    
    return {
        "session_id": session_id,
        "estado": "ESPERANDO",
        "expiracion": (datetime.now(timezone.utc) + timedelta(seconds=QR_EXPIRATION_SECONDS)).isoformat(),
        "mensaje": "Sesion iniciada. Esperando escaneo del celular..."
    }


@router.get("/sincronizar/estado/{session_id}")
def consultar_estado_carpeta(session_id: str, db: Session = Depends(get_db)):
    """PC consulta si el celular ya vinculó un grupo"""
    grupo = db.query(Grupo).filter(
        Grupo.session_activo == session_id
    ).first()
    
    if grupo:
        return {
            "sincronizado": True,
            "estado": "VINCULADO",
            "carpeta": {
                "id": grupo.id,
                "nombre": grupo.nombre,
                "docente": grupo.docente_id or "Docente",
                "color": "#4F46E5",
                "recursos": grupo.recursos or []
            }
        }
    
    return {"sincronizado": False, "estado": "ESPERANDO"}


@router.get("/sincronizar/escanear/{session_id}")
def escanear_qr(session_id: str, db: Session = Depends(get_db)):
    """Celular escanea el QR. Retorna grupos disponibles"""
    grupos = db.query(Grupo).order_by(Grupo.created_at.desc()).all()
    
    return {
        "session_id": session_id,
        "estado": "ESCANEADO",
        "grupos_disponibles": [
            {
                "id": g.id,
                "nombre": g.nombre,
                "total_alumnos": len(g.alumnos or []),
                "total_recursos": len(g.recursos or []),
                "total_examenes": 0
            }
            for g in grupos
        ]
    }


@router.post("/sincronizar/vincular")
def vincular_grupo_carpeta(data: dict, db: Session = Depends(get_db)):
    """Celular selecciona un grupo para proyectar en la PC"""
    session_id = data.get("session_id")
    grupo_id = data.get("grupo_id")
    
    if not session_id or not grupo_id:
        raise HTTPException(status_code=400, detail="session_id y grupo_id requeridos")
    
    grupo = db.query(Grupo).filter(Grupo.id == grupo_id).first()
    if not grupo:
        raise HTTPException(status_code=404, detail="Grupo no encontrado")
    
    db.query(Grupo).filter(Grupo.session_activo == session_id).update({"session_activo": None})
    
    grupo.session_activo = session_id
    db.commit()
    
    return {
        "success": True,
        "mensaje": f"Grupo '{grupo.nombre}' vinculado correctamente",
        "grupo": {
            "id": grupo.id,
            "nombre": grupo.nombre,
            "docente": grupo.docente_id or "Docente",
            "color": "#4F46E5",
            "recursos": grupo.recursos or []
        }
    }


@router.delete("/sincronizar/cerrar/{session_id}")
def cerrar_sesion_carpeta(session_id: str, db: Session = Depends(get_db)):
    """Cierra la sesión de Carpeta Docente"""
    grupo = db.query(Grupo).filter(
        Grupo.session_activo == session_id
    ).first()
    
    if grupo:
        grupo.session_activo = None
        db.commit()
    
    return {"success": True, "mensaje": "Sesion cerrada correctamente"}


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
    """Busca alumnos por nombre, apellido o DNI"""
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
# RESULTADOS
# =============================================

@router.post("/resultados", response_model=ResultadoResponse, status_code=201)
def guardar_resultado(data: ResultadoCreate, db: Session = Depends(get_db)):
    """Guarda el resultado - EL BACKEND CALCULA LA NOTA"""
    examen = db.query(Examen).filter(Examen.id == data.examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    
    if examen.intentos_permitidos > 0:
        intentos_actuales = db.query(ResultadoExamen).filter(
            ResultadoExamen.examen_id == data.examen_id,
            ResultadoExamen.alumno_id == data.alumno_id
        ).count()
        if intentos_actuales >= examen.intentos_permitidos:
            raise HTTPException(status_code=400, detail="Limite de intentos alcanzado")
    
    preguntas = db.query(Pregunta).filter(
        Pregunta.examen_id == data.examen_id
    ).order_by(Pregunta.orden).all()
    
    total_puntos = 0
    puntos_obtenidos = 0
    correctas_reales = 0
    respuestas_alumno = data.respuestas or {}
    
    for i, pregunta in enumerate(preguntas):
        respuesta = respuestas_alumno.get(str(i))
        pts = pregunta.puntos if pregunta.puntos is not None else 0
        total_puntos += pts
        pregunta_correcta = False
        
        if pregunta.tipo == 'opcion_multiple':
            if respuesta is not None and respuesta == pregunta.respuesta_correcta:
                puntos_obtenidos += pts
                pregunta_correcta = True
                
        elif pregunta.tipo == 'verdadero_falso':
            if isinstance(respuesta, list) and pregunta.afirmaciones and len(pregunta.afirmaciones) > 0:
                correctas = sum(1 for j, af in enumerate(pregunta.afirmaciones) 
                    if j < len(respuesta) and respuesta[j] == af.get('esVerdadero', False))
                proporcion = correctas / len(pregunta.afirmaciones)
                puntos_obtenidos += round(proporcion * pts, 2)
                pregunta_correcta = (correctas == len(pregunta.afirmaciones))
                
        elif pregunta.tipo == 'relacionar':
            if isinstance(respuesta, dict) and pregunta.columna_a:
                total_pares = len([a for a in pregunta.columna_a if a and a.strip()])
                if total_pares > 0:
                    correctas = sum(1 for j in range(total_pares) 
                        if str(j) in respuesta and respuesta[str(j)] == j)
                    proporcion = correctas / total_pares
                    puntos_obtenidos += round(proporcion * pts, 2)
                    pregunta_correcta = (correctas == total_pares)
                    
        elif pregunta.tipo == 'completar':
            if pregunta.frases and isinstance(respuesta, list):
                espacios = []
                for frase in pregunta.frases:
                    for seg in (frase.get('segmentos') or []):
                        if seg.get('tipo') == 'espacio':
                            espacios.append(seg.get('respuesta', ''))
                if espacios:
                    correctas = sum(1 for j, esp in enumerate(espacios)
                        if j < len(respuesta) and str(respuesta[j] or '').lower().strip() == esp.lower().strip())
                    proporcion = correctas / len(espacios)
                    puntos_obtenidos += round(proporcion * pts, 2)
                    pregunta_correcta = (correctas == len(espacios))
                    
        elif pregunta.tipo == 'ordenamiento':
            if isinstance(respuesta, list) and pregunta.elementos:
                total_elem = len([e for e in pregunta.elementos if e and e.strip()])
                if total_elem > 0:
                    correctas = sum(1 for j in range(total_elem) 
                        if j < len(respuesta) and respuesta[j] == j + 1)
                    proporcion = correctas / total_elem
                    puntos_obtenidos += round(proporcion * pts, 2)
                    pregunta_correcta = (correctas == total_elem)
                    
        elif pregunta.tipo == 'respuesta_corta':
            respuestas_aceptadas = [pregunta.respuesta_corta or '']
            if pregunta.respuestas_alternativas:
                respuestas_aceptadas.extend(pregunta.respuestas_alternativas)
            if str(respuesta or '').lower().strip() in [r.lower().strip() for r in respuestas_aceptadas if r]:
                puntos_obtenidos += pts
                pregunta_correcta = True
                
        elif pregunta.tipo == 'ensayo':
            pass
        
        if pregunta_correcta:
            correctas_reales += 1
    
    calificacion = round((puntos_obtenidos / total_puntos * 100), 2) if total_puntos > 0 else 0
    estado_final = data.estado or 'COMPLETADO'
    
    if data.violaciones and data.violaciones >= 3:
        estado_final = 'TRAMPA'
        calificacion = 0
        puntos_obtenidos = 0
        correctas_reales = 0
    
    resultado = ResultadoExamen(
        id=str(uuid.uuid4()),
        examen_id=data.examen_id,
        alumno_id=data.alumno_id,
        alumno_nombre=data.alumno_nombre,
        alumno_grado=data.alumno_grado,
        alumno_dni=data.alumno_dni,
        respuestas=data.respuestas,
        calificacion=calificacion,
        correctas=correctas_reales,
        total_preguntas=len(preguntas),
        puntos_obtenidos=round(puntos_obtenidos, 2),
        total_puntos=total_puntos,
        tiempo_usado=data.tiempo_usado or 0,
        tiempo_restante=data.tiempo_restante or 0,
        violaciones=data.violaciones or 0,
        eventos_seguridad=data.eventos_seguridad,
        entregado_por_tiempo=data.entregado_por_tiempo or False,
        estado=estado_final
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
    return {"mensaje": "Resultados eliminados", "ok": True}


@router.delete("/resultados/{examen_id}/{alumno_id}", response_model=MensajeResponse)
def eliminar_resultado_alumno(examen_id: str, alumno_id: str, db: Session = Depends(get_db)):
    """Reinicia el intento de un alumno"""
    eliminados = db.query(ResultadoExamen).filter(
        ResultadoExamen.examen_id == examen_id,
        ResultadoExamen.alumno_id == alumno_id
    ).delete()
    db.commit()
    if eliminados > 0:
        return {"mensaje": "Intento reiniciado", "ok": True}
    raise HTTPException(status_code=404, detail="No se encontro resultado")


# =============================================
# EXAMENES
# =============================================

@router.get("/", response_model=List[ExamenResponse])
def listar_examenes(
    estado: Optional[str] = Query(None),
    busqueda: Optional[str] = Query(None),
    grupo_id: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Lista todos los examenes con filtros opcionales"""
    query = db.query(Examen)
    if estado:
        query = query.filter(Examen.estado == estado)
    if busqueda:
        query = query.filter(
            (Examen.titulo.ilike(f"%{busqueda}%")) |
            (Examen.codigo.ilike(f"%{busqueda}%"))
        )
    if grupo_id:
        query = query.filter(Examen.grupo_id == grupo_id)
    return query.order_by(Examen.created_at.desc()).all()


@router.get("/publicados", response_model=List[ExamenResponse])
def listar_examenes_publicados(db: Session = Depends(get_db)):
    """Lista solo examenes publicados"""
    return db.query(Examen).filter(Examen.estado == 'PUBLICADO').order_by(Examen.created_at.desc()).all()


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
        estado='BORRADOR',
        grupo_id=data.grupo_id
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
    """Actualiza un examen existente y sus preguntas"""
    examen = db.query(Examen).filter(Examen.id == examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    
    examen.titulo = data.titulo
    examen.descripcion = data.descripcion
    examen.tiempo_limite = data.tiempo_limite
    examen.puntaje_aprobacion = data.puntaje_aprobacion
    if data.configuracion:
        examen.configuracion = data.configuracion.model_dump()
    if data.intentos_permitidos is not None:
        examen.intentos_permitidos = data.intentos_permitidos
    if data.grupo_id is not None:
        examen.grupo_id = data.grupo_id
    examen.updated_at = datetime.now(timezone.utc)
    
    db.query(Pregunta).filter(Pregunta.examen_id == examen_id).delete()
    
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
    """Elimina un examen"""
    examen = db.query(Examen).filter(Examen.id == examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    db.delete(examen)
    db.commit()
    return {"mensaje": "Examen eliminado", "ok": True}


@router.put("/{examen_id}/estado", response_model=MensajeResponse)
def cambiar_estado_examen(
    examen_id: str,
    estado: str = Query(..., pattern="^(BORRADOR|PUBLICADO|CERRADO)$"),
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
        'PUBLICADO': 'Examen publicado',
        'CERRADO': 'Examen cerrado',
        'BORRADOR': 'Examen vuelto a borrador'
    }
    return {"mensaje": mensajes.get(estado, 'Estado actualizado'), "ok": True}


# =============================================
# RUTA DINAMICA - SIEMPRE AL FINAL
# =============================================

@router.get("/{examen_id}", response_model=ExamenDetailResponse)
def obtener_examen(examen_id: str, db: Session = Depends(get_db)):
    """Obtiene un examen con todas sus preguntas"""
    examen = db.query(Examen).filter(Examen.id == examen_id).first()
    if not examen:
        raise HTTPException(status_code=404, detail="Examen no encontrado")
    return examen


@router.get("/resultados/{examen_id}/revision/{resultado_id}")
def obtener_revision(examen_id: str, resultado_id: str, db: Session = Depends(get_db)):
    """Devuelve el detalle de revision"""
    resultado = db.query(ResultadoExamen).filter(
        ResultadoExamen.id == resultado_id,
        ResultadoExamen.examen_id == examen_id
    ).first()
    
    if not resultado:
        raise HTTPException(status_code=404, detail="Resultado no encontrado")
    
    preguntas = db.query(Pregunta).filter(
        Pregunta.examen_id == examen_id
    ).order_by(Pregunta.orden).all()
    
    detalle = []
    respuestas_alumno = resultado.respuestas or {}
    
    for i, pregunta in enumerate(preguntas):
        respuesta = respuestas_alumno.get(str(i))
        item = {
            "numero": i + 1, "tipo": pregunta.tipo, "enunciado": pregunta.enunciado,
            "puntos": pregunta.puntos or 0, "respuesta_alumno": respuesta,
            "correcta": False, "puntos_obtenidos": 0, "detalle": {}
        }
        
        if pregunta.tipo == 'opcion_multiple':
            item["opciones"] = {"A": pregunta.opcion_a, "B": pregunta.opcion_b, "C": pregunta.opcion_c, "D": pregunta.opcion_d, "E": pregunta.opcion_e}
            item["respuesta_correcta"] = pregunta.respuesta_correcta
            item["correcta"] = (respuesta == pregunta.respuesta_correcta)
            item["puntos_obtenidos"] = pregunta.puntos if item["correcta"] else 0
            
        elif pregunta.tipo == 'verdadero_falso':
            afirmaciones = []
            for j, af in enumerate(pregunta.afirmaciones or []):
                resp_af = respuesta[j] if isinstance(respuesta, list) and j < len(respuesta) else None
                afirmaciones.append({
                    "texto": af.get("texto", ""), "respuesta_alumno": resp_af,
                    "respuesta_correcta": af.get("esVerdadero", False),
                    "correcta": resp_af == af.get("esVerdadero", False)
                })
            item["afirmaciones"] = afirmaciones
            correctas = sum(1 for a in afirmaciones if a["correcta"])
            item["correcta"] = correctas == len(afirmaciones)
            item["puntos_obtenidos"] = round((correctas / len(afirmaciones)) * pregunta.puntos, 2) if afirmaciones else 0
            
        elif pregunta.tipo == 'relacionar':
            pares = []
            col_a = [a for a in (pregunta.columna_a or []) if a and a.strip()]
            col_b = [b for b in (pregunta.columna_b or []) if b and b.strip()]
            for j in range(len(col_a)):
                resp_par = respuesta.get(str(j)) if isinstance(respuesta, dict) else None
                pares.append({
                    "elemento_a": col_a[j],
                    "respuesta_alumno": col_b[resp_par] if resp_par is not None and resp_par < len(col_b) else "Sin responder",
                    "respuesta_correcta": col_b[j], "correcta": resp_par == j
                })
            item["pares"] = pares
            correctas = sum(1 for p in pares if p["correcta"])
            item["correcta"] = correctas == len(pares)
            item["puntos_obtenidos"] = round((correctas / len(pares)) * pregunta.puntos, 2) if pares else 0
            
        elif pregunta.tipo == 'completar':
            espacios = []
            espacio_idx = 0
            for frase in (pregunta.frases or []):
                for seg in (frase.get("segmentos") or []):
                    if seg.get("tipo") == "espacio":
                        resp_esp = respuesta[espacio_idx] if isinstance(respuesta, list) and espacio_idx < len(respuesta) else ""
                        espacios.append({
                            "texto_anterior": "", "respuesta_alumno": resp_esp,
                            "respuesta_correcta": seg.get("respuesta", ""),
                            "correcta": str(resp_esp or "").lower().strip() == str(seg.get("respuesta", "")).lower().strip()
                        })
                        espacio_idx += 1
            item["espacios"] = espacios
            correctas = sum(1 for e in espacios if e["correcta"])
            item["correcta"] = correctas == len(espacios)
            item["puntos_obtenidos"] = round((correctas / len(espacios)) * pregunta.puntos, 2) if espacios else 0
            
        elif pregunta.tipo == 'ordenamiento':
            elementos = [e for e in (pregunta.elementos or []) if e and e.strip()]
            posiciones = []
            for j in range(len(elementos)):
                resp_pos = respuesta[j] if isinstance(respuesta, list) and j < len(respuesta) else None
                posiciones.append({
                    "elemento": elementos[j], "posicion_alumno": resp_pos,
                    "posicion_correcta": j + 1, "correcta": resp_pos == j + 1
                })
            item["posiciones"] = posiciones
            correctas = sum(1 for p in posiciones if p["correcta"])
            item["correcta"] = correctas == len(posiciones)
            item["puntos_obtenidos"] = round((correctas / len(posiciones)) * pregunta.puntos, 2) if posiciones else 0
            
        elif pregunta.tipo == 'respuesta_corta':
            aceptadas = [pregunta.respuesta_corta or ""]
            if pregunta.respuestas_alternativas: aceptadas.extend(pregunta.respuestas_alternativas)
            item["respuesta_correcta"] = pregunta.respuesta_corta
            item["respuestas_aceptadas"] = [r for r in aceptadas if r]
            item["correcta"] = str(respuesta or "").lower().strip() in [r.lower().strip() for r in aceptadas if r]
            item["puntos_obtenidos"] = pregunta.puntos if item["correcta"] else 0
            
        elif pregunta.tipo == 'ensayo':
            item["longitud_minima"] = pregunta.longitud_minima
            item["correcta"] = None
            item["puntos_obtenidos"] = 0
            item["detalle"]["nota"] = "Las preguntas de ensayo no se califican automaticamente"
        
        detalle.append(item)
    
    return {
        "resultado_id": resultado.id, "alumno_nombre": resultado.alumno_nombre,
        "calificacion": resultado.calificacion, "correctas": resultado.correctas,
        "total_preguntas": resultado.total_preguntas, "puntos_obtenidos": resultado.puntos_obtenidos,
        "total_puntos": resultado.total_puntos, "estado": resultado.estado, "detalle": detalle
    }