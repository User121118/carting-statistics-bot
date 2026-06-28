from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import config
from db.models import Base, Race, RaceResult, User

engine = create_async_engine(config.DATABASE_URL, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_or_create_user(
    telegram_id: int,
    username: Optional[str],
    first_name: Optional[str],
) -> User:
    async with Session() as session:
        result = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = result.scalar_one_or_none()
        if not user:
            user = User(
                telegram_id=telegram_id,
                username=username,
                first_name=first_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        return user


async def create_race(
    race_number: Optional[int],
    start_time: Optional[datetime],
    venue: Optional[str],
) -> Race:
    async with Session() as session:
        race = Race(race_number=race_number, start_time=start_time, venue=venue)
        session.add(race)
        await session.commit()
        await session.refresh(race)
        return race


async def save_result(
    user_id: int,
    race_id: int,
    kart_number: str,
    position: Optional[int],
    best_lap: Optional[float],
    avg_lap: Optional[float],
    lap_times: list,
) -> RaceResult:
    async with Session() as session:
        result = RaceResult(
            user_id=user_id,
            race_id=race_id,
            kart_number=kart_number,
            position=position,
            best_lap=best_lap,
            avg_lap=avg_lap,
            lap_times=lap_times,
        )
        session.add(result)
        await session.commit()
        await session.refresh(result)
        return result


async def get_last_result(telegram_id: int) -> Optional[RaceResult]:
    async with Session() as session:
        user_row = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_row.scalar_one_or_none()
        if not user:
            return None
        row = await session.execute(
            select(RaceResult)
            .where(RaceResult.user_id == user.id)
            .order_by(RaceResult.created_at.desc())
            .limit(1)
        )
        return row.scalar_one_or_none()


async def get_best_result(telegram_id: int) -> Optional[RaceResult]:
    async with Session() as session:
        user_row = await session.execute(
            select(User).where(User.telegram_id == telegram_id)
        )
        user = user_row.scalar_one_or_none()
        if not user:
            return None
        row = await session.execute(
            select(RaceResult)
            .where(RaceResult.user_id == user.id)
            .order_by(RaceResult.best_lap.asc())
            .limit(1)
        )
        return row.scalar_one_or_none()
