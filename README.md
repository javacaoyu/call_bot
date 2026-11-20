# callbot —— 外呼机器人（智能体）

「音频流进 → 智能体对话 → 音频流出」的**实时流式语音对话引擎 + 话术编排平台**，可对外售卖（SaaS 多租户 + 私有化 license，同一套代码）。

## 技术栈

Python 3.12 / FastAPI / WebRTC(aiortc) / PostgreSQL 16 + pgvector / AgentScope（纯文字编排）/ FunASR / CosyVoice2-0.5B / BGE-M3

## 快速开始

```bash
# 1. 安装依赖（torch 走 cu126 源，需 NVIDIA GPU）
uv sync --all-extras

# 2. 启动数据库（PostgreSQL 16 + pgvector）
docker compose up -d

# 3. 运行本地模型前必须设置（onnxruntime CUDA provider 依赖）：
export LD_LIBRARY_PATH=$(find .venv/lib/python3.12/site-packages/nvidia -name lib -type d | tr '\n' ':')$LD_LIBRARY_PATH

# 4. 运行测试
uv run pytest
```

> 系统依赖：`build-essential`（pyworld 编译）。模型权重与第三方源码不入库，部署方法见 `docs/local-models.md`。

## 目录结构

```
src/callbot/
├── channel/         # 接入层：WebRTC 等媒体通道
├── engine/          # 语音引擎：VAD/打断、会话状态机、流式 ASR/TTS
├── orchestration/   # 对话编排层：AgentScope（纯文字）
├── providers/       # Model Providers：本地 ↔ 云端切换
├── business/        # 业务层：话术/知识库/音色/合规/多租户
├── data/            # 数据层：PostgreSQL + pgvector
└── api/             # API 层：FastAPI 路由
```

## 文档

| 文档 | 内容 |
|---|---|
| `docs/PRD.md` | 产品需求文档 |
| `docs/WBS.md` | 工作分解与排期 |
| `docs/local-models.md` | 本地模型部署与关键版本约束 |
| `docs/函数注册表.md` | 函数签名索引 |
| `CLAUDE.md` | 项目偏好与工程约束 |
