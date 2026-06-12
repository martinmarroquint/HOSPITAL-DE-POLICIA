# backend/app/api/v1/cartera.py
# VERSIÓN FINAL - CON SELECTOR DE MES EN PORTAL PÚBLICO
from fastapi import APIRouter, Depends, UploadFile, File, Form, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from uuid import UUID
from datetime import date, timedelta
import os
import json
import time

from app.database import get_db
from app.models.cartera import Especialidad, Programacion, CargaExcel
from app.services.excel_parser import ExcelParserService
from app.schemas.cartera import EspecialidadResponse, MedicoResponse

router = APIRouter(tags=["Cartera de Servicios"])

UPLOAD_DIR = "uploads/cartera"
os.makedirs(UPLOAD_DIR, exist_ok=True)


def _get_semana(mes: Optional[int] = None, anio: Optional[int] = None):
    """Calcula lunes y domingo de la semana actual o del mes indicado"""
    hoy = date.today()
    
    if mes and anio:
        # Buscar el primer día del mes que tenga programaciones
        inicio_mes = date(anio, mes, 1)
        fin_mes = date(anio, mes + 1, 1) if mes < 12 else date(anio + 1, 1, 1)
        return inicio_mes, fin_mes
    else:
        lunes = hoy - timedelta(days=hoy.weekday())
        domingo = lunes + timedelta(days=6)
        return lunes, domingo


# =====================================================
# PORTAL PUBLICO
# =====================================================

@router.get("/especialidades", response_model=List[EspecialidadResponse])
async def listar_especialidades(
    mes: Optional[int] = Query(None),
    anio: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Lista especialidades con medicos disponibles. Si se especifica mes/anio, muestra todo el mes."""
    inicio, fin = _get_semana(mes, anio)
    
    especialidades = db.query(Especialidad).filter(Especialidad.activo == True).all()
    
    resultado = []
    for esp in especialidades:
        count = db.query(Programacion.medico_dni).filter(
            Programacion.especialidad_id == esp.id,
            Programacion.fecha >= inicio,
            Programacion.fecha <= fin
        ).distinct().count()
        
        if count > 0:
            resultado.append({
                'id': esp.id,
                'nombre': esp.nombre,
                'total_medicos': count
            })
    
    return resultado


@router.get("/especialidades/{especialidad_id}/medicos", response_model=List[MedicoResponse])
async def listar_medicos(
    especialidad_id: UUID,
    mes: Optional[int] = Query(None),
    anio: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    """Lista medicos de una especialidad con horarios. Si se especifica mes/anio, muestra todo el mes."""
    inicio, fin = _get_semana(mes, anio)
    
    programaciones = db.query(Programacion).filter(
        Programacion.especialidad_id == especialidad_id,
        Programacion.fecha >= inicio,
        Programacion.fecha <= fin
    ).order_by(Programacion.medico_nombre, Programacion.fecha).all()
    
    medicos = {}
    for prog in programaciones:
        if prog.medico_dni not in medicos:
            medicos[prog.medico_dni] = {
                'medico_dni': prog.medico_dni,
                'medico_nombre': prog.medico_nombre,
                'horarios': []
            }
        medicos[prog.medico_dni]['horarios'].append({
            'fecha': prog.fecha.isoformat() if isinstance(prog.fecha, date) else str(prog.fecha),
            'dia': prog.dia,
            'dia_semana': prog.dia_semana,
            'turno': prog.turno,
            'turno_texto': prog.turno_texto
        })
    
    return list(medicos.values())


# =====================================================
# PANEL ADMIN
# =====================================================

@router.post("/cargar-excel")
async def cargar_excel(
    archivo: UploadFile = File(...),
    mes: int = Form(...),
    anio: int = Form(...)
):
    """Valida un Excel de programacion medica sin guardar"""
    if not archivo.filename or not archivo.filename.endswith(('.xlsx', '.xls')):
        raise HTTPException(status_code=400, detail="Formato no permitido")
    
    file_path = os.path.join(UPLOAD_DIR, f"temp_{archivo.filename}")
    
    try:
        with open(file_path, "wb") as f:
            content = await archivo.read()
            f.write(content)
        
        parser = ExcelParserService()
        resultado = parser.procesar(file_path, mes, anio)
        
        return {
            'especialidades': resultado.get('especialidades', []),
            'total_medicos': resultado.get('total_medicos', 0),
            'total_especialidades': resultado.get('total_especialidades', 0),
            'total_registros': resultado.get('total_registros', 0),
            'total_errores': resultado.get('total_errores', 0),
            'errores': resultado.get('errores', []),
            'advertencias': resultado.get('advertencias', []),
            'programaciones': resultado.get('programaciones', [])
        }
        
    except Exception as e:
        return {
            'especialidades': [],
            'total_medicos': 0,
            'total_especialidades': 0,
            'total_registros': 0,
            'total_errores': 1,
            'errores': [{'tipo': 'error', 'mensaje': str(e)}],
            'advertencias': [],
            'programaciones': []
        }
    finally:
        time.sleep(0.5)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
        except PermissionError:
            pass


@router.post("/guardar-programacion")
async def guardar_programacion(
    archivo: UploadFile = File(...),
    mes: int = Form(...),
    anio: int = Form(...),
    total_medicos: int = Form(0),
    total_especialidades: int = Form(0),
    total_registros: int = Form(0),
    total_errores: int = Form(0),
    errores: str = Form("[]"),
    especialidades: str = Form("[]"),
    programaciones: str = Form("[]"),
    db: Session = Depends(get_db)
):
    """Guarda la programacion validada y REEMPLAZA el mes completo"""
    try:
        errores_list = json.loads(errores)
        especialidades_list = json.loads(especialidades)
        programaciones_list = json.loads(programaciones)
        
        inicio = date(anio, mes, 1)
        fin = date(anio, mes + 1, 1) if mes < 12 else date(anio + 1, 1, 1)
        
        eliminados = db.query(Programacion).filter(
            Programacion.fecha >= inicio,
            Programacion.fecha < fin
        ).delete()
        
        carga = CargaExcel(
            nombre_archivo=archivo.filename or "programacion.xlsx",
            mes=mes, anio=anio,
            total_medicos=total_medicos,
            total_especialidades=total_especialidades,
            total_registros=total_registros,
            total_errores=total_errores,
            errores=errores_list,
            estado="completado"
        )
        db.add(carga)
        db.flush()
        
        esp_map = {}
        for nombre in especialidades_list:
            esp = db.query(Especialidad).filter(Especialidad.nombre == nombre).first()
            if not esp:
                esp = Especialidad(nombre=nombre)
                db.add(esp)
                db.flush()
            esp_map[nombre] = esp.id
        
        count = 0
        for prog in programaciones_list:
            fecha_str = prog.get('fecha', '')
            try:
                fecha_val = date.fromisoformat(fecha_str)
            except (ValueError, TypeError):
                continue
            
            esp_id = esp_map.get(prog.get('especialidad', ''))
            if not esp_id:
                continue
            
            db.add(Programacion(
                especialidad_id=esp_id,
                medico_dni=str(prog.get('medico_dni', '')),
                medico_nombre=str(prog.get('medico_nombre', '')),
                fecha=fecha_val,
                dia=int(prog.get('dia', 0)),
                dia_semana=str(prog.get('dia_semana', '')),
                turno=str(prog.get('turno', '')),
                turno_texto=str(prog.get('turno_texto', '')),
                carga_id=carga.id
            ))
            count += 1
        
        db.commit()
        
        return {
            "success": True,
            "message": f"Guardado: {count} registros. Se eliminaron {eliminados} anteriores.",
            "carga_id": str(carga.id),
            "registros_nuevos": count,
            "registros_eliminados": eliminados
        }
        
    except json.JSONDecodeError as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"JSON invalido: {str(e)}")
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))