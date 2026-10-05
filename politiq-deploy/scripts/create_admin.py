"""Usage: python -m scripts.create_admin you@example.com 'strong-password'"""
import asyncio
import sys

from sqlalchemy import select

from app.core.security import hash_password
from app.db.session import SessionLocal
from app.models.platform import Role, User


async def main(email: str, password: str) -> None:
    async with SessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email.lower()))
        if u:
            u.role = Role.ADMIN
        else:
            db.add(User(email=email.lower(), hashed_password=hash_password(password), role=Role.ADMIN))
        await db.commit()
    print("admin ready:", email)


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2]))
