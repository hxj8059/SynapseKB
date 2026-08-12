from __future__ import annotations

from fastapi import APIRouter, Query
from sqlalchemy import select

from synapsekb.api.schemas import AuditLogRead, OperationTaskRead
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_admin
from synapsekb.database.models import (
    AgentRun,
    AuditLog,
    ProcessingJob,
    ProviderModel,
    WikiHealthJob,
    WikiUpdateJob,
)

router = APIRouter()


@router.get("/tasks", response_model=list[OperationTaskRead])
async def list_tasks(
    user: CurrentUser,
    session: DatabaseSession,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0, le=100_000),
    category: str = Query(
        default="all",
        pattern="^(all|document|agent|wiki_update|wiki_health)$",
    ),
) -> list[OperationTaskRead]:
    require_admin(user)
    query_limit = limit + offset if category == "all" else limit
    query_offset = 0 if category == "all" else offset
    processing = (
        list(
            (
                await session.scalars(
                    select(ProcessingJob)
                    .order_by(ProcessingJob.created_at.desc())
                    .offset(query_offset)
                    .limit(query_limit)
                )
            ).all()
        )
        if category in {"all", "document"}
        else []
    )
    agents = (
        list(
            (
                await session.scalars(
                    select(AgentRun)
                    .order_by(AgentRun.created_at.desc())
                    .offset(query_offset)
                    .limit(query_limit)
                )
            ).all()
        )
        if category in {"all", "agent"}
        else []
    )
    wiki = (
        list(
            (
                await session.scalars(
                    select(WikiUpdateJob)
                    .order_by(WikiUpdateJob.created_at.desc())
                    .offset(query_offset)
                    .limit(query_limit)
                )
            ).all()
        )
        if category in {"all", "wiki_update"}
        else []
    )
    wiki_health = (
        list(
            (
                await session.scalars(
                    select(WikiHealthJob)
                    .order_by(WikiHealthJob.created_at.desc())
                    .offset(query_offset)
                    .limit(query_limit)
                )
            ).all()
        )
        if category in {"all", "wiki_health"}
        else []
    )
    wiki_model_ids = {
        item.model_id for item in wiki if item.model_id is not None
    } | {
        item.model_id for item in wiki_health if item.model_id is not None
    }
    wiki_model_names = {
        model.id: model.name
        for model in (
            (
                await session.scalars(
                    select(ProviderModel).where(ProviderModel.id.in_(wiki_model_ids))
                )
            ).all()
            if wiki_model_ids
            else []
        )
    }
    tasks = [
        OperationTaskRead(
            id=item.id,
            task_type=f"document.{item.job_type}",
            resource_id=item.document_id,
            status=item.status,
            stage=item.stage,
            progress=item.progress,
            error_summary=item.error_summary,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in processing
    ]
    tasks.extend(
        OperationTaskRead(
            id=item.id,
            task_type="agent.run",
            resource_id=item.agent_id,
            status=item.status,
            stage=None,
            progress=None,
            error_summary=item.error_summary,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in agents
    )
    tasks.extend(
        OperationTaskRead(
            id=item.id,
            task_type="wiki.update",
            resource_id=item.space_id,
            status=item.status,
            stage=(
                "document_analysis"
                if item.status == "running"
                else item.status
            ),
            progress=(
                float(processed_count) / float(expected_count)
                if expected_count > 0
                else None
            ),
            model_id=item.model_id,
            model_name=(wiki_model_names.get(item.model_id) if item.model_id else None),
            summary=item.change_summary,
            error_summary=item.error_summary,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in wiki
        for coverage in [item.quality_report.get("document_coverage", {})]
        for expected_count in [
            int(coverage.get("expected_document_count", 0) or 0)
            if isinstance(coverage, dict)
            else 0
        ]
        for processed_count in [
            int(coverage.get("processed_document_count", 0) or 0)
            if isinstance(coverage, dict)
            else 0
        ]
    )
    tasks.extend(
        OperationTaskRead(
            id=item.id,
            task_type="wiki.health",
            resource_id=item.space_id,
            status=item.status,
            stage=item.status,
            progress=None,
            model_id=item.model_id,
            model_name=(wiki_model_names.get(item.model_id) if item.model_id else None),
            summary=(
                str(item.report.get("summary"))
                if item.report and item.report.get("summary")
                else None
            ),
            error_summary=item.error_summary,
            created_at=item.created_at,
            updated_at=item.updated_at,
        )
        for item in wiki_health
    )
    ordered = sorted(tasks, key=lambda item: item.created_at, reverse=True)
    return ordered[offset : offset + limit] if category == "all" else ordered


@router.get("/audit", response_model=list[AuditLogRead])
async def list_audit_logs(
    user: CurrentUser,
    session: DatabaseSession,
    limit: int = Query(default=100, ge=1, le=500),
) -> list[AuditLog]:
    require_admin(user)
    return list(
        (
            await session.scalars(
                select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit)
            )
        ).all()
    )
