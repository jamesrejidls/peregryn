"""
Database models and session management.
Uses SQLite for local development; switch DATABASE_URL to Postgres for production.
"""
import os
import json
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, Integer, String, Text, DateTime, ForeignKey, JSON
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./app.db")

# Render and Heroku give a "postgres://..." URL, but SQLAlchemy 2.x requires "postgresql://...".
# Normalize the prefix so either works.
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# SQLite needs check_same_thread=False; Postgres doesn't.
# For Postgres, enable pre-ping so dropped connections are silently retried instead of erroring.
if DATABASE_URL.startswith("sqlite"):
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    datasets = relationship("Dataset", back_populates="owner", cascade="all, delete-orphan")


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(255), nullable=False)
    source_type = Column(String(20), nullable=False)  # 'csv' or 'text'
    row_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="datasets")
    items = relationship("FeedbackItem", back_populates="dataset", cascade="all, delete-orphan")
    insights = relationship("Insight", back_populates="dataset", cascade="all, delete-orphan")


class FeedbackItem(Base):
    __tablename__ = "feedback_items"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    content = Column(Text, nullable=False)
    user_label = Column(String(255), nullable=True)  # email or name from CSV
    extra_metadata = Column(JSON, nullable=True)  # any other CSV columns

    dataset = relationship("Dataset", back_populates="items")


class Insight(Base):
    __tablename__ = "insights"
    id = Column(Integer, primary_key=True, index=True)
    dataset_id = Column(Integer, ForeignKey("datasets.id"), nullable=False)
    rank = Column(Integer)  # 1-5
    title = Column(String(500))
    description = Column(Text)
    frequency = Column(Integer)
    affected_users = Column(String(500))
    emotional_tone = Column(String(255))
    recommendation = Column(Text)
    citations = Column(JSON)  # list of feedback_item IDs
    sentiment_summary = Column(JSON, nullable=True)  # {"positive": 30, "neutral": 40, "negative": 30}
    trending_topics = Column(JSON, nullable=True)  # list of strings
    created_at = Column(DateTime, default=datetime.utcnow)

    dataset = relationship("Dataset", back_populates="insights")
    prds = relationship("PRD", back_populates="insight", cascade="all, delete-orphan")


class PRD(Base):
    __tablename__ = "prds"
    id = Column(Integer, primary_key=True, index=True)
    insight_id = Column(Integer, ForeignKey("insights.id"), nullable=False)
    title = Column(String(500))
    problem_statement = Column(Text)
    who_affected = Column(Text)
    success_metrics = Column(JSON)  # list of strings
    user_stories = Column(JSON)  # list of strings
    acceptance_criteria = Column(JSON)  # list of strings
    created_at = Column(DateTime, default=datetime.utcnow)

    insight = relationship("Insight", back_populates="prds")
    tasks = relationship("DevTask", back_populates="prd", cascade="all, delete-orphan")


class DevTask(Base):
    __tablename__ = "dev_tasks"
    id = Column(Integer, primary_key=True, index=True)
    prd_id = Column(Integer, ForeignKey("prds.id"), nullable=False)
    title = Column(String(500))
    context = Column(Text)
    acceptance_criteria = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    prd = relationship("PRD", back_populates="tasks")


def init_db():
    Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
