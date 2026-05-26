# backend/app/services/validador.py
from typing import List, Dict, Any, Optional
from app.services.dto import ErrorValidacionDTO

class ValidadorServicio:
    """Valida datos extraidos del Excel"""
    
    @classmethod
    def validar_medico(
        cls, fila: List[str], numero_fila: int
    ) -> List[ErrorValidacionDTO]:
        errores = []
        
        if len(fila) < 3:
            errores.append(ErrorValidacionDTO(
                tipo='fila_incompleta',
                mensaje=f'Fila {numero_fila} incompleta',
                fila=numero_fila
            ))
            return errores
        
        dni = fila[1].strip() if len(fila) > 1 else ''
        nombre = fila[2].strip() if len(fila) > 2 else ''
        
        if not dni or not dni.isdigit():
            errores.append(ErrorValidacionDTO(
                tipo='dni_invalido',
                mensaje=f'DNI invalido en fila {numero_fila}: {dni}',
                fila=numero_fila
            ))
        
        if len(dni) < 7:
            errores.append(ErrorValidacionDTO(
                tipo='dni_corto',
                mensaje=f'DNI demasiado corto en fila {numero_fila}',
                fila=numero_fila
            ))
        
        if not nombre:
            errores.append(ErrorValidacionDTO(
                tipo='nombre_vacio',
                mensaje=f'Nombre vacio en fila {numero_fila}',
                fila=numero_fila
            ))
        
        return errores
    
    @classmethod
    def validar_turno(
        cls, valor: str, medico: str, dia: int, fila: int
    ) -> Optional[ErrorValidacionDTO]:
        from app.services.normalizador import NormalizadorServicio
        
        turno = NormalizadorServicio.normalizar_turno(valor)
        
        if not turno and valor:
            return ErrorValidacionDTO(
                tipo='turno_invalido',
                mensaje=f'Turno invalido "{valor}" para {medico} dia {dia}',
                medico=medico,
                dia=dia,
                valor=valor,
                fila=fila
            )
        
        return None