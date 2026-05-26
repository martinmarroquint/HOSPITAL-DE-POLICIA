# backend/app/services/excel_parser.py
import pandas as pd
import calendar
from datetime import date
from typing import Dict, List, Any, Optional, Set
import re
import openpyxl

from app.core.logger import setup_logger
from app.services.normalizador import NormalizadorServicio

logger = setup_logger(__name__)


class ExcelParserService:
    """
    Parser inteligente para Excel de programacion medica hospitalaria.
    Detecta estructura heuristicamente. No depende de posiciones fijas.
    """
    
    TURNOS_VALIDOS = {'M', 'T', 'MT', 'TM'}
    TURNO_TEXTO = {
        'M': 'Manana',
        'T': 'Tarde',
        'MT': 'Manana y Tarde',
        'TM': 'Manana y Tarde'
    }
    
    def __init__(self):
        self._errores = []
        self._advertencias = []
        self._normalizador = NormalizadorServicio()
    
    def procesar(self, file_path: str, mes: int, anio: int) -> Dict[str, Any]:
        """Procesa el Excel y retorna datos estructurados"""
        self._errores = []
        self._advertencias = []
        
        try:
            df = self._cargar_dataframe(file_path)
            dias_mes = calendar.monthrange(anio, mes)[1]
            
            logger.info(f"Procesando: {file_path} ({df.shape[0]} filas, {df.shape[1]} cols) - {mes}/{anio}")
            
            resultado = self._procesar_dataframe(df, mes, anio, dias_mes)
            
            logger.info(
                f"Resultado: {resultado['total_especialidades']} esp, "
                f"{resultado['total_medicos']} med, "
                f"{resultado['total_registros']} reg, "
                f"{resultado['total_errores']} err"
            )
            
            return resultado
            
        except Exception as e:
            logger.exception(f"Error critico procesando Excel: {e}")
            return {
                'especialidades': [],
                'total_medicos': 0,
                'total_especialidades': 0,
                'total_registros': 0,
                'total_errores': 1,
                'errores': [{'tipo': 'error_critico', 'mensaje': str(e)}],
                'advertencias': [],
                'programaciones': []
            }
    
    def _cargar_dataframe(self, file_path: str) -> pd.DataFrame:
        """
        Carga el archivo Excel usando openpyxl en modo solo datos.
        Evita el error 'expected float' leyendo valores directamente.
        """
        wb = openpyxl.load_workbook(file_path, data_only=True, read_only=True)
        ws = wb.active
        
        data = []
        for row in ws.iter_rows(values_only=True):
            data.append([str(c) if c is not None else '' for c in row])
        
        wb.close()
        
        df = pd.DataFrame(data)
        df = df.fillna('')
        df = df.replace('nan', '')
        df = df.replace('None', '')
        
        logger.info(f"Excel cargado: {df.shape[0]} filas x {df.shape[1]} columnas")
        return df
    
    def _procesar_dataframe(
        self, df: pd.DataFrame, mes: int, anio: int, dias_mes: int
    ) -> Dict[str, Any]:
        """Procesa el DataFrame fila por fila"""
        
        especialidades_detectadas = []
        medicos_procesados = set()
        programaciones = []
        
        especialidad_actual = None
        columnas_dias = {}
        dias_semana_map = {}
        
        total_filas = len(df)
        total_columnas = len(df.columns)
        
        for idx in range(total_filas):
            fila = []
            for c in range(total_columnas):
                val = df.iloc[idx, c]
                fila.append(str(val).strip() if val and val != 'nan' and val != 'None' else '')
            
            # Saltar filas vacias
            if all(v == '' for v in fila):
                continue
            
            # Saltar filas 0 y 1 (titulo)
            if idx <= 1:
                continue
            
            col_a = fila[0] if len(fila) > 0 else ''
            col_b = fila[1] if len(fila) > 1 else ''
            col_c = fila[2] if len(fila) > 2 else ''
            
            # Detectar especialidad
            if self._es_especialidad(col_a, col_b, col_c):
                esp = col_a.upper()
                if esp not in especialidades_detectadas:
                    especialidades_detectadas.append(esp)
                    logger.debug(f"Especialidad: {esp}")
                especialidad_actual = esp
                continue
            
            # Detectar cabecera de dias
            if col_a == 'N' and col_b == 'DNI' and 'APELLIDOS' in col_c.upper():
                columnas_dias = self._detectar_columnas_dias(fila, dias_mes)
                logger.debug(f"Cabecera: {len(columnas_dias)} dias")
                continue
            
            # Detectar fila de dias de semana
            if self._es_fila_dias_semana(fila):
                dias_semana_map = self._mapear_dias_semana(fila, columnas_dias)
                logger.debug(f"Dias semana: {len(dias_semana_map)}")
                continue
            
            # Detectar medico
            if col_a.isdigit() and len(col_b) >= 7 and col_b.isdigit() and especialidad_actual:
                dni = col_b
                nombre = col_c
                medicos_procesados.add(dni)
                
                for dia_num, col in columnas_dias.items():
                    if col >= len(fila):
                        continue
                    
                    valor = fila[col].upper().replace(' ', '')
                    
                    if valor in self.TURNOS_VALIDOS:
                        turno = 'MT' if valor in ('MT', 'TM') else valor
                        
                        try:
                            fecha_obj = date(anio, mes, dia_num)
                        except ValueError:
                            continue
                        
                        programaciones.append({
                            'medico_dni': dni,
                            'medico_nombre': nombre,
                            'especialidad': especialidad_actual,
                            'fecha': fecha_obj.isoformat(),
                            'dia': int(dia_num),
                            'dia_semana': dias_semana_map.get(dia_num, ''),
                            'turno': turno,
                            'turno_texto': self.TURNO_TEXTO.get(turno, '')
                        })
                    elif valor and valor not in ('', 'NAN', 'NONE'):
                        self._errores.append({
                            'tipo': 'turno_invalido',
                            'medico': nombre,
                            'dia': dia_num,
                            'valor': valor,
                            'mensaje': f'Turno invalido "{valor}" para {nombre} dia {dia_num}'
                        })
        
        return {
            'especialidades': especialidades_detectadas,
            'total_medicos': int(len(medicos_procesados)),
            'total_especialidades': int(len(especialidades_detectadas)),
            'total_registros': int(len(programaciones)),
            'total_errores': int(len(self._errores)),
            'errores': self._errores,
            'advertencias': self._advertencias,
            'programaciones': programaciones
        }
    
    def _es_especialidad(self, col_a: str, col_b: str, col_c: str) -> bool:
        """Detecta si la fila es un nombre de especialidad"""
        if not col_a:
            return False
        if col_a == 'N' and col_b == 'DNI':
            return False
        if col_a.isdigit():
            return False
        dias = ['LUNES','MARTES','MIERCOLES','JUEVES','VIERNES','SABADO','DOMINGO']
        if col_a.upper() in dias:
            return False
        # Especialidad: texto en A, B y C vacias
        return not col_b and not col_c
    
    def _es_fila_dias_semana(self, fila: List[str]) -> bool:
        """Detecta fila con dias de la semana"""
        dias = {'VIERNES','SABADO','DOMINGO','LUNES','MARTES','MIERCOLES','JUEVES'}
        count = sum(1 for v in fila if v.upper() in dias)
        return count >= 5
    
    def _detectar_columnas_dias(self, fila: List[str], dias_mes: int) -> Dict[int, int]:
        """Mapea columnas a numeros de dia"""
        columnas = {}
        for i, valor in enumerate(fila):
            try:
                num = int(valor)
                if 1 <= num <= dias_mes:
                    columnas[num] = i
            except (ValueError, TypeError):
                continue
        return columnas
    
    def _mapear_dias_semana(self, fila: List[str], columnas_dias: Dict[int, int]) -> Dict[int, str]:
        """Relaciona dia del mes con dia de la semana"""
        dias_validos = {
            'LUNES': 'LUNES', 'MARTES': 'MARTES', 'MIERCOLES': 'MIERCOLES',
            'JUEVES': 'JUEVES', 'VIERNES': 'VIERNES', 'SABADO': 'SABADO', 'DOMINGO': 'DOMINGO'
        }
        dias_nombre = {}
        for dia_num, col in columnas_dias.items():
            if col < len(fila):
                valor = fila[col].upper()
                if valor in dias_validos:
                    dias_nombre[dia_num] = dias_validos[valor]
        return dias_nombre