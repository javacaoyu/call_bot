"""千问平台（通义 DashScope）实时语音识别云端实现。

协议要点（官方文档 api-reference/speech-recognition/qwen-audio-asr-streaming）：
- wss://maas.qianwenaiapi.com/api-ws/v1/inference，Authorization: Bearer $KEY；
- 任务事件：run-task（配置模型/格式）→ task-started → 二进制 PCM 帧 →
  result-generated（**句级修订语义**：sentence_end 标记最终句，heartbeat 心跳）
  → finish-task → task-finished；任务级协议，连接可复用重开新任务。

结果归一化：服务端 text 为「当前句全文」（中间结果会修订）——实现内部维护
句子 map，emit 统一为「最终句增量（text，进 utterance）+ 页面快照（snapshot，
已确认句 + 当前句预览，前端替换显示）」。
"""

from __future__ import annotations

import json
import logging
import uuid

from callbot.providers.asr import ASRResult
from callbot.providers.cloud.base_cloud import CloudASRBase

logger = logging.getLogger(__name__)

_URL = "wss://maas.qianwenaiapi.com/api-ws/v1/inference"
_MODEL = "qwen-audio-3.1-asr-flash-streaming"
_SAMPLE_RATE = 16000


def build_qwen_asr_event(action: str, task_id: str, model: str) -> str:
    """构造 DashScope ASR 任务事件（run-task / finish-task）。

    ⚠️ 必须返回 str：服务端只认文本帧，二进制帧会被静默忽略（实测教训）。
    """
    payload: dict = {
        "task_group": "audio",
        "task": "asr",
        "function": "recognition",
        "model": model,
        "parameters": {"format": "pcm", "sample_rate": _SAMPLE_RATE},
        "input": {},
    }
    if action == "finish-task":
        payload = {"input": {}}
    return json.dumps(
        {
            "header": {"action": action, "task_id": task_id, "streaming": "duplex"},
            "payload": payload,
        }
    )


class QwenStreamingASR(CloudASRBase):
    """千问实时语音识别（Qwen-Audio-ASR-Streaming）云端实现。

    长连接 + 任务级协议：flush 发 finish-task 触发句尾最终结果；下一轮
    音频前重发 run-task（新任务）。
    """

    _keep_connection = True

    def __init__(self, api_key: str, model: str = _MODEL) -> None:
        super().__init__()
        self._api_key = api_key
        self._model = model
        self._task_id = ""
        # 任务串行化：服务端要求上一任务 task-finished 后才能开新任务
        # （finish 后立即 run-task 会被拒：任务失败 {} + 会话重建，实测）
        self._task_done = True
        # 句级修订归一化：已定稿句 id 集合（去重）+ 当前句预览。
        # 快照语义 = 仅当前句（修订式）——历史定稿句不进快照，
        # 否则新一轮转写会显示「上轮句+当前句」前缀（实测 bug）。
        self._finalized_ids: set[int] = set()
        self._current_id: int | None = None
        self._current_text = ""


    # -- 协议钩子 --
    def _build_url(self) -> str:
        return _URL

    def _handshake_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _start_frame(self) -> str:
        self._task_id = uuid.uuid4().hex[:32]
        self._task_done = False
        return build_qwen_asr_event("run-task", self._task_id, self._model)

    def _encode_audio(self, data: bytes) -> bytes | None:
        """裸 PCM 二进制帧；纯静音块返回 None（跳过发送）。

        千问是任务级协议：finish-task 即收尾，不靠静音判停。浏览器持续
        发送的静音 PCM 若照发会触发无意义的新任务，并与上一任务收尾
        竞态（实测：任务失败 + 连接重建）。静音只存在于音频流中，
        真正语音块不会全零（麦克风底噪非零）。
        """
        if not data or not any(data):
            return None
        return data

    def _final_frames(self) -> list[str | bytes]:
        """判停静音 + finish-task：触发服务端收尾并推句尾最终结果。

        先补发 1.2s 静音帧触发服务端 VAD 判停（max_sentence_silence），
        最终句随之推来（settle 窗口内可达）；finish-task 收尾兜底。
        若不补静音，finish 后服务端处理延迟 2-3s，最终句错过收尾窗口
        （实测：无回复）。

        同时重置句状态（新一轮基线）。
        """
        logger.info("千问 finish-task: %s", self._task_id)
        self._finalized_ids.clear()
        self._current_id = None
        self._current_text = ""
        silence = b"\x00" * (16000 * 2 * 600 // 1000)  # 600ms @16k PCM16
        return [
            silence,
            silence,
            build_qwen_asr_event("finish-task", self._task_id, self._model),
        ]

    def _final_frame_interval_s(self) -> float:
        """静音帧后等判停窗口再发 finish-task（否则判停不生效）。"""
        return 0.8

    def _resume_frames(self) -> list[str]:
        """新任务：finish 后继续说话需重新 run-task（同连接复用）。"""
        self._task_id = uuid.uuid4().hex[:32]
        self._task_done = False
        logger.info("千问 run-task（新任务）: %s", self._task_id)
        return [build_qwen_asr_event("run-task", self._task_id, self._model)]

    def _resume_ready(self) -> bool:
        """上一任务收尾（task-finished/failed）后才可重开任务。

        非阻塞：任务事件由同一线程 recv 循环解析（task-finished 置
        _task_done），未就绪时 sender 跳过本轮发送继续 recv。
        """
        return self._task_done

    # -- 结果解析（句级修订 → 最终句增量 + 快照） --
    def _parse_message(self, raw: bytes | str) -> ASRResult | None:
        if isinstance(raw, bytes):
            return None  # 音频不回传；结果均为文本帧
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return None
        header = msg.get("header") or {}
        event = header.get("event")
        if event == "task-failed":
            status = (msg.get("payload") or {}).get("output") or {}
            logger.error("千问 ASR 任务失败: %s", json.dumps(status, ensure_ascii=False)[:200])
            self._task_done = True  # 失败也视为收尾完成，允许下一任务
            return None
        if event in ("task-started", "task-finished"):
            if event == "task-finished":
                self._task_done = True  # 允许下一任务
            logger.info("千问 %s: %s", event, header.get("task_id"))
            return None
        if event != "result-generated":
            return None
        sentence = ((msg.get("payload") or {}).get("output") or {}).get("sentence") or {}
        logger.info("千问结果: end=%s text=%r", sentence.get("sentence_end"), sentence.get("text"))
        if sentence.get("heartbeat") or not sentence.get("text"):
            return None
        sid = sentence.get("sentence_id")
        text = sentence["text"]
        if sentence.get("sentence_end"):
            # 最终句定稿：同句重复跳过；新句 emit 句文本（增量进 utterance）
            if sid is not None:
                if sid in self._finalized_ids:
                    return None
                self._finalized_ids.add(sid)
            self._current_id = None
            self._current_text = ""
            return ASRResult(text=text, is_final=True, snapshot=text)
        # 中间结果：快照仅当前句（修订式替换显示），text 空增量
        self._current_id = sid
        self._current_text = text
        return ASRResult(text="", is_final=False, snapshot=text)

    def reset(self) -> None:
        """软重置：任务状态由 _resume_frames 重开；句级基准保留。"""
