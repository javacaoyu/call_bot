# 项目偏好（外呼机器人）

> 本文件记录本项目专属偏好；通用偏好见用户级 `~/.claude/CLAUDE.md`。两者冲突时，本文件优先。

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

## 音频链路约束（实测教训，勿走回头路）

- **Web 端音频传输必须走 PCM 直传**：浏览器 `AudioContext(16000)` 采集 → int16 二进制帧经信令 WebSocket 直传后端 → 引擎。**不要用 aiortc 音轨承载音频**——本环境（联想立体声麦克风阵列 + Chrome）下 aiortc 的 opus 解码输出损坏音频（48k 假标签 + 逐样本重复，听感「慢放猪叫」，ASR 完全无法识别）；WebRTC 仅用于连接建立（offer/answer/ICE）。
- **getUserMedia 约束**：`echoCancellation/noiseSuppression/autoGainControl = false`；设备默认优先真实麦克风（排除 LegionZone 等虚拟设备）。
- **paraformer 在线模型输出约定**：每 chunk 吐「增量文本」，完整转写 = 全部增量拼接；`is_final=True` **不会**释放解码器扣住的句尾（表现为尾字延迟到下次说话）——收尾必须三段式：剩余真实音频（非 final）→ 追喂 2 块静音释放句尾 → 静音块 final 收尾 → reset。`engine.flush_asr()` 已实现，勿简化为单次 final。
- **静音自动收尾**：后端监测 PCM 流，静音超 0.8s 触发 flush（正式 VAD 在 WBS 3.1 接入）。

## 开发环境（本项目）

- Python 用 UV；Docker 在 WSL Ubuntu；开发机 GPU 为 RTX 4060 8GB。
- 本地只跑 ASR/TTS（FunASR + CosyVoice2-0.5B），LLM 走云端 DeepSeek。

## 依赖与运行约束（血的教训，勿动）

> 完整复盘见 `docs/local-models.md`。以下 pin 均经 WBS 1.3 实测踩坑得出，**不得随意升级**：

- torch / torchaudio **==2.11.0**（cu126 源）：驱动 560.94 上限 CUDA 12.6 → 只能用 cu126；cu126 源 torchaudio 最高 2.11.0，故 torch 必须同为 2.11.0。
- transformers **==4.51.3**：CosyVoice2 LLM 权重为 BFloat16；5.x 在 fp32 下 dtype 崩溃、fp16 下生成退化。
- sentence-transformers **<5.3**：6.x 依赖 transformers 5.x 的 `is_kernels_available`，与上条互斥。
- wetext **==0.0.4**（CosyVoice2 文本前端，0.2.1 致 token 异常）；torchcodec **==0.11.1**（torchaudio 2.11 ABI 匹配）；onnxruntime-gpu **==1.20.2**（1.32 需 CUDA 13，本机不支持；1.18 与 numpy 2 ABI 冲突）。
- matcha 不装 pip 包：源码放 `third_party/Matcha-TTS` 并加入 sys.path（PyPI 元数据带 gradio→websockets<12 与项目冲突，仓库 pyproject 亦过旧）。

**运行本地模型前必须设置**（否则 onnxruntime CUDA provider 找不到 CUDA 库，flow 落 CPU → 坏 latent → 合成乱语）：

```bash
export LD_LIBRARY_PATH=$(find .venv/lib/python3.12/site-packages/nvidia -name lib -type d | tr '\n' ':')$LD_LIBRARY_PATH
```

**CosyVoice2 调用约束**：`inference_instruct2` 的 instruct 文本必须以 `<|endofprompt|>` 结尾（缺 → LLM 无限生成）；0.5B 模型无内置音色，必须传 prompt_wav 参考音频。

**系统依赖**：`build-essential`（pyworld 需源码编译）；uv 实际位于 `~/.local/bin/uv`（非交互 shell 的 PATH 可能不含 `~/.local/bin`，命令用完整路径）。

## 工程操作教训

- **uv sync 会重置 venv** 为 pyproject+lock 的声明集合：临时 `uv pip install` 的包若不写进 pyproject，下次 sync 会被清掉。
- **后台任务命令不要接管道**（`| tail` 等会掩盖退出码，已两次误判「失败」为「成功」）；大模型下载/安装任务完成后必须核对输出文件确认真成功。
- pkill -f 的模式会匹配自身 shell 命令行导致误杀自己，改用精确 PID 或进程名。
- Bash 会话的 cwd 会漂移（`cd` 不持久，background 命令的 cd 不生效）：运行 pytest/uv/git 前先 `cd /home/caoyu/call_bot` 或检查当前目录（在 frontend/ 下跑 pytest 会「收集 0 个测试」、相对模型路径会失效）。

## 提交约定

- 提交信息遵循 Conventional Commits。
- 不直接提交到 main（新功能先开分支，遵循用户级 Git 规范）。
- 新增文件类型需判断是否加入 `.gitignore`；录音、模型权重、`.env` 不入库。
