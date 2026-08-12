from __future__ import annotations

import base64
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from synapsekb.auth.security import decrypt_secret
from synapsekb.config import get_settings
from synapsekb.database.models import SystemSetting

OCR_SETTING_KEY = "ocr.paddle"
OCR_SECRET_CONTEXT = "setting:ocr.paddle"


@dataclass(frozen=True, slots=True)
class PaddleOcrConfig:
    base_url: str | None
    api_key: str
    default_model: str
    timeout_seconds: int
    max_concurrency: int
    source: str


async def load_paddle_ocr_config(session: AsyncSession) -> PaddleOcrConfig:
    setting = await session.get(SystemSetting, OCR_SETTING_KEY)
    if setting is not None:
        value = setting.value
        encrypted = value.get("encrypted_api_key")
        api_key = (
            decrypt_secret(
                base64.urlsafe_b64decode(encrypted),
                context=OCR_SECRET_CONTEXT,
            )
            if isinstance(encrypted, str) and encrypted
            else ""
        )
        return PaddleOcrConfig(
            base_url=str(value["base_url"]).rstrip("/") if value.get("base_url") else None,
            api_key=api_key,
            default_model=str(value.get("default_model") or "PaddleOCR-VL-1.6"),
            timeout_seconds=int(value.get("timeout_seconds") or 60),
            max_concurrency=int(value.get("max_concurrency") or 2),
            source="database",
        )
    settings = get_settings()
    return PaddleOcrConfig(
        base_url=settings.paddleocr_base_url.rstrip("/") if settings.paddleocr_base_url else None,
        api_key=settings.paddleocr_api_key.get_secret_value(),
        default_model="PaddleOCR-VL-1.6",
        timeout_seconds=60,
        max_concurrency=settings.paddleocr_max_concurrency,
        source="environment",
    )
