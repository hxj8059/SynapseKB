from __future__ import annotations

import re
from pathlib import Path

ALLOWED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".md",
    ".markdown",
    ".txt",
    ".html",
    ".htm",
    ".jpg",
    ".jpeg",
    ".png",
    ".tif",
    ".tiff",
}
SAFE_FILENAME = re.compile(r"[^0-9A-Za-z\u4e00-\u9fff._ -]+")
EXPECTED_MEDIA_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".md": {"text/markdown", "text/plain"},
    ".markdown": {"text/markdown", "text/plain"},
    ".txt": {"text/plain"},
    ".html": {"text/html", "application/xhtml+xml"},
    ".htm": {"text/html", "application/xhtml+xml"},
    ".jpg": {"image/jpeg"},
    ".jpeg": {"image/jpeg"},
    ".png": {"image/png"},
    ".tif": {"image/tiff"},
    ".tiff": {"image/tiff"},
}


def safe_filename(filename: str) -> str:
    name = Path(filename).name
    cleaned = SAFE_FILENAME.sub("_", name).strip(" .")
    if not cleaned or cleaned in {".", ".."}:
        raise ValueError("文件名无效")
    return cleaned[:240]


def validate_upload(filename: str, media_type: str, first_bytes: bytes) -> str:
    name = safe_filename(filename)
    suffix = Path(name).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise ValueError("不支持的文件类型")
    normalized_media_type = media_type.partition(";")[0].strip().lower()
    if normalized_media_type and normalized_media_type != "application/octet-stream":
        expected = EXPECTED_MEDIA_TYPES[suffix]
        if normalized_media_type not in expected:
            raise ValueError("文件 MIME 类型与扩展名不一致")
    if suffix == ".pdf" and not first_bytes.startswith(b"%PDF-"):
        raise ValueError("文件内容不是有效 PDF")
    if suffix in {".docx", ".xlsx", ".pptx"} and not first_bytes.startswith(b"PK"):
        raise ValueError("Office 文件结构无效")
    if suffix in {".jpg", ".jpeg"} and not first_bytes.startswith(b"\xff\xd8\xff"):
        raise ValueError("文件内容不是有效 JPEG")
    if suffix == ".png" and not first_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("文件内容不是有效 PNG")
    if suffix in {".tif", ".tiff"} and not first_bytes.startswith((b"II*\x00", b"MM\x00*")):
        raise ValueError("文件内容不是有效 TIFF")
    if "\x00" in first_bytes.decode("utf-8", errors="ignore") and suffix in {
        ".txt",
        ".md",
        ".markdown",
        ".html",
        ".htm",
    }:
        raise ValueError("文本文件包含无效二进制内容")
    return name
