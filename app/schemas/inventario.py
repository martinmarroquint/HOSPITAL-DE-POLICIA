from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime


class CatalogoItemCreate(BaseModel):
    nombre: str
    icono: Optional[str] = "mdi:package-variant-closed"
    categoria: Optional[str] = None
    precio_unitario: Optional[float] = 0
    stock_minimo: Optional[int] = 5
    detalles: Optional[List[Dict[str, str]]] = []


class CatalogoItemUpdate(BaseModel):
    nombre: Optional[str] = None
    icono: Optional[str] = None
    categoria: Optional[str] = None
    precio_unitario: Optional[float] = None
    stock_minimo: Optional[int] = None
    detalles: Optional[List[Dict[str, str]]] = None


class CatalogoItemResponse(BaseModel):
    id: UUID
    nombre: str
    icono: str
    categoria: Optional[str]
    precio_unitario: float
    stock_minimo: int
    detalles: List[Dict[str, str]]
    created_at: Optional[datetime]


class InventarioUnidadCreate(BaseModel):
    catalogo_item_id: UUID
    unidad_nombre: Optional[str] = None
    cantidades: Optional[Dict[str, int]] = {}
    movimientos: Optional[List[Dict[str, Any]]] = []


class InventarioUnidadUpdate(BaseModel):
    cantidades: Optional[Dict[str, int]] = None
    movimientos: Optional[List[Dict[str, Any]]] = None


class InventarioUnidadResponse(BaseModel):
    id: UUID
    catalogo_item_id: UUID
    unidad_nombre: str
    cantidades: Dict[str, int]
    movimientos: List[Dict[str, Any]]
    updated_at: Optional[datetime]