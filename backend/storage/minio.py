from __future__ import annotations

import io
from pathlib import Path

from minio import Minio


class MinioObjectStorage:
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ) -> None:
        self._client = Minio(
            endpoint=endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )
        self._bucket = bucket

    def put_bytes(self, key: str, data: bytes, *, content_type: str = "application/octet-stream") -> None:
        self._client.put_object(
            bucket_name=self._bucket,
            object_name=key,
            data=io.BytesIO(data),
            length=len(data),
            content_type=content_type,
        )

    def get_bytes(self, key: str) -> bytes:
        response = self._client.get_object(
            bucket_name=self._bucket,
            object_name=key,
        )
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def put_file(self, key: str, path: Path, *, content_type: str = "application/octet-stream") -> None:
        self._client.fput_object(
            bucket_name=self._bucket,
            object_name=key,
            file_path=str(path),
            content_type=content_type,
        )
