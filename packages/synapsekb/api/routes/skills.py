from __future__ import annotations

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from synapsekb.auth.dependencies import CurrentUser

router = APIRouter()

SKILL_NAMES = (
    "synapsekb-shared",
    "synapsekb-rag-search",
    "synapsekb-temporal-research",
    "synapsekb-wiki",
)
SKILLS_ROOT = Path(__file__).resolve().parents[4] / "skills"


def build_skill_archive(skill_names: tuple[str, ...]) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        for skill_name in skill_names:
            skill_path = SKILLS_ROOT / skill_name
            if not (skill_path / "SKILL.md").is_file():
                raise FileNotFoundError(f"Skill 包不存在: {skill_name}")
            for path in sorted(skill_path.rglob("*")):
                if path.is_file():
                    archive.write(path, f"{skill_name}/{path.relative_to(skill_path)}")
    return buffer.getvalue()


def archive_response(content: bytes, filename: str) -> Response:
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/bundle")
async def download_skill_bundle(user: CurrentUser) -> Response:
    del user
    try:
        return archive_response(build_skill_archive(SKILL_NAMES), "synapsekb-skills.zip")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Skill 包尚未部署到 API 服务") from exc


@router.get("/{skill_name}/download")
async def download_skill(skill_name: str, user: CurrentUser) -> Response:
    del user
    if skill_name not in SKILL_NAMES:
        raise HTTPException(status_code=404, detail="Skill 不存在")
    try:
        return archive_response(build_skill_archive((skill_name,)), f"{skill_name}.zip")
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="Skill 包尚未部署到 API 服务") from exc
