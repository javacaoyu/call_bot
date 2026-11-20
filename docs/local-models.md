# 本地模型部署说明（WBS 1.3）

> 更新时间：2026-11-20 ｜ 状态：**三模型全部跑通 ✅**（FunASR / CosyVoice2 / BGE，均经 TTS→ASR 回路实测）

## 1. 模型清单与位置

| 模型 | 用途 | 位置 | 来源 |
|---|---|---|---|
| paraformer-large_asr_nat-zh-cn-16k-online | 流式 ASR | `models/paraformer-zh-streaming/` | ModelScope `iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online` |
| CosyVoice2-0.5B | 流式 TTS | `third_party/CosyVoice/pretrained_models/CosyVoice2-0.5B/` | ModelScope `iic/CosyVoice2-0.5B` |
| bge-m3 | Embedding | `models/bge-m3/` | HF `BAAI/bge-m3`（hf-mirror 下载） |
| bge-reranker-base | Rerank | `models/bge-reranker-base/` | HF `BAAI/bge-reranker-base`（hf-mirror 下载） |

> 源码克隆：`third_party/CosyVoice`（FunAudioLLM/CosyVoice）、`third_party/Matcha-TTS`（shivammehta25/Matcha-TTS）。模型权重与源码均不入库（.gitignore：`models/`、`third_party/`）。

## 2. 关键版本约束（血的教训，勿动）

- **torch / torchaudio 锁定 `==2.11.0`（cu126 源）**：驱动 560.94 上限 CUDA 12.6 → 只能用 cu126；而 cu126 源 torchaudio 最高 2.11.0，故 torch 必须同为 2.11.0。
- **transformers 锁定 `==4.51.3`**：CosyVoice2 的 LLM 权重是 BFloat16，transformers 5.x 在 fp32 模式不归一化 dtype → `mat1 and mat2 must have the same dtype (Float vs BFloat16)` 崩溃 / fp16 下生成退化。
- **sentence-transformers `<5.3`**：6.x 依赖 transformers 5.x 的 `is_kernels_available`，与上一条互斥；5.2.3 验证可用。
- **torchcodec `==0.11.1`**：torchaudio 2.11 解码依赖它，且必须与 torch 2.11 ABI 匹配（0.17 等新版不兼容）。
- **onnxruntime-gpu `==1.20.2`**：1.32 需 CUDA 13（本机不支持）；1.18 与 numpy 2.x ABI 冲突。
- **wetext `==0.0.4`**：CosyVoice2 文本前端。0.2.1 会导致 token 数量异常、生成时长失控（实测 3s → 17.6s）。
- **matcha 不装 pip 包**：PyPI 元数据带 gradio→websockets<12 与项目冲突，仓库 pyproject 过旧无法构建。以源码形式放 `third_party/Matcha-TTS` 并加入 `sys.path`。
- **pyworld 需源码编译**：系统必须装 `build-essential`（`sudo apt-get install -y build-essential`）。
- **必须设置 `LD_LIBRARY_PATH` 指向 torch 自带的 nvidia pip 库**，否则 onnxruntime 的 CUDA provider 找不到 libcublasLt/libcudnn，flow 落到 CPU（RTF 7~10，且产出坏 latent 导致合成乱语）：

```bash
export LD_LIBRARY_PATH=$(find .venv/lib/python3.12/site-packages/nvidia -name lib -type d | tr '\n' ':')$LD_LIBRARY_PATH
```

## 3. 验证结果（全部 ✅）

| 模型 | 验证方式 | 结果 |
|---|---|---|
| FunASR 流式 | 官方示例音频 600ms/块流式送入 | ✅ 转写完美「欢迎大家来体验达摩院推出的语音识别模型」，RTF ~0.06 |
| CosyVoice2-0.5B | instruct2 流式合成 + ASR 回路 | ✅ 转写与原文完全一致；fp16/fp32 均正确；流式 3 块输出，稳态 RTF ~0.5–1.1 |
| BGE-M3 | 句子向量化 + 相似度排序 | ✅ 排序正确（0.764/0.521/0.414），加载 2.9s |
| bge-reranker-base | 3 候选重排打分 | ✅ 0.979/0.039/0.0，加载 1.6s |

## 4. CosyVoice2 乱语问题复盘（已全部修复）

| # | 根因 | 修复 |
|---|---|---|
| 1 | `inference_instruct2` 的 instruct 文本缺 `<|endofprompt|>` 结束标记 → LLM 无限生成 | 调用方式：instruct 文本必须以 `<|endofprompt|>` 结尾 |
| 2 | wetext 0.2.1 文本规范化异常 | pin `wetext==0.0.4` |
| 3 | transformers 5.23 与 BFloat16 权重不兼容（fp32 直接崩溃，fp16 生成退化） | pin `transformers==4.51.3` |
| 4 | onnxruntime CUDA provider 加载失败，flow 在 CPU 上跑出坏 latent | pin `onnxruntime-gpu==1.20.2` + 设置 `LD_LIBRARY_PATH`（见 §2） |

## 5. 快速验证命令

```bash
# TTS（一次合成一句，输出 /tmp/cosyvoice_test.wav）
export LD_LIBRARY_PATH=$(find .venv/lib/python3.12/site-packages/nvidia -name lib -type d | tr '\n' ':')$LD_LIBRARY_PATH
uv run python /tmp/cosyvoice_t2s.py
# ASR 回路（转写 /tmp/cosyvoice_test.wav）
uv run python /tmp/funasr_test.py
```

## 6. 延迟观测（初测，正式调优在阶段 9）

- TTS 首块 ~3.5–4.4s（含模型加载 + 预热；稳态 chunk RTF 0.5–1.1，后续可优化）
- ASR 流式 RTF 0.06，性能余量充足
- 显存：单模型常驻 FunASR + CosyVoice2 可行（与 HANDOFF 结论一致）；BGE 按需加载
