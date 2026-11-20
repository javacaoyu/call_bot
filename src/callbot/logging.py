"""统一日志配置。"""

import logging

_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: str = "INFO") -> None:
    """初始化根日志器：stdout 输出 + 统一格式。

    Args:
        level: 日志级别（DEBUG / INFO / WARNING / ERROR），默认 INFO。
    """
    logging.basicConfig(
        level=level.upper(),
        format=_FORMAT,
        datefmt=_DATEFMT,
    )
