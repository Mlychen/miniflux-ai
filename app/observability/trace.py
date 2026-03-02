import logging
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict


def get_logger(log_level='INFO', name='miniflux_ai'):
    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    if not logger.handlers:
        formatter = logging.Formatter('%(asctime)s - %(filename)s - %(levelname)s - %(message)s')
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        logger.addHandler(console)

    logger.propagate = False
    return logger


def ensure_logger(logger=None, log_level='INFO', name='miniflux_ai'):
    """
    Get or create a logger with the specified configuration.

    如果传入了 logger 对象，则直接返回；
    否则创建一个新的 logger。
    """
    # 如果已经是一个 logger 对象，直接返回
    if logger is not None and isinstance(logger, logging.Logger):
        return logger
    # 如果传入的是字符串，作为 log_level 处理
    if isinstance(logger, str):
        log_level = logger
    return get_logger(log_level, name)


class JsonFormatter(logging.Formatter):
    """JSON 格式的日志 Formatter"""

    def format(self, record: logging.LogRecord) -> str:
        log_data: Dict[str, Any] = {
            'timestamp': datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
        }

        # 添加额外的字段
        if hasattr(record, 'trace_id'):
            log_data['trace_id'] = record.trace_id
        if hasattr(record, 'entry_id'):
            log_data['entry_id'] = record.entry_id
        if hasattr(record, 'stage'):
            log_data['stage'] = record.stage
        if hasattr(record, 'action'):
            log_data['action'] = record.action
        if hasattr(record, 'duration_ms'):
            log_data['duration_ms'] = record.duration_ms
        if hasattr(record, 'status'):
            log_data['status'] = record.status
        if hasattr(record, 'data'):
            log_data['data'] = record.data

        # 添加文件名和行号
        log_data['file'] = record.filename
        log_data['line'] = record.lineno

        # 异常信息
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


def get_process_logger(log_level='DEBUG', name='process_trace', log_dir='logs'):
    """
    获取处理追踪专用的 JSON 日志器

    Args:
        log_level: 日志级别
        name: logger 名称
        log_dir: 日志目录

    Returns:
        配置好的 logger 实例
    """
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    logger.propagate = False

    # 清除已有的 handlers
    if logger.handlers:
        logger.handlers.clear()

    # 确保日志目录存在
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, 'manual-process.log')

    # JSON 文件 handler
    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(log_level)
    file_handler.setFormatter(JsonFormatter())
    logger.addHandler(file_handler)

    # Console handler（可选，便于调试）
    # console_handler = logging.StreamHandler()
    # console_handler.setLevel(log_level)
    # console_handler.setFormatter(JsonFormatter())
    # logger.addHandler(console_handler)

    return logger