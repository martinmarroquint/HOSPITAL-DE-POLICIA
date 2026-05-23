# app/api/biometric.py
"""
RUTAS DE AUTENTICACIÓN BIOMÉTRICA (WebAuthn) - SEGURAS Y FUNCIONALES
Huella digital, Face ID, PIN
Verificación criptográfica real con py_webauthn
"""

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, Dict
import os
import base64
import json
from datetime import datetime, timezone, timedelta

# Librería criptográfica para WebAuthn
import webauthn
from webauthn.helpers import (
    verify_authentication_response,
    verify_registration_response,
    parse_authentication_credential_json,
    parse_registration_credential_json,
    structs,
)
from webauthn.helpers.exceptions import InvalidAuthenticationResponse, InvalidRegistrationResponse

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
    attestation_object: Optional[str] = None
    client_data_json: Optional[str] = None

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
    """Genera un desafío criptográfico seguro."""
    return os.urandom(length)

def base64url_encode(data: bytes) -> str:
    """Codifica bytes a base64url sin padding."""
    return base64.urlsafe_b64encode(data).rstrip(b'=').decode('ascii')

def base64url_decode(data: str) -> bytes:
    """Decodifica base64url a bytes."""
    if isinstance(data, bytes):
        data = data.decode('ascii')
    data = data.replace('-', '+').replace('_', '/')
    padding = 4 - len(data) % 4
    if padding != 4:
        data += '=' * padding
    return base64.b64decode(data)

def bytes_to_base64url(data: bytes) -> str:
    """Alias para base64url_encode."""
    return base64url_encode(data)

# Almacenamiento de desafíos (en producción: Redis)
_challenges: Dict[str, str] = {}

# =====================================================
# OPCIONES DE REGISTRO
# =====================================================

@router.post("/biometric/register-options")
async def biometric_register_options(
    request: BiometricRegisterOptionsRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Genera opciones para registro biométrico según el estándar WebAuthn."""
    try:
        if current_user.email.lower() != request.email.lower():
            raise HTTPException(status_code=403, detail="Email no coincide con el usuario autenticado")
        
        challenge = generate_challenge()
        user_id = str(current_user.id)
        _challenges[user_id] = base64url_encode(challenge)
        
        options = {
            "challenge": _challenges[user_id],
            "rp": {
                "name": WEBAUTHN_RP_NAME,
                "id": WEBAUTHN_RP_ID
            },
            "user": {
                "id": base64url_encode(user_id.encode()),
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
        
        print(f"[REGISTER] Opciones generadas para: {current_user.email} (RP: {WEBAUTHN_RP_ID})")
        return options
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[REGISTER] Error en register-options: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# VERIFICAR REGISTRO (VALIDACIÓN CRIPTOGRÁFICA REAL)
# =====================================================

@router.post("/biometric/register-verify")
async def biometric_register_verify(
    request: BiometricRegisterVerifyRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Verifica y almacena una credencial biométrica.
    Ahora valida criptográficamente la respuesta del autenticador.
    """
    try:
        user_id = str(current_user.id)
        
        # Recuperar el desafío original
        expected_challenge = _challenges.pop(user_id, None)
        if not expected_challenge:
            raise HTTPException(status_code=400, detail="Desafío no encontrado. Reinicie el registro.")
        
        # Construir el objeto de credencial para verificación
        registration_credential = {
            "id": request.credential_id,
            "rawId": request.credential_id,
            "response": {
                "attestationObject": request.attestation_object or "",
                "clientDataJSON": request.client_data_json or "",
            },
            "type": "public-key"
        }
        
        # Verificar criptográficamente la respuesta de registro
        try:
            verification = verify_registration_response(
                credential=registration_credential,
                expected_challenge=expected_challenge,
                expected_rp_id=WEBAUTHN_RP_ID,
                expected_origin=WEBAUTHN_ORIGIN,
            )
        except InvalidRegistrationResponse as e:
            print(f"[REGISTER] Fallo en verificación criptográfica: {e}")
            raise HTTPException(status_code=400, detail="Falló la verificación de seguridad del registro biométrico.")
        
        # Extraer datos verificados
        credential_id = base64url_encode(verification.credential_id)
        credential_public_key = base64url_encode(verification.credential_public_key)
        sign_count = verification.sign_count
        
        # Almacenar o actualizar en base de datos
        existente = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).first()
        
        if existente:
            existente.credential_id = credential_id
            existente.public_key = credential_public_key
            existente.sign_count = sign_count
            existente.device_name = "Dispositivo movil"
        else:
            nueva = BiometricCredential(
                usuario_id=current_user.id,
                credential_id=credential_id,
                public_key=credential_public_key,
                sign_count=sign_count,
                device_name="Dispositivo movil"
            )
            db.add(nueva)
        
        db.commit()
        print(f"[REGISTER] Credencial verificada y almacenada: {current_user.email}")
        return {"success": True, "message": "Registro biometrico exitoso y verificado"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        print(f"[REGISTER] Error en register-verify: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# OPCIONES DE LOGIN
# =====================================================

@router.post("/biometric/login-options")
async def biometric_login_options(
    request: BiometricLoginOptionsRequest,
    db: Session = Depends(get_db)
):
    """Genera opciones para autenticación biométrica."""
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
        user_id = str(usuario.id)
        _challenges[user_id] = base64url_encode(challenge)
        
        options = {
            "challenge": _challenges[user_id],
            "rpId": WEBAUTHN_RP_ID,
            "allowCredentials": [
                {"id": cred.credential_id, "type": "public-key"}
                for cred in credenciales
            ],
            "timeout": 60000,
            "userVerification": "required"
        }
        
        print(f"[LOGIN] Opciones generadas para: {usuario.email}")
        return options
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"[LOGIN] Error en login-options: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# VERIFICAR LOGIN (VALIDACIÓN CRIPTOGRÁFICA REAL)
# =====================================================

@router.post("/biometric/login-verify")
async def biometric_login_verify(
    request: BiometricLoginVerifyRequest,
    db: Session = Depends(get_db)
):
    """
    Verifica la autenticación biométrica con validación criptográfica real.
    Solo genera JWT si la firma del dispositivo es válida.
    """
    try:
        # 1. Buscar usuario por email
        usuario = db.query(Usuario).filter(
            Usuario.email.ilike(request.email),
            Usuario.activo == True
        ).first()
        
        if not usuario:
            raise HTTPException(status_code=401, detail="Usuario no encontrado o inactivo")
        
        user_id = str(usuario.id)
        
        # 2. Recuperar el desafío original
        expected_challenge = _challenges.pop(user_id, None)
        if not expected_challenge:
            raise HTTPException(status_code=400, detail="Desafío expirado. Reinicie el login.")
        
        # 3. Buscar la credencial biométrica del usuario
        credencial = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == usuario.id
        ).first()
        
        if not credencial:
            raise HTTPException(status_code=401, detail="Sin credenciales biometricas para este usuario")
        
        # 4. Decodificar la clave pública almacenada
        try:
            credential_public_key = base64url_decode(credencial.public_key)
        except Exception:
            raise HTTPException(status_code=500, detail="Error al decodificar la clave pública almacenada")
        
        # 5. Construir el objeto de autenticación para verificación
        authentication_credential = {
            "id": request.credential_id,
            "rawId": request.credential_id,
            "response": {
                "authenticatorData": request.authenticator_data,
                "clientDataJSON": request.client_data_json,
                "signature": request.signature,
            },
            "type": "public-key"
        }
        
        # 6. VERIFICACIÓN CRIPTOGRÁFICA REAL
        try:
            verification = verify_authentication_response(
                credential=authentication_credential,
                expected_challenge=expected_challenge,
                expected_rp_id=WEBAUTHN_RP_ID,
                expected_origin=WEBAUTHN_ORIGIN,
                credential_public_key=credential_public_key,
                credential_current_sign_count=credencial.sign_count or 0,
            )
        except InvalidAuthenticationResponse as e:
            print(f"[LOGIN] Fallo en verificación criptográfica: {e}")
            raise HTTPException(status_code=401, detail="Autenticación biométrica fallida. Firma inválida.")
        
        # 7. Actualizar contador de firmas (anti-replay)
        credencial.sign_count = verification.new_sign_count
        credencial.last_used_at = datetime.now(timezone.utc)
        db.commit()
        
        # 8. Obtener datos de personal para enriquecer el JWT
        personal = db.query(Personal).filter(
            Personal.id == usuario.personal_id,
            Personal.activo == True
        ).first()
        
        roles = personal.roles if personal else (usuario.roles or [])
        area = personal.area if personal else None
        
        # 9. Generar JWT
        token_data = {
            "sub": usuario.email,
            "user_id": user_id,
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
        
        print(f"[LOGIN] Autenticación biométrica exitosa: {usuario.email}")
        
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
        print(f"[LOGIN] Error en login-verify: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =====================================================
# ELIMINAR REGISTRO
# =====================================================

@router.delete("/biometric/unregister")
async def biometric_unregister(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Elimina el registro biométrico del usuario."""
    try:
        eliminados = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).delete()
        db.commit()
        print(f"[UNREGISTER] Registro biometrico eliminado: {current_user.email}")
        return {"success": True, "message": "Registro biometrico eliminado"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))