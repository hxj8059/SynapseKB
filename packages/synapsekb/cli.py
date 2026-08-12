from __future__ import annotations

import asyncio
import getpass

import typer
from sqlalchemy import select

from synapsekb.auth.security import hash_password
from synapsekb.database.models import User
from synapsekb.database.session import AsyncSessionFactory

app = typer.Typer(help="SynapseKB administration commands")


async def _create_admin(email: str, name: str, password: str) -> None:
    async with AsyncSessionFactory() as session:
        normalized = email.lower()
        if await session.scalar(select(User.id).where(User.email == normalized)):
            raise typer.BadParameter("该邮箱已存在")
        user = User(
            email=normalized,
            display_name=name,
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
        )
        session.add(user)
        await session.commit()


@app.command("create")
def create_admin(
    email: str = typer.Option(..., help="管理员邮箱"),
    name: str = typer.Option("管理员", help="显示名称"),
) -> None:
    password = getpass.getpass("管理员密码（至少 12 个字符）: ")
    confirmation = getpass.getpass("再次输入密码: ")
    if password != confirmation:
        raise typer.BadParameter("两次密码不一致")
    asyncio.run(_create_admin(email, name, password))
    typer.echo(f"已创建管理员 {email.lower()}")
