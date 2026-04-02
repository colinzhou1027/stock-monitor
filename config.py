"""
配置管理模块
加载环境变量和定义股票监控列表（支持韩股、美股、港股）
"""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Tuple, Dict
from dotenv import load_dotenv

# 加载 .env 文件
load_dotenv()

# 市场类型常量
MARKET_KR = "kr"  # 韩股
MARKET_US = "us"  # 美股
MARKET_HK = "hk"  # 港股


@dataclass
class Config:
    """应用配置类"""
    
    # 企业微信配置
    wecom_webhook_urls: List[str]
    
    # AI 配置（使用通义千问）
    ai_api_key: str
    ai_model: str
    ai_provider: str  # "qwen"
    
    # 监控配置
    change_threshold: float
    
    # 调度配置
    schedule_time: str
    timezone: str
    
    # 日志配置
    log_level: str
    
    # 网页配置
    webpage_url: str  # GitHub Pages 网页地址


def load_config() -> Config:
    """从环境变量加载配置"""
    # 收集 webhook URL
    webhook_urls = []
    
    # 主要的 webhook
    main_webhook = os.getenv("WECOM_WEBHOOK_URL", "")
    if main_webhook:
        webhook_urls.append(main_webhook)
        key_suffix = main_webhook.split("key=")[-1][-8:] if "key=" in main_webhook else "***"
        print(f"✅ 加载主 webhook: ...{key_suffix}")
    
    print(f"📊 总共加载了 {len(webhook_urls)} 个 webhook")
    
    # AI 配置：使用通义千问
    ai_api_key = os.getenv("QWEN_API_KEY", "")
    ai_model = os.getenv("QWEN_MODEL", "qwen-max")
    ai_provider = "qwen"
    
    if ai_api_key:
        print(f"🤖 使用通义千问 {ai_model}")
    else:
        print("⚠️ 未配置 QWEN_API_KEY")
    
    return Config(
        wecom_webhook_urls=webhook_urls,
        ai_api_key=ai_api_key,
        ai_model=ai_model,
        ai_provider=ai_provider,
        change_threshold=float(os.getenv("CHANGE_THRESHOLD", "10.0")),
        schedule_time=os.getenv("SCHEDULE_TIME", "10:00"),
        timezone=os.getenv("TIMEZONE", "Asia/Shanghai"),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
        webpage_url=os.getenv("WEBPAGE_URL", ""),
    )


def validate_config(config: Config) -> List[str]:
    """
    验证配置是否完整
    返回错误消息列表，空列表表示配置有效
    """
    errors = []
    
    if not config.wecom_webhook_urls:
        errors.append("未配置任何企业微信 Webhook URL")
    else:
        for i, url in enumerate(config.wecom_webhook_urls, 1):
            if not url.startswith("https://qyapi.weixin.qq.com"):
                errors.append(f"第 {i} 个 WECOM_WEBHOOK_URL 格式不正确")
    
    if config.change_threshold <= 0:
        errors.append("CHANGE_THRESHOLD 必须大于 0")
    
    try:
        hour, minute = config.schedule_time.split(":")
        if not (0 <= int(hour) <= 23 and 0 <= int(minute) <= 59):
            errors.append("SCHEDULE_TIME 格式不正确，应为 HH:MM")
    except ValueError:
        errors.append("SCHEDULE_TIME 格式不正确，应为 HH:MM")
    
    return errors


# ============================================================
# 韩股配置
# ============================================================

# 韩国游戏公司股票列表
# 格式：(股票代码, 公司名称, 市场)
# 使用 pykrx 库获取数据，股票代码为纯数字格式
KR_STOCK_LIST: List[Tuple[str, str, str]] = [
    ("462870", "Shift Up", "KOSPI"),          # 胜利女神：妮姬 开发商
    ("259960", "Krafton", "KOSPI"),           # PUBG 开发商
    ("036570", "NCsoft", "KOSPI"),            # 天堂系列
    ("251270", "Netmarble", "KOSPI"),         # 网石游戏
    ("225570", "Nexon Games", "KOSDAQ"),      # 冒险岛、DNF
    ("263750", "Pearl Abyss", "KOSPI"),       # 黑色沙漠
]


# ============================================================
# 美股配置
# ============================================================

# 美股大盘指数
US_INDEX_LIST: List[Tuple[str, str, str]] = [
    ("^GSPC", "标普500", "index"),           # S&P 500
]

# 美股科技股
US_TECH_LIST: List[Tuple[str, str, str]] = [
    ("AAPL", "苹果", "tech"),
    ("GOOGL", "谷歌", "tech"),
    ("AMZN", "亚马逊", "tech"),
    ("NVDA", "英伟达", "tech"),
    ("META", "Meta", "tech"),
    ("TSLA", "特斯拉", "tech"),
    ("MSFT", "微软", "tech"),
]

# 美股游戏股
US_GAME_LIST: List[Tuple[str, str, str]] = [
    ("EA", "艺电", "game"),
    ("TTWO", "Take-Two", "game"),
    ("RBLX", "Roblox", "game"),
    ("U", "Unity", "game"),
]

# 合并美股列表
US_STOCK_LIST: List[Tuple[str, str, str]] = US_TECH_LIST + US_GAME_LIST


# ============================================================
# 港股配置
# ============================================================

# 港股大盘指数
HK_INDEX_LIST: List[Tuple[str, str, str]] = [
    ("^HSI", "恒生指数", "index"),           # Hang Seng Index
]

# 港股科技股
HK_TECH_LIST: List[Tuple[str, str, str]] = [
    ("0700.HK", "腾讯控股", "tech"),
    ("9988.HK", "阿里巴巴", "tech"),
    ("9999.HK", "网易", "tech"),
    ("1810.HK", "小米集团", "tech"),
    ("9888.HK", "百度集团", "tech"),
    ("0100.HK", "MiniMax", "tech"),  # yfinance 使用 4 位格式 0100.HK
    ("2513.HK", "智谱AI", "tech"),
]

# 港股游戏股
HK_GAME_LIST: List[Tuple[str, str, str]] = [
    ("0302.HK", "中手游", "game"),
    ("2400.HK", "心动公司", "game"),
    ("9626.HK", "哔哩哔哩", "game"),
    ("1119.HK", "创梦天地", "game"),
    ("0799.HK", "IGG", "game"),
]

# 合并港股列表
HK_STOCK_LIST: List[Tuple[str, str, str]] = HK_TECH_LIST + HK_GAME_LIST


# ============================================================
# 统一获取函数
# ============================================================

def get_stock_list(market: str) -> List[Tuple[str, str, str]]:
    """
    根据市场获取股票列表
    
    Args:
        market: 市场类型 (kr/us/hk)
    
    Returns:
        股票列表
    """
    if market == MARKET_KR:
        return KR_STOCK_LIST
    elif market == MARKET_US:
        return US_STOCK_LIST
    elif market == MARKET_HK:
        return HK_STOCK_LIST
    else:
        raise ValueError(f"不支持的市场类型: {market}")


def get_index_list(market: str) -> List[Tuple[str, str, str]]:
    """
    根据市场获取大盘指数列表
    
    Args:
        market: 市场类型 (kr/us/hk)
    
    Returns:
        指数列表
    """
    if market == MARKET_KR:
        return []  # 韩股使用 KODEX 200 ETF 代理
    elif market == MARKET_US:
        return US_INDEX_LIST
    elif market == MARKET_HK:
        return HK_INDEX_LIST
    else:
        raise ValueError(f"不支持的市场类型: {market}")


def get_tech_list(market: str) -> List[Tuple[str, str, str]]:
    """获取科技股列表（美股/港股）"""
    if market == MARKET_US:
        return US_TECH_LIST
    elif market == MARKET_HK:
        return HK_TECH_LIST
    return []


def get_game_list(market: str) -> List[Tuple[str, str, str]]:
    """获取游戏股列表（美股/港股）"""
    if market == MARKET_US:
        return US_GAME_LIST
    elif market == MARKET_HK:
        return HK_GAME_LIST
    return []


def get_market_info(market: str) -> Dict[str, str]:
    """
    获取市场信息
    
    Args:
        market: 市场类型 (kr/us/hk)
    
    Returns:
        包含市场名称、时区、货币符号等信息的字典
    """
    info = {
        MARKET_KR: {
            "name": "韩国",
            "full_name": "韩国游戏股票",
            "timezone": "Asia/Seoul",
            "currency": "₩",
            "currency_name": "韩元",
        },
        MARKET_US: {
            "name": "美股",
            "full_name": "美股",
            "timezone": "America/New_York",
            "currency": "$",
            "currency_name": "美元",
        },
        MARKET_HK: {
            "name": "港股",
            "full_name": "港股",
            "timezone": "Asia/Hong_Kong",
            "currency": "HK$",
            "currency_name": "港元",
        },
    }
    
    if market not in info:
        raise ValueError(f"不支持的市场类型: {market}")
    
    return info[market]
