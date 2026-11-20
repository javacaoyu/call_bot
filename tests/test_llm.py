"""LLM Provider 单元测试（fake 客户端，不访问网络）。"""

from callbot.config import Settings
from callbot.providers.llm import DeepSeekStreamingLLM


class FakeCompletions:
    """模拟 openai.chat.completions 流式接口。"""

    def __init__(self, deltas: list[str | None]) -> None:
        self._deltas = deltas
        self.closed = False

    async def create(self, **kwargs: object) -> "FakeStream":
        assert kwargs["stream"] is True
        return FakeStream(self._deltas, self)


class FakeStream:
    def __init__(self, deltas: list[str | None], parent: FakeCompletions) -> None:
        self._deltas = iter(deltas)
        self._parent = parent

    def __aiter__(self) -> "FakeStream":
        return self

    async def __anext__(self) -> object:
        try:
            delta = next(self._deltas)
        except StopIteration:
            raise StopAsyncIteration from None
        return type(
            "Chunk",
            (),
            {
                "choices": [
                    type("C", (), {"delta": type("D", (), {"content": delta})()})()
                ]
            },
        )()

    async def close(self) -> None:
        self._parent.closed = True


class FakeClient:
    def __init__(self, deltas: list[str | None]) -> None:
        self.chat = type("Chat", (), {"completions": FakeCompletions(deltas)})()


async def _collect(llm: DeepSeekStreamingLLM, messages: list[dict[str, str]]) -> list[str]:
    return [token async for token in llm.generate(messages)]


async def test_streaming_yields_deltas() -> None:
    """逐 delta 产出，跳过空增量。"""
    llm = DeepSeekStreamingLLM(
        client=FakeClient(["你", "好", None, "", "！", None])
    )
    assert await _collect(llm, [{"role": "user", "content": "hi"}]) == ["你", "好", "！"]


async def test_close_stream_on_cancel() -> None:
    """生成器被提前关闭时底层流被关闭（打断=关流）。"""
    completions = FakeCompletions(["你", "好", "！"])
    client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    llm = DeepSeekStreamingLLM(client=client)
    gen = llm.generate([{"role": "user", "content": "hi"}])
    first = await anext(gen)
    assert first == "你"
    await gen.aclose()  # 模拟打断关流
    assert completions.closed is True


def test_settings_llm_defaults() -> None:
    """LLM 配置默认值：DeepSeek 官方端点。"""
    settings = Settings(_env_file=None)
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.llm_model == "deepseek-chat"
    assert settings.llm_api_key == ""
