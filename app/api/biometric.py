# app/api/biometric.py
"""
RUTAS DE AUTENTICACIÓN BIOMÉTRICA (WebAuthn 2.x) - PRODUCTION READY
Huella digital, Face ID, PIN, Windows Hello, Touch ID

CAMBIOS PRINCIPALES:
1. Los modelos Pydantic aceptan el payload WebAuthn completo del navegador
2. Se usa request.model_dump() para pasar el credential directamente
3. credential_id se normaliza SIEMPRE: bytes_to_base64url(base64url_to_bytes(rawId))
4. Eliminado public_key_pem (el backend extrae la clave pública real)
5. Soporte para userHandle en login
6. Manejo de errores sin exponer detalles internos
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
import os
from datetime import datetime, timezone, timedelta

from webauthn import verify_authentication_response, verify_registration_response
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.exceptions import (
    InvalidRegistrationResponse,
    InvalidAuthenticationResponse,
)

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
# SCHEMAS - Compatibles con el payload WebAuthn del navegador
# =====================================================

class BiometricRegisterOptionsRequest(BaseModel):
    """Solicitud de opciones para registro biométrico."""
    email: str


class BiometricRegisterVerifyRequest(BaseModel):
    """
    Payload COMPLETO enviado por navigator.credentials.create().
    El frontend debe enviar el objeto credential completo tal cual lo devuelve el navegador.
    """
    id: str = Field(..., description="Credential ID (base64url)")
    rawId: str = Field(..., description="Raw credential ID (base64url)")
    type: str = Field(default="public-key", description="Tipo de credencial")
    response: Dict[str, Any] = Field(..., description="Objeto response del navegador")
    clientExtensionResults: Optional[Dict[str, Any]] = Field(
        default={}, description="Extension results del cliente"
    )


class BiometricLoginOptionsRequest(BaseModel):
    """Solicitud de opciones para login biométrico."""
    email: str


class BiometricLoginVerifyRequest(BaseModel):
    """
    Payload COMPLETO enviado por navigator.credentials.get().
    El frontend debe enviar el objeto assertion completo tal cual lo devuelve el navegador.
    """
    id: str = Field(..., description="Credential ID (base64url)")
    rawId: str = Field(..., description="Raw credential ID (base64url)")
    type: str = Field(default="public-key", description="Tipo de credencial")
    response: Dict[str, Any] = Field(..., description="Objeto response del navegador")
    clientExtensionResults: Optional[Dict[str, Any]] = Field(
        default={}, description="Extension results del cliente"
    )
    email: str = Field(..., description="Email del usuario (enviado por el frontend)")
    # userHandle viene dentro de response, el frontend no lo envía por separado


# =====================================================
# ALMACENAMIENTO TEMPORAL DE DESAFÍOS (CHALLENGES)
# En producción: Redis o base de datos con TTL
# =====================================================
_challenges: Dict[str, str] = {}

def generate_challenge(length: int = 32) -> bytes:
    """Genera un desafío criptográfico seguro usando os.urandom."""
    return os.urandom(length)


def normalize_credential_id(raw_id: str) -> str:
    """
    Normaliza un credential_id a formato base64url canónico.
    
    IMPORTANTE: El navegador puede enviar el mismo ID con diferente
    codificación. Esta función asegura que siempre guardemos y comparemos
    la misma representación.
    
    Flujo: rawId -> bytes -> base64url canónico
    """
    return bytes_to_base64url(base64url_to_bytes(raw_id))


# =====================================================
# OPCIONES DE REGISTRO
# =====================================================

@router.post("/biometric/register-options")
async def biometric_register_options(
    request: BiometricRegisterOptionsRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Genera las opciones de registro biométrico según el estándar WebAuthn.
    El usuario debe estar autenticado (JWT válido).
    """
    try:
        # Verificar que el email coincide con el usuario autenticado
        if current_user.email.lower() != request.email.lower():
            raise HTTPException(status_code=403, detail="Email no coincide con el usuario autenticado")
        
        challenge = generate_challenge()
        user_id = str(current_user.id)
        
        # Almacenar challenge para verificación posterior
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
        raise HTTPException(status_code=500, detail="Error interno al generar opciones de registro")


# =====================================================
# VERIFICAR REGISTRO CRIPTOGRÁFICAMENTE
# =====================================================

@router.post("/biometric/register-verify")
async def biometric_register_verify(
    request: BiometricRegisterVerifyRequest,
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """
    Verifica criptográficamente una respuesta de registro WebAuthn.
    
    FLUJO:
    1. Recupera el challenge original
    2. Pasa el payload completo a verify_registration_response
    3. La librería extrae y verifica la clave pública automáticamente
    4. Guarda credential_id normalizado + clave pública en BD
    """
    try:
        user_id = str(current_user.id)
        expected_challenge = _challenges.pop(f"reg_{user_id}", None)
        
        if not expected_challenge:
            raise HTTPException(status_code=400, detail="Desafio expirado. Reinicie el registro.")

        # Usar model_dump() para pasar el credential completo a la librería
        credential_dict = request.model_dump()
        
        try:
            verification = verify_registration_response(
                credential=credential_dict,
                expected_challenge=base64url_to_bytes(expected_challenge),
                expected_origin=WEBAUTHN_ORIGIN,
                expected_rp_id=WEBAUTHN_RP_ID,
                require_user_verification=True
            )
        except InvalidRegistrationResponse as e:
            raise HTTPException(status_code=400, detail="Verificacion biometrica fallida. Intente de nuevo.")
        except Exception as e:
            raise HTTPException(status_code=400, detail="Error en la verificacion del dispositivo.")

        # Normalizar credential_id (CANÓNICO - misma representación siempre)
        credential_id_clean = normalize_credential_id(request.rawId)
        
        # La clave pública la extrae la librería automáticamente
        public_key_clean = bytes_to_base64url(verification.credential_public_key)

        # Guardar o actualizar en base de datos
        existente = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).first()
        
        if existente:
            existente.credential_id = credential_id_clean
            existente.public_key = public_key_clean
            existente.sign_count = verification.sign_count
            existente.device_name = "Dispositivo biometrico"
        else:
            nueva = BiometricCredential(
                usuario_id=current_user.id,
                credential_id=credential_id_clean,
                public_key=public_key_clean,
                sign_count=verification.sign_count,
                device_name="Dispositivo biometrico"
            )
            db.add(nueva)
        
        db.commit()
        return {"success": True, "message": "Dispositivo biometrico registrado correctamente"}
        
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error interno al verificar registro")


# =====================================================
# OPCIONES DE LOGIN
# =====================================================

@router.post("/biometric/login-options")
async def biometric_login_options(
    request: BiometricLoginOptionsRequest,
    db: Session = Depends(get_db)
):
    """
    Genera opciones para autenticación biométrica.
    No requiere autenticación previa.
    """
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
            raise HTTPException(status_code=404, detail="No hay registro biometrico para este usuario")
        
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
        raise HTTPException(status_code=500, detail="Error interno al generar opciones de login")


# =====================================================
# VERIFICAR LOGIN (VALIDACIÓN CRIPTOGRÁFICA DE FIRMA)
# =====================================================

@router.post("/biometric/login-verify")
async def biometric_login_verify(
    request: BiometricLoginVerifyRequest,
    db: Session = Depends(get_db)
):
    """
    Verifica criptográficamente una respuesta de autenticación WebAuthn.
    
    FLUJO:
    1. Busca al usuario por email
    2. Recupera el challenge original
    3. Normaliza el credential_id para buscar en BD
    4. Pasa el payload completo a verify_authentication_response
    5. La librería verifica la firma contra la clave pública almacenada
    6. Si es válida: actualiza sign_count (anti-replay) y genera JWT
    """
    try:
        # 1. Buscar usuario por email
        usuario = db.query(Usuario).filter(
            Usuario.email.ilike(request.email),
            Usuario.activo == True
        ).first()
        
        if not usuario:
            raise HTTPException(status_code=401, detail="Credenciales invalidas")
        
        # 2. Recuperar challenge
        expected_challenge = _challenges.pop(f"login_{usuario.email.lower()}", None)
        if not expected_challenge:
            raise HTTPException(status_code=400, detail="Desafio vencido. Intente de nuevo.")

        # 3. Normalizar credential_id para buscar en BD
        normalized_id = normalize_credential_id(request.rawId)
        
        credencial = db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == usuario.id,
            BiometricCredential.credential_id == normalized_id
        ).first()
        
        if not credencial:
            raise HTTPException(status_code=401, detail="Dispositivo biometrico no reconocido")

        # 4. Pasar el payload completo a la librería
        credential_dict = request.model_dump()

        try:
            verification = verify_authentication_response(
                credential=credential_dict,
                expected_challenge=base64url_to_bytes(expected_challenge),
                expected_origin=WEBAUTHN_ORIGIN,
                expected_rp_id=WEBAUTHN_RP_ID,
                credential_public_key=base64url_to_bytes(credencial.public_key),
                credential_current_sign_count=credencial.sign_count,
                require_user_verification=True
            )
        except InvalidAuthenticationResponse as e:
            raise HTTPException(status_code=401, detail="Autenticacion biometrica fallida.")
        except Exception as e:
            raise HTTPException(status_code=401, detail="Error en la verificacion biometrica.")

        # 5. Actualizar sign_count (protección anti-replay)
        credencial.sign_count = verification.new_sign_count
        credencial.last_used_at = datetime.now(timezone.utc)
        db.commit()
        
        # 6. Generar JWT con los datos del usuario
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
        raise HTTPException(status_code=500, detail="Error interno en la verificacion")


# =====================================================
# ELIMINAR REGISTRO
# =====================================================

@router.delete("/biometric/unregister")
async def biometric_unregister(
    db: Session = Depends(get_db),
    current_user: Usuario = Depends(get_current_active_user)
):
    """Elimina el registro biométrico del usuario autenticado."""
    try:
        db.query(BiometricCredential).filter(
            BiometricCredential.usuario_id == current_user.id
        ).delete()
        db.commit()
        return {"success": True, "message": "Registro biometrico eliminado"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail="Error al eliminar el registro")