# 项目交接提示词（给接续开发的 Claude）

---

## 0. 环境

- 开发环境：**WSL2 Ubuntu**（已确认 GPU 直通：NVIDIA GeForce RTX 4060 Laptop，`nvidia-smi` 可用）。
- 项目已复制到 WSL 内；该目录已有 git 仓库（main 分支，2 个 commit），保留历史，**不要重建**。
- git 身份配置：`javacaoyu` / `javacaoyu@163.com`。

## 1. 项目一句话

外呼机器人（智能体）——「音频流进 → 智能体对话 → 音频流出」的**实时流式语音对话引擎 + 话术编排平台**，可对外售卖，支持**本地/云端模型切换**。

## 2. 已敲定的需求基线（不要重新讨论，除非用户主动改）

| 维度 | 定案 |
|---|---|
| 产品内核 | 媒体无关的实时流式语音对话引擎 |
| 场景 | 通用：营销 / 催收 / 回访 / 通知 / 客服 |
| 售卖模式 | SaaS 多租户 + 私有化 license（同一套代码） |
| 目标市场 | 中国大陆（合规为刚需） |
| 呼叫通道 | 先不打真电话；Web/WebRTC 流式进出；后期接云通讯厂商 API |
| 对话模式 | 全双工 + 打断（P1 先半双工，P2 上全双工） |
| 模型切换 | ASR / LLM / TTS 三环节**独立**切换本地↔云端 |
| 交付形态 | Web 网页 + API/SDK + 桌面/移动 App（后期） |
| 技术栈 | Python（PEP 8，类型注解完整） |
| Web 实时音频 | WebRTC（aiortc） |
| 数据库 | PostgreSQL 16 + pgvector（Docker Compose，WSL Ubuntu） |
| LLM 编排 | AgentScope（纯文字进出）；语音引擎 + 接入层自建 |
| 并发规模 | 起步 ≤ 几十路，架构留扩展 |
| 开发期模型 | LLM=DeepSeek（云端）；ASR=FunASR Paraformer（本地流式）；TTS=CosyVoice2-0.5B（本地流式） |
| 检索 | Embedding=BGE-M3；Rerank=BGE-reranker；向量库=pgvector |
| 资源 | 单人开发，无时间限制 |

## 3. 关键技术决策（已达成共识，Claude 必须遵守）

1. **AgentScope 定位**：只做「纯文字进、纯文字出」的 LLM 编排层（提示词/上下文/状态/记忆/工具/RAG）。语音引擎自建，接入层（流式调用、关流、换 URL）自建。不要用 AgentScope 的语音/端到端方案（其级联方案尚未稳定，且依赖云端闭源 API，与本地/私有化冲突）。
2. **三环节切换 = 配置驱动**：ASR/LLM/TTS/Embedding/Rerank 各一个 Provider 接口；本地↔云端切换 = 换 `base_url + api_key + model`（全部 OpenAI 兼容），配置放 `provider_config`，Web 后台可改。
3. **全双工 + 打断**：打断 = ①立即停 TTS 音频播放 ②接入层关流/取消 task 停止 LLM 生成 ③用「机器人已完整说出的句子」+ 用户新话重建上下文（被打断的半句丢弃，可调）。打断「停止生成」在接入层完成，与编排层无关。
4. **延迟优先（核心指标是 TTFT）**：
   - 感知目标：TTFT < 500ms（命中缓存 < 300ms）；TTS 首包 < 300ms；打断响应 < 150ms；端到端 < 1s。
   - 首 token 即触发 TTS 合成；精简且稳定的 Prompt 前缀（利用 DeepSeek 上下文缓存 / vLLM prefix caching）；上下文滑窗+摘要；限制生成长度（max_tokens 128~256）。
   - RAG 侧：FAQ 精确匹配优先；pgvector HNSW + 小 top-k（20~50）；rerank 只算召回集、高置信度跳过；检索缓存 + 预取；分块 200~500 token。
   - 后期做「边说边想」预响应流水线（partial 实时预检索/预生成，final 确认后续用或作废）。
5. **知识库（FAQ + RAG）**：FAQ 精确匹配优先 → pgvector 向量 + tsvector 关键词混合检索 → BGE-reranker 重排 → top-k（带引用）→ 拼入 LLM 上下文。金融/银行安全：**无据则拒答并转人工，答案必须可溯源**。
6. **本地模型硬件结论**：RTX 4060 8GB 可同时跑 FunASR(Paraformer 流式) + CosyVoice2-0.5B；TTS 必须选 0.5B 流式版，避开 GPT-SoVITS/ChatTTS/F5-TTS 等非流式方案。CosyVoice2 安装属 WBS 1.3（源码 + 模型权重），不属 1.1。
7. **合规内置**：录音留存/回放、时段/频次/黑名单、敏感词与违规话术拦截。

## 4. 文档与文件位置

| 文件 | 内容 |
|---|---|
| `docs/PRD.md` | 产品需求文档 v1.0（功能 P0/P1/P2、非功能需求、技术架构、5.2 延迟优化设计） |
| `docs/WBS.md` | WBS 工作分解与排期 v1.1（10 阶段，117.5 人日，约 25 周理想） |
| `AGENTS.md` | 项目级偏好（技术栈/分层/关键设计/开发环境/提交约定） |
| `pyproject.toml` | 依赖配置（核心 + web/audio/db/dev 分组，torch 走 cu121 源） |
| `.python-version` | 锁定 3.12 |
| `.gitignore` | 忽略 `.uv-cache/`、`.uv-python/`、模型权重、录音、`.env` 等 |

## 5. 当前进度

- 仅产出PRD和WBS文档



## 6. 关键数字

- 总工作量 117.5 人日；理想 25 周，含 1.4 倍缓冲约 35 周（约 9 个月）。
- 首个可演示里程碑 M2（第 5 周末，Web Demo 半双工对话）；可售卖 M10（第 25 周末）。
- 延迟目标：TTFT < 500ms、TTS 首包 < 300ms、打断 < 150ms、端到端 < 1s。
