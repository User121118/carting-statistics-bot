from datetime import datetime
from sqlalchemy import BigInteger, Column, DateTime, Float, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    telegram_id = Column(BigInteger, unique=True, nullable=False, index=True)
    username = Column(String, nullable=True)
    first_name = Column(String, nullable=True)
    racer_name = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    results = relationship("RaceResult", back_populates="user")


class Race(Base):
    __tablename__ = "races"

    id = Column(Integer, primary_key=True)
    race_number = Column(Integer, nullable=True)
    start_time = Column(DateTime, nullable=True)
    venue = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    results = relationship("RaceResult", back_populates="race")


class RaceResult(Base):
    __tablename__ = "race_results"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    race_id = Column(Integer, ForeignKey("races.id"), nullable=False)
    kart_number = Column(String, nullable=False)
    position = Column(Integer, nullable=True)
    best_lap = Column(Float, nullable=True)
    avg_lap = Column(Float, nullable=True)
    lap_times = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="results")
    race = relationship("Race", back_populates="results")
