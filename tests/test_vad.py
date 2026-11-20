"""Silero VAD 状态机单元测试（fake 模型脚本化概率；真实模型靠冒烟验证）。"""

import torch

from callbot.engine.frames import AudioFrame
from callbot.engine.vad import SileroVAD, VADEvent

_SPEECH = 0.9
_SILENCE = 0.1


class FakeModel:
    """脚本化概率的假 VAD 模型：按序吐 prob，耗尽后用 default。"""

    def __init__(self, probs: list[float], default: float = _SILENCE) -> None:
        self._probs = list(probs)
        self._default = default
        self.calls = 0

    def __call__(self, samples: torch.Tensor, sr: int) -> torch.Tensor:
        assert samples.shape == (512,), "VAD 必须按 512 样本块推理"
        assert sr == 16000
        self.calls += 1
        prob = self._probs.pop(0) if self._probs else self._default
        return torch.tensor(prob)


def _make_vad(probs: list[float], default: float = _SILENCE) -> SileroVAD:
    vad = SileroVAD()
    vad._model = FakeModel(probs, default)  # noqa: SLF001 - 测试注入假模型
    return vad


def _frame_of_n_blocks(n: int, value: int = 0) -> AudioFrame:
    """构造 n 个 512 样本块的 PCM16 帧。"""
    return AudioFrame(data=(b"\x00\x00" if value == 0 else b"\x01\x00") * 512 * n)


def test_onset_after_min_speech() -> None:
    """连续语音达到 250ms（8 块=256ms）发出起音事件。"""
    vad = _make_vad([_SPEECH] * 8)
    event = vad.process_frame(_frame_of_n_blocks(8))
    assert event is VADEvent.SPEECH_START
    assert vad.in_speech


def test_short_noise_filtered() -> None:
    """3 块语音（96ms<250ms）后静音 → 计数清零，无事件。"""
    vad = _make_vad([_SPEECH] * 3)
    assert vad.process_frame(_frame_of_n_blocks(3)) is None
    assert vad.process_frame(_frame_of_n_blocks(1)) is None  # 静音清零
    assert vad.process_frame(_frame_of_n_blocks(3, value=1)) is None  # 重新累计仍未达标
    assert not vad.in_speech


def test_end_after_min_silence() -> None:
    """起音后连续静音 400ms（13 块=416ms）发出端点事件。"""
    vad = _make_vad([_SPEECH] * 8 + [_SILENCE] * 13)
    assert vad.process_frame(_frame_of_n_blocks(8)) is VADEvent.SPEECH_START
    event = vad.process_frame(_frame_of_n_blocks(13))
    assert event is VADEvent.SPEECH_END
    assert not vad.in_speech


def test_silence_tolerance_not_split() -> None:
    """语音中 5 块静音（160ms<400ms）后语音恢复 → 无端点事件。"""
    vad = _make_vad([_SPEECH] * 8)
    assert vad.process_frame(_frame_of_n_blocks(8)) is VADEvent.SPEECH_START
    assert vad.process_frame(_frame_of_n_blocks(5)) is None  # 短暂停顿
    assert vad.process_frame(_frame_of_n_blocks(1, value=1)) is None  # 恢复
    assert vad.in_speech


def test_event_fires_once() -> None:
    """起音后持续语音不再重复发事件。"""
    vad = _make_vad([_SPEECH] * 8, default=_SPEECH)
    assert vad.process_frame(_frame_of_n_blocks(8)) is VADEvent.SPEECH_START
    assert vad.process_frame(_frame_of_n_blocks(10)) is None
    assert vad.in_speech


def test_partial_frames_buffered() -> None:
    """不足 512 样本的帧先缓冲，累积满块后推理。"""
    vad = _make_vad([_SPEECH] * 8)
    small = AudioFrame(data=b"\x01\x00" * 100)  # 100 样本/帧
    for _ in range(40):  # 40 帧 = 4000 样本 ≈ 7.8 块
        vad.process_frame(small)
    event = vad.process_frame(AudioFrame(data=b"\x01\x00" * 120))  # 补齐第 8 块
    assert event is VADEvent.SPEECH_START
    assert vad._model.calls == 8  # noqa: SLF001 - 恰好 8 块推理


def test_flush_in_speech_emits_end() -> None:
    """语音中 flush 强制端点。"""
    vad = _make_vad([_SPEECH] * 8)
    vad.process_frame(_frame_of_n_blocks(8))
    assert vad.flush() is VADEvent.SPEECH_END
    assert not vad.in_speech


def test_flush_in_silence_returns_none() -> None:
    """静音中 flush 无事件。"""
    vad = _make_vad([])
    assert vad.flush() is None


def test_reset_clears_state() -> None:
    """reset 后状态归零，起音计数从头开始。"""
    vad = _make_vad([_SPEECH] * 8)
    vad.process_frame(_frame_of_n_blocks(8))
    vad.reset()
    assert not vad.in_speech
    assert vad.process_frame(_frame_of_n_blocks(7, value=1)) is None  # 未达标不发事件
