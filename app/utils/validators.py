# app/utils/validators.py
from datetime import date, timedelta
from typing import List, Tuple, Optional, Dict, Any
from sqlalchemy.orm import Session

from app.models.planificacion import Planificacion
from app.models.personal import Personal

def validar_dias_franco_consecutivos(
    db: Session,
    personal_id: str,
    fecha_cambio: date,
    turnos_adicionales: Dict[str, Any] = None
) -> Tuple[bool, str]:
    """
    Valida que un cambio de turno NO genere 3 días libres consecutivos
    Versión corregida para trabajar con el frontend
    
    Args:
        db: Sesión de base de datos
        personal_id: ID del personal
        fecha_cambio: Fecha del cambio (debe ser date object)
        turnos_adicionales: Diccionario con turnos simulados para validación
    
    Returns:
        Tuple[bool, str]: (válido, mensaje)
    """
    try:
        # Asegurar que fecha_cambio sea date object
        if isinstance(fecha_cambio, str):
            fecha_cambio = date.fromisoformat(fecha_cambio)
        
        # Obtener turnos reales de la BD para los días alrededor
        dias_a_verificar = 7  # 3 antes + día del cambio + 3 después
        fecha_inicio = fecha_cambio - timedelta(days=3)
        fecha_fin = fecha_cambio + timedelta(days=3)
        
        # Consultar turnos en la BD
        turnos_db = db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha.between(fecha_inicio, fecha_fin)
        ).all()
        
        # Crear mapa de turnos por fecha
        turnos_map = {}
        for t in turnos_db:
            turnos_map[t.fecha.isoformat()] = t.turno_codigo
        
        # Si hay turnos adicionales (simulados), sobreescribir
        if turnos_adicionales:
            turnos_map.update(turnos_adicionales)
        
        # Verificar días alrededor
        dias = []
        for i in range(-3, 4):  # -3 a +3 días
            fecha_check = fecha_cambio + timedelta(days=i)
            fecha_str = fecha_check.isoformat()
            turno = turnos_map.get(fecha_str)
            
            dias.append({
                "fecha": fecha_str,
                "fecha_formateada": fecha_check.strftime("%d/%m"),
                "turno": turno if turno else "S/T",
                "es_franco": turno == "FR"
            })
        
        # Contar días franco consecutivos
        max_consecutivos = 0
        consecutivos_actuales = 0
        
        for dia in dias:
            if dia["es_franco"]:
                consecutivos_actuales += 1
                max_consecutivos = max(max_consecutivos, consecutivos_actuales)
            else:
                consecutivos_actuales = 0
        
        # Validar
        if max_consecutivos >= 3:
            return False, f"El cambio generaría {max_consecutivos} días libres consecutivos"
        else:
            return True, "Validación de días libres OK"
            
    except Exception as e:
        print(f"Error en validar_dias_franco_consecutivos: {e}")
        return False, str(e)

def validar_disponibilidad_turno(
    db: Session,
    personal_id: str,
    fecha: date
) -> bool:
    """
    Valida si el personal tiene turno asignado en esa fecha
    """
    try:
        if isinstance(fecha, str):
            fecha = date.fromisoformat(fecha)
        
        planificacion = db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.fecha == fecha
        ).first()
        
        # Consideramos válido si tiene turno y no es FR (franco)
        return planificacion is not None and planificacion.turno_codigo not in [None, '', 'FR']
        
    except Exception as e:
        print(f"Error en validar_disponibilidad_turno: {e}")
        return False

def validar_sin_duplicado_dm(
    db: Session,
    personal_id: str,
    fecha_inicio: date,
    fecha_fin: date
) -> Tuple[bool, Optional[str]]:
    """
    Valida que no haya DM activos en el período
    """
    try:
        if isinstance(fecha_inicio, str):
            fecha_inicio = date.fromisoformat(fecha_inicio)
        if isinstance(fecha_fin, str):
            fecha_fin = date.fromisoformat(fecha_fin)
        
        dm_activo = db.query(Planificacion).filter(
            Planificacion.personal_id == personal_id,
            Planificacion.dm_info.isnot(None),
            Planificacion.fecha.between(fecha_inicio, fecha_fin)
        ).first()
        
        if dm_activo:
            return False, "Ya existe un descanso médico en ese período"
        return True, None
        
    except Exception as e:
        print(f"Error en validar_sin_duplicado_dm: {e}")
        return False, str(e)

def validar_limite_dias_dm(dias: int, max_dias: int = 30) -> Tuple[bool, Optional[str]]:
    """
    Valida que los días de DM no excedan el límite
    """
    if dias > max_dias:
        return False, f"El descanso médico no puede exceder {max_dias} días"
    return True, None