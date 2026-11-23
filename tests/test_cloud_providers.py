"""云端 Provider 单元测试（千问/火山协议层；无真实密钥，mock 流式循环）。"""

import base64
import gzip
import json
import time

import pytest

from callbot.engine.frames import AudioFrame
from callbot.providers.asr import ASRResult
from callbot.providers.base import ProviderConfig, create_asr, create_tts
from callbot.providers.cloud.base_cloud import CloudASRBase
from callbot.providers.cloud.qwen_asr import QwenStreamingASR, build_qwen_asr_event
from callbot.providers.cloud.qwen_tts import QwenStreamingTTS
from callbot.providers.cloud.volc_asr import (
    VolcStreamingASR,
    decode_server_packet,
    encode_audio_packet,
    encode_full_client_request,
)
from callbot.providers.cloud.volc_tts import VolcStreamingTTS

# ---------- 千问 ASR ----------


def test_build_qwen_run_task() -> None:
    """run-task 事件：header 与 payload 字段完整。"""
    raw = build_qwen_asr_event("run-task", "task1", "qwen-audio-3.1-asr-flash-streaming")
    msg = json.loads(raw)
    assert msg["header"] == {"action": "run-task", "task_id": "task1", "streaming": "duplex"}
    assert msg["payload"]["task"] == "asr"
    assert msg["payload"]["model"] == "qwen-audio-3.1-asr-flash-streaming"
    assert msg["payload"]["parameters"] == {"format": "pcm", "sample_rate": 16000}


def test_build_qwen_finish_task() -> None:
    """finish-task 事件：payload 仅 input: {}。"""
    msg = json.loads(build_qwen_asr_event("finish-task", "task1", "m"))
    assert msg["header"]["action"] == "finish-task"
    assert msg["payload"] == {"input": {}}


def _sentence_event(
    text: str,
    sentence_id: int = 1,
    sentence_end: bool = False,
    heartbeat: bool = False,
) -> str:
    return json.dumps(
        {
            "header": {"event": "result-generated"},
            "payload": {
                "output": {
                    "sentence": {
                        "sentence_id": sentence_id,
                        "text": text,
                        "sentence_end": sentence_end,
                        "heartbeat": heartbeat,
                    }
                }
            },
        }
    )


def test_qwen_intermediate_emits_snapshot() -> None:
    """中间结果：快照替换语义（text 空增量）。"""
    asr = QwenStreamingASR(api_key="k")
    result = asr._parse_message(_sentence_event("你好"))  # noqa: SLF001
    assert result is not None
    assert result.text == ""
    assert result.is_final is False
    assert result.snapshot == "你好"
    result = asr._parse_message(_sentence_event("你好世界"))  # 修订  # noqa: SLF001
    assert result.snapshot == "你好世界"


def test_qwen_final_emits_sentence_delta() -> None:
    """最终句：text = 句增量（进 utterance），snapshot = 该句文本。"""
    asr = QwenStreamingASR(api_key="k")
    asr._parse_message(_sentence_event("你好世界"))  # noqa: SLF001
    result = asr._parse_message(_sentence_event("你好世界。", sentence_end=True))  # noqa: SLF001
    assert result is not None
    assert result.text == "你好世界。"
    assert result.is_final is True
    assert result.snapshot == "你好世界。"
    # 第二句：快照仅当前句（不含历史定稿）
    asr._parse_message(_sentence_event("再见", sentence_id=2))  # noqa: SLF001
    result = asr._parse_message(_sentence_event("再见。", sentence_id=2, sentence_end=True))  # noqa: SLF001
    assert result.text == "再见。"
    assert result.snapshot == "再见。"


def test_qwen_final_duplicate_skipped() -> None:
    """同句最终结果重复：跳过（定稿句不再重发）。"""
    asr = QwenStreamingASR(api_key="k")
    asr._parse_message(_sentence_event("你好世界。", sentence_end=True))  # noqa: SLF001
    assert asr._parse_message(_sentence_event("你好世界。", sentence_end=True)) is None  # noqa: SLF001


def test_qwen_heartbeat_and_failed_skipped() -> None:
    """心跳跳过；task-failed 返回 None（错误已记日志）。"""
    asr = QwenStreamingASR(api_key="k")
    assert asr._parse_message(_sentence_event("x", heartbeat=True)) is None  # noqa: SLF001
    failed = json.dumps({"header": {"event": "task-failed"}, "payload": {"output": {"code": 1}}})
    assert asr._parse_message(failed) is None  # noqa: SLF001
    assert asr._parse_message(b"binary") is None  # noqa: SLF001


def test_qwen_finish_resets_snapshot_baseline() -> None:
    """finish-task 后定稿 id 清空：settle 期重推最终句作为新句 emit（增量正确）。"""
    asr = QwenStreamingASR(api_key="k")
    asr._parse_message(_sentence_event("你们有什么产品？", sentence_end=True))  # noqa: SLF001
    asr._final_frames()  # flush：finish-task + 重置  # noqa: SLF001
    # settle 期服务端重推最终句（id 已被清空）→ 作为新句再次 emit
    result = asr._parse_message(_sentence_event("你们有什么产品？", sentence_end=True))  # noqa: SLF001
    assert result is not None
    assert result.text == "你们有什么产品？"
    # 新句中间结果快照仅当前句
    preview = asr._parse_message(_sentence_event("还有什么", sentence_id=3))  # noqa: SLF001
    assert preview is not None
    assert preview.snapshot == "还有什么"


def test_qwen_task_serialization_state() -> None:
    """任务串行状态机：初始就绪 → run-task 未就绪 → finished/failed 后恢复。

    回归：resume 必须非阻塞等待（旧实现 sender 线程 sleep 死锁——
    task-finished 由同线程 recv 解析，永远等不到）。
    """
    asr = QwenStreamingASR(api_key="k")
    assert asr._resume_ready() is True  # noqa: SLF001 - 初始就绪
    asr._start_frame()  # 首任务：run-task  # noqa: SLF001
    assert asr._resume_ready() is False  # noqa: SLF001 - 任务进行中不可重开
    finished = json.dumps({"header": {"event": "task-finished", "task_id": "x"}})
    asr._parse_message(finished)  # noqa: SLF001
    assert asr._resume_ready() is True  # noqa: SLF001 - 收尾后恢复
    asr._resume_frames()  # 新任务  # noqa: SLF001
    assert asr._resume_ready() is False  # noqa: SLF001
    failed = json.dumps({"header": {"event": "task-failed"}, "payload": {"output": {}}})
    asr._parse_message(failed)  # noqa: SLF001
    assert asr._resume_ready() is True  # noqa: SLF001 - 失败也视为收尾完成


# ---------- 千问 TTS ----------


async def test_qwen_tts_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP SSE 流式：base64 分块 → AudioFrame(24000)；请求体/头正确。"""
    lines = [
        json.dumps({"output": {"audio": {"data": base64.b64encode(b"\x01\x00" * 100).decode()}}}),
        json.dumps({"output": {"audio": {"data": base64.b64encode(b"\x02\x00" * 50).decode()}}}),
    ]
    client = FakeHttpClient(lines)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)
    tts = QwenStreamingTTS(api_key="k")
    frames = [f async for f in tts.synthesize("你好。", speed=1.2)]
    assert [f.data for f in frames] == [b"\x01\x00" * 100, b"\x02\x00" * 50]
    assert all(f.sample_rate == 24000 for f in frames)
    body = client.last_body
    assert body is not None
    assert body["model"] == "qwen-audio-3.1-tts-flash"
    assert body["input"]["text"] == "你好。"
    assert body["input"]["voice"] == "longanhuan_v3.1"
    assert body["input"]["rate"] == 1.2  # speed 直接映射
    assert client.last_headers == {
        "Authorization": "Bearer k",
        "Content-Type": "application/json",
        "X-DashScope-SSE": "enable",
    }


async def test_qwen_tts_sse_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSE data: 前缀兼容。"""
    lines = [json.dumps({"output": {"audio": {"data": base64.b64encode(b"\x03\x00").decode()}}})]
    lines[0] = "data: " + lines[0]
    client = FakeHttpClient(lines)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)
    tts = QwenStreamingTTS(api_key="k")
    frames = [f async for f in tts.synthesize("好。")]
    assert frames[0].data == b"\x03\x00"


async def test_qwen_tts_empty_text() -> None:
    """空/纯符号文本直接返回。"""
    tts = QwenStreamingTTS(api_key="k")
    assert [f async for f in tts.synthesize(" \n ")] == []


# ---------- 火山 ----------


def test_encode_full_client_request_layout() -> None:
    """首帧字节布局：header（JSON+Gzip）+ payload_size(BE) + gzip JSON。"""
    raw = encode_full_client_request({"audio": {"format": "pcm"}})
    assert raw[:4] == bytes([0x11, 0x10, 0x11, 0x00])  # serialization=JSON, compression=Gzip
    size = int.from_bytes(raw[4:8], "big")
    body = gzip.decompress(raw[8 : 8 + size])
    assert json.loads(body) == {"audio": {"format": "pcm"}}
    assert len(raw) == 8 + size


def test_encode_audio_packet_layout() -> None:
    """音频帧：Gzip 压缩 payload；普通帧 flags=0000，最后一帧 flags=0010。"""
    raw = encode_audio_packet(b"pcmdata")
    assert raw[:4] == bytes([0x11, 0x20, 0x01, 0x00])  # raw + Gzip
    size = int.from_bytes(raw[4:8], "big")
    assert gzip.decompress(raw[8 : 8 + size]) == b"pcmdata"
    last = encode_audio_packet(b"x", last=True)
    assert last[:4] == bytes([0x11, 0x22, 0x01, 0x00])


def _server_frame(
    payload: dict, gzip_payload: bool = False, last_package: bool = False
) -> bytes:
    """构造服务端帧：flags=0011（最后一包）带 sequence，其余不带（2026-11 实测）。"""
    body = json.dumps(payload).encode()
    if gzip_payload:
        body = gzip.compress(body)
        header = bytes([0x11, 0x90 | 0b0011 if last_package else 0x90, 0x01, 0x00])
    else:
        header = bytes([0x11, 0x93 if last_package else 0x90, 0x00, 0x00])
    seq = (1).to_bytes(4, "big") if last_package else b""
    return header + seq + len(body).to_bytes(4, "big") + body


def test_decode_server_packet_result() -> None:
    """full server response 解析（明文/gzip/尾包带 sequence 三种布局）。"""
    parsed = decode_server_packet(_server_frame({"result": {"text": "你好"}}))
    assert parsed is not None
    kind, payload = parsed
    assert kind == "result"
    assert json.loads(payload) == {"result": {"text": "你好"}}
    parsed = decode_server_packet(_server_frame({"result": {"text": "x"}}, gzip_payload=True))
    assert parsed is not None
    assert json.loads(parsed[1]) == {"result": {"text": "x"}}


def test_decode_server_packet_last_package() -> None:
    """最后一包响应（flags=0011）带 4B sequence，payload 偏移正确。"""
    parsed = decode_server_packet(
        _server_frame({"result": {"text": "最终"}}, last_package=True)
    )
    assert parsed is not None
    assert json.loads(parsed[1]) == {"result": {"text": "最终"}}


def test_decode_server_packet_error_and_short() -> None:
    """error 帧返回 None；短帧返回 None。"""
    err = (
        bytes([0x11, 0xF0, 0x00, 0x00])
        + (45000001).to_bytes(4, "big")
        + (2).to_bytes(4, "big")
        + b"xx"
    )
    assert decode_server_packet(err) is None
    assert decode_server_packet(b"short") is None


def test_volc_incremental_prefix_delta() -> None:
    """result.text 全量语义：增量取前缀差；修正时重发全量；无变化返回 None。"""
    vad = VolcStreamingASR(api_key="k")
    r1 = vad._parse_message(_server_frame({"result": {"text": "你好"}}))  # noqa: SLF001
    assert r1 == ASRResult(text="你好", is_final=False)
    r2 = vad._parse_message(_server_frame({"result": {"text": "你好世界"}}))  # noqa: SLF001
    assert r2.text == "世界"
    r3 = vad._parse_message(_server_frame({"result": {"text": "你好世界"}}))  # noqa: SLF001
    assert r3 is None
    r4 = vad._parse_message(_server_frame({"result": {"text": "您好世界"}}))  # noqa: SLF001
    assert r4.text == "您好世界"  # 服务端修正 → 全量
    vad.reset()  # 软重置：长连接下基准保持
    r5 = vad._parse_message(_server_frame({"result": {"text": "您好世界"}}))  # noqa: SLF001
    assert r5 is None  # 基准未清，无变化不重复推


# ---------- 云端 ASR 公共线程模型 ----------


class FakeAsyncWS:
    """伪异步 WebSocket 连接：记录 sent，按脚本吐帧。"""

    def __init__(self, frames: list) -> None:
        self.sent: list[str] = []
        self._frames = list(frames)

    async def send(self, data: str) -> None:
        self.sent.append(data)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._frames:
            raise StopAsyncIteration
        return self._frames.pop(0)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False


class FakeWS:
    """伪同步 WebSocket 连接（云端 ASR 基类用）：recv 吐帧/超时。"""

    def __init__(self, frames: list) -> None:
        self.sent: list[bytes] = []
        self._frames = list(frames)

    def send(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, timeout: float | None = None):  # noqa: ANN201
        if self._frames:
            return self._frames.pop(0)
        raise TimeoutError

    def __enter__(self):
        return self

    def __exit__(self, *args) -> bool:
        return False


class _FakeCloudASR(CloudASRBase):
    """钩子全空的测试实现：原样发音频，服务端消息原样转 ASRResult。"""

    def _build_url(self) -> str:
        return "wss://fake"

    def _start_frame(self) -> bytes | None:
        return None

    def _encode_audio(self, data: bytes) -> bytes:
        return data

    def _end_frame(self) -> bytes | None:
        return None

    def _parse_message(self, raw: bytes | str) -> ASRResult | None:
        return ASRResult(text=raw.decode(), is_final=False)


def test_cloud_asr_thread_callback(monkeypatch: pytest.MonkeyPatch) -> None:
    """后台线程建连 → 音频投递 → 服务端消息经回调直推 → reset 关会话。"""
    ws = FakeWS([b"hello"])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *a, **kw: ws)
    asr = _FakeCloudASR()
    received: list[str] = []
    asr.set_callback(lambda r: received.append(r.text))
    asr.process_chunk(AudioFrame(data=b"\x00" * 320))
    deadline = time.monotonic() + 3
    while not received and time.monotonic() < deadline:
        time.sleep(0.05)
    assert received == ["hello"]
    assert ws.sent and ws.sent[0] == b"\x00" * 320  # 音频原样投递
    asr.reset()  # 关当前会话，线程驻留等下一轮


class _KeepAliveCloudASR(_FakeCloudASR):
    """长连接模式 fake：is_final 后连接保持。"""

    _keep_connection = True

    def _final_frames(self) -> list[bytes]:
        return [b"settle-silence"]


def test_cloud_asr_keep_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """长连接模式：is_final 只发判停静音不关连接，后续音频续传。"""
    ws = FakeWS([b"tail", b"after"])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *a, **kw: ws)
    asr = _KeepAliveCloudASR()
    received: list[str] = []
    asr.set_callback(lambda r: received.append(r.text))
    asr.process_chunk(AudioFrame(data=b"first"), is_final=True)
    asr.process_chunk(AudioFrame(data=b"more"))  # final 后继续投递
    deadline = time.monotonic() + 3
    while len(received) < 2 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert received == ["tail", "after"]
    # sender 与 recv 并发：等发送完成再断言
    deadline2 = time.monotonic() + 3
    while len(ws.sent) < 3 and time.monotonic() < deadline2:
        time.sleep(0.05)
    assert b"settle-silence" in ws.sent  # 判停静音已发
    assert b"more" in ws.sent  # final 后音频续传（连接未断）
    asr.reset()  # 软重置不关连接


# ---------- 工厂云端分支 ----------


def test_factory_cloud_branches() -> None:
    """create_asr/create_tts 云端 kind 分发正确类型。"""
    asr = create_asr(ProviderConfig(kind="volc", api_key="k"))
    assert isinstance(asr, VolcStreamingASR)
    asr2 = create_asr(ProviderConfig(kind="qwen", api_key="k"))
    assert isinstance(asr2, QwenStreamingASR)
    tts2 = create_tts(ProviderConfig(kind="volc", api_key="k", params={"speaker": "s1"}))
    assert isinstance(tts2, VolcStreamingTTS)
    tts3 = create_tts(ProviderConfig(kind="qwen", api_key="k", params={"voice": "v1"}))
    assert isinstance(tts3, QwenStreamingTTS)


# ---------- 火山 TTS（HTTP chunked 流式） ----------


class FakeStreamResponse:
    """伪 HTTP 流式响应：按脚本吐行。"""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    def raise_for_status(self) -> None:
        pass

    async def aiter_lines(self):  # noqa: ANN201
        for line in self._lines:
            yield line


class FakeHttpClient:
    """伪 httpx 客户端：记录请求并返回脚本化响应。"""

    def __init__(self, lines: list[str]) -> None:
        self._resp = FakeStreamResponse(lines)
        self.last_body: dict | None = None
        self.last_headers: dict | None = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args) -> bool:
        return False

    def stream(self, method: str, url: str, json=None, headers=None):  # noqa: ANN001, ANN201
        self.last_body = json
        self.last_headers = headers
        return self._resp


def _volc_tts_lines(*audio_chunks: bytes) -> list[str]:
    lines = [
        json.dumps({"code": 0, "message": "", "data": base64.b64encode(c).decode()})
        for c in audio_chunks
    ]
    lines.append(json.dumps({"code": 0, "message": "", "data": None, "sentence": {}}))
    return lines


async def test_volc_tts_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """chunked JSON 流 → 逐块 AudioFrame(24k)；请求 body/headers 正确。"""
    client = FakeHttpClient(_volc_tts_lines(b"\x01\x00" * 100, b"\x02\x00" * 50))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)
    tts = VolcStreamingTTS(api_key="k")
    frames = [f async for f in tts.synthesize("你好。")]
    assert [f.data for f in frames] == [b"\x01\x00" * 100, b"\x02\x00" * 50]
    assert all(f.sample_rate == 24000 for f in frames)
    body = client.last_body
    assert body is not None
    assert body["req_params"]["text"] == "你好。"
    assert body["req_params"]["speaker"] == "zh_female_vv_uranus_bigtts"
    assert body["req_params"]["audio_params"] == {
        "format": "pcm",
        "sample_rate": 24000,
        "speech_rate": 0,
    }
    assert client.last_headers == {
        "X-Api-Key": "k",
        "X-Api-Resource-Id": "seed-tts-2.0",
        "Content-Type": "application/json",
    }


async def test_volc_tts_speed_mapping(monkeypatch: pytest.MonkeyPatch) -> None:
    """speed 1.5 → speech_rate 50（线性映射）。"""
    client = FakeHttpClient(_volc_tts_lines(b"\x00" * 10))
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)
    tts = VolcStreamingTTS(api_key="k")
    await tts.synthesize("你好。", speed=1.5).__anext__()
    assert client.last_body is not None
    assert client.last_body["req_params"]["audio_params"]["speech_rate"] == 50


async def test_volc_tts_sse_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    """SSE 'data:' 前缀行兼容。"""
    lines = _volc_tts_lines(b"\x03\x00")
    lines[0] = "data: " + lines[0]
    client = FakeHttpClient(lines)
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)
    tts = VolcStreamingTTS(api_key="k")
    frames = [f async for f in tts.synthesize("好。")]
    assert frames[0].data == b"\x03\x00"


async def test_volc_tts_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    """服务端非 0 错误码抛 RuntimeError。"""
    client = FakeHttpClient([json.dumps({"code": 55000031, "message": "服务器繁忙"})])
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **kw: client)
    tts = VolcStreamingTTS(api_key="k")
    with pytest.raises(RuntimeError, match="55000031"):
        await tts.synthesize("你好。").__anext__()


async def test_volc_tts_empty_text() -> None:
    """空/纯符号文本直接返回。"""
    tts = VolcStreamingTTS(api_key="k")
    frames = [f async for f in tts.synthesize(" \n ")]
    assert frames == []
