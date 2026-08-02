"""User / Role repository (phase B2, DEV_SPEC B2)."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fiat_agent.users.models import Role, User, UserRole


class UserRepository:
    """Async CRUD for users and roles.

    Methods take an ``AsyncSession`` so they are trivially testable with a
    temporary sqlite database and reusable inside the API layer.
    """

    async def create_user(
        self,
        session: AsyncSession,
        *,
        username: str,
        display_name: str = "",
        email: str = "",
        enabled: bool = True,
        id: str | None = None,
    ) -> User:
        user = User(
            id=id or uuid4().hex,
            username=username,
            display_name=display_name,
            email=email,
            enabled=enabled,
        )
        session.add(user)
        await session.flush()
        return user

    async def get(self, session: AsyncSession, user_id: str) -> User | None:
        return await session.get(User, user_id)

    async def get_by_username(
        self, session: AsyncSession, username: str
    ) -> User | None:
        result = await session.execute(select(User).where(User.username == username))
        return result.scalar_one_or_none()

    async def set_enabled(
        self, session: AsyncSession, user_id: str, enabled: bool
    ) -> User | None:
        user = await session.get(User, user_id)
        if user is None:
            return None
        user.enabled = enabled
        await session.flush()
        return user

    async def create_role(
        self,
        session: AsyncSession,
        *,
        name: str,
        description: str = "",
        id: str | None = None,
    ) -> Role:
        role = Role(id=id or uuid4().hex, name=name, description=description)
        session.add(role)
        await session.flush()
        return role

    async def get_role(self, session: AsyncSession, role_id: str) -> Role | None:
        return await session.get(Role, role_id)

    async def assign_role(
        self,
        session: AsyncSession,
        user_id: str,
        role_id: str,
        granted_by: str | None = None,
    ) -> UserRole:
        link = UserRole(user_id=user_id, role_id=role_id, granted_by=granted_by)
        session.add(link)
        await session.flush()
        return link

    async def list_roles(self, session: AsyncSession, user_id: str) -> list[Role]:
        result = await session.execute(
            select(Role)
            .join(UserRole, Role.id == UserRole.role_id)
            .where(UserRole.user_id == user_id)
        )
        return list(result.scalars().all())
