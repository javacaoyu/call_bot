"""云端 Provider 单元测试（讯飞/火山/阿里协议层；无真实密钥，mock 流式循环）。"""

import base64
import gzip
import json
import time
from urllib.parse import unquote

import pytest

from callbot.engine.frames import AudioFrame
from callbot.providers.asr import ASRResult
from callbot.providers.base import ProviderConfig, create_asr, create_tts
from callbot.providers.cloud.aliyun_tts import (
    AliyunStreamingTTS,
    build_create_token_url,
    build_synthesis_message,
    percent_encode,
)
from callbot.providers.cloud.volc_asr import (
    VolcStreamingASR,
    decode_server_packet,
    encode_audio_packet,
    encode_full_client_request,
)
from callbot.providers.cloud.volc_tts import VolcStreamingTTS
from callbot.providers.cloud.xfyun_asr import (
    XfyunStreamingASR,
    build_iat_frame,
    build_iat_url,
    parse_iat_message,
    sign_iat,
)

# ---------- 讯飞 ----------


def test_sign_iat_anchor_vector() -> None:
    """固定输入签名锚定（防拼接格式回归）。"""
    sig = sign_iat("iat-api.xfyun.cn", "/v2/iat", "Wed, 10 Jul 2019 07:35:43 GMT", "secret123")
    assert sig == "rJPrdydoQvXOYTlARIKkXrQXeYeyIbE7RVnxG8q9bd0="


def test_build_iat_url_structure() -> None:
    """URL 含 wss 前缀与鉴权三参数；authorization 可解码回 api_key 串。"""
    url = build_iat_url("iat-api.xfyun.cn", "/v2/iat", "mykey", "mysecret")
    assert url.startswith("wss://iat-api.xfyun.cn/v2/iat?")
    assert "host=iat-api.xfyun.cn" in url
    assert "date=" in url
    auth = url.split("authorization=")[1].split("&")[0]
    decoded = base64.b64decode(auth).decode()
    assert 'api_key="mykey"' in decoded
    assert 'algorithm="hmac-sha256"' in decoded


def test_build_iat_frame() -> None:
    """status 0/1/2 帧的 JSON 字段与 audio base64。"""
    frame = json.loads(build_iat_frame(1, b"\x01\x02"))
    data = frame["data"]
    assert data["status"] == 1
    assert data["format"] == "audio/L16;rate=16000"
    assert data["encoding"] == "raw"
    assert base64.b64decode(data["audio"]) == b"\x01\x02"
    assert json.loads(build_iat_frame(2))["data"]["status"] == 2


def test_parse_iat_message() -> None:
    """增量词拼接、ls 判定句尾、错误码返回 None。"""
    msg = {
        "code": 0,
        "data": {"result": {"sn": 1, "ls": False, "ws": [{"cw": [{"w": "你好"}]}]}},
    }
    result = parse_iat_message(json.dumps(msg))
    assert result == ASRResult(text="你好", is_final=False)
    msg["data"]["result"]["ws"] = [{"cw": [{"w": "，"}, {"w": "世界"}]}]
    result = parse_iat_message(json.dumps(msg))
    assert result.text == "，世界"
    msg["data"]["result"]["ls"] = True
    assert parse_iat_message(json.dumps(msg)).is_final is True
    assert parse_iat_message('{"code": 10105, "message": "error"}') is None
    assert parse_iat_message('{"code": 0, "data": {}}') is None


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


# ---------- 阿里 ----------


def test_percent_encode() -> None:
    """阿里签名 percentEncode：空格 %20，安全字符不动，中文转码。"""
    assert percent_encode("a b") == "a%20b"
    assert percent_encode("A-Za-z0-9-_.~") == "A-Za-z0-9-_.~"
    assert percent_encode("中文") == "%E4%B8%AD%E6%96%87"


def test_build_create_token_url() -> None:
    """CreateToken URL：参数齐全、签名 percent 解码后可 base64 还原。"""
    url = build_create_token_url("ak123", "sk456")
    assert url.startswith("https://nls-meta.cn-shanghai.aliyuncs.com/?")
    assert "Action=CreateToken" in url
    assert "AccessKeyId=ak123" in url
    assert "Signature=" in url
    sig = unquote(url.split("Signature=")[1])
    assert base64.b64decode(sig)  # base64 可解码


def test_build_synthesis_message() -> None:
    """Start/Stop 消息 header/payload 字段。"""
    msg = json.loads(
        build_synthesis_message("StartSynthesis", "appkey1", "task1", {"text": "你好"})
    )
    header = msg["header"]
    assert header["name"] == "StartSynthesis"
    assert header["namespace"] == "FlowingSpeechSynthesizer"
    assert header["appkey"] == "appkey1"
    assert header["task_id"] == "task1"
    assert msg["payload"]["text"] == "你好"
    stop = json.loads(build_synthesis_message("StopSynthesis", "appkey1", "task1", {}))
    assert stop["header"]["name"] == "StopSynthesis"


class FakeAsyncWS:
    """伪异步 WebSocket 连接（阿里 TTS 用）：记录 sent，按脚本吐帧。"""

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


def _synthesis_event(name: str) -> str:
    return json.dumps({"header": {"name": name}})


async def test_aliyun_synthesize_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """流式合成：Start → Started（立即 Stop）→ 音频帧 → Completed。"""
    ws = FakeAsyncWS(
        [
            _synthesis_event("SynthesisStarted"),
            b"\x01\x00" * 100,
            _synthesis_event("SynthesisCompleted"),
        ]
    )
    monkeypatch.setattr("websockets.connect", lambda *a, **kw: ws)
    tts = AliyunStreamingTTS(appkey="appk", token="tok")
    frames = [f async for f in tts.synthesize("你好。")]
    assert len(frames) == 1
    assert frames[0].data == b"\x01\x00" * 100
    assert frames[0].sample_rate == 24000
    assert len(ws.sent) == 2  # Start + Stop
    start = json.loads(ws.sent[0])
    assert start["header"]["name"] == "StartSynthesis"
    assert start["payload"]["text"] == "你好。"
    assert json.loads(ws.sent[1])["header"]["name"] == "StopSynthesis"


async def test_aliyun_synthesize_empty_text() -> None:
    """空/纯符号文本直接返回。"""
    tts = AliyunStreamingTTS(appkey="appk", token="tok")
    frames = [f async for f in tts.synthesize("  \n ")]
    assert frames == []


# ---------- 云端 ASR 公共线程模型 ----------


class _FakeCloudASR(XfyunStreamingASR):
    """钩子全空的测试实现：原样发音频，服务端消息原样转 ASRResult。"""

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
    asr = _FakeCloudASR(app_id="1", api_key="k", api_secret="s")
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

    def _pre_end_frames(self) -> list[bytes]:
        return [b"settle-silence"]


def test_cloud_asr_keep_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """长连接模式：is_final 只发判停静音不关连接，后续音频续传。"""
    ws = FakeWS([b"tail", b"after"])
    monkeypatch.setattr("websockets.sync.client.connect", lambda *a, **kw: ws)
    asr = _KeepAliveCloudASR(app_id="1", api_key="k", api_secret="s")
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
    asr = create_asr(
        ProviderConfig(kind="xfyun", api_key="k", params={"app_id": "a", "api_secret": "s"})
    )
    assert isinstance(asr, XfyunStreamingASR)
    asr2 = create_asr(ProviderConfig(kind="volc", api_key="k"))
    assert isinstance(asr2, VolcStreamingASR)
    tts = create_tts(ProviderConfig(kind="aliyun", params={"appkey": "a", "token": "t"}))
    assert isinstance(tts, AliyunStreamingTTS)
    tts2 = create_tts(ProviderConfig(kind="volc", api_key="k", params={"speaker": "s1"}))
    assert isinstance(tts2, VolcStreamingTTS)


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
