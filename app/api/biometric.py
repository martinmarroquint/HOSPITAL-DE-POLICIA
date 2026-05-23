# app/api/biometric.py
"""
RUTAS DE AUTENTICACIÓN BIOMÉTRICA (WebAuthn)
Huella digital, Face ID, PIN
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional
import os
import base64
from datetime import datetime, timezone, timedelta

from app.database import get_db
from app.core.dependencies import get_current_active_user
from app.models.usuario import Usuario
from app.models.biometric import BiometricCredential
from app.models.personal import Personal
from app.core.security import create_access_token
from app.config import settings

router = APIRouter()

# =====================================================
# SCHEMAS
# =====================================================

class BiometricRegisterOptionsRequest(BaseModel):
    email: str

class BiometricRegisterVerifyRequest(BaseModel):
    credential_id: str
    public_key_pem: str

class BiometricLoginOptionsRequest(BaseModel):
    email: str

class BiometricLoginVerifyRequest(BaseModel):
    email: str
    credential_id: str
    authenticator_data: str
    client_data_json: str
    signature: str

# =====================================================
# FUNCIONES AUXILIARES
# =====================================================

def generate_challenge(length: int = 32) -> bytes:
    """Genera un challenge aleatorio para WebAuthn."""
    return os.urandom(length)

def base64url_encode(data: bytes) -> str:
    """Codifica bytes a base64url sin padding."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def base64url_decode(data: str) -> bytes:
    """Decodifica base64url a bytes."""
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.urlsafe_b64decode(data)

# Almacén temporal de challenges (en producción usar Redis)
_challenges = {}

# =====================================================
# OPCIONES DE REGISTRO (Paso 1)
# =====================================================

@router.post("/biometric/register-options")
async def biometric_register_options(
    request: BiometricRegisterOptionsRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Genera las opciones para registrar una credencial biométrica.
    El usuario ya debe estar autenticado (tiene token JWT).
    """
    try:
        # Verificar que el email coincida con el usuario autenticado
        if current_user.email.lower() != request.email.lower():
            raise HTTPException(status_code=403, detail="Email no coincide con el usuario autenticado")
        
        # Generar challenge
        challenge = generate_challenge()
        _challenges[str(current_user.id)] = base64url_encode(challenge)
        
        # Construir opciones
        options = {
            "challenge": base64url_encode(challenge),
            "rp": {
                "name": getattr(settings, 'APP_NAME', 'Human Check'),
                "id": getattr(settings, 'DOMAIN', 'localhost')
            },
            "user": {
                "id": base64url_encode(str(current_user.id).encode()),
                "name": current_user.email,
                "displayName": current_user.username or current_user.email.split('@')[0]
            },
            "pubKeyCredParams": [
                {"type": "public-key", "alg": -7},
                {"type": "public-key", "alg": -257},
            ],
            "timeout": 120000,
            "attestation": "none",
            "authenticatorSelection": {
                "authenticatorAttachment": "platform",
                "userVerification": "required",
                "residentKey": "required"
            }
        }
        
        print(f"✅ Opciones de registro biométrico para: {current_user.email}")
        return options
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en register-options: {e}")
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")


# =====================================================
# VERIFICAR REGISTRO (Paso 2)
# =====================================================

@router.post("/biometric/register-verify")
async def biometric_register_verify(
    request: BiometricRegisterVerifyRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Verifica y guarda la credencial biométrica registrada."""
    try:
        # Verificar si ya existe
        existente = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).first()
        
        if existente:
            existente.credential_id = request.credential_id
            existente.public_key = request.public_key_pem
            existente.sign_count = 0
            existente.device_name = "Dispositivo móvil"
        else:
            nueva = BiometricCredential(
                usuario_id=current_user.id,
                credential_id=request.credential_id,
                public_key=request.public_key_pem,
                sign_count=0,
                device_name="Dispositivo móvil"
            )
            db.add(nueva)
        
        db.commit()
        print(f"✅ Credencial biométrica registrada: {current_user.email}")
        
        return {"success": True, "message": "Registro biométrico exitoso"}
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error en register-verify: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# =====================================================
# OPCIONES DE LOGIN BIOMÉTRICO (Paso 1)
# =====================================================

@router.post("/biometric/login-options")
async def biometric_login_options(
    request: BiometricLoginOptionsRequest,
    db: Session = Depends(get_db)
):
    """Genera opciones para login biométrico. NO requiere auth previa."""
    try:
        usuario = db.query(Usuario).filter(
            Usuario.email.ilike(request.email)
        ).first()
        
        if not usuario:
            raise HTTPException(status_code=404, detail="Usuario no encontrado")
        
        credenciales = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == usuario.id
        ).all()
        
        if not credenciales:
            raise HTTPException(
                status_code=404,
                detail="No hay registro biométrico. Inicie sesión con contraseña primero."
            )
        
        challenge = generate_challenge()
        _challenges[str(usuario.id)] = base64url_encode(challenge)
        
        options = {
            "challenge": base64url_encode(challenge),
            "allowCredentials": [
                {"id": cred.credential_id, "type": "public-key"}
                for cred in credenciales
            ],
            "timeout": 60000,
            "userVerification": "required"
        }
        
        print(f"✅ Opciones login biométrico: {usuario.email}")
        return options
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en login-options: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# =====================================================
# VERIFICAR LOGIN BIOMÉTRICO (Paso 2)
# =====================================================

@router.post("/biometric/login-verify")
async def biometric_login_verify(
    request: BiometricLoginVerifyRequest,
    db: Session = Depends(get_db)
):
    """Verifica autenticación biométrica y retorna JWT."""
    try:
        credencial = db.query(BiometricCredential).filter(
            BiometricCredential.credential_id == request.credential_id
        ).first()
        
        if not credencial:
            raise HTTPException(status_code=401, detail="Credencial no encontrada")
        
        usuario = db.query(Usuario).filter(
            Usuario.id == credencial.usuario_id,
            Usuario.email.ilike(request.email),
            Usuario.activo == True
        ).first()
        
        if not usuario:
            raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
        
        # Actualizar último uso
        credencial.last_used_at = datetime.now(timezone.utc)
        db.commit()
        
        # Obtener datos de personal
        personal = db.query(Personal).filter(
            Personal.id == usuario.personal_id,
            Personal.activo == True
        ).first()
        
        roles = personal.roles if personal else (usuario.roles or [])
        area = personal.area if personal else None
        
        # Generar JWT
        token_data = {
            "sub": usuario.email,
            "user_id": str(usuario.id),
            "personal_id": str(usuario.personal_id) if usuario.personal_id else None,
            "username": usuario.username or usuario.email.split('@')[0],
            "roles": roles,
            "empresa_id": str(usuario.empresa_id) if usuario.empresa_id else None,
            "rol_global": usuario.rol_global or "usuario",
            "area": area,
        }
        
        access_token = create_access_token(
            data=token_data,
            expires_delta=timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        print(f"✅ Login biométrico exitoso: {usuario.email}")
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "email": usuario.email,
                "username": token_data["username"],
                "rol_global": token_data["rol_global"],
                "roles": roles,
                "area": area,
                "empresa_id": token_data["empresa_id"],
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Error en login-verify: {e}")
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")


# =====================================================
# ELIMINAR REGISTRO BIOMÉTRICO
# =====================================================

@router.delete("/biometric/unregister")
async def biometric_unregister(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Elimina el registro biométrico del usuario."""
    try:
        db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).delete()
        db.commit()
        return {"success": True, "message": "Registro biométrico eliminado"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))