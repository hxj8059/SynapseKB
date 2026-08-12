from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, cast

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from synapsekb.storage.config import StorageConfig


class S3ObjectStorage:
    """S3-compatible adapter used for S3, COS and compatible OSS gateways."""

    def __init__(self, config: StorageConfig) -> None:
        self.config = config
        self.bucket = config.bucket
        self.session = aioboto3.Session(
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            region_name=config.region,
        )
        self.options: dict[str, Any] = {
            "endpoint_url": config.service_endpoint,
            "config": Config(
                signature_version="s3v4",
                s3={
                    "addressing_style": (
                        "path" if config.backend == "s3" and config.force_path_style else "virtual"
                    ),
                    "payload_signing_enabled": False,
                },
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        }

    async def put_file(self, key: str, path: Path, content_type: str) -> None:
        async with self.session.client("s3", **self.options) as client:
            with path.open("rb") as handle:
                await client.upload_fileobj(
                    handle,
                    self.bucket,
                    self.config.object_key(key),
                    ExtraArgs={"ContentType": content_type},
                )

    async def read(self, key: str) -> bytes:
        async with self.session.client("s3", **self.options) as client:
            response = await client.get_object(
                Bucket=self.bucket,
                Key=self.config.object_key(key),
            )
            return cast(bytes, await response["Body"].read())

    async def delete(self, key: str) -> None:
        async with self.session.client("s3", **self.options) as client:
            await client.delete_object(Bucket=self.bucket, Key=self.config.object_key(key))

    async def exists(self, key: str) -> bool:
        async with self.session.client("s3", **self.options) as client:
            try:
                await client.head_object(
                    Bucket=self.bucket,
                    Key=self.config.object_key(key),
                )
            except ClientError as exc:
                if exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode") == 404:
                    return False
                raise
            return True

    async def iter_bytes(self, key: str) -> AsyncIterator[bytes]:
        async with self.session.client("s3", **self.options) as client:
            response = await client.get_object(
                Bucket=self.bucket,
                Key=self.config.object_key(key),
            )
            async for chunk in response["Body"].iter_chunks(chunk_size=1024 * 1024):
                yield chunk

    async def presign_upload(self, key: str, content_type: str, expires_seconds: int = 900) -> str:
        options = {**self.options, "endpoint_url": self.config.endpoint}
        async with self.session.client("s3", **options) as client:
            return cast(
                str,
                await client.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": self.bucket,
                        "Key": self.config.object_key(key),
                        "ContentType": content_type,
                    },
                    ExpiresIn=expires_seconds,
                ),
            )

    async def presign_download(self, key: str, expires_seconds: int = 300) -> str:
        options = {**self.options, "endpoint_url": self.config.endpoint}
        async with self.session.client("s3", **options) as client:
            return cast(
                str,
                await client.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": self.bucket, "Key": self.config.object_key(key)},
                    ExpiresIn=expires_seconds,
                ),
            )
