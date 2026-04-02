"""
股票数据模型
定义股票信息和变化数据的数据结构
"""

from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime


@dataclass
class StockInfo:
    """股票基本信息"""
    symbol: str       # 股票代码，如 '259960'
    name: str         # 公司名称，如 'Krafton'
    market: str = "KOSPI"  # 市场：KOSPI 或 KOSDAQ
    
    def __str__(self) -> str:
        return f"{self.name} ({self.symbol})"


@dataclass
class StockChange:
    """股票变化数据 - 上一交易日收盘价 vs 上上交易日收盘价"""
    stock: StockInfo
    prev_close: float             # 上一交易日收盘价（韩元）
    prev_prev_close: float        # 上上交易日收盘价（韩元）
    change_percent: float         # 涨跌幅百分比
    prev_date: datetime           # 上一交易日日期
    prev_prev_date: datetime      # 上上交易日日期
    analysis: Optional[str] = None  # AI分析原因
    
    # 向后兼容的属性
    @property
    def current_price(self) -> float:
        """上一交易日收盘价（向后兼容）"""
        return self.prev_close
    
    @property
    def close_price(self) -> float:
        """上一交易日收盘价"""
        return self.prev_close
    
    @property
    def is_rising(self) -> bool:
        """是否上涨"""
        return self.change_percent > 0
    
    @property
    def change_direction(self) -> str:
        """涨跌方向描述"""
        return "📈 上涨" if self.is_rising else "📉 下跌"
    
    @property
    def formatted_change(self) -> str:
        """格式化的涨跌幅"""
        sign = "+" if self.is_rising else ""
        return f"{sign}{self.change_percent:.2f}%"
    
    @property
    def formatted_prev_close(self) -> str:
        """格式化的上一交易日收盘价"""
        return f"₩{self.prev_close:,.0f}"
    
    @property
    def formatted_prev_prev_close(self) -> str:
        """格式化的上上交易日收盘价"""
        return f"₩{self.prev_prev_close:,.0f}"
    
    @property
    def prev_date_str(self) -> str:
        """上一交易日日期字符串 (M/D)"""
        return self.prev_date.strftime("%-m/%d")
    
    @property
    def prev_prev_date_str(self) -> str:
        """上上交易日日期字符串 (M/D)"""
        return self.prev_prev_date.strftime("%-m/%d")
    
    def __str__(self) -> str:
        return (
            f"{self.stock.name}: {self.prev_prev_date_str}收盘{self.formatted_prev_prev_close} → "
            f"{self.prev_date_str}收盘{self.formatted_prev_close} ({self.formatted_change})"
        )


@dataclass
class MarketIndex:
    """大盘指数数据"""
    name: str                     # 指数名称，如 "KOSPI"
    prev_close: float             # 上一交易日收盘
    prev_prev_close: float        # 上上交易日收盘
    change_percent: float         # 涨跌幅
    prev_date: datetime           # 上一交易日日期
    prev_prev_date: datetime      # 上上交易日日期
    
    @property
    def is_rising(self) -> bool:
        return self.change_percent > 0
    
    @property
    def formatted_change(self) -> str:
        sign = "+" if self.is_rising else ""
        return f"{sign}{self.change_percent:.2f}%"
    
    @property
    def prev_date_str(self) -> str:
        return self.prev_date.strftime("%-m/%d")
    
    @property
    def prev_prev_date_str(self) -> str:
        return self.prev_prev_date.strftime("%-m/%d")


@dataclass
class StockAlert:
    """股票预警信息"""
    changes: list[StockChange]    # 触发预警的股票变化列表
    threshold: float              # 触发阈值
    analysis: str                 # AI综合分析
    timestamp: datetime           # 预警时间
    
    @property
    def has_alerts(self) -> bool:
        """是否有预警"""
        return len(self.changes) > 0
    
    @property
    def rising_count(self) -> int:
        """上涨股票数量"""
        return sum(1 for c in self.changes if c.is_rising)
    
    @property
    def falling_count(self) -> int:
        """下跌股票数量"""
        return sum(1 for c in self.changes if not c.is_rising)
