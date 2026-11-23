"""数据模型（WBS 5.3）：通话记录表。

SQLAlchemy 2.x 声明式；create_all 启动建表（无迁移框架，表结构演进
时手动 ALTER）。transcript 存 JSONB 气泡流：[{role, text, ts}]。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, create_engine, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from callbot.config import Settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    """声明式基类。"""


class CallRecord(Base):
    """一通通话的记录（含转写气泡流；录音路径 8.1 接入）。"""

    __tablename__ = "call_records"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
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

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text)
    # 开场白模板（6.2）：外呼连接后 AI 首先说的话；支持客户变量隐式注入，
    # 空串表示未配置（由 LLM 按人设兜底生成）
    opening: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(default=False)
    # 场景（6.3）：从场景库选择（非手填）；外呼时按场景过滤人设
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenes.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Customer(Base):
    """外呼客户（6.2）：外呼前选择，变量插槽的姓名/电话数据源。"""

    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(20))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Scene(Base):
    """场景（6.3）：话术资产组织单元——流程图/人设/工具都挂在场景下。"""

    __tablename__ = "scenes"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Tool(Base):
    """工具（6.3）：场景工具库，handler 子智能体绑定使用。

    kind: http（配置式：config 存 URL/方法/参数表/header，热生效）
        | plugin（代码插件：config 存插件名，启动加载）
    """

    __tablename__ = "tools"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("scenes.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    kind: Mapped[str] = mapped_column(String(16), default="http")
    config: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Flow(Base):
    """话术流程图（6.3）：一场景一流程（scene_id 唯一）。

    draft：草稿（编辑中，不影响线上）；published：发布快照（新会话使用）；
    version 发布版本号。定义 schema 见 callbot/flow/definitions.py。
    """

    __tablename__ = "flows"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    scene_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scenes.id", ondelete="CASCADE"),
        unique=True,
    )
    name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    draft: Mapped[dict] = mapped_column(JSONB, default=dict)
    published: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=0)
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class FlowVersion(Base):
    """流程图发布历史快照（6.3）：回滚 = 历史快照重新发布为新版本。"""

    __tablename__ = "flow_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    flow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("flows.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    definition: Mapped[dict] = mapped_column(JSONB)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


def init_db(settings: Settings | None = None) -> None:
    """建表（幂等 create_all）+ 种子：默认场景 / 默认人设 / 示例客户 / 默认流程。"""
    engine = get_engine(settings)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        # 场景（6.3）：种子默认场景（人设/流程/工具的归属根）
        default_scene = session.scalars(
            select(Scene).where(Scene.name == "通用客服").limit(1)
        ).first()
        if default_scene is None:
            default_scene = Scene(name="通用客服", description="默认场景：通用外呼客服话术")
            session.add(default_scene)
            session.flush()
            logger.info("已种子默认场景")
        if session.query(Persona).count() == 0:
            from callbot.orchestration.context import DEFAULT_SYSTEM_PROMPT

            session.add(
                Persona(
                    name="默认客服",
                    description="通用外呼客服：简洁、礼貌、口语化",
                    system_prompt=DEFAULT_SYSTEM_PROMPT,
                    is_active=True,
                    scene_id=default_scene.id,
                )
            )
            session.commit()
            logger.info("已种子默认人设")
        if session.query(Customer).count() == 0:
            for name, phone, notes in [
                ("陈女士", "13800002047", "理财回访场景示例客户"),
                ("王先生", "13900001182", "产品介绍场景示例客户"),
                ("李女士", "13700004503", "续费提醒场景示例客户"),
            ]:
                session.add(Customer(name=name, phone=phone, notes=notes))
            session.commit()
            logger.info("已种子 3 条示例客户")
        # 默认外呼流程（6.3）：开场白(空=6.2 双轨) → 意图识别 → 主对话 → 结束语；
        # 直接以 v1 发布（未选流程的场景/兼容 6.2 行为）
        if session.query(Flow).count() == 0:
            from callbot.flow.definitions import build_default_flow

            definition = build_default_flow()
            now = datetime.now(UTC)
            flow = Flow(
                scene_id=default_scene.id,
                name="默认外呼流程",
                description="开场白 → 意图识别 → 主对话 → 结束语（兼容 6.2 行为）",
                draft=definition,
                published=definition,
                version=1,
                published_at=now,
            )
            session.add(flow)
            session.flush()
            session.add(
                FlowVersion(
                    flow_id=flow.id, version=1, definition=definition, published_at=now
                )
            )
            session.commit()
            logger.info("已种子默认外呼流程（v1 已发布）")


def save_call_record(
    record: CallRecord,
    settings: Settings | None = None,
) -> None:
    """落库一条通话记录（独立短连接，会话线程调用）。"""
    with Session(get_engine(settings), expire_on_commit=False) as session:
        session.add(record)
        session.commit()
