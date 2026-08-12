from pathlib import Path

import pytest
from synapsekb.document_processing.parsers import NeedsOcrError, parse_document
from synapsekb.document_processing.validation import validate_upload


@pytest.mark.parametrize(
    ("filename", "media_type", "signature"),
    [
        ("scan.jpg", "image/jpeg", b"\xff\xd8\xff\xe0"),
        ("scan.png", "image/png", b"\x89PNG\r\n\x1a\n"),
        ("scan.tiff", "image/tiff", b"II*\x00"),
    ],
)
def test_scanned_image_types_are_validated_and_sent_to_ocr(
    tmp_path: Path,
    filename: str,
    media_type: str,
    signature: bytes,
) -> None:
    path = tmp_path / filename
    path.write_bytes(signature + b"test")
    assert validate_upload(filename, media_type, signature) == filename
    with pytest.raises(NeedsOcrError):
        parse_document(path, filename, media_type)


def test_image_extension_with_wrong_signature_is_rejected() -> None:
    with pytest.raises(ValueError, match="PNG"):
        validate_upload("scan.png", "image/png", b"not a png")


def test_mime_type_must_match_extension() -> None:
    with pytest.raises(ValueError, match="MIME"):
        validate_upload("scan.png", "text/plain", b"\x89PNG\r\n\x1a\n")
