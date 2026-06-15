# app/api/pre_registros.py
# VERSIÓN FINAL - EMAIL CON FORMATO CORRECTO AL APROBAR

from fastapi import APIRouter, Depends, HTTPException, Query, Body, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified
from typing import List, Optional
from datetime import datetime, date, timedelta
from uuid import UUID
import secrets
import logging
import unicodedata

from app.database import get_db
from app.core.dependencies import require_roles, get_current_user
from app.models.pre_registro import PreRegistro
from app.models.personal import Personal
from app.models.usuario import Usuario
from app.models.empresa import Empresa

logger = logging.getLogger(__name__)
router = APIRouter()

ROLES_ADMIN = ["admin_empresa", "jefe"]


# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def generar_token() -> str:
    return secrets.token_urlsafe(12)

def aplicar_filtro_empresa(query, current_user, modelo):
    if current_user.empresa_id and current_user.rol_global != "super_admin":
        if hasattr(modelo, 'empresa_id'):
            query = query.filter(modelo.empresa_id == current_user.empresa_id)
    return query

def quitar_tildes(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn').lower()

def generar_email_interno(nombre_completo: str, dni: str = None, dominio: str = None) -> str:
    """Genera email: nombre.apellido@empresa.com"""
    dominio_final = dominio or "sistema.com"
    if not nombre_completo or nombre_completo == 'PENDIENTE':
        return f"pendiente{hash(dni) % 10000 if dni else 0}@{dominio_final}"
    
    nombre = nombre_completo.upper().strip().replace(',', ' ')
    palabras = [p for p in nombre.split() if p]
    if not palabras:
        return f"usuario{hash(dni) % 10000 if dni else 0}@{dominio_final}"
    
    primer_nombre = palabras[0]
    primer_apellido = palabras[-1] if len(palabras) > 1 else palabras[0]
    return f"{quitar_tildes(primer_nombre)}.{quitar_tildes(primer_apellido)}@{dominio_final}"

def obtener_dominio_empresa(db: Session, empresa_id) -> str:
    if not empresa_id:
        return "sistema.com"
    empresa = db.query(Empresa).filter(Empresa.id == empresa_id).first()
    if empresa:
        if empresa.dominio_email:
            return empresa.dominio_email
        if empresa.subdominio:
            return f"{empresa.subdominio}.com"
    return "sistema.com"


# =====================================================
# ENDPOINTS PÚBLICOS
# =====================================================

@router.post("/public/pre-registro/{empresa_slug}/{token}")
async def recibir_pre_registro(
    empresa_slug: str, token: str, request: Request,
    nombre: str = Body(...), documento: str = Body(...),
    sexo: Optional[str] = Body(None), fecha_nacimiento: Optional[str] = Body(None),
    email: Optional[str] = Body(None), telefono: Optional[str] = Body(None),
    area: Optional[str] = Body(None), cargo: Optional[str] = Body(None),
    especialidad: Optional[str] = Body(None), cip: Optional[str] = Body(None),
    fecha_ingreso: Optional[str] = Body(None), observaciones: Optional[str] = Body(None),
    tiempo_llenado: Optional[int] = Body(None), honeypot: Optional[str] = Body(None),
    db: Session = Depends(get_db)
):
    try:
        empresa = db.query(Empresa).filter(Empresa.subdominio == empresa_slug, Empresa.activo == True).first()
        if not empresa:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
        config = empresa.configuracion or {}
        pre_config = config.get("pre_registro", {})
        
        habilitado = pre_config.get("habilitado", False)
        if isinstance(habilitado, str):
            habilitado = habilitado.lower() == "true"
        if not habilitado:
            raise HTTPException(status_code=403, detail="Pre-registro deshabilitado")
        if pre_config.get("token") != token:
            raise HTTPException(status_code=403, detail="Token inválido")
        
        fecha_inicio = pre_config.get("fecha_inicio")
        fecha_fin = pre_config.get("fecha_fin")
        hoy = date.today()
        if fecha_inicio:
            try:
                if hoy < date.fromisoformat(fecha_inicio):
                    raise HTTPException(status_code=403, detail="Pre-registro no vigente")
            except ValueError: pass
        if fecha_fin:
            try:
                if hoy > date.fromisoformat(fecha_fin):
                    raise HTTPException(status_code=403, detail="Pre-registro expirado")
            except ValueError: pass
        
        max_registros = pre_config.get("max_registros", 50)
        total_pendientes = db.query(PreRegistro).filter(
            PreRegistro.empresa_id == empresa.id, PreRegistro.estado == "PENDIENTE"
        ).count()
        if total_pendientes >= max_registros:
            raise HTTPException(status_code=429, detail=f"Límite de {max_registros} alcanzado")
        
        if honeypot:
            return {"success": True, "message": "Registro recibido. Será revisado por RRHH."}
        if tiempo_llenado and tiempo_llenado < 5:
            raise HTTPException(status_code=400, detail="Complete el formulario correctamente.")
        
        ip = request.client.host
        hace_1_hora = datetime.utcnow() - timedelta(hours=1)
        if db.query(PreRegistro).filter(PreRegistro.ip_origen == ip, PreRegistro.created_at >= hace_1_hora).count() >= 5:
            raise HTTPException(status_code=429, detail="Demasiados intentos.")
        
        if not nombre or not nombre.strip():
            raise HTTPException(status_code=400, detail="Nombre obligatorio")
        if not documento or not documento.strip():
            raise HTTPException(status_code=400, detail="Documento obligatorio")
        
        if db.query(PreRegistro).filter(
            PreRegistro.empresa_id == empresa.id, PreRegistro.documento == documento.strip(), PreRegistro.estado == "PENDIENTE"
        ).first():
            raise HTTPException(status_code=409, detail="Este documento ya tiene un pre-registro pendiente")
        if db.query(Personal).filter(Personal.empresa_id == empresa.id, Personal.dni == documento.strip()).first():
            raise HTTPException(status_code=409, detail="Este documento ya está registrado")
        
        pre_registro = PreRegistro(
            empresa_id=empresa.id, nombre=nombre.strip(), documento=documento.strip(),
            sexo=sexo.strip() if sexo else None,
            fecha_nacimiento=date.fromisoformat(fecha_nacimiento) if fecha_nacimiento else None,
            email=None, telefono=telefono.strip() if telefono else None,
            area=None, cargo=cargo.strip() if cargo else None,
            especialidad=especialidad.strip() if especialidad else None,
            cip=cip.strip() if cip else None,
            fecha_ingreso=date.fromisoformat(fecha_ingreso) if fecha_ingreso else None,
            observaciones=observaciones.strip() if observaciones else None,
            ip_origen=ip, tiempo_llenado_segundos=tiempo_llenado, estado="PENDIENTE"
        )
        db.add(pre_registro)
        db.commit()
        db.refresh(pre_registro)
        
        logger.info(f"✅ Pre-registro: {nombre} - {documento} - {empresa.nombre}")
        return {"success": True, "message": "Registro recibido. Será revisado por RRHH.", "id": str(pre_registro.id)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error en recibir_pre_registro: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail="Error interno")


# =====================================================
# ENDPOINTS ADMIN
# =====================================================

@router.get("/admin/pre-registro/config")
async def obtener_config_pre_registro(
    db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    try:
        if not current_user.empresa_id:
            raise HTTPException(status_code=400, detail="Usuario sin empresa")
        empresa = db.query(Empresa).filter(Empresa.id == current_user.empresa_id).first()
        if not empresa:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
        config = empresa.configuracion or {}
        pre_config = config.get("pre_registro", {})
        if not pre_config.get("token"):
            pre_config["token"] = generar_token()
            config["pre_registro"] = pre_config
            empresa.configuracion = config
            flag_modified(empresa, "configuracion")
            db.commit()
        
        return {"success": True, "config": {
            "habilitado": pre_config.get("habilitado", False),
            "token": pre_config.get("token", ""),
            "fecha_inicio": pre_config.get("fecha_inicio"),
            "fecha_fin": pre_config.get("fecha_fin"),
            "max_registros": pre_config.get("max_registros", 50),
            "notificar_email": pre_config.get("notificar_email"),
            "empresa_slug": empresa.subdominio,
            "link_completo": f"/pre-registro/{empresa.subdominio}/{pre_config.get('token', '')}"
        }}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/admin/pre-registro/config")
async def actualizar_config_pre_registro(
    habilitado: bool = Body(False), fecha_inicio: Optional[str] = Body(None),
    fecha_fin: Optional[str] = Body(None), max_registros: int = Body(50),
    notificar_email: Optional[str] = Body(None),
    db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    try:
        if not current_user.empresa_id:
            raise HTTPException(status_code=400, detail="Usuario sin empresa")
        empresa = db.query(Empresa).filter(Empresa.id == current_user.empresa_id).first()
        if not empresa:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
        config = empresa.configuracion or {}
        pre_config = config.get("pre_registro", {})
        if not pre_config.get("token"):
            pre_config["token"] = generar_token()
        
        pre_config["habilitado"] = habilitado
        pre_config["max_registros"] = max_registros
        pre_config["notificar_email"] = notificar_email
        if fecha_inicio: pre_config["fecha_inicio"] = fecha_inicio
        else: pre_config.pop("fecha_inicio", None)
        if fecha_fin: pre_config["fecha_fin"] = fecha_fin
        else: pre_config.pop("fecha_fin", None)
        
        config["pre_registro"] = pre_config
        empresa.configuracion = config
        flag_modified(empresa, "configuracion")
        db.commit()
        
        return {"success": True, "message": "Configuración actualizada", "config": pre_config}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/pre-registro/regenerar-token")
async def regenerar_token(db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(ROLES_ADMIN))):
    try:
        if not current_user.empresa_id:
            raise HTTPException(status_code=400, detail="Usuario sin empresa")
        empresa = db.query(Empresa).filter(Empresa.id == current_user.empresa_id).first()
        if not empresa:
            raise HTTPException(status_code=404, detail="Empresa no encontrada")
        
        nuevo_token = generar_token()
        config = empresa.configuracion or {}
        pre_config = config.get("pre_registro", {})
        pre_config["token"] = nuevo_token
        config["pre_registro"] = pre_config
        empresa.configuracion = config
        flag_modified(empresa, "configuracion")
        db.commit()
        
        return {"success": True, "token": nuevo_token, "link_completo": f"/pre-registro/{empresa.subdominio}/{nuevo_token}"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/admin/pre-registros")
async def listar_pre_registros(
    estado: Optional[str] = Query(None), busqueda: Optional[str] = Query(None),
    limit: int = Query(50, le=100), db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    try:
        query = db.query(PreRegistro)
        query = aplicar_filtro_empresa(query, current_user, PreRegistro)
        if estado: query = query.filter(PreRegistro.estado == estado.upper())
        if busqueda:
            t = f"%{busqueda}%"
            query = query.filter(PreRegistro.nombre.ilike(t) | PreRegistro.documento.ilike(t) | PreRegistro.area.ilike(t) | PreRegistro.email.ilike(t))
        
        registros = query.order_by(PreRegistro.created_at.desc()).limit(limit).all()
        resultado = [{
            "id": str(r.id), "empresa_id": str(r.empresa_id), "nombre": r.nombre,
            "documento": r.documento, "sexo": r.sexo,
            "fecha_nacimiento": r.fecha_nacimiento.isoformat() if r.fecha_nacimiento else None,
            "email": r.email, "telefono": r.telefono, "area": r.area,
            "cargo": r.cargo, "especialidad": r.especialidad, "cip": r.cip,
            "fecha_ingreso": r.fecha_ingreso.isoformat() if r.fecha_ingreso else None,
            "observaciones": r.observaciones, "estado": r.estado,
            "motivo_rechazo": r.motivo_rechazo, "ip_origen": r.ip_origen,
            "tiempo_llenado_segundos": r.tiempo_llenado_segundos,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "aprobado_en": r.aprobado_en.isoformat() if r.aprobado_en else None
        } for r in registros]
        return {"success": True, "total": len(resultado), "registros": resultado}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/pre-registros/{pre_registro_id}/aprobar")
async def aprobar_pre_registro(
    pre_registro_id: UUID, db: Session = Depends(get_db),
    current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    try:
        pre = db.query(PreRegistro).filter(PreRegistro.id == pre_registro_id).first()
        if not pre: raise HTTPException(status_code=404, detail="Pre-registro no encontrado")
        if current_user.empresa_id and str(pre.empresa_id) != str(current_user.empresa_id):
            raise HTTPException(status_code=403, detail="No tiene acceso")
        if pre.estado != "PENDIENTE":
            raise HTTPException(status_code=400, detail=f"Ya fue {pre.estado}")
        if db.query(Personal).filter(Personal.empresa_id == pre.empresa_id, Personal.dni == pre.documento).first():
            raise HTTPException(status_code=409, detail="DNI ya registrado")
        
        # ✅ Generar email con formato correcto
        dominio = obtener_dominio_empresa(db, pre.empresa_id)
        email_generado = generar_email_interno(pre.nombre, pre.documento, dominio)
        
        nuevo_personal = Personal(
            empresa_id=pre.empresa_id, dni=pre.documento, cip=pre.cip,
            grado="PENDIENTE", nombre=pre.nombre,
            email=email_generado,  # ✅ nombre.apellido@empresa.com
            telefono=pre.telefono, fecha_nacimiento=pre.fecha_nacimiento,
            area=pre.area or "PENDIENTE", especialidad=pre.especialidad,
            sexo=pre.sexo or "No especificado",
            fecha_ingreso=pre.fecha_ingreso or date.today(),
            observaciones=f"Pre-registro aprobado. {pre.observaciones or ''}",
            condicion="Titular", activo=True, roles=["usuario"]
        )
        db.add(nuevo_personal)
        db.flush()
        
        pre.estado = "APROBADO"
        pre.aprobado_por = current_user.id
        pre.aprobado_en = datetime.utcnow()
        pre.personal_creado_id = nuevo_personal.id
        db.commit()
        
        logger.info(f"✅ Aprobado: {pre.nombre} → Email: {email_generado}")
        return {
            "success": True,
            "message": f"Personal creado: {nuevo_personal.nombre}",
            "personal_id": str(nuevo_personal.id),
            "pre_registro_id": str(pre.id),
            "email_asignado": email_generado
        }
    except HTTPException: raise
    except Exception as e:
        logger.error(f"Error en aprobar: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/admin/pre-registros/{pre_registro_id}/rechazar")
async def rechazar_pre_registro(
    pre_registro_id: UUID, motivo: str = Body("Rechazado por administrador"),
    db: Session = Depends(get_db), current_user: Usuario = Depends(require_roles(ROLES_ADMIN))
):
    try:
        pre = db.query(PreRegistro).filter(PreRegistro.id == pre_registro_id).first()
        if not pre: raise HTTPException(status_code=404, detail="No encontrado")
        if current_user.empresa_id and str(pre.empresa_id) != str(current_user.empresa_id):
            raise HTTPException(status_code=403, detail="No tiene acceso")
        if pre.estado != "PENDIENTE":
            raise HTTPException(status_code=400, detail=f"Ya fue {pre.estado}")
        pre.estado = "RECHAZADO"
        pre.motivo_rechazo = motivo
        pre.aprobado_por = current_user.id
        pre.aprobado_en = datetime.utcnow()
        db.commit()
        logger.info(f"❌ Rechazado: {pre.nombre} - {motivo}")
        return {"success": True, "message": "Rechazado", "id": str(pre.id)}
    except HTTPException: raise
    except Exception as e:
        logger.error(f"Error en rechazar: {str(e)}")
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))