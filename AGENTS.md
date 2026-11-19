# 项目偏好（外呼机器人）

> 本文件记录本项目专属偏好；通用偏好见用户级 `~/.dsh/AGENTS.md`。两者冲突时，本文件优先。

## 项目定位

- 产品：外呼机器人（智能体）——「音频流进 → 智能体对话 → 音频流出」的实时流式语音对话引擎 + 话术编排平台。
- 权威文档：`docs/PRD.md`（产品需求）、`docs/WBS.md`（工作分解与排期）。

## 技术栈（固定）

- 语言：Python（PEP 8，类型注解完整）
- Web/API：FastAPI + WebSocket
- Web 实时音频：WebRTC（aiortc）
- 数据库：PostgreSQL 16 + pgvector（Docker Compose，WSL Ubuntu）
- LLM 编排：AgentScope（纯文字进出）
- 语音引擎：自建（VAD → 流式 ASR → 流式 TTS）
- 开发期模型：LLM=DeepSeek（云端）、ASR=FunASR Paraformer（本地）、TTS=CosyVoice2-0.5B（本地）
- 检索：Embedding=BGE-M3、Rerank=BGE-reranker、向量库=pgvector
- 前端：Web（React/Vue）+ WebRTC

## 分层约定

- 分层：接入层（Channel）/ 语音引擎 / 对话编排层（AgentScope）/ 接入层（Provider 调用）/ Model Providers / 业务层 / 数据层。
- 文档统一放 `docs/`；代码与 PRD/WBS 保持同步。

## 本项目关键设计约定

1. 三环节独立切换：ASR / LLM / TTS 各一个 Provider 接口；本地↔云端 = 换 `base_url + api_key + model`（OpenAI 兼容），配置驱动、Web 可改。
2. 全双工 + 打断：打断 = 立即停 TTS 音频 + 接入层关流停止 LLM 生成 + 用「已完整说出的句子」重建上下文（半句丢弃，可调）。
3. 延迟优先：TTFT 为第一指标；首 token 即触发 TTS；稳定前缀 + Prompt 缓存；上下文管控；RAG 侧 FAQ 优先 + HNSW 小 top-k + rerank 跳过 + 检索缓存；后期做「边说边想」预响应。
4. 合规内置：录音留存、时段/频次/黑名单、敏感词拦截。
5. 媒体无关：内核只处理 PCM 音频帧 + 文本事件，电话通道作为后期 Adapter 接入。

## 开发环境（本项目）

- Python 用 UV；Docker 在 WSL Ubuntu；开发机 GPU 为 RTX 4060 8GB。
- 本地只跑 ASR/TTS（FunASR + CosyVoice2-0.5B），LLM 走云端 DeepSeek。

## 提交约定

- 提交信息遵循 Conventional Commits。
- 不直接提交到 main（新功能先开分支，遵循用户级 Git 规范）。
- 新增文件类型需判断是否加入 `.gitignore`；录音、模型权重、`.env` 不入库。
