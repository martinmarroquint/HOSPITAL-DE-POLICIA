# backend/app/services/normalizador.py
import re
from typing import Optional

class NormalizadorServicio:
    """Limpia y normaliza datos del Excel"""
    
    TURNOS_VALIDOS = {'M', 'T', 'MT', 'TM'}
    
    TURNO_TEXTO = {
        'M': 'Manana',
        'T': 'Tarde',
        'MT': 'Manana y Tarde',
    }
    
    DIAS_SEMANA_VALIDOS = {
        'LUNES', 'MARTES', 'MIERCOLES', 'JUEVES',
        'VIERNES', 'SABADO', 'DOMINGO',
        'LUN', 'MAR', 'MIE', 'JUE', 'VIE', 'SAB', 'DOM'
    }
    
    DIAS_SEMANA_CANONICOS = {
        'LUNES': 'LUNES', 'LUN': 'LUNES',
        'MARTES': 'MARTES', 'MAR': 'MARTES',
        'MIERCOLES': 'MIERCOLES', 'MIE': 'MIERCOLES',
        'JUEVES': 'JUEVES', 'JUE': 'JUEVES',
        'VIERNES': 'VIERNES', 'VIE': 'VIERNES',
        'SABADO': 'SABADO', 'SAB': 'SABADO',
        'DOMINGO': 'DOMINGO', 'DOM': 'DOMINGO'
    }
    
    @classmethod
    def limpiar_valor(cls, valor: str) -> str:
        """Elimina espacios, caracteres invisibles y convierte a mayusculas"""
        if not valor:
            return ''
        valor = re.sub(r'\s+', '', str(valor))
        valor = valor.strip().upper()
        return valor
    
    @classmethod
    def normalizar_turno(cls, valor: str) -> Optional[str]:
        """Normaliza un valor de turno a M, T o MT"""
        valor = cls.limpiar_valor(valor)
        
        if not valor:
            return None
        
        if valor in cls.TURNOS_VALIDOS:
            return 'MT' if valor in ('MT', 'TM') else valor
        
        return None
    
    @classmethod
    def obtener_texto_turno(cls, turno: str) -> str:
        """Obtiene texto legible del turno"""
        return cls.TURNO_TEXTO.get(turno, '')
    
    @classmethod
    def normalizar_dia_semana(cls, valor: str) -> Optional[str]:
        """Normaliza nombre de dia de la semana"""
        valor = cls.limpiar_valor(valor)
        return cls.DIAS_SEMANA_CANONICOS.get(valor)
    
    @classmethod
    def es_dia_semana_valido(cls, valor: str) -> bool:
        """Verifica si un valor es un dia de la semana valido"""
        return cls.limpiar_valor(valor) in cls.DIAS_SEMANA_VALIDOS