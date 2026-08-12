from __future__ import annotations

import uuid
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Query, Response
from sqlalchemy import select

from synapsekb.api.schemas import (
    ChatCitationRead,
    ChatMessageRead,
    ChatSessionDetail,
    ChatSessionRead,
    ChatSessionUpdate,
)
from synapsekb.auth.dependencies import CurrentUser, DatabaseSession
from synapsekb.database.models import ChatMessage, ChatSession, Chunk, MessageCitation

router = APIRouter()


async def _owned_session(
    session: DatabaseSession,
    user: CurrentUser,
    session_id: uuid.UUID,
) -> ChatSession:
    chat_session = await session.scalar(
        select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == user.id,
        )
    )
    if chat_session is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return chat_session


@router.get("", response_model=list[ChatSessionRead])
async def list_chat_sessions(
    user: CurrentUser,
    session: DatabaseSession,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[ChatSession]:
    return list(
        (
            await session.scalars(
                select(ChatSession)
                .where(ChatSession.user_id == user.id)
                .order_by(ChatSession.updated_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ).all()
    )


@router.get("/{session_id}", response_model=ChatSessionDetail)
async def get_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> ChatSessionDetail:
    chat_session = await _owned_session(session, user, session_id)
    messages = list(
        (
            await session.scalars(
                select(ChatMessage)
                .where(ChatMessage.session_id == chat_session.id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).all()
    )
    grouped: dict[uuid.UUID, list[ChatCitationRead]] = defaultdict(list)
    if messages:
        citations = list(
            (
                await session.execute(
                    select(MessageCitation, Chunk.document_id)
                    .outerjoin(Chunk, Chunk.id == MessageCitation.chunk_id)
                    .where(MessageCitation.message_id.in_([item.id for item in messages]))
                    .order_by(
                        MessageCitation.message_id,
                        MessageCitation.citation_number,
                    )
                )
            ).all()
        )
        for citation, document_id in citations:
            grouped[citation.message_id].append(
                ChatCitationRead(
                    citation_number=citation.citation_number,
                    chunk_id=citation.chunk_id,
                    document_id=document_id,
                    document_title=citation.document_title,
                    page_from=citation.page_from,
                    page_to=citation.page_to,
                    section=citation.section,
                    original_text=citation.original_text,
                    source_time=citation.source_time,
                )
            )
    return ChatSessionDetail(
        **ChatSessionRead.model_validate(chat_session).model_dump(),
        messages=[
            ChatMessageRead(
                **ChatMessageRead.model_validate(message).model_dump(exclude={"citations"}),
                citations=grouped[message.id],
            )
            for message in messages
        ],
    )


@router.patch("/{session_id}", response_model=ChatSessionRead)
async def update_chat_session(
    session_id: uuid.UUID,
    payload: ChatSessionUpdate,
    user: CurrentUser,
    session: DatabaseSession,
) -> ChatSession:
    chat_session = await _owned_session(session, user, session_id)
    chat_session.title = payload.title
    await session.commit()
    await session.refresh(chat_session)
    return chat_session


@router.delete("/{session_id}", status_code=204)
async def delete_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> Response:
    chat_session = await _owned_session(session, user, session_id)
    await session.delete(chat_session)
    await session.commit()
    return Response(status_code=204)


@router.get("/{session_id}/export")
async def export_chat_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    session: DatabaseSession,
) -> Response:
    detail = await get_chat_session(session_id, user, session)
    lines = [f"# {detail.title}", ""]
    for message in detail.messages:
        lines.extend(
            [
                "## 用户" if message.role == "user" else "## SynapseKB",
                "",
                message.content,
                "",
            ]
        )
        if message.citations:
            lines.extend(["### 引用", ""])
            for citation in message.citations:
                time_label = (
                    citation.source_time.isoformat() if citation.source_time else "时间未知"
                )
                page_label = (
                    f"第 {citation.page_from} 页" if citation.page_from is not None else "页码未知"
                )
                lines.append(
                    f"- [{citation.citation_number}] {citation.document_title}；"
                    f"{page_label}；source_time: {time_label}"
                )
            lines.append("")
    content = "\n".join(lines)
    return Response(
        content=content,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": (
                f'attachment; filename="synapsekb-chat-{chat_session_filename(session_id)}.md"'
            )
        },
    )


def chat_session_filename(session_id: uuid.UUID) -> str:
    return str(session_id)
