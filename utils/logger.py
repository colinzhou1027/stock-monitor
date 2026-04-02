"""
日志工具模块
配置统一的日志格式和输出
"""

import logging
import sys
from typing import Optional


# 日志格式
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 全局 logger 实例缓存
_loggers: dict[str, logging.Logger] = {}


def setup_logger(
    level: str = "INFO",
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    设置根日志记录器
    
    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_file: 可选的日志文件路径
    
    Returns:
        配置好的根 Logger 实例
    """
    # 获取日志级别
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    
    # 配置根 logger
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # 清除现有处理器
    root_logger.handlers.clear()
    
    # 创建格式器
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)
    
    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)
    
    # 文件处理器（可选）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(numeric_level)
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
    
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """
    获取指定名称的 Logger 实例
    
    Args:
        name: Logger 名称，通常使用模块名 __name__
    
    Returns:
        Logger 实例
    """
    if name not in _loggers:
        _loggers[name] = logging.getLogger(name)
    return _loggers[name]


class LoggerMixin:
    """
    Logger Mixin 类
    为类添加日志功能
    """
    
    @property
    def logger(self) -> logging.Logger:
        """获取类专属的 Logger"""
        if not hasattr(self, "_logger"):
            self._logger = get_logger(self.__class__.__name__)
        return self._logger
