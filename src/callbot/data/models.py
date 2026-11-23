"""数据模型（WBS 5.3）：通话记录表。

SQLAlchemy 2.x 声明式；create_all 启动建表（无迁移框架，表结构演进
时手动 ALTER）。transcript 存 JSONB 气泡流：[{role, text, ts}]。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String, Text, create_engine
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from callbot.config import Settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """声明式基类。"""


class CallRecord(Base):
    """一通通话的记录（含转写气泡流；录音路径 8.1 接入）。"""

    __tablename__ = "call_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_s: Mapped[int] = mapped_column(Integer, default=0)
    # connected（接通并有对话）/ no_answer（无有效转写）/ error（异常断开）
    status: Mapped[str] = mapped_column(String(16), default="connected")
    interrupt_count: Mapped[int] = mapped_column(Integer, default=0)
    # 转写气泡流：[{role: user|bot|mark, text, ts}]
    transcript: Mapped[list] = mapped_column(JSONB, default=list)
    # 录音文件路径（8.1 录音留存接入时填充）
    audio_path: Mapped[str | None] = mapped_column(Text, nullable=True)


def get_engine(settings: Settings | None = None):
    """创建 DB 引擎（psycopg3 驱动）。"""
    cfg = settings or Settings()
    return create_engine(cfg.db_url.replace("postgresql://", "postgresql+psycopg://"))


class Persona(Base):
    """人设（WBS 6.1）：外呼机器人的角色设定与 system prompt 模板。

    is_active 唯一激活（当前会话使用）；首次启动种子一条默认人设。
    """

    __tablename__ = "personas"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


def init_db(settings: Settings | None = None) -> None:
    """建表（幂等 create_all）+ 种子默认人设。"""
    engine = get_engine(settings)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        if session.query(Persona).count() == 0:
            from callbot.orchestration.context import DEFAULT_SYSTEM_PROMPT

            session.add(
                Persona(
                    name="默认客服",
                    description="通用外呼客服：简洁、礼貌、口语化",
                    system_prompt=DEFAULT_SYSTEM_PROMPT,
                    is_active=True,
                )
            )
            session.commit()
            logger.info("已种子默认人设")


def save_call_record(
    record: CallRecord,
    settings: Settings | None = None,
) -> None:
    """落库一条通话记录（独立短连接，会话线程调用）。"""
    with Session(get_engine(settings), expire_on_commit=False) as session:
        session.add(record)
        session.commit()
