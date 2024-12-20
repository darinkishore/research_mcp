import asyncio
import datetime
import os
from contextlib import asynccontextmanager

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, String, Text, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, relationship


# Create async database engine - note the async sqlite driver
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///results.db')
engine = create_async_engine(
    DATABASE_URL,
    future=True,
)


# Create async database engine - note the async sqlite driver
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite+aiosqlite:///results.db')
engine = create_async_engine(
    DATABASE_URL,
    future=True,
    connect_args={
        'check_same_thread': False,
    },
)


# Set journal_mode to WAL upon connection
def set_sqlite_pragma(dbapi_connection, connection_record):
    # dbapi_connection is a synchronous connection
    cursor = dbapi_connection.cursor()
    cursor.execute('PRAGMA journal_mode=WAL')
    cursor.close()


# Listen for the 'connect' event to set PRAGMA


event.listen(engine.sync_engine, 'connect', set_sqlite_pragma)


# Create async sessionmaker
AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


# Create base class for declarative models
class Base(DeclarativeBase):
    pass


class Result(Base):
    """Database model for research results."""

    __tablename__ = 'results'

    id = Column(String, primary_key=True)
    title = Column(Text, nullable=True)
    author = Column(Text, nullable=True)
    url = Column(Text, nullable=True)

    # Summaries
    dense_summary = Column(Text, nullable=False)
    relevance_summary = Column(Text, nullable=False)

    # Content
    text = Column(Text, nullable=False)

    # Relevance
    relevance_score = Column(Float, nullable=False)

    # Query Context
    query_purpose = Column(Text, nullable=False)
    query_question = Column(Text, nullable=False)

    published_date = Column(Text, nullable=True)

    # Metadata
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now(tz=datetime.UTC))
    updated_at = Column(
        DateTime,
        nullable=False,
        default=datetime.datetime.now(tz=datetime.UTC),
        onupdate=datetime.datetime.now(tz=datetime.UTC),
    )

    # Relationships
    query_results = relationship('QueryResult', back_populates='result', lazy='selectin')


class ExaQuery(Base):
    """Database model for Exa queries."""

    __tablename__ = 'exa_queries'

    id = Column(Integer, primary_key=True, autoincrement=True)
    query_text = Column(Text, nullable=False)
    category = Column(String, nullable=True)
    livecrawl = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.datetime.now(tz=datetime.UTC))

    # Relationships
    query_results = relationship('QueryResult', back_populates='exa_query', lazy='selectin')


class QueryResult(Base):
    """Database model for query-result relationships."""

    __tablename__ = 'query_results'

    query_id = Column(Integer, ForeignKey('exa_queries.id'), primary_key=True)
    result_id = Column(String, ForeignKey('results.id'), primary_key=True)

    # Relationships
    exa_query = relationship('ExaQuery', back_populates='query_results', lazy='selectin')
    result = relationship('Result', back_populates='query_results', lazy='selectin')


@asynccontextmanager
async def db():
    """Database session context manager."""
    try:
        async with AsyncSessionLocal() as session:
            try:
                yield session
                await session.commit()
            except asyncio.CancelledError:
                await session.rollback()
                raise
            except Exception:
                await session.rollback()
                raise
    except Exception:
        raise


# Create all tables asynchronously
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
