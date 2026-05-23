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
# CONFIGURACIÓN DE DOMINIO PARA WEBAUTHN
# =====================================================
import os as _os
WEBAUTHN_RP_ID = _os.getenv("WEBAUTHN_RP_ID", "hospital-pnp.web.app")
WEBAUTHN_RP_NAME = getattr(settings, 'APP_NAME', 'Human Check')

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
    return os.urandom(length)

def base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def base64url_decode(data: str) -> bytes:
    if isinstance(data, bytes):
        data = data.decode('ascii')
    data = data.replace('-', '+').replace('_', '/')
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.b64decode(data)

_challenges = {}

# =====================================================
# OPCIONES DE REGISTRO
# =====================================================

@router.post("/biometric/register-options")
async def biometric_register_options(
    request: BiometricRegisterOptionsRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    try:
        if current_user.email.lower() != request.email.lower():
            raise HTTPException(status_code=403, detail="Email no coincide")
        
        challenge = generate_challenge()
        _challenges[str(current_user.id)] = base64url_encode(challenge)
        
        options = {
            "challenge": base64url_encode(challenge),
            "rp": {
                "name": WEBAUTHN_RP_NAME,
                "id": WEBAUTHN_RP_ID
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
        
        print(f"Opciones biometricas para: {current_user.email} (RP: {WEBAUTHN_RP_ID})")
        return options
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error en register-options: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# VERIFICAR REGISTRO
# =====================================================

@router.post("/biometric/register-verify")
async def biometric_register_verify(
    request: BiometricRegisterVerifyRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    try:
        try:
            decoded = base64url_decode(request.credential_id)
            credential_id_clean = base64url_encode(decoded)
        except:
            credential_id_clean = request.credential_id
        
        existente = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).first()
        
        if existente:
            existente.credential_id = credential_id_clean
            existente.public_key = request.public_key_pem
            existente.sign_count = 0
            existente.device_name = "Dispositivo movil"
        else:
            nueva = BiometricCredential(
                usuario_id=current_user.id,
                credential_id=credential_id_clean,
                public_key=request.public_key_pem,
                sign_count=0,
                device_name="Dispositivo movil"
            )
            db.add(nueva)
        
        db.commit()
        print(f"Credencial registrada: {current_user.email}")
        return {"success": True, "message": "Registro biometrico exitoso"}
        
    except Exception as e:
        db.rollback()
        print(f"Error en register-verify: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# OPCIONES DE LOGIN
# =====================================================

@router.post("/biometric/login-options")
async def biometric_login_options(
    request: BiometricLoginOptionsRequest,
    db: Session = Depends(get_db)
):
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
            raise HTTPException(status_code=404, detail="No hay registro biometrico. Inicie sesion con contrasena primero.")
        
        challenge = generate_challenge()
        _challenges[str(usuario.id)] = base64url_encode(challenge)
        
        options = {
            "challenge": base64url_encode(challenge),
            "rpId": WEBAUTHN_RP_ID,
            "allowCredentials": [
                {"id": cred.credential_id, "type": "public-key"}
                for cred in credenciales
            ],
            "timeout": 60000,
            "userVerification": "required"
        }
        
        print(f"Opciones login biometrico: {usuario.email} (RP: {WEBAUTHN_RP_ID})")
        return options
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"Error en login-options: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# VERIFICAR LOGIN (CORREGIDO - Busca por usuario, no por credential_id)
# =====================================================

@router.post("/biometric/login-verify")
async def biometric_login_verify(
    request: BiometricLoginVerifyRequest,
    db: Session = Depends(get_db)
):
    """Verifica autenticacion biometrica y retorna JWT."""
    try:
        # 1. Buscar usuario por email (IGNORANDO credential_id)
        usuario = db.query(Usuario).filter(
            Usuario.email.ilike(request.email),
            Usuario.activo == True
        ).first()
        
        if not usuario:
            raise HTTPException(status_code=401, detail="Usuario no encontrado")
        
        # 2. Verificar que tenga credenciales biometricas
        credencial = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == usuario.id
        ).first()
        
        if not credencial:
            raise HTTPException(status_code=401, detail="Sin credenciales biometricas")
        
        # 3. Actualizar ultimo uso
        credencial.last_used_at = datetime.now(timezone.utc)
        db.commit()
        
        # 4. Obtener datos de personal
        personal = db.query(Personal).filter(
            Personal.id == usuario.personal_id
        ).first()
        
        roles = personal.roles if personal else (usuario.roles or [])
        area = personal.area if personal else None
        
        # 5. Generar JWT
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
        print(f"Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# ELIMINAR REGISTRO
# =====================================================

@router.delete("/biometric/unregister")
async def biometric_unregister(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    try:
        eliminados = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).delete()
        db.commit()
        print(f"Registro biometrico eliminado: {current_user.email}")
        return {"success": True, "message": "Registro biometrico eliminado"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))