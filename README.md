# callbot —— 外呼机器人（智能体）

「音频流进 → 智能体对话 → 音频流出」的**实时流式语音对话引擎 + 话术编排平台**：全双工打断、三环节模型切换（本地/云端）、可视化流程图编排、行业模板库、工具库、通话记录。

## 技术栈

Python 3.12 / FastAPI / WebSocket / WebRTC(aiortc) / Vue 3 + TypeScript + Vite + Tailwind CSS v4 + vue-flow / PostgreSQL 16 + pgvector / SQLAlchemy 2.x / AgentScope 2.x / DeepSeek / 火山引擎豆包语音 / 千问平台（ASR/TTS）/ FunASR Paraformer（本地 ASR）/ CosyVoice2-0.5B（本地 TTS）/ Silero VAD

## 快速开始（如何启动项目）

### 环境要求

- WSL2 Ubuntu（项目按此环境开发验证）+ NVIDIA GPU（RTX 4060 8GB 即可）
- Docker（PostgreSQL 容器）
- Python 3.12 + [UV](https://docs.astral.sh/uv/)（默认位于 `~/.local/bin/uv`）
- Node 20+（用 [fnm](https://github.com/Schniz/fnm) 管理）
- 系统依赖：`build-essential`（pyworld 需源码编译）

### 1. 安装后端依赖

```bash
uv sync --all-extras        # torch 走 cu126 源；依赖版本互锁，勿随意升级（见 docs/local-models.md）
```

### 2. 配置环境变量

```bash
cp .env.example .env       # .env 不入库，按需填写
```

关键配置（前缀 `CALLBOT_`，优先级：环境变量 > `.env` > 默认值）：

| 变量 | 说明 | 默认 |
|---|---|---|
| `CALLBOT_DB_URL` | PostgreSQL 连接串 | `postgresql://callbot:callbot@localhost:5432/callbot` |
| `CALLBOT_LLM_API_KEY` | DeepSeek API Key（LLM 必需） | 空 |
| `CALLBOT_ASR_KIND` | ASR 环节：`funasr`(本地) \| `volc` \| `qwen` | `funasr` |
| `CALLBOT_TTS_KIND` | TTS 环节：`cosyvoice`(本地) \| `volc` \| `qwen` | `cosyvoice` |
| `CALLBOT_ASR_VOLC_API_KEY` / `CALLBOT_ASR_QWEN_API_KEY` | 云端 ASR Key（火山/千问） | 空 |
| `CALLBOT_ORCHESTRATION_BACKEND` | 编排后端：`agentscope` \| `simple` | `agentscope` |

> 三环节（ASR/LLM/TTS）也可在 Web「线路配置」页面热切换，无需改文件。

### 3. 启动数据库

```bash
docker compose up -d
```

### 4. 启动后端（uvicorn）

```bash
# 运行本地模型（FunASR/CosyVoice2）前必须设置（onnxruntime CUDA provider 依赖）：
export LD_LIBRARY_PATH=$(find .venv/lib/python3.12/site-packages/nvidia -name lib -type d | tr '\n' ':')$LD_LIBRARY_PATH

uv run uvicorn callbot.api.app:create_app --factory --host 0.0.0.0 --port 8000
```

- 首次启动自动建表 + 种子（默认场景/默认人设/示例客户/默认外呼流程/内置工具 kb_search）
- 首次外呼时本地模型加载约 10~20 秒（进程级单例，之后秒开）
- 模型权重：Silero VAD 需 `models/silero_vad.jit`（下载方式见 `docs/local-models.md`；FunASR/CosyVoice2 权重同样见该文档）

### 5. 启动前端（Vite 开发服务器）

```bash
cd frontend
eval "$(fnm env)" && fnm use --install-if-missing
npm install
npm run dev -- --port 5173 --strictPort
```

### 6. 打开管理台

浏览器访问 **http://localhost:5173**（前端经 Vite 代理访问后端 8000 端口）：

1. 「线路配置」确认 ASR/LLM/TTS 走线（无本地 GPU 时全部切云端）
2. 「模板库」一键实例化行业场景（如银行信用卡催收）→ 自动进入流程图可微调
3. 「客户管理」维护外呼客户 → 回到「对话工作台」选场景+客户 → 点「外呼」→ AI 主动开口
4. 说「再见」→ 结束语播完自动挂断；通话记录留档

### 7. 测试与检查

```bash
# 后端（215 用例，依赖 docker postgres）
uv run pytest
uv run ruff check src/callbot tests

# 前端
cd frontend && npm test          # vitest
npm run type-check               # vue-tsc
```

> 云端服务（ASR/TTS/LLM）不进自动化测试，用真实 Key 联调验收。

## 目录结构

```
src/callbot/
├── channel/         # 接入层：WebRTC 信令 + 会话主循环（打断/收尾/落库）
├── engine/          # 语音引擎：VAD 状态机、会话状态机、LLM→TTS 衔接器
├── providers/       # Model Providers：ASR/LLM/TTS 三环节本地↔云端切换
├── orchestration/   # 对话编排层：AgentScope + 共享状态多智能体 + 上下文管理
├── flow/            # 话术引擎：流程图定义/校验 + 意图分类器 + 意图中枢状态机
├── tools/           # 工具系统：代码插件加载器 + Toolkit 装配 + 内置工具
├── templates/       # 行业模板库（营销/催收/回访/通知/客服）
├── api/             # API 层：FastAPI 路由（场景/流程/工具/人设/客户/通话记录/模板）
└── data/            # 数据层：SQLAlchemy 模型 + 变量渲染
frontend/src/        # Vue 3 管理台：对话工作台/流程图编辑器/各管理页
tests/               # pytest 后端测试
```

## 文档

| 文档 | 内容 |
|---|---|
| `docs/PRD.md` | 产品需求文档 |
| `docs/WBS.md` | 工作分解与排期 |
| `docs/local-models.md` | 本地模型部署与关键版本约束（踩坑复盘） |
| `docs/函数注册表.md` | 函数签名索引 |
| `docs/工具插件规范.md` | 代码插件开发约定 |
| `docs/resume/入门文档.md` | 20 分钟了解项目（含通话全生命周期） |
| `docs/resume/架构图集.md` | Mermaid 架构/时序/状态图集 |
| `docs/resume/` | 简历模板与面试问答（技术/非技术） |
| `CLAUDE.md` | 项目偏好与工程约束 |
