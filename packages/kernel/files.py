"""File storage on MinIO (S3 API) and the upload gate. Files are keyed by content hash."""

import io
import os
from dataclasses import dataclass
from uuid import UUID

import boto3
from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import ClientError

from kernel.canonical import sha256_hex
from kernel.errors import SecurityCheckUnavailable, ValidationFailed

BUCKET = "astrarh"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".docx": "application/docx",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".htm": "text/html",
}
TEXT_SUFFIXES = {".txt", ".md", ".html", ".htm"}

_client: BaseClient | None = None


@dataclass(frozen=True)
class StoredFile:
    key: str
    sha256: str
    content_type: str
    size: int


def _s3() -> BaseClient:
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=os.environ["S3_ENDPOINT"],
            aws_access_key_id=os.environ["S3_ACCESS_KEY"],
            aws_secret_access_key=os.environ["S3_SECRET_KEY"],
            region_name="us-east-1",
            config=Config(connect_timeout=3, read_timeout=30, retries={"max_attempts": 2}),
        )
        try:
            _client.head_bucket(Bucket=BUCKET)
        except ClientError:
            _client.create_bucket(Bucket=BUCKET)
    return _client


def check_upload(filename: str, data: bytes) -> str:
    """Decide by content, never by the name or type the client claims."""
    if not data:
        raise ValidationFailed(f"{filename}: the file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValidationFailed(f"{filename}: larger than {MAX_UPLOAD_BYTES // 1024 // 1024} MB")
    suffix = os.path.splitext(filename.lower())[1]
    if suffix not in ALLOWED_TYPES:
        raise ValidationFailed(f"{filename}: only PDF, DOCX, HTML, Markdown and TXT are accepted")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise ValidationFailed(f"{filename}: this is not a real PDF")
    if suffix == ".docx" and not data.startswith(b"PK"):
        raise ValidationFailed(f"{filename}: this is not a real DOCX")
    if suffix in TEXT_SUFFIXES:
        if b"\x00" in data:
            raise ValidationFailed(f"{filename}: this is not a text file")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValidationFailed(f"{filename}: text files must be UTF-8") from exc
    return ALLOWED_TYPES[suffix]


def put(tenant_id: UUID, filename: str, data: bytes) -> StoredFile:
    content_type = check_upload(filename, data)
    digest = sha256_hex(data)
    key = f"{tenant_id}/{digest}"
    try:
        _s3().upload_fileobj(io.BytesIO(data), BUCKET, key, ExtraArgs={"ContentType": content_type})
    except ClientError as exc:
        raise SecurityCheckUnavailable("File storage is unavailable") from exc
    return StoredFile(key=key, sha256=digest, content_type=content_type, size=len(data))


def get(tenant_id: UUID, key: str) -> bytes:
    """A key from another tenant is refused even if a bug passes one in."""
    if not key.startswith(f"{tenant_id}/"):
        raise ValidationFailed("This file belongs to another tenant")
    buffer = io.BytesIO()
    _s3().download_fileobj(BUCKET, key, buffer)
    return buffer.getvalue()
