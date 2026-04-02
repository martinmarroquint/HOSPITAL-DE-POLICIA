import os
import shutil
import uuid
from pathlib import Path
from fastapi import UploadFile, HTTPException
from typing import List, Optional
from datetime import datetime
import boto3
from botocore.exceptions import ClientError

from app.config import settings

# Configuración S3 (opcional)
s3_client = None
if settings.AWS_ACCESS_KEY_ID and settings.AWS_SECRET_ACCESS_KEY:
    s3_client = boto3.client(
        's3',
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        region_name=settings.AWS_REGION
    )

async def save_upload_file(upload_file: UploadFile, subfolder: str = "general") -> str:
    """
    Guarda un archivo subido y retorna la URL
    """
    # Validar extensión
    file_ext = os.path.splitext(upload_file.filename)[1].lower()
    if file_ext not in settings.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Extensión no permitida. Permisos: {settings.ALLOWED_EXTENSIONS}"
        )
    
    # Validar tamaño (leyendo el contenido)
    contents = await upload_file.read()
    file_size = len(contents)
    if file_size > settings.MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"Archivo demasiado grande. Máximo: {settings.MAX_UPLOAD_SIZE} bytes"
        )
    
    # Resetear el puntero del archivo
    await upload_file.seek(0)
    
    # Generar nombre único
    unique_filename = f"{uuid.uuid4().hex}{file_ext}"
    
    # Si está configurado S3, subir a S3
    if s3_client and settings.AWS_S3_BUCKET:
        return await upload_to_s3(upload_file, unique_filename, subfolder)
    else:
        # Subida local
        return await upload_local(upload_file, unique_filename, subfolder)

async def upload_to_s3(upload_file: UploadFile, filename: str, subfolder: str) -> str:
    """Sube archivo a S3 y retorna URL"""
    try:
        # Crear key con subcarpeta
        key = f"{subfolder}/{filename}"
        
        # Subir a S3
        s3_client.upload_fileobj(
            upload_file.file,
            settings.AWS_S3_BUCKET,
            key,
            ExtraArgs={'ACL': 'public-read'}
        )
        
        # Generar URL
        url = f"https://{settings.AWS_S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"
        return url
    
    except ClientError as e:
        raise HTTPException(status_code=500, detail=f"Error subiendo a S3: {str(e)}")

async def upload_local(upload_file: UploadFile, filename: str, subfolder: str) -> str:
    """Guarda archivo localmente y retorna URL"""
    # Crear directorio si no existe
    upload_dir = Path(settings.UPLOAD_PATH) / subfolder
    upload_dir.mkdir(parents=True, exist_ok=True)
    
    # Ruta completa del archivo
    file_path = upload_dir / filename
    
    # Guardar archivo
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(upload_file.file, buffer)
    
    # Retornar URL relativa (para servir con FastAPI)
    return f"/uploads/{subfolder}/{filename}"

def delete_file(file_url: str):
    """Elimina un archivo por su URL"""
    if file_url.startswith("http"):
        # Es una URL de S3, extraer key
        if s3_client and settings.AWS_S3_BUCKET:
            try:
                # Extraer key de la URL
                key = "/".join(file_url.split("/")[3:])
                s3_client.delete_object(Bucket=settings.AWS_S3_BUCKET, Key=key)
            except ClientError as e:
                print(f"Error eliminando de S3: {e}")
    else:
        # Es archivo local
        file_path = Path(".") / file_url.lstrip("/")
        if file_path.exists():
            file_path.unlink()