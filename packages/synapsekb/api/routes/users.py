from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from synapsekb.api.schemas import (
    KnowledgeBaseMembersRead,
    KnowledgeBaseMembersUpdate,
    UserApprovalDecision,
    UserApprovalRead,
    UserCreate,
    UserRead,
    UserUpdate,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.auth.policy import require_admin, require_super_admin
from synapsekb.auth.security import hash_password
from synapsekb.database.models import (
    AuditLog,
    KnowledgeBase,
    KnowledgeBaseMember,
    User,
    UserApprovalRequest,
)

router = APIRouter()


@router.get("", response_model=list[UserRead])
async def list_users(user: CurrentUser, session: DatabaseSession) -> list[User]:
    require_admin(user)
    return list((await session.scalars(select(User).order_by(User.created_at))).all())


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    user: CurrentUser,
    session: DatabaseSession,
) -> User:
    require_admin(user)
    if user.role != "super_admin" and payload.role != "user":
        raise HTTPException(status_code=403, detail="管理员只能申请添加普通用户")
    email = payload.email.lower()
    if await session.scalar(select(User.id).where(User.email == email)):
        raise HTTPException(status_code=409, detail="邮箱已存在")
    created = User(
        email=email,
        display_name=payload.display_name,
        password_hash=hash_password(payload.password),
        role=payload.role,
        timezone=payload.timezone,
        approval_status="approved" if user.role == "super_admin" else "pending",
        is_active=user.role == "super_admin",
    )
    session.add(created)
    try:
        await session.flush()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="邮箱已存在") from exc
    if created.approval_status == "pending":
        session.add(UserApprovalRequest(user_id=created.id, requested_by_id=user.id))
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="user.create" if created.is_active else "user.approval_requested",
            resource_type="user",
            resource_id=created.id,
            metadata_json={"role": created.role},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return created


@router.get("/approvals", response_model=list[UserApprovalRead])
async def list_approvals(user: CurrentUser, session: DatabaseSession) -> list[UserApprovalRequest]:
    require_admin(user)
    query = select(UserApprovalRequest).order_by(UserApprovalRequest.created_at.desc()).limit(200)
    if user.role != "super_admin":
        query = query.where(UserApprovalRequest.requested_by_id == user.id)
    return list((await session.scalars(query)).all())


@router.post("/approvals/{approval_id}/review", response_model=UserApprovalRead)
async def review_approval(
    approval_id: uuid.UUID,
    payload: UserApprovalDecision,
    user: CurrentUser,
    session: DatabaseSession,
) -> UserApprovalRequest:
    require_super_admin(user)
    approval = await session.scalar(
        select(UserApprovalRequest).where(UserApprovalRequest.id == approval_id).with_for_update()
    )
    if approval is None:
        raise HTTPException(status_code=404, detail="审批请求不存在")
    if approval.status != "pending":
        raise HTTPException(status_code=409, detail="此请求已经审批，请刷新列表")
    target = await session.get(User, approval.user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="申请账号不存在")
    target.approval_status = payload.decision
    target.is_active = payload.decision == "approved"
    approval.status = payload.decision
    approval.reviewed_by_id = user.id
    approval.reviewed_at = datetime.now(UTC)
    approval.review_note = payload.note
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action=f"user.approval_{payload.decision}",
            resource_type="user",
            resource_id=target.id,
            metadata_json={"approval_id": str(approval.id), "note": payload.note},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return approval


@router.get("/knowledge-base-permissions", response_model=list[KnowledgeBaseMembersRead])
async def list_knowledge_base_permissions(
    user: CurrentUser,
    session: DatabaseSession,
) -> list[KnowledgeBaseMembersRead]:
    require_admin(user)
    bases = (
        await session.scalars(
            select(KnowledgeBase)
            .where(KnowledgeBase.lifecycle_status == "active")
            .options(selectinload(KnowledgeBase.members))
            .order_by(KnowledgeBase.name)
        )
    ).all()
    return [
        KnowledgeBaseMembersRead(
            id=kb.id,
            name=kb.name,
            visibility=kb.visibility,
            member_ids=[member.user_id for member in kb.members],
        )
        for kb in bases
    ]


@router.put(
    "/knowledge-base-permissions/{knowledge_base_id}", response_model=KnowledgeBaseMembersRead
)
async def update_knowledge_base_permissions(
    knowledge_base_id: uuid.UUID,
    payload: KnowledgeBaseMembersUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> KnowledgeBaseMembersRead:
    require_admin(user)
    kb = await session.scalar(
        select(KnowledgeBase)
        .where(
            KnowledgeBase.id == knowledge_base_id,
            KnowledgeBase.lifecycle_status == "active",
        )
        .with_for_update()
    )
    if kb is None:
        raise HTTPException(status_code=404, detail="知识库不存在或正在删除")
    members = set(payload.member_ids)
    valid = (
        set(
            (
                await session.scalars(
                    select(User.id).where(
                        User.id.in_(members),
                        User.is_active.is_(True),
                        User.approval_status == "approved",
                    )
                )
            ).all()
        )
        if members
        else set()
    )
    if members != valid:
        raise HTTPException(status_code=422, detail="成员包含未审批、停用或不存在的账号")
    kb.visibility = payload.visibility
    await session.execute(
        delete(KnowledgeBaseMember).where(
            KnowledgeBaseMember.knowledge_base_id == kb.id,
        )
    )
    for member_id in members:
        session.add(
            KnowledgeBaseMember(
                knowledge_base_id=kb.id,
                user_id=member_id,
                created_at=datetime.now(UTC),
            )
        )
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="knowledge_base.members_updated",
            resource_type="knowledge_base",
            resource_id=kb.id,
            metadata_json={
                "visibility": payload.visibility,
                "member_ids": sorted(str(mid) for mid in members),
            },
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return KnowledgeBaseMembersRead(
        id=kb.id,
        name=kb.name,
        visibility=kb.visibility,
        member_ids=list(members),
    )


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> User:
    require_admin(user)
    # Serialize role/activation changes so two reviewers cannot remove the last super admin.
    await session.execute(text("SELECT pg_advisory_xact_lock(hashtext('user-role-management'))"))
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.role != "super_admin" and (target.role != "user" or payload.role not in {None, "user"}):
        raise HTTPException(status_code=403, detail="只有超级管理员可以管理管理员或调整角色")
    if target.approval_status != "approved" and payload.is_active is True:
        raise HTTPException(status_code=409, detail="账号必须通过超级管理员审批后才能启用")
    if target.role == "super_admin" and (
        payload.is_active is False or payload.role not in {None, "super_admin"}
    ):
        another = await session.scalar(
            select(User.id)
            .where(
                User.role == "super_admin",
                User.is_active.is_(True),
                User.id != target.id,
            )
            .limit(1)
        )
        if another is None:
            raise HTTPException(status_code=409, detail="必须保留至少一位启用的超级管理员")
    if target.id == user.id and payload.is_active is False:
        raise HTTPException(status_code=409, detail="不能停用当前登录管理员")
    if target.id == user.id and payload.role == "user":
        raise HTTPException(status_code=409, detail="不能降低当前登录管理员的角色")
    supplied = payload.model_fields_set
    if "display_name" in supplied and payload.display_name is not None:
        target.display_name = payload.display_name
    if "password" in supplied and payload.password is not None:
        target.password_hash = hash_password(payload.password)
    if "role" in supplied and payload.role is not None:
        target.role = payload.role
    if "is_active" in supplied and payload.is_active is not None:
        target.is_active = payload.is_active
    if "timezone" in supplied and payload.timezone is not None:
        target.timezone = payload.timezone
    session.add(
        AuditLog(
            actor_user_id=user.id,
            action="user.update",
            resource_type="user",
            resource_id=target.id,
            metadata_json={"fields": sorted(supplied)},
            created_at=datetime.now(UTC),
        )
    )
    await session.commit()
    return target
