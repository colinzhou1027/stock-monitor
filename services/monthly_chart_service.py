"""
月度股价趋势图服务
支持韩股、美股、港股三个市场的月度趋势图生成
在每月第一个中国工作日生成上月股价趋势图

数据源优先级（2026-03更新，与日报完全一致）：
- 韩股股票：pykrx
- 美股股票：yfinance → akshare → 腾讯股票（历史K线兜底）
- 港股股票：yfinance → akshare → 腾讯股票（历史K线兜底）
- 韩股指数（KOSPI 200）：pykrx（使用 KODEX 200 ETF）
- 美股指数（标普500）：yfinance → akshare
- 港股指数（恒生）：yfinance → akshare
"""

import io
import os
import json
import base64
import hashlib
import platform
from datetime import datetime, timedelta
from calendar import monthrange
from typing import Optional, Tuple, List, Set, Dict

import pytz
import matplotlib
matplotlib.use('Agg')  # 使用非交互式后端
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.font_manager as fm
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Patch
from pykrx import stock as krx

from utils.logger import LoggerMixin
from config import (
    MARKET_KR, MARKET_US, MARKET_HK,
    KR_STOCK_LIST, US_STOCK_LIST, HK_STOCK_LIST,
    get_market_info
)


# 韩股 Shift Up 股票代码（保持向后兼容）
SHIFTUP_TICKER = "462870"
SHIFTUP_NAME = "Shift Up"

# 市场名称映射
MARKET_NAMES = {
    MARKET_KR: "韩股",
    MARKET_US: "美股",
    MARKET_HK: "港股",
}

# 全局字体对象
CHINESE_FONT = None

# 记录已发送月份的文件路径
SENT_MONTHS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "sent_monthly_charts.json")


def setup_chinese_font():
    """设置中文字体 - 直接查找字体文件"""
    global CHINESE_FONT
    
    # 直接从字体列表中找到中文字体文件
    font_path = None
    for f in fm.fontManager.ttflist:
        if f.name == 'Songti SC':
            font_path = f.fname
            break
        elif f.name == 'STHeiti' and font_path is None:
            font_path = f.fname
        elif f.name == 'Microsoft YaHei' and font_path is None:
            font_path = f.fname
        elif f.name == 'SimHei' and font_path is None:
            font_path = f.fname
        elif f.name == 'WenQuanYi Micro Hei' and font_path is None:
            font_path = f.fname
    
    if font_path:
        CHINESE_FONT = FontProperties(fname=font_path)
        # 同时设置全局默认
        plt.rcParams['font.family'] = 'sans-serif'
        plt.rcParams['font.sans-serif'] = ['Songti SC', 'STHeiti', 'Microsoft YaHei', 'SimHei', 'DejaVu Sans']
    else:
        CHINESE_FONT = FontProperties()
    
    plt.rcParams['axes.unicode_minus'] = False
    return CHINESE_FONT


# 初始化字体
CHINESE_FONT = setup_chinese_font()


# 中国法定节假日（2026年）
# 参考：国务院办公厅关于2026年部分节假日安排的通知
CHINA_HOLIDAYS_2026 = {
    # 元旦
    datetime(2026, 1, 1), datetime(2026, 1, 2), datetime(2026, 1, 3),
    # 春节
    datetime(2026, 2, 15), datetime(2026, 2, 16), datetime(2026, 2, 17),
    datetime(2026, 2, 18), datetime(2026, 2, 19), datetime(2026, 2, 20),
    datetime(2026, 2, 21), datetime(2026, 2, 22), datetime(2026, 2, 23),
    # 清明节
    datetime(2026, 4, 4), datetime(2026, 4, 5), datetime(2026, 4, 6),
    # 劳动节
    datetime(2026, 5, 1), datetime(2026, 5, 2), datetime(2026, 5, 3),
    datetime(2026, 5, 4), datetime(2026, 5, 5),
    # 端午节
    datetime(2026, 6, 19), datetime(2026, 6, 20), datetime(2026, 6, 21),
    # 中秋节
    datetime(2026, 9, 25), datetime(2026, 9, 26), datetime(2026, 9, 27),
    # 国庆节
    datetime(2026, 10, 1), datetime(2026, 10, 2), datetime(2026, 10, 3),
    datetime(2026, 10, 4), datetime(2026, 10, 5), datetime(2026, 10, 6),
    datetime(2026, 10, 7),
}

# 中国调休工作日（2026年）- 周末但需要上班
CHINA_WORKDAYS_2026 = {
    datetime(2026, 1, 4),   # 元旦调休
    datetime(2026, 2, 14),  # 春节调休
    datetime(2026, 2, 28),  # 春节调休
    datetime(2026, 5, 9),   # 劳动节调休
}


class MonthlyChartService(LoggerMixin):
    """月度股价趋势图服务"""
    
    def __init__(self, timezone: str = "Asia/Seoul"):
        self.korea_tz = pytz.timezone(timezone)
        self.china_tz = pytz.timezone("Asia/Shanghai")
        # 确保数据目录存在
        data_dir = os.path.dirname(SENT_MONTHS_FILE)
        if not os.path.exists(data_dir):
            os.makedirs(data_dir)
    
    def _is_china_workday(self, date: datetime) -> bool:
        """
        判断给定日期是否是中国工作日
        
        Args:
            date: 日期（不含时区信息的日期部分）
            
        Returns:
            是否是中国工作日
        """
        # 转换为不含时区的日期
        date_only = datetime(date.year, date.month, date.day)
        
        # 如果是调休工作日，返回 True
        if date_only in CHINA_WORKDAYS_2026:
            return True
        
        # 如果是法定假日，返回 False
        if date_only in CHINA_HOLIDAYS_2026:
            return False
        
        # 否则，周一到周五是工作日
        return date.weekday() < 5  # 0-4 是周一到周五
    
    def _get_first_china_workday_of_month(self, year: int, month: int) -> datetime:
        """
        获取指定月份的第一个中国工作日
        
        Args:
            year: 年份
            month: 月份
            
        Returns:
            第一个工作日的日期
        """
        date = datetime(year, month, 1)
        while not self._is_china_workday(date):
            date += timedelta(days=1)
            # 防止无限循环（虽然不太可能）
            if date.day > 15:
                break
        return date
    
    def _load_sent_months(self) -> dict:
        """
        加载已发送的月份记录
        
        Returns:
            dict: 格式为 {"sent_months": [...], "market_sent": {"kr": [...], "us": [...], "hk": [...]}}
        """
        try:
            if os.path.exists(SENT_MONTHS_FILE):
                with open(SENT_MONTHS_FILE, 'r') as f:
                    data = json.load(f)
                    # 兼容旧格式：如果没有 market_sent，就使用旧的 sent_months
                    if "market_sent" not in data:
                        # 旧格式迁移：假设旧记录都是韩股的
                        old_months = data.get("sent_months", [])
                        data = {
                            "sent_months": old_months,  # 保留旧格式兼容
                            "market_sent": {
                                "kr": old_months,
                                "us": [],
                                "hk": []
                            }
                        }
                    return data
        except Exception as e:
            self.logger.warning(f"加载已发送月份记录失败: {e}")
        return {"sent_months": [], "market_sent": {"kr": [], "us": [], "hk": []}}
    
    def _save_sent_month(self, year: int, month: int, market: str = None) -> None:
        """
        保存已发送的月份记录
        
        Args:
            year: 年份
            month: 月份
            market: 市场类型 (kr/us/hk)，如果为 None 则保存到全局列表
        """
        try:
            data = self._load_sent_months()
            month_key = f"{year}-{month:02d}"
            
            # 保存到指定市场的记录
            if market:
                if market not in data["market_sent"]:
                    data["market_sent"][market] = []
                if month_key not in data["market_sent"][market]:
                    data["market_sent"][market].append(month_key)
                    # 只保留最近12个月
                    data["market_sent"][market] = sorted(data["market_sent"][market], reverse=True)[:12]
                self.logger.info(f"已记录 {market.upper()} 发送月份: {month_key}")
            else:
                # 旧格式兼容：保存到全局列表
                if month_key not in data["sent_months"]:
                    data["sent_months"].append(month_key)
                    data["sent_months"] = sorted(data["sent_months"], reverse=True)[:24]
                self.logger.info(f"已记录发送月份: {month_key}")
            
            with open(SENT_MONTHS_FILE, 'w') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
        except Exception as e:
            self.logger.error(f"保存已发送月份记录失败: {e}")
    
    def _is_month_sent(self, year: int, month: int, market: str = None) -> bool:
        """
        检查指定月份是否已发送过
        
        Args:
            year: 年份
            month: 月份
            market: 市场类型 (kr/us/hk)，如果指定则检查该市场的记录
            
        Returns:
            是否已发送
        """
        month_key = f"{year}-{month:02d}"
        data = self._load_sent_months()
        
        if market:
            # 检查指定市场的记录
            market_sent = data.get("market_sent", {}).get(market, [])
            return month_key in market_sent
        else:
            # 旧格式兼容：检查全局记录
            return month_key in data.get("sent_months", [])
    
    def _is_korea_trading_day(self, date: datetime) -> bool:
        """
        检查韩国股市是否在指定日期有交易
        
        Args:
            date: 日期
            
        Returns:
            是否有交易
        """
        try:
            date_str = date.strftime("%Y%m%d")
            df = krx.get_market_ohlcv_by_date(
                fromdate=date_str,
                todate=date_str,
                ticker=SHIFTUP_TICKER
            )
            return not df.empty
        except Exception as e:
            self.logger.warning(f"检查韩国交易日失败: {e}")
            return False
    
    def should_send_monthly_chart(self, force_month: int = 0, force_year: int = 0, market: str = None) -> Tuple[bool, int, int]:
        """
        判断今天是否应该发送月度趋势图
        
        规则：
        1. 只在每月第一个中国工作日发送上月趋势图
        2. 如果第一个中国工作日恰好是韩国休市日，则次日（第二个中国工作日）也可以发送（作为参考）
        3. 防止重复发送：已发送的月份不再发送（按市场区分）
        
        Args:
            force_month: 强制指定月份（用于测试，0表示不强制）
            force_year: 强制指定年份（用于测试，0表示不强制）
            market: 市场类型 (kr/us/hk)，用于按市场区分发送记录
        
        Returns:
            (是否发送, 上月月份, 上月年份)
        """
        # 使用中国时区判断
        today_china = datetime.now(self.china_tz)
        today = datetime(today_china.year, today_china.month, today_china.day)
        
        market_name = {"kr": "韩股", "us": "美股", "hk": "港股"}.get(market, "")
        self.logger.info(f"检查{market_name}月度图发送条件，今天（中国时间）: {today.strftime('%Y-%m-%d')} 星期{today.weekday()}")
        
        # 如果今天不是中国工作日，不发送
        if not self._is_china_workday(today):
            self.logger.info(f"今天不是中国工作日，不发送月度图")
            return (False, 0, 0)
        
        # 获取上个月信息
        if today.month == 1:
            last_month = 12
            last_year = today.year - 1
        else:
            last_month = today.month - 1
            last_year = today.year
        
        # 强制指定月份（用于测试）
        if force_month > 0 and force_year > 0:
            last_month = force_month
            last_year = force_year
            self.logger.info(f"强制发送 {force_year}年{force_month}月 {market_name}趋势图")
        else:
            # 检查是否已发送过该月份（按市场区分）
            if self._is_month_sent(last_year, last_month, market):
                self.logger.info(f"{last_year}年{last_month}月 {market_name}趋势图已发送过，跳过")
                return (False, 0, 0)
        
        # 获取当月第一个中国工作日
        first_workday = self._get_first_china_workday_of_month(today.year, today.month)
        self.logger.info(f"本月第一个中国工作日: {first_workday.strftime('%Y-%m-%d')}")
        
        # 情况1：今天是本月第一个中国工作日
        if today == first_workday:
            self.logger.info(f"今天是本月第一个中国工作日，发送 {last_year}年{last_month}月 趋势图")
            return (True, last_month, last_year)
        
        # 情况2：今天是本月第二个中国工作日，且第一个工作日是韩国休市日
        # 获取第二个中国工作日
        second_workday = first_workday + timedelta(days=1)
        while not self._is_china_workday(second_workday):
            second_workday += timedelta(days=1)
            if second_workday.day > 15:
                break
        
        if today == second_workday:
            # 检查第一个工作日是否是韩国休市日
            if not self._is_korea_trading_day(first_workday):
                self.logger.info(f"今天是第二个中国工作日，且第一个工作日({first_workday.strftime('%Y-%m-%d')})韩国休市")
                self.logger.info(f"作为参考信息发送 {last_year}年{last_month}月 趋势图")
                return (True, last_month, last_year)
            else:
                self.logger.info(f"第一个工作日韩国有交易，应该已发送过，不重复发送")
                return (False, 0, 0)
        
        # 其他情况不发送
        self.logger.info(f"今天既不是第一个工作日也不是符合条件的第二个工作日，不发送")
        return (False, 0, 0)
    
    def get_monthly_data(self, year: int, month: int):
        """获取指定月份的股票数据"""
        first_day = datetime(year, month, 1)
        last_day = datetime(year, month, monthrange(year, month)[1])
        
        start_str = first_day.strftime("%Y%m%d")
        end_str = last_day.strftime("%Y%m%d")
        
        self.logger.info(f"获取 {year}年{month}月 股票数据: {start_str} - {end_str}")
        
        try:
            df = krx.get_market_ohlcv_by_date(
                fromdate=start_str,
                todate=end_str,
                ticker=SHIFTUP_TICKER
            )
            
            if df.empty:
                self.logger.error("获取数据为空")
                return None
            
            # 重命名列
            df = df.rename(columns={
                '시가': 'open',
                '고가': 'high',
                '저가': 'low',
                '종가': 'close',
                '거래량': 'volume'
            })
            
            self.logger.info(f"获取到 {len(df)} 个交易日数据")
            return df
            
        except Exception as e:
            self.logger.error(f"获取股票数据失败: {e}")
            return None
    
    def create_chart(self, df, month: int, year: int) -> Optional[bytes]:
        """
        创建月度股价趋势图
        
        Args:
            df: 股票数据 DataFrame
            month: 月份
            year: 年份
            
        Returns:
            图片的 bytes 数据
        """
        global CHINESE_FONT
        
        try:
            # 计算统计数据
            prices = df['close'].values
            start_price = prices[0]
            end_price = prices[-1]
            change_percent = ((end_price - start_price) / start_price) * 100
            
            # 创建图表
            fig, ax1 = plt.subplots(figsize=(12, 6), dpi=150)
            fig.patch.set_facecolor('#ffffff')
            ax1.set_facecolor('#ffffff')
            
            dates = df.index
            
            # ===== 成交量柱状图（左Y轴） =====
            colors = ['#22c55e' if df['close'].iloc[i] >= df['open'].iloc[i] else '#ef4444' 
                      for i in range(len(df))]
            
            ax1.bar(dates, df['volume'], color=colors, alpha=0.6, width=0.8)
            
            # Y轴格式化（成交量）
            def format_volume(x, p):
                if x >= 10000:
                    return f'{x/10000:.0f}W'  # W = 万
                elif x >= 1000:
                    return f'{x/1000:.0f}K'
                return f'{int(x)}'
            
            ax1.yaxis.set_major_formatter(plt.FuncFormatter(format_volume))
            ax1.set_ylabel('成交量', fontsize=10, color='#666666', fontproperties=CHINESE_FONT)
            ax1.tick_params(axis='y', labelcolor='#666666', labelsize=9)
            
            # ===== 股价折线图（右Y轴） =====
            ax2 = ax1.twinx()
            
            ax2.plot(dates, df['close'], color='#2563eb', linewidth=2.5, 
                     marker='o', markersize=5, markerfacecolor='#2563eb',
                     markeredgecolor='white', markeredgewidth=1.5)
            
            # 标注起点和终点价格（使用 KRW 代替韩元符号）
            ax2.annotate(f'KRW {int(start_price):,}', 
                         xy=(dates[0], start_price),
                         xytext=(5, 15), textcoords='offset points',
                         fontsize=9, fontweight='bold', color='#2563eb',
                         bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                                  edgecolor='#2563eb', alpha=0.9))
            
            ax2.annotate(f'KRW {int(end_price):,}', 
                         xy=(dates[-1], end_price),
                         xytext=(-55, 15), textcoords='offset points',
                         fontsize=9, fontweight='bold', color='#2563eb',
                         bbox=dict(boxstyle='round,pad=0.3', facecolor='white', 
                                  edgecolor='#2563eb', alpha=0.9))
            
            # Y轴格式化（股价）
            ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
            ax2.set_ylabel('收盘价', fontsize=10, color='#2563eb', fontproperties=CHINESE_FONT)
            ax2.tick_params(axis='y', labelcolor='#2563eb', labelsize=9)
            
            # 设置Y轴范围
            price_range = prices.max() - prices.min()
            y_margin = price_range * 0.15 if price_range > 0 else prices.min() * 0.05
            ax2.set_ylim(prices.min() - y_margin, prices.max() + y_margin * 1.5)
            
            # ===== 标题 =====
            change_symbol = '+' if change_percent >= 0 else ''
            # 使用中文"涨"/"跌"代替三角形符号
            trend_text = '涨' if change_percent >= 0 else '跌'
            change_color = '#22c55e' if change_percent >= 0 else '#ef4444'
            
            title = f'{SHIFTUP_NAME} {year}年{month}月 股价趋势'
            ax1.set_title(title, fontsize=14, fontweight='bold', color='#1f2937', 
                          pad=15, loc='left', fontproperties=CHINESE_FONT)
            
            # 右上角显示涨跌幅
            ax1.text(0.99, 1.02, f'{trend_text} {change_symbol}{change_percent:.2f}%', 
                     transform=ax1.transAxes, fontsize=12, fontweight='bold',
                     color=change_color, ha='right', va='bottom', fontproperties=CHINESE_FONT)
            
            # ===== X轴日期格式 =====
            ax1.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax1.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates)//12)))
            plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')
            ax1.tick_params(axis='x', labelsize=9)
            
            # ===== 网格 =====
            ax1.grid(True, linestyle='--', alpha=0.3, color='#e5e7eb', axis='y')
            ax1.set_axisbelow(True)
            
            # ===== 图例（使用中文） =====
            legend_elements = [
                Patch(facecolor='#22c55e', alpha=0.6, label='上涨成交量'),
                Patch(facecolor='#ef4444', alpha=0.6, label='下跌成交量'),
                plt.Line2D([0], [0], color='#2563eb', linewidth=2.5, marker='o', 
                           markersize=5, label='收盘价')
            ]
            ax1.legend(handles=legend_elements, loc='upper left', fontsize=8,
                       framealpha=0.9, edgecolor='#e5e7eb', prop=CHINESE_FONT)
            
            # 调整布局
            plt.tight_layout()
            
            # 保存到内存
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            buf.seek(0)
            plt.close(fig)
            
            return buf.getvalue()
            
        except Exception as e:
            self.logger.error(f"生成图表失败: {e}")
            return None
    
    def generate_monthly_chart(self, force_month: int = 0, force_year: int = 0) -> Tuple[Optional[bytes], int, int, float]:
        """
        生成月度趋势图
        
        Args:
            force_month: 强制指定月份（用于测试，0表示不强制）
            force_year: 强制指定年份（用于测试，0表示不强制）
        
        Returns:
            (图片数据, 月份, 年份, 涨跌幅) 或 (None, 0, 0, 0) 如果不需要生成
        """
        should_send, month, year = self.should_send_monthly_chart(force_month, force_year)
        
        if not should_send:
            return (None, 0, 0, 0)
        
        # 获取数据
        df = self.get_monthly_data(year, month)
        if df is None:
            return (None, 0, 0, 0)
        
        # 计算涨跌幅
        start_price = df['close'].iloc[0]
        end_price = df['close'].iloc[-1]
        change_percent = ((end_price - start_price) / start_price) * 100
        
        # 生成图表
        image_data = self.create_chart(df, month, year)
        
        if image_data:
            self.logger.info(f"成功生成 {year}年{month}月 月度趋势图，涨跌幅: {change_percent:+.2f}%")
            # 记录已发送（只有不是强制发送时才记录）
            if force_month == 0 and force_year == 0:
                self._save_sent_month(year, month)
        
        return (image_data, month, year, change_percent)
    
    def force_generate_chart(self, year: int, month: int) -> Tuple[Optional[bytes], int, int, float]:
        """
        强制生成指定月份的趋势图（不检查发送条件，不记录发送状态）
        用于特殊情况下的手动发送
        
        Args:
            year: 年份
            month: 月份
        
        Returns:
            (图片数据, 月份, 年份, 涨跌幅)
        """
        self.logger.info(f"强制生成 {year}年{month}月 趋势图")
        
        # 获取数据
        df = self.get_monthly_data(year, month)
        if df is None:
            return (None, 0, 0, 0)
        
        # 计算涨跌幅
        start_price = df['close'].iloc[0]
        end_price = df['close'].iloc[-1]
        change_percent = ((end_price - start_price) / start_price) * 100
        
        # 生成图表
        image_data = self.create_chart(df, month, year)
        
        if image_data:
            self.logger.info(f"成功生成 {year}年{month}月 月度趋势图，涨跌幅: {change_percent:+.2f}%")
        
        return (image_data, month, year, change_percent)
    
    # ============================================================
    # 多市场月报功能
    # ============================================================
    
    def get_multi_stock_monthly_data(
        self, 
        market: str, 
        year: int, 
        month: int,
        stock_type: str = 'all'
    ) -> Dict:
        """
        获取指定市场所有股票的月度数据
        
        数据源优先级（与日报一致）：
        - 韩股：pykrx
        - 港股/美股：yfinance → akshare → 腾讯股票
        
        Args:
            market: 市场类型 (kr/us/hk)
            year: 年份
            month: 月份
            stock_type: 股票类型 ('all'=全部, 'tech'=仅科技股, 'game'=仅游戏股)
            
        Returns:
            包含所有股票数据的字典 {symbol: {name, data, change_percent}}
        """
        from config import get_tech_list, get_game_list
        
        first_day = datetime(year, month, 1)
        last_day = datetime(year, month, monthrange(year, month)[1])
        
        start_str = first_day.strftime("%Y%m%d")
        end_str = last_day.strftime("%Y%m%d")
        
        type_text = {'all': '所有', 'tech': '科技股', 'game': '游戏股'}.get(stock_type, stock_type)
        self.logger.info(f"获取 {MARKET_NAMES.get(market, market)} {year}年{month}月 {type_text}数据")
        
        # 根据市场和 stock_type 获取股票列表
        if market == MARKET_KR:
            stock_list = KR_STOCK_LIST  # 韩股只有游戏股
        elif market == MARKET_US:
            if stock_type == 'tech':
                stock_list = get_tech_list(market)
            elif stock_type == 'game':
                stock_list = get_game_list(market)
            else:
                stock_list = US_STOCK_LIST
        elif market == MARKET_HK:
            if stock_type == 'tech':
                stock_list = get_tech_list(market)
            elif stock_type == 'game':
                stock_list = get_game_list(market)
            else:
                stock_list = HK_STOCK_LIST
        else:
            self.logger.error(f"不支持的市场类型: {market}")
            return {}
        
        result = {}
        
        for symbol, name, _ in stock_list:
            try:
                if market == MARKET_KR:
                    df = self._get_kr_monthly_data(symbol, start_str, end_str)
                elif market == MARKET_US:
                    df = self._get_us_monthly_data(symbol, year, month)
                elif market == MARKET_HK:
                    df = self._get_hk_monthly_data(symbol, year, month)
                else:
                    continue
                
                if df is not None and len(df) >= 2:
                    # 确保索引不带时区信息，统一处理
                    if hasattr(df.index, 'tz') and df.index.tz is not None:
                        df.index = df.index.tz_localize(None)
                    
                    start_price = df['close'].iloc[0]
                    end_price = df['close'].iloc[-1]
                    change_percent = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
                    
                    result[symbol] = {
                        'name': name,
                        'data': df,
                        'change_percent': change_percent,
                        'start_price': start_price,
                        'end_price': end_price
                    }
                    self.logger.info(f"  {name}: {change_percent:+.2f}%")
                else:
                    self.logger.warning(f"  {name}: 数据不足")
                    
            except Exception as e:
                self.logger.error(f"  获取 {name} 数据失败: {e}")
        
        self.logger.info(f"成功获取 {len(result)}/{len(stock_list)} 只股票数据")
        return result
    
    def _get_kr_monthly_data(self, symbol: str, start_str: str, end_str: str):
        """获取韩股月度数据"""
        df = krx.get_market_ohlcv_by_date(
            fromdate=start_str,
            todate=end_str,
            ticker=symbol
        )
        
        if df.empty:
            return None
        
        df = df.rename(columns={
            '시가': 'open',
            '고가': 'high',
            '저가': 'low',
            '종가': 'close',
            '거래량': 'volume'
        })
        
        return df
    
    def _get_us_monthly_data(self, symbol: str, year: int, month: int):
        """
        获取美股月度数据 - 多数据源备用策略（与日报一致）
        
        优先级：yfinance（最稳定）→ akshare（爬虫，易被封）→ 腾讯股票（历史K线兜底）
        """
        # 1. 首先尝试 yfinance
        df = self._get_us_monthly_data_yfinance(symbol, year, month)
        if df is not None:
            return df
        
        # 2. yfinance 失败，尝试 akshare
        self.logger.debug(f"yfinance 获取 {symbol} 失败，尝试 akshare...")
        df = self._get_us_monthly_data_akshare(symbol, year, month)
        if df is not None:
            return df
        
        # 3. akshare 也失败，尝试腾讯股票
        self.logger.debug(f"akshare 获取 {symbol} 失败，尝试腾讯股票...")
        return self._get_us_monthly_data_tencent(symbol, year, month)
    
    def _get_us_monthly_data_yfinance(self, symbol: str, year: int, month: int):
        """获取美股月度数据 - 使用 yfinance"""
        try:
            import yfinance as yf
            
            ticker = yf.Ticker(symbol)
            df = ticker.history(period='3mo')  # 获取最近3个月确保有足够数据
            
            if df is None or df.empty:
                return None
            
            # 筛选指定月份数据
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{monthrange(year, month)[1]}"
            
            df_filtered = df[(df.index.strftime('%Y-%m-%d') >= start_date) & 
                            (df.index.strftime('%Y-%m-%d') <= end_date)]
            
            if df_filtered.empty:
                return None
            
            # 重命名列以统一格式
            df_filtered = df_filtered.rename(columns={
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            })
            
            # 确保索引不带时区信息
            if hasattr(df_filtered.index, 'tz') and df_filtered.index.tz is not None:
                df_filtered.index = df_filtered.index.tz_localize(None)
            
            return df_filtered[['open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            self.logger.debug(f"yfinance 获取 {symbol} 失败: {e}")
            return None
    
    def _get_us_monthly_data_akshare(self, symbol: str, year: int, month: int):
        """获取美股月度数据 - 使用 akshare"""
        import akshare as ak
        
        try:
            df = ak.stock_us_daily(symbol=symbol)
            
            if df is None or df.empty:
                return None
            
            # 筛选指定月份数据
            df['date'] = df['date'].astype(str)
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{monthrange(year, month)[1]}"
            
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            
            if df.empty:
                return None
            
            # 重命名列以统一格式
            df = df.rename(columns={
                'open': 'open',
                'high': 'high',
                'low': 'low',
                'close': 'close',
                'volume': 'volume'
            })
            
            # 设置日期为索引
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            
            return df
            
        except Exception as e:
            self.logger.debug(f"akshare 获取 {symbol} 失败: {e}")
            return None
    
    def _get_us_monthly_data_tencent(self, symbol: str, year: int, month: int):
        """
        获取美股月度数据 - 使用腾讯股票 API（与日报一致）
        
        接口地址：https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
        """
        try:
            import requests
            
            # 美股: AAPL -> usAAPL
            tencent_symbol = f'us{symbol.upper()}'
            
            # 腾讯股票日K接口
            url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            
            # 获取整月数据（多取一些确保数据充足）
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{monthrange(year, month)[1]}"
            
            params = {
                "param": f"{tencent_symbol},day,{start_date},{end_date},50,qfq"
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://gu.qq.com/"
            }
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            
            if data.get("code") != 0:
                return None
            
            # 解析数据
            stock_data = data.get("data", {}).get(tencent_symbol, {})
            
            # 优先使用前复权数据(qfqday)，如果没有则使用原始数据(day)
            klines = stock_data.get("qfqday") or stock_data.get("day", [])
            
            if not klines:
                return None
            
            # 筛选指定月份数据
            # 格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
            filtered_klines = [k for k in klines if k[0] >= start_date and k[0] <= end_date]
            
            if not filtered_klines:
                return None
            
            # 转换为 DataFrame
            df_data = {
                'date': [k[0] for k in filtered_klines],
                'open': [float(k[1]) for k in filtered_klines],
                'close': [float(k[2]) for k in filtered_klines],
                'high': [float(k[3]) for k in filtered_klines],
                'low': [float(k[4]) for k in filtered_klines],
                'volume': [float(k[5]) if len(k) > 5 else 0 for k in filtered_klines]
            }
            
            df = pd.DataFrame(df_data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df = df.sort_index()
            
            return df[['open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            self.logger.debug(f"腾讯股票获取 {symbol} 失败: {e}")
            return None
    
    def _get_hk_monthly_data(self, symbol: str, year: int, month: int):
        """
        获取港股月度数据 - 多数据源备用策略（与日报一致）
        
        优先级：yfinance（最稳定）→ akshare（爬虫，易被封）→ 腾讯股票（历史K线兜底）
        """
        # 1. 首先尝试 yfinance
        df = self._get_hk_monthly_data_yfinance(symbol, year, month)
        if df is not None:
            return df
        
        # 2. yfinance 失败，尝试 akshare
        self.logger.debug(f"yfinance 获取 {symbol} 失败，尝试 akshare...")
        df = self._get_hk_monthly_data_akshare(symbol, year, month)
        if df is not None:
            return df
        
        # 3. akshare 也失败，尝试腾讯股票
        self.logger.debug(f"akshare 获取 {symbol} 失败，尝试腾讯股票...")
        return self._get_hk_monthly_data_tencent(symbol, year, month)
    
    def _get_hk_monthly_data_yfinance(self, symbol: str, year: int, month: int):
        """获取港股月度数据 - 使用 yfinance"""
        try:
            import yfinance as yf
            
            # 港股代码格式：0700.HK
            # 需要去除多余的前导零，保留至少 4 位
            symbol_num = symbol.replace('.HK', '').lstrip('0')
            if not symbol_num:
                symbol_num = '0'
            yf_symbol = f"{symbol_num.zfill(4)}.HK"
            
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period='3mo')  # 获取最近3个月确保有足够数据
            
            if df is None or df.empty:
                return None
            
            # 筛选指定月份数据
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{monthrange(year, month)[1]}"
            
            df_filtered = df[(df.index.strftime('%Y-%m-%d') >= start_date) & 
                            (df.index.strftime('%Y-%m-%d') <= end_date)]
            
            if df_filtered.empty:
                return None
            
            # 重命名列以统一格式
            df_filtered = df_filtered.rename(columns={
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            })
            
            # 确保索引不带时区信息
            if hasattr(df_filtered.index, 'tz') and df_filtered.index.tz is not None:
                df_filtered.index = df_filtered.index.tz_localize(None)
            
            return df_filtered[['open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            self.logger.debug(f"yfinance 获取 {symbol} 失败: {e}")
            return None
    
    def _get_hk_monthly_data_akshare(self, symbol: str, year: int, month: int):
        """获取港股月度数据 - 使用 akshare"""
        import akshare as ak
        
        try:
            # 港股代码格式：00700（不带.HK）
            symbol_clean = symbol.replace('.HK', '').zfill(5)
            df = ak.stock_hk_hist(symbol=symbol_clean, period='daily', adjust='')
            
            if df is None or df.empty:
                return None
            
            # 筛选指定月份数据
            df['日期'] = df['日期'].astype(str)
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{monthrange(year, month)[1]}"
            
            df = df[(df['日期'] >= start_date) & (df['日期'] <= end_date)]
            
            if df.empty:
                return None
            
            # 重命名列以统一格式
            df = df.rename(columns={
                '开盘': 'open',
                '最高': 'high',
                '最低': 'low',
                '收盘': 'close',
                '成交量': 'volume'
            })
            
            # 设置日期为索引
            df['日期'] = pd.to_datetime(df['日期'])
            df = df.set_index('日期')
            
            return df
            
        except Exception as e:
            self.logger.debug(f"akshare 获取 {symbol} 失败: {e}")
            return None
    
    def _get_hk_monthly_data_tencent(self, symbol: str, year: int, month: int):
        """
        获取港股月度数据 - 使用腾讯股票 API（与日报一致）
        
        接口地址：https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
        """
        try:
            import requests
            
            # 港股: 0100.HK -> hk00100
            symbol_clean = symbol.replace('.HK', '').zfill(5)
            tencent_symbol = f'hk{symbol_clean}'
            
            # 腾讯股票日K接口
            url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            
            # 获取整月数据（多取一些确保数据充足）
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{monthrange(year, month)[1]}"
            
            params = {
                "param": f"{tencent_symbol},day,{start_date},{end_date},50,qfq"
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://gu.qq.com/"
            }
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code != 200:
                return None
            
            data = resp.json()
            
            if data.get("code") != 0:
                return None
            
            # 解析数据
            stock_data = data.get("data", {}).get(tencent_symbol, {})
            
            # 优先使用前复权数据(qfqday)，如果没有则使用原始数据(day)
            klines = stock_data.get("qfqday") or stock_data.get("day", [])
            
            if not klines:
                return None
            
            # 筛选指定月份数据
            # 格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
            filtered_klines = [k for k in klines if k[0] >= start_date and k[0] <= end_date]
            
            if not filtered_klines:
                return None
            
            # 转换为 DataFrame
            df_data = {
                'date': [k[0] for k in filtered_klines],
                'open': [float(k[1]) for k in filtered_klines],
                'close': [float(k[2]) for k in filtered_klines],
                'high': [float(k[3]) for k in filtered_klines],
                'low': [float(k[4]) for k in filtered_klines],
                'volume': [float(k[5]) if len(k) > 5 else 0 for k in filtered_klines]
            }
            
            df = pd.DataFrame(df_data)
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            df = df.sort_index()
            
            return df[['open', 'high', 'low', 'close', 'volume']]
            
        except Exception as e:
            self.logger.debug(f"腾讯股票获取 {symbol} 失败: {e}")
            return None
    
    def _get_kr_index_monthly_data(self, year: int, month: int) -> Optional[Dict]:
        """
        获取韩股 KOSPI 指数的月度数据
        
        Args:
            year: 年份
            month: 月份
            
        Returns:
            指数数据字典 {name, data, change_percent, daily_changes} 或 None
        """
        self.logger.info(f"正在获取 KOSPI 指数 {year}年{month}月数据...")
        
        # 方法1：使用 pykrx 获取
        result = self._get_kr_index_via_pykrx(year, month)
        if result:
            return result
        
        # 方法2：使用 akshare 作为备用
        self.logger.info("pykrx 获取失败，尝试使用 akshare 备用方案...")
        result = self._get_kr_index_via_akshare(year, month)
        if result:
            return result
        
        self.logger.warning(f"无法获取 KOSPI 指数 {year}年{month}月数据（两种方法都失败）")
        return None
    
    def _get_kr_index_via_pykrx(self, year: int, month: int) -> Optional[Dict]:
        """使用 pykrx 获取 KOSPI 指数（使用 KODEX 200 ETF 作为代理，与日报一致）"""
        try:
            first_day = datetime(year, month, 1)
            last_day = datetime(year, month, monthrange(year, month)[1])
            start_str = first_day.strftime("%Y%m%d")
            end_str = last_day.strftime("%Y%m%d")
            
            self.logger.info(f"pykrx: 获取 {start_str} - {end_str} KOSPI 数据（使用 KODEX 200 ETF）...")
            
            # 使用 KODEX 200 ETF (069500) 作为 KOSPI 指数的代理，与日报一致
            # 这个方法比 get_index_ohlcv_by_date 更稳定
            df = krx.get_market_ohlcv_by_date(
                fromdate=start_str,
                todate=end_str,
                ticker="069500"  # KODEX 200 ETF
            )
            
            if df is None or df.empty:
                self.logger.warning("pykrx: KOSPI 数据为空")
                return None
            
            self.logger.info(f"pykrx: 获取到 {len(df)} 条数据")
            
            # 重命名列
            df = df.rename(columns={
                '시가': 'open',
                '고가': 'high',
                '저가': 'low',
                '종가': 'close',
                '거래량': 'volume'
            })
            
            if len(df) < 2:
                self.logger.warning("pykrx: 数据不足（少于2条）")
                return None
            
            # 计算月度涨跌幅
            start_price = float(df['close'].iloc[0])
            end_price = float(df['close'].iloc[-1])
            change_percent = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
            
            # 计算每日变化
            daily_changes = []
            for i in range(len(df)):
                date = df.index[i]
                close = df['close'].iloc[i]
                if i == 0:
                    daily_change = 0
                else:
                    prev_close = df['close'].iloc[i - 1]
                    daily_change = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0
                daily_changes.append({
                    'date': date,
                    'close': close,
                    'change': daily_change
                })
            
            self.logger.info(f"✅ pykrx: KOSPI 200 指数月度数据获取成功: {change_percent:+.2f}%")
            return {
                'name': 'KOSPI 200',
                'data': df[['close']],
                'change_percent': change_percent,
                'daily_changes': daily_changes
            }
            
        except Exception as e:
            self.logger.warning(f"pykrx: 获取 KOSPI 失败: {e}")
            return None
    
    def _get_kr_index_via_akshare(self, year: int, month: int) -> Optional[Dict]:
        """使用 akshare 获取 KOSPI 指数（备用方案）"""
        try:
            import akshare as ak
            
            first_day = datetime(year, month, 1)
            last_day = datetime(year, month, monthrange(year, month)[1])
            start_date = first_day.strftime('%Y-%m-%d')
            end_date = last_day.strftime('%Y-%m-%d')
            
            self.logger.info(f"akshare: 获取 {start_date} - {end_date} KOSPI 数据...")
            
            # 尝试使用 akshare 获取韩国 KOSPI 指数
            df = ak.index_global_hist_em(symbol='韩国KOSPI')
            
            if df is None or df.empty:
                self.logger.warning("akshare: KOSPI 数据为空")
                return None
            
            # 筛选日期范围
            df['日期'] = df['日期'].astype(str)
            df = df[(df['日期'] >= start_date) & (df['日期'] <= end_date)]
            
            if len(df) < 2:
                self.logger.warning("akshare: 筛选后数据不足")
                return None
            
            self.logger.info(f"akshare: 获取到 {len(df)} 条数据")
            
            # 转换格式
            df = df.rename(columns={'最新价': 'close'})
            df['日期'] = pd.to_datetime(df['日期'])
            df = df.set_index('日期')
            df = df.sort_index()  # 确保按日期排序
            
            start_price = float(df['close'].iloc[0])
            end_price = float(df['close'].iloc[-1])
            change_percent = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
            
            # 计算每日变化
            daily_changes = []
            for i in range(len(df)):
                date = df.index[i]
                close = df['close'].iloc[i]
                if i == 0:
                    daily_change = 0
                else:
                    prev_close = df['close'].iloc[i - 1]
                    daily_change = ((close - prev_close) / prev_close) * 100 if prev_close > 0 else 0
                daily_changes.append({
                    'date': date,
                    'close': close,
                    'change': daily_change
                })
            
            self.logger.info(f"✅ akshare: KOSPI 指数月度数据获取成功: {change_percent:+.2f}%")
            return {
                'name': 'KOSPI',
                'data': df[['close']],
                'change_percent': change_percent,
                'daily_changes': daily_changes
            }
            
        except Exception as e:
            self.logger.warning(f"akshare: 获取 KOSPI 失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _get_index_monthly_data(self, market: str, year: int, month: int) -> Optional[Dict]:
        """
        获取大盘指数的月度数据 - 多数据源备用策略
        
        优先级：
        - 韩股：pykrx → akshare
        - 港股/美股：yfinance → akshare
        
        Args:
            market: 市场类型 (kr/us/hk)
            year: 年份
            month: 月份
            
        Returns:
            指数数据字典 {name, data, change_percent} 或 None
        """
        first_day = datetime(year, month, 1)
        last_day = datetime(year, month, monthrange(year, month)[1])
        start_date = first_day.strftime('%Y-%m-%d')
        end_date = last_day.strftime('%Y-%m-%d')
        
        if market == MARKET_KR:
            # 韩股使用 pykrx → akshare
            return self._get_kr_index_monthly_data(year, month)
                
        elif market == MARKET_US:
            # 美股 - 标普500: yfinance → akshare
            result = self._get_us_index_monthly_data_yfinance(start_date, end_date)
            if result:
                return result
            self.logger.info("yfinance 获取标普500失败，尝试 akshare...")
            return self._get_us_index_monthly_data_akshare(start_date, end_date)
                
        elif market == MARKET_HK:
            # 港股 - 恒生指数: yfinance → akshare
            result = self._get_hk_index_monthly_data_yfinance(start_date, end_date)
            if result:
                return result
            self.logger.info("yfinance 获取恒生指数失败，尝试 akshare...")
            return self._get_hk_index_monthly_data_akshare(start_date, end_date)
        
        return None
    
    def _get_us_index_monthly_data_yfinance(self, start_date: str, end_date: str) -> Optional[Dict]:
        """获取标普500指数月度数据 - 使用 yfinance"""
        try:
            import yfinance as yf
            
            ticker = yf.Ticker('^GSPC')
            df = ticker.history(period='3mo')
            
            if df is None or df.empty:
                return None
            
            df_filtered = df[(df.index.strftime('%Y-%m-%d') >= start_date) & 
                            (df.index.strftime('%Y-%m-%d') <= end_date)]
            
            if len(df_filtered) < 2:
                return None
            
            df_filtered = df_filtered.rename(columns={'Close': 'close'})
            
            # 确保索引不带时区信息
            if hasattr(df_filtered.index, 'tz') and df_filtered.index.tz is not None:
                df_filtered.index = df_filtered.index.tz_localize(None)
            
            start_price = float(df_filtered['close'].iloc[0])
            end_price = float(df_filtered['close'].iloc[-1])
            change_percent = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
            
            self.logger.info(f"标普500指数月度数据获取成功: {change_percent:+.2f}% [yfinance]")
            return {
                'name': '标普500',
                'data': df_filtered[['close']],
                'change_percent': change_percent
            }
        except Exception as e:
            self.logger.debug(f"yfinance 获取标普500失败: {e}")
            return None
    
    def _get_us_index_monthly_data_akshare(self, start_date: str, end_date: str) -> Optional[Dict]:
        """获取标普500指数月度数据 - 使用 akshare"""
        try:
            import akshare as ak
            
            df = ak.index_global_hist_em(symbol='标普500')
            if df is None or df.empty:
                return None
            
            df['日期'] = df['日期'].astype(str)
            df = df[(df['日期'] >= start_date) & (df['日期'] <= end_date)]
            
            if len(df) < 2:
                return None
            
            df = df.rename(columns={'最新价': 'close'})
            df['日期'] = pd.to_datetime(df['日期'])
            df = df.set_index('日期')
            
            start_price = float(df['close'].iloc[0])
            end_price = float(df['close'].iloc[-1])
            change_percent = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
            
            self.logger.info(f"标普500指数月度数据获取成功: {change_percent:+.2f}% [akshare]")
            return {
                'name': '标普500',
                'data': df[['close']],
                'change_percent': change_percent
            }
        except Exception as e:
            self.logger.warning(f"akshare 获取标普500指数失败: {e}")
            return None
    
    def _get_hk_index_monthly_data_yfinance(self, start_date: str, end_date: str) -> Optional[Dict]:
        """获取恒生指数月度数据 - 使用 yfinance"""
        try:
            import yfinance as yf
            
            ticker = yf.Ticker('^HSI')
            df = ticker.history(period='3mo')
            
            if df is None or df.empty:
                return None
            
            df_filtered = df[(df.index.strftime('%Y-%m-%d') >= start_date) & 
                            (df.index.strftime('%Y-%m-%d') <= end_date)]
            
            if len(df_filtered) < 2:
                return None
            
            df_filtered = df_filtered.rename(columns={'Close': 'close'})
            
            # 确保索引不带时区信息
            if hasattr(df_filtered.index, 'tz') and df_filtered.index.tz is not None:
                df_filtered.index = df_filtered.index.tz_localize(None)
            
            start_price = float(df_filtered['close'].iloc[0])
            end_price = float(df_filtered['close'].iloc[-1])
            change_percent = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
            
            self.logger.info(f"恒生指数月度数据获取成功: {change_percent:+.2f}% [yfinance]")
            return {
                'name': '恒生指数',
                'data': df_filtered[['close']],
                'change_percent': change_percent
            }
        except Exception as e:
            self.logger.debug(f"yfinance 获取恒生指数失败: {e}")
            return None
    
    def _get_hk_index_monthly_data_akshare(self, start_date: str, end_date: str) -> Optional[Dict]:
        """获取恒生指数月度数据 - 使用 akshare"""
        try:
            import akshare as ak
            
            df = ak.stock_hk_index_daily_sina(symbol='HSI')
            if df is None or df.empty:
                return None
            
            df['date'] = df['date'].astype(str)
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]
            
            if len(df) < 2:
                return None
            
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
            
            start_price = float(df['close'].iloc[0])
            end_price = float(df['close'].iloc[-1])
            change_percent = ((end_price - start_price) / start_price) * 100 if start_price > 0 else 0
            
            self.logger.info(f"恒生指数月度数据获取成功: {change_percent:+.2f}% [akshare]")
            return {
                'name': '恒生指数',
                'data': df[['close']],
                'change_percent': change_percent
            }
        except Exception as e:
            self.logger.warning(f"akshare 获取恒生指数失败: {e}")
            return None
    
    def create_multi_stock_chart(
        self,
        market: str,
        stock_data: Dict,
        month: int,
        year: int,
        title_prefix: str = "",
        index_data: Optional[Dict] = None,
        stock_type: str = "game"
    ) -> Optional[bytes]:
        """
        创建多股票月度走势折线图（所有股票在一张图中，显示归一化股价）
        
        Args:
            market: 市场类型
            stock_data: 股票数据字典
            month: 月份
            year: 年份
            title_prefix: 标题前缀
            index_data: 大盘指数数据（可选）
            stock_type: 股票类型 ('game'=游戏股, 'tech'=科技股, 'all'=全部)
            
        Returns:
            图片的 bytes 数据
        """
        global CHINESE_FONT
        
        if not stock_data:
            self.logger.error("没有股票数据可绘制")
            return None
        
        try:
            # 获取市场信息
            market_name = MARKET_NAMES.get(market, market)
            
            # 计算整体涨跌幅（所有股票的平均值）
            total_change = sum(d['change_percent'] for d in stock_data.values()) / len(stock_data)
            
            # 按涨跌幅排序（从高到低）
            sorted_stocks = sorted(stock_data.items(), key=lambda x: x[1]['change_percent'], reverse=True)
            
            # 根据股票数量调整图表尺寸
            n_stocks = len(sorted_stocks)
            fig_width = max(14, 12)
            fig_height = max(8, n_stocks * 0.4 + 3)
            
            fig, ax = plt.subplots(figsize=(fig_width, fig_height), dpi=150)
            fig.patch.set_facecolor('#ffffff')
            ax.set_facecolor('#fafafa')
            
            # 预定义颜色列表（用于区分不同股票）
            color_palette = [
                '#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#9333ea',
                '#0891b2', '#c2410c', '#4f46e5', '#be185d', '#059669',
                '#7c3aed', '#ea580c', '#0d9488', '#d97706', '#6366f1',
                '#e11d48', '#14b8a6', '#f59e0b', '#8b5cf6', '#84cc16'
            ]
            
            # 收集所有日期用于统一 X 轴
            all_dates = set()
            for symbol, data in stock_data.items():
                df = data['data']
                all_dates.update(df.index.tolist())
            all_dates = sorted(all_dates)
            
            # 绘制每只股票的折线（实际股价）
            legend_handles = []
            
            # 根据市场确定货币符号
            if market == MARKET_KR:
                currency_symbol = '₩'
                currency_unit = ''  # 韩元数值大，不需要单位
            elif market == MARKET_HK:
                currency_symbol = 'HK$'
                currency_unit = ''
            else:
                currency_symbol = '$'
                currency_unit = ''
            
            for idx, (symbol, data) in enumerate(sorted_stocks):
                df = data['data']
                name = data['name']
                change = data['change_percent']
                
                # 使用实际股价
                actual_price = df['close']
                
                color = color_palette[idx % len(color_palette)]
                change_symbol = '+' if change >= 0 else ''
                # 显示股票名称、涨跌幅和最新价格
                latest_price = actual_price.iloc[-1]
                
                # 韩股价格格式化（数值大，使用千分位）
                if market == MARKET_KR:
                    price_str = f'{currency_symbol}{int(latest_price):,}'
                else:
                    price_str = f'{currency_symbol}{latest_price:.1f}'
                
                label = f"{name} {price_str} ({change_symbol}{change:.1f}%)"
                
                line, = ax.plot(df.index, actual_price, 
                               color=color, linewidth=1.8, 
                               marker='o', markersize=3,
                               label=label, alpha=0.85)
                legend_handles.append(line)
            
            # 绘制大盘指数（使用右侧Y轴，显眼样式）
            ax2 = None
            if index_data:
                try:
                    idx_df = index_data['data']
                    idx_name = index_data['name']
                    idx_change = index_data['change_percent']
                    
                    # 创建右侧Y轴
                    ax2 = ax.twinx()
                    
                    idx_change_symbol = '+' if idx_change >= 0 else ''
                    idx_label = f"★ {idx_name} ({idx_change_symbol}{idx_change:.1f}%)"
                    
                    # 指数颜色：黑色
                    idx_color = '#333333'
                    
                    # 绘制指数线（粗虚线，无填充）
                    idx_line, = ax2.plot(idx_df.index, idx_df['close'],
                                        color=idx_color, linewidth=2.5,
                                        linestyle='--', marker='D', markersize=3,
                                        label=idx_label, alpha=0.9, zorder=1)
                    
                    legend_handles.append(idx_line)
                    
                    # 设置右侧Y轴样式
                    ax2.set_ylabel(f'{idx_name}', fontsize=11, fontproperties=CHINESE_FONT, color=idx_color)
                    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{x:,.0f}'))
                    ax2.tick_params(axis='y', labelsize=9, colors=idx_color)
                    ax2.spines['right'].set_color(idx_color)
                    ax2.spines['right'].set_linewidth(2)
                    
                    # 让右侧Y轴与左侧Y轴的涨跌幅比例一致，展现真实走势关系
                    # 获取左侧Y轴的实际范围（在图表渲染前需要先draw一下）
                    ax.figure.canvas.draw()
                    left_ymin, left_ymax = ax.get_ylim()
                    
                    # 计算左侧Y轴中间值和上下百分比范围
                    left_mid = (left_ymin + left_ymax) / 2
                    left_pct_range = (left_ymax - left_ymin) / left_mid  # 上下浮动的百分比
                    
                    # 用同样的百分比范围设置右侧Y轴
                    idx_first = idx_df['close'].iloc[0]  # 用月初值作为基准
                    idx_mid = idx_first
                    right_half_range = idx_mid * left_pct_range / 2
                    ax2.set_ylim(idx_mid - right_half_range, idx_mid + right_half_range)
                    
                    self.logger.info(f"已绘制大盘指数线（右侧Y轴）: {idx_name}")
                except Exception as e:
                    self.logger.warning(f"绘制指数线失败: {e}")
            
            # 设置 X 轴日期格式
            ax.xaxis.set_major_formatter(mdates.DateFormatter('%m/%d'))
            ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(all_dates)//15)))
            plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right', fontsize=9)
            
            # 设置左侧 Y 轴标签（股价）- 根据市场使用不同货币
            if market == MARKET_KR:
                ax.set_ylabel('股价 (KRW)', fontsize=11, fontproperties=CHINESE_FONT)
                ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'{int(x):,}'))
            elif market == MARKET_HK:
                ax.set_ylabel('股价 (HKD)', fontsize=11, fontproperties=CHINESE_FONT)
                ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:.1f}'))
            else:
                ax.set_ylabel('股价 (USD)', fontsize=11, fontproperties=CHINESE_FONT)
                ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, p: f'${x:.0f}'))
            ax.tick_params(axis='y', labelsize=9)
            
            # 添加网格（只用左侧Y轴的网格）
            ax.grid(True, linestyle='--', alpha=0.4, color='#e5e7eb')
            ax.set_axisbelow(True)
            
            # 根据 stock_type 确定标题
            if stock_type == 'tech':
                type_text = '科技股'
            elif stock_type == 'game':
                type_text = '游戏股'
            else:
                type_text = '股票'
            
            # 标题
            trend_text = '涨' if total_change >= 0 else '跌'
            change_symbol = '+' if total_change >= 0 else ''
            title = f"{market_name}{year}年{month}月{type_text}月报"
            ax.set_title(title, fontsize=14, fontweight='bold', color='#1f2937',
                        pad=15, loc='left', fontproperties=CHINESE_FONT)
            
            # 右上角显示平均涨跌幅
            avg_color = '#22c55e' if total_change >= 0 else '#ef4444'
            ax.text(0.99, 1.02, f'平均{trend_text}: {change_symbol}{total_change:.2f}%',
                   transform=ax.transAxes, fontsize=12, fontweight='bold',
                   color=avg_color, ha='right', va='bottom', fontproperties=CHINESE_FONT)
            
            # 图例（放在图表右侧或下方）
            # 根据股票数量决定图例位置
            if n_stocks <= 8:
                ax.legend(handles=legend_handles, loc='upper left', fontsize=8,
                         framealpha=0.9, edgecolor='#e5e7eb', prop=CHINESE_FONT,
                         ncol=2)
            else:
                # 股票多时，图例放在下方
                ax.legend(handles=legend_handles, loc='upper center', 
                         bbox_to_anchor=(0.5, -0.15), fontsize=8,
                         framealpha=0.9, edgecolor='#e5e7eb', prop=CHINESE_FONT,
                         ncol=min(4, (n_stocks + 1) // 2))
            
            # 调整布局
            plt.tight_layout()
            
            # 保存到内存
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=150, bbox_inches='tight',
                        facecolor='white', edgecolor='none')
            buf.seek(0)
            plt.close(fig)
            
            return buf.getvalue()
            
        except Exception as e:
            self.logger.error(f"生成多股票图表失败: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def generate_market_monthly_report(
        self,
        market: str,
        year: int,
        month: int,
        stock_type: str = 'all'
    ) -> Tuple[Optional[bytes], Dict, float, Optional[Dict]]:
        """
        生成指定市场的月度报告
        
        Args:
            market: 市场类型 (kr/us/hk)
            year: 年份
            month: 月份
            stock_type: 股票类型 ('all'=全部, 'tech'=仅科技股, 'game'=仅游戏股)
            
        Returns:
            (图片数据, 股票数据字典, 平均涨跌幅, 指数数据)
        """
        market_name = MARKET_NAMES.get(market, market)
        type_text = {'all': '', 'tech': '科技股', 'game': '游戏股'}.get(stock_type, '')
        self.logger.info(f"生成 {market_name} {year}年{month}月 {type_text}月度报告")
        
        # 获取股票数据（根据 stock_type 筛选）
        stock_data = self.get_multi_stock_monthly_data(market, year, month, stock_type)
        
        if not stock_data:
            self.logger.error(f"无法获取 {market_name} 股票数据")
            return (None, {}, 0, None)
        
        # 获取大盘指数数据
        index_data = self._get_index_monthly_data(market, year, month)
        if index_data:
            self.logger.info(f"大盘指数 {index_data['name']}: {index_data['change_percent']:+.2f}%")
        
        # 计算平均涨跌幅
        avg_change = sum(d['change_percent'] for d in stock_data.values()) / len(stock_data)
        
        # 生成图表（包含指数线）
        image_data = self.create_multi_stock_chart(
            market, stock_data, month, year,
            index_data=index_data,
            stock_type=stock_type
        )
        
        if image_data:
            self.logger.info(f"成功生成 {market_name} {year}年{month}月 月报，平均涨跌幅: {avg_change:+.2f}%")
        
        return (image_data, stock_data, avg_change, index_data)


# 添加 pandas 导入（在需要时）
try:
    import pandas as pd
except ImportError:
    pd = None
