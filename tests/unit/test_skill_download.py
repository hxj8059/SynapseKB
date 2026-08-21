from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest

from synapsekb.api.routes import skills


def test_skill_bundle_contains_all_skill_manifests() -> None:
    with ZipFile(BytesIO(skills.build_skill_archive(skills.SKILL_NAMES))) as archive:
        names = set(archive.namelist())

    for name in skills.SKILL_NAMES:
        assert f"{name}/SKILL.md" in names
        assert f"{name}/agents/openai.yaml" in names


def test_skill_archive_rejects_missing_package(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(skills, "SKILLS_ROOT", tmp_path)

    with pytest.raises(FileNotFoundError, match="Skill 包不存在"):
        skills.build_skill_archive(("synapsekb-shared",))
