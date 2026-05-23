# app/api/biometric.py
"""
RUTAS DE AUTENTICACIÓN BIOMÉTRICA (WebAuthn) - Completamente Criptográficas y Seguras
Huella digital, Face ID, PIN
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, Dict
import os
from datetime import datetime, timezone, timedelta

import webauthn
from webauthn import (
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url

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
WEBAUTHN_ORIGIN = _os.getenv("WEBAUTHN_ORIGIN", "https://hospital-pnp.web.app")

# =====================================================
# SCHEMAS
# =====================================================

class BiometricRegisterOptionsRequest(BaseModel):
    email: str

class BiometricRegisterVerifyRequest(BaseModel):
    credential_id: str
    public_key_pem: str
    attestation_object: str
    client_data_json: str

class BiometricLoginOptionsRequest(BaseModel):
    email: str

class BiometricLoginVerifyRequest(BaseModel):
    email: str
    credential_id: str
    authenticator_data: str
    client_data_json: str
    signature: str

# =====================================================
# ALMACENAMIENTO TEMPORAL DE DESAFÍOS (CHALLENGES)
# =====================================================
_challenges: Dict[str, str] = {}

def generate_challenge(length: int = 32) -> bytes:
    return os.urandom(length)

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
        user_id = str(current_user.id)
        
        _challenges[f"reg_{user_id}"] = bytes_to_base64url(challenge)
        
        options = {
            "challenge": _challenges[f"reg_{user_id}"],
            "rp": {
                "name": WEBAUTHN_RP_NAME,
                "id": WEBAUTHN_RP_ID
            },
            "user": {
                "id": bytes_to_base64url(user_id.encode()),
                "name": current_user.email,
                "displayName": current_user.username or current_user.email.split('@')[0]
            },
            "pubKeyCredParams": [
                {"type": "public-key", "alg": -7},    # ES256
                {"type": "public-key", "alg": -257},  # RS256
            ],
            "timeout": 120000,
            "attestation": "none",
            "authenticatorSelection": {
                "authenticatorAttachment": "platform",
                "userVerification": "required",
                "residentKey": "required"
            }
        }
        
        return options
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================
# VERIFICAR REGISTRO CRIPTOGRÁFICAMENTE
# =====================================================

@router.post("/biometric/register-verify")
async def biometric_register_verify(
    request: BiometricRegisterVerifyRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    try:
        user_id = str(current_user.id)
        expected_challenge = _challenges.pop(f"reg_{user_id}", None)
        
        if not expected_challenge:
            raise HTTPException(status_code=400, detail="Desafío no encontrado o expirado. Reinicie el proceso.")

        try:
            # Verificación real delegando el tipado dinámico a Python
            verification = verify_registration_response(
                credential_id=request.credential_id,
                attestation_object=request.attestation_object,
                client_data_json=request.client_data_json,
                expected_challenge=base64url_to_bytes(expected_challenge),
                expected_origin=WEBAUTHN_ORIGIN,
                expected_rp_id=WEBAUTHN_RP_ID,
                require_user_verification=True
            )
        except Exception as verification_error:
            raise HTTPException(status_code=400, detail=f"Fallo de verificación WebAuthn: {str(verification_error)}")

        credential_id_clean = bytes_to_base64url(verification.credential_id)
        public_key_clean = bytes_to_base64url(verification.credential_public_key)

        existente = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).first()
        
        if existente:
            existente.credential_id = credential_id_clean
            existente.public_key = public_key_clean
            existente.sign_count = verification.sign_count
            existente.device_name = "Dispositivo móvil verificado"
            existente.updated_at = datetime.now(timezone.utc)
        else:
            nueva = BiometricCredential(
                usuario_id=current_user.id,
                credential_id=credential_id_clean,
                public_key=public_key_clean,
                sign_count=verification.sign_count,
                device_name="Dispositivo móvil verificado"
            )
            db.add(nueva)
        
        db.commit()
        return {"success": True, "message": "Dispositivo biométrico registrado de forma segura"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
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
            raise HTTPException(status_code=404, detail="El usuario no cuenta con un registro biométrico activo")
        
        challenge = generate_challenge()
        _challenges[f"login_{usuario.email.lower()}"] = bytes_to_base64url(challenge)
        
        options = {
            "challenge": _challenges[f"login_{usuario.email.lower()}"],
            "rpId": WEBAUTHN_RP_ID,
            "allowCredentials": [
                {"id": cred.credential_id, "type": "public-key"}
                for cred in credenciales
            ],
            "timeout": 60000,
            "userVerification": "required"
        }
        
        return options
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =====================================================
# VERIFICAR LOGIN (VALIDACIÓN CRIPTOGRÁFICA DE FIRMA)
# =====================================================

@router.post("/biometric/login-verify")
async def biometric_login_verify(
    request: BiometricLoginVerifyRequest,
    db: Session = Depends(get_db)
):
    try:
        usuario = db.query(Usuario).filter(
            Usuario.email.ilike(request.email),
            Usuario.activo == True
        ).first()
        
        if not usuario:
            raise HTTPException(status_code=401, detail="Credenciales inválidas o usuario inactivo")
        
        credencial = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == usuario.id,
            BiometricCredential.credential_id == request.credential_id
        ).first()
        
        if not credencial:
            raise HTTPException(status_code=401, detail="Credencial biométrica no reconocida")

        expected_challenge = _challenges.pop(f"login_{usuario.email.lower()}", None)
        if not expected_challenge:
            raise HTTPException(status_code=400, detail="Desafío de autenticación vencido. Intente de nuevo.")

        try:
            # Validación robusta de la firma contra la llave pública almacenada
            verification = verify_authentication_response(
                credential_id=request.credential_id,
                authenticator_data=request.authenticator_data,
                client_data_json=request.client_data_json,
                signature=request.signature,
                credential_public_key=base64url_to_bytes(credencial.public_key),
                credential_current_sign_count=credencial.sign_count,
                expected_challenge=base64url_to_bytes(expected_challenge),
                expected_origin=WEBAUTHN_ORIGIN,
                expected_rp_id=WEBAUTHN_RP_ID,
                require_user_verification=True
            )
        except Exception as auth_error:
            raise HTTPException(status_code=401, detail=f"Fallo en la firma biométrica: {str(auth_error)}")

        credencial.sign_count = verification.new_sign_count
        credencial.last_used_at = datetime.now(timezone.utc)
        db.commit()
        
        personal = db.query(Personal).filter(Personal.id == usuario.personal_id).first()
        roles = personal.roles if personal else (usuario.roles or [])
        area = personal.area if personal else None
        
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
        db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).delete()
        db.commit()
        return {"success": True, "message": "Registro biométrico eliminado correctamente"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))