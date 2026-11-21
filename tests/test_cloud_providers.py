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
    """首帧字节布局：header + payload_size(BE) + JSON。"""
    raw = encode_full_client_request({"audio": {"format": "pcm"}})
    assert raw[:4] == bytes([0x11, 0x10, 0x10, 0x00])
    size = int.from_bytes(raw[4:8], "big")
    assert json.loads(raw[8 : 8 + size]) == {"audio": {"format": "pcm"}}
    assert len(raw) == 8 + size


def test_encode_audio_packet_layout() -> None:
    """音频帧：普通帧 flags=0000，最后一帧 flags=0010。"""
    raw = encode_audio_packet(b"pcmdata")
    assert raw[:4] == bytes([0x11, 0x20, 0x00, 0x00])
    assert int.from_bytes(raw[4:8], "big") == 7
    assert raw[8:] == b"pcmdata"
    last = encode_audio_packet(b"x", last=True)
    assert last[:4] == bytes([0x11, 0x22, 0x00, 0x00])


def _server_frame(payload: dict, gzip_payload: bool = True) -> bytes:
    body = json.dumps(payload).encode()
    if gzip_payload:
        body = gzip.compress(body)
    header = bytes([0x11, 0x90, 0x00, 0x00]) + (1).to_bytes(4, "big")
    return header + len(body).to_bytes(4, "big") + body


def test_decode_server_packet_result() -> None:
    """full server response 解析（gzip 与明文 payload）。"""
    parsed = decode_server_packet(_server_frame({"result": {"text": "你好"}}))
    assert parsed is not None
    kind, payload = parsed
    assert kind == "result"
    assert json.loads(payload) == {"result": {"text": "你好"}}
    parsed = decode_server_packet(_server_frame({"result": {"text": "x"}}, gzip_payload=False))
    assert parsed is not None


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
    vad.reset()
    r5 = vad._parse_message(_server_frame({"result": {"text": "你好"}}))  # noqa: SLF001
    assert r5.text == "你好"  # reset 后基准清零


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
