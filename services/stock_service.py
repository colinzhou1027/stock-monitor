"""
股票数据服务
支持韩股（pykrx）、美股/港股（yfinance + akshare + 腾讯股票 多数据源）

数据源优先级（2026-03更新）：
- 韩股：pykrx（专用韩股库，非常稳定）
- 港股/美股：yfinance（最稳定）→ akshare（数据完整但易被封）→ 腾讯股票（兜底，历史K线）

大盘指数优先级：
- 韩股：pykrx
- 港股/美股：yfinance → akshare → 腾讯股票

休市日检测优先级：
- 韩股：pykrx
- 港股/美股：yfinance → akshare → 腾讯股票

策略说明：
- yfinance：Yahoo Finance 官方库，最稳定，但对部分新股（如 MiniMax）历史数据不完整
- akshare：从东方财富获取数据，历史数据最完整准确，但频繁请求容易被封
- 腾讯股票：提供历史K线数据（上一交易日与上上交易日收盘价），作为兜底方案
"""

from datetime import datetime, timedelta
from typing import List, Optional, Tuple
import pytz
import time

from models.stock import StockInfo, StockChange, MarketIndex
from utils.logger import LoggerMixin
from config import MARKET_KR, MARKET_US, MARKET_HK, get_market_info, get_index_list

# 请求配置常量
REQUEST_DELAY = 0.8  # 每次请求之间的延迟（秒）
MAX_RETRIES = 3  # 最大重试次数
RETRY_DELAY = 2.0  # 重试前的延迟（秒）


class StockService(LoggerMixin):
    """统一股票数据服务类 - 支持多市场"""
    
    def __init__(self, market: str, timezone: str = "Asia/Shanghai"):
        """
        初始化股票服务
        
        Args:
            market: 市场类型 (kr/us/hk)
            timezone: 时区设置
        """
        self.market = market
        self.timezone = pytz.timezone(timezone)
        self.market_info = get_market_info(market)
        self.market_tz = pytz.timezone(self.market_info["timezone"])
        self.currency = self.market_info["currency"]
        # 缓存最后已知的交易日期，用于新浪财经等实时数据源的日期对齐
        self._last_known_trading_date: Optional[datetime] = None
        self._last_known_prev_trading_date: Optional[datetime] = None
        
        self.logger.info(f"股票服务初始化完成，市场: {self.market_info['name']}")
    
    def get_stock_data(self, stock: StockInfo, days: int = 15) -> Optional[StockChange]:
        """
        获取单只股票的价格变化（上一交易日收盘 vs 上上交易日收盘）
        
        Args:
            stock: 股票信息
            days: 向前查找天数
        
        Returns:
            StockChange 对象，如果获取失败则返回 None
        """
        if self.market == MARKET_KR:
            return self._get_kr_stock_data(stock, days)
        else:
            return self._get_us_hk_stock_data(stock, days)
    
    def _get_kr_stock_data(self, stock: StockInfo, days: int = 15) -> Optional[StockChange]:
        """获取韩股数据 - 使用 pykrx"""
        try:
            from pykrx import stock as krx
            
            self.logger.debug(f"正在获取 {stock.name} ({stock.symbol}) 的股票数据...")
            
            # 统一使用中国时区计算日期，确保三个市场日期一致
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            end_date = yesterday.strftime("%Y%m%d")
            start_date = (today - timedelta(days=days)).strftime("%Y%m%d")
            
            df = krx.get_market_ohlcv_by_date(
                fromdate=start_date,
                todate=end_date,
                ticker=stock.symbol
            )
            
            if df.empty:
                self.logger.warning(f"无法获取 {stock.name} 的股票数据 (空数据)")
                return None
            
            if len(df) < 2:
                self.logger.warning(f"{stock.name} 的历史数据不足 (仅有 {len(df)} 天)")
                return None
            
            prev_close = float(df['종가'].iloc[-1])
            prev_date = df.index[-1].to_pydatetime()
            
            prev_prev_close = float(df['종가'].iloc[-2])
            prev_prev_date = df.index[-2].to_pydatetime()
            
            if prev_prev_close == 0:
                self.logger.warning(f"{stock.name} 上上交易日价格为0，无法计算涨跌幅")
                return None
                
            change_percent = ((prev_close - prev_prev_close) / prev_prev_close) * 100
            
            stock_change = StockChange(
                stock=stock,
                prev_close=prev_close,
                prev_prev_close=prev_prev_close,
                change_percent=change_percent,
                prev_date=prev_date,
                prev_prev_date=prev_prev_date
            )
            
            self.logger.info(
                f"{stock.name}: {prev_prev_date.strftime('%m/%d')}收盘{self.currency}{int(prev_prev_close):,} → "
                f"{prev_date.strftime('%m/%d')}收盘{self.currency}{int(prev_close):,} ({stock_change.formatted_change})"
            )
            
            return stock_change
            
        except Exception as e:
            self.logger.error(f"获取 {stock.name} ({stock.symbol}) 数据时出错: {str(e)}")
            return None
    
    def _get_us_hk_stock_data(self, stock: StockInfo, days: int = 15) -> Optional[StockChange]:
        """
        获取美股/港股数据 - 多数据源备用策略
        
        港股优先级：腾讯股票（国内源更稳定及时）→ yfinance → akshare
        美股优先级：yfinance（最稳定）→ akshare → 腾讯股票（兜底）
        
        注意：akshare 从东方财富获取数据，频繁请求可能被封，但历史数据比 yfinance 更完整（尤其是新股）
        """
        if self.market == MARKET_HK:
            # 港股：腾讯股票优先（与休市日检测保持一致，国内数据源更新更及时）
            # 1. 首先尝试腾讯股票
            result = self._get_tencent_stock_data(stock, days)
            if result:
                self._last_known_trading_date = result.prev_date
                self._last_known_prev_trading_date = result.prev_prev_date
                return result
            
            # 2. 腾讯股票失败，尝试 yfinance
            self.logger.info(f"腾讯股票获取 {stock.symbol} 失败，尝试 yfinance 备用数据源...")
            result = self._get_yfinance_stock_data(stock, days)
            if result:
                self._last_known_trading_date = result.prev_date
                self._last_known_prev_trading_date = result.prev_prev_date
                return result
            
            # 3. yfinance 也失败，最后尝试 akshare
            self.logger.info(f"yfinance 获取 {stock.symbol} 失败，尝试 akshare 备用数据源...")
            result = self._get_akshare_stock_data(stock, days)
            if result:
                self._last_known_trading_date = result.prev_date
                self._last_known_prev_trading_date = result.prev_prev_date
                return result
        else:
            # 美股：yfinance 优先（最稳定）
            # 1. 首先尝试 yfinance
            result = self._get_yfinance_stock_data(stock, days)
            if result:
                self._last_known_trading_date = result.prev_date
                self._last_known_prev_trading_date = result.prev_prev_date
                return result
            
            # 2. yfinance 失败，尝试 akshare
            self.logger.info(f"yfinance 获取 {stock.symbol} 失败，尝试 akshare 备用数据源...")
            result = self._get_akshare_stock_data(stock, days)
            if result:
                self._last_known_trading_date = result.prev_date
                self._last_known_prev_trading_date = result.prev_prev_date
                return result
            
            # 3. akshare 也失败，最后尝试腾讯股票（历史K线）
            self.logger.info(f"akshare 获取 {stock.symbol} 失败，尝试腾讯股票备用数据源...")
            result = self._get_tencent_stock_data(stock, days)
            if result:
                self._last_known_trading_date = result.prev_date
                self._last_known_prev_trading_date = result.prev_prev_date
                return result
        
        # 所有数据源都失败
        self.logger.error(f"所有数据源都无法获取 {stock.symbol} 数据")
        return None
    
    def _get_tencent_stock_data(self, stock: StockInfo, days: int = 15) -> Optional[StockChange]:
        """
        获取股票数据 - 使用腾讯股票 API（支持港股和美股历史K线）
        
        接口地址：https://web.ifzq.gtimg.cn/appstock/app/fqkline/get
        
        数据含义：
        返回历史日K线数据，格式为 [日期, 开盘, 收盘, 最高, 最低, 成交量]
        可以准确获取上一交易日与上上交易日的收盘价
        
        代码格式：
        - 港股: hk + 5位代码，如 hk00700（腾讯）、hk00100（MiniMax）
        - 美股: us + 大写代码，如 usAAPL（苹果）
        """
        try:
            import requests
            import json
            
            # 根据市场转换代码格式
            if self.market == MARKET_HK:
                # 港股: 0100.HK -> hk00100
                symbol_clean = stock.symbol.replace('.HK', '').zfill(5)
                tencent_symbol = f'hk{symbol_clean}'
            else:
                # 美股: AAPL -> usAAPL
                tencent_symbol = f'us{stock.symbol.upper()}'
            
            # 腾讯股票日K接口
            url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            
            # 统一使用中国时区计算日期
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            start_date = (today - timedelta(days=days + 10)).strftime('%Y-%m-%d')  # 多取10天确保数据充足
            end_date = yesterday.strftime('%Y-%m-%d')
            
            params = {
                "param": f"{tencent_symbol},day,{start_date},{end_date},{days},qfq"
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://gu.qq.com/"
            }
            
            self.logger.debug(f"正在获取 {stock.name} ({tencent_symbol}) 的股票数据 (腾讯股票)...")
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code != 200:
                self.logger.debug(f"腾讯股票 API 返回状态码: {resp.status_code}")
                return None
            
            data = resp.json()
            
            if data.get("code") != 0:
                self.logger.debug(f"腾讯股票 API 返回错误: {data.get('msg')}")
                return None
            
            # 解析数据
            stock_data = data.get("data", {}).get(tencent_symbol, {})
            
            # 优先使用前复权数据(qfqday)，如果没有则使用原始数据(day)
            klines = stock_data.get("qfqday") or stock_data.get("day", [])
            
            if not klines or len(klines) < 2:
                self.logger.debug(f"腾讯股票数据不足: {len(klines) if klines else 0} 条")
                return None
            
            # 过滤截止到昨天的数据
            end_date_str = yesterday.strftime('%Y-%m-%d')
            filtered_klines = [k for k in klines if k[0] <= end_date_str]
            
            if len(filtered_klines) < 2:
                self.logger.debug(f"腾讯股票过滤后数据不足: {len(filtered_klines)} 条")
                return None
            
            # 取最后两条数据：上一交易日和上上交易日
            # 格式: [日期, 开盘, 收盘, 最高, 最低, 成交量]
            prev_kline = filtered_klines[-1]  # 上一交易日
            prev_prev_kline = filtered_klines[-2]  # 上上交易日
            
            prev_date = datetime.strptime(prev_kline[0], '%Y-%m-%d')
            prev_close_price = float(prev_kline[2])  # 收盘价在索引2
            
            prev_prev_date = datetime.strptime(prev_prev_kline[0], '%Y-%m-%d')
            prev_prev_close_price = float(prev_prev_kline[2])  # 收盘价在索引2
            
            if prev_close_price <= 0 or prev_prev_close_price <= 0:
                self.logger.debug(f"腾讯股票价格无效: prev={prev_close_price}, prev_prev={prev_prev_close_price}")
                return None
            
            # 计算涨跌幅：上一交易日收盘 vs 上上交易日收盘
            change_percent = ((prev_close_price - prev_prev_close_price) / prev_prev_close_price) * 100
            
            # 缓存交易日期供其他数据源使用
            self._last_known_trading_date = prev_date
            self._last_known_prev_trading_date = prev_prev_date
            
            # 构建股票变化对象
            stock_change = StockChange(
                stock=stock,
                prev_close=prev_close_price,        # 上一交易日收盘价
                prev_prev_close=prev_prev_close_price,  # 上上交易日收盘价
                change_percent=change_percent,
                prev_date=prev_date,
                prev_prev_date=prev_prev_date
            )
            
            self.logger.info(
                f"{stock.name}: {prev_prev_date.strftime('%m/%d')}收盘{self.currency}{prev_prev_close_price:,.2f} → "
                f"{prev_date.strftime('%m/%d')}收盘{self.currency}{prev_close_price:,.2f} ({stock_change.formatted_change}) [腾讯股票]"
            )
            
            return stock_change
            
        except Exception as e:
            self.logger.warning(f"腾讯股票获取 {stock.name} ({stock.symbol}) 失败: {e}")
            return None
    
    def _get_reference_trading_dates(self) -> Optional[Tuple[datetime, datetime]]:
        """
        获取参考交易日期（用于新浪财经等实时数据源的日期对齐）
        
        通过快速查询 yfinance 获取最近的交易日期，用于保证日期一致性。
        
        Returns:
            (上一交易日, 上上交易日) 的元组，如果获取失败则返回 None
        """
        try:
            import yfinance as yf
            
            # 根据市场选择参考股票
            if self.market == MARKET_HK:
                ref_symbol = '0700.HK'  # 腾讯
            else:
                ref_symbol = 'AAPL'  # 苹果
            
            self.logger.debug(f"正在获取参考交易日期 ({ref_symbol})...")
            
            ticker = yf.Ticker(ref_symbol)
            df = ticker.history(period='5d')  # 只需要最近几天的数据
            
            if df is None or df.empty or len(df) < 2:
                self.logger.debug("无法获取参考交易日期")
                return None
            
            # 过滤数据截止日期：统一使用中国时区
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            end_date_str = yesterday.strftime('%Y-%m-%d')
            
            # 过滤截止到昨天的数据
            df = df[df.index.strftime('%Y-%m-%d') <= end_date_str]
            
            if len(df) < 2:
                self.logger.debug("参考交易日期数据不足")
                return None
            
            prev_date = df.index[-1].to_pydatetime().replace(tzinfo=None)
            prev_prev_date = df.index[-2].to_pydatetime().replace(tzinfo=None)
            
            self.logger.debug(f"获取到参考交易日期: {prev_date.strftime('%Y-%m-%d')}, {prev_prev_date.strftime('%Y-%m-%d')}")
            return (prev_date, prev_prev_date)
            
        except Exception as e:
            self.logger.debug(f"获取参考交易日期失败: {e}")
            return None
    
    def _get_yfinance_stock_data(self, stock: StockInfo, days: int = 15, retry_count: int = 0) -> Optional[StockChange]:
        """获取美股/港股数据 - 使用 yfinance（Yahoo Finance 数据源）"""
        try:
            import yfinance as yf
            
            # 转换股票代码格式
            if self.market == MARKET_HK:
                # 港股：yfinance 使用 4 位数字格式，如 0700.HK, 0100.HK
                # 但部分新股可能需要 5 位格式，如 00100.HK
                symbol_num = stock.symbol.replace('.HK', '').lstrip('0')
                if not symbol_num:
                    symbol_num = '0'
                # 先尝试 4 位格式
                symbol = f"{symbol_num.zfill(4)}.HK"
            else:
                # 美股：直接使用代码
                symbol = stock.symbol
            
            self.logger.debug(f"正在获取 {stock.name} ({symbol}) 的股票数据 (yfinance)...")
            
            # 获取历史数据（使用 period 参数更稳定）
            ticker = yf.Ticker(symbol)
            df = ticker.history(period='1mo')  # 获取最近一个月的数据
            
            # 如果 4 位格式失败且是港股，尝试 5 位格式（针对新股如 MiniMax）
            if (df is None or df.empty) and self.market == MARKET_HK:
                symbol_5digit = f"{symbol_num.zfill(5)}.HK"
                self.logger.debug(f"4位格式 {symbol} 无数据，尝试5位格式: {symbol_5digit}")
                ticker = yf.Ticker(symbol_5digit)
                df = ticker.history(period='1mo')
                if df is not None and not df.empty:
                    symbol = symbol_5digit  # 更新为成功的格式
                    self.logger.debug(f"5位格式 {symbol_5digit} 获取成功")
            
            if df is None or df.empty:
                self.logger.debug(f"yfinance 无法获取 {stock.name} ({symbol}) 的数据")
                return None
            
            # 过滤数据截止日期：统一使用中国时区
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            end_date_str = yesterday.strftime('%Y-%m-%d')
            
            # yfinance 返回的索引是 DatetimeIndex
            df = df[df.index.strftime('%Y-%m-%d') <= end_date_str]
            
            # 取最近的数据
            df = df.tail(days)
            
            if len(df) < 2:
                self.logger.warning(f"yfinance {stock.name} 数据不足（只有 {len(df)} 条），可能是新上市股票")
                return None
            
            # 获取收盘价
            prev_close = float(df['Close'].iloc[-1])
            prev_date = df.index[-1].to_pydatetime().replace(tzinfo=None)
            
            prev_prev_close = float(df['Close'].iloc[-2])
            prev_prev_date = df.index[-2].to_pydatetime().replace(tzinfo=None)
            
            if prev_prev_close == 0:
                self.logger.warning(f"{stock.name} 上上交易日价格为0")
                return None
                
            change_percent = ((prev_close - prev_prev_close) / prev_prev_close) * 100
            
            stock_change = StockChange(
                stock=stock,
                prev_close=prev_close,
                prev_prev_close=prev_prev_close,
                change_percent=change_percent,
                prev_date=prev_date,
                prev_prev_date=prev_prev_date
            )
            
            self.logger.info(
                f"{stock.name}: {prev_prev_date.strftime('%m/%d')}收盘{self.currency}{prev_prev_close:,.2f} → "
                f"{prev_date.strftime('%m/%d')}收盘{self.currency}{prev_close:,.2f} ({stock_change.formatted_change}) [yfinance]"
            )
            
            return stock_change
            
        except Exception as e:
            error_msg = str(e)
            # 检查是否是连接错误，支持重试
            if retry_count < MAX_RETRIES and ('Connection' in error_msg or 'timeout' in error_msg.lower() or 'HTTPError' in error_msg):
                self.logger.warning(f"yfinance 获取 {stock.name} ({stock.symbol}) 失败 (第{retry_count + 1}次): {error_msg}，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
                return self._get_yfinance_stock_data(stock, days, retry_count + 1)
            
            self.logger.warning(f"yfinance 获取 {stock.name} ({stock.symbol}) 失败: {error_msg}")
            return None
    
    def _get_akshare_stock_data(self, stock: StockInfo, days: int = 15, retry_count: int = 0) -> Optional[StockChange]:
        """获取美股/港股数据 - 使用 akshare（国内数据源，更稳定）"""
        try:
            import akshare as ak
            
            self.logger.debug(f"正在获取 {stock.name} ({stock.symbol}) 的股票数据 (akshare)...")
            
            if self.market == MARKET_HK:
                # 港股：使用 stock_hk_hist，代码格式为 00700（不带.HK）
                symbol_clean = stock.symbol.replace('.HK', '').zfill(5)
                df = ak.stock_hk_hist(symbol=symbol_clean, period='daily', adjust='')
                close_col = '收盘'
                date_col = '日期'
            else:
                # 美股：使用 stock_us_daily
                df = ak.stock_us_daily(symbol=stock.symbol)
                close_col = 'close'
                date_col = 'date'
            
            if df is None or df.empty:
                self.logger.debug(f"akshare 无法获取 {stock.name} 的数据")
                return None
            
            # 过滤数据截止日期：统一使用中国时区，确保三个市场日期一致
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            end_date_str = yesterday.strftime('%Y-%m-%d')
            
            # 将日期列转换为字符串进行比较
            df_dates = df[date_col].astype(str)
            df = df[df_dates <= end_date_str]
            
            # 取最近的数据
            df = df.tail(days)
            
            if len(df) < 2:
                self.logger.debug(f"akshare {stock.name} 数据不足")
                return None
            
            prev_close = float(df[close_col].iloc[-1])
            prev_date_val = df[date_col].iloc[-1]
            if hasattr(prev_date_val, 'to_pydatetime'):
                prev_date = prev_date_val.to_pydatetime()
            elif isinstance(prev_date_val, str):
                prev_date = datetime.strptime(prev_date_val, '%Y-%m-%d')
            else:
                prev_date = datetime.combine(prev_date_val, datetime.min.time())
            
            prev_prev_close = float(df[close_col].iloc[-2])
            prev_prev_date_val = df[date_col].iloc[-2]
            if hasattr(prev_prev_date_val, 'to_pydatetime'):
                prev_prev_date = prev_prev_date_val.to_pydatetime()
            elif isinstance(prev_prev_date_val, str):
                prev_prev_date = datetime.strptime(prev_prev_date_val, '%Y-%m-%d')
            else:
                prev_prev_date = datetime.combine(prev_prev_date_val, datetime.min.time())
            
            if prev_prev_close == 0:
                self.logger.warning(f"{stock.name} 上上交易日价格为0")
                return None
                
            change_percent = ((prev_close - prev_prev_close) / prev_prev_close) * 100
            
            stock_change = StockChange(
                stock=stock,
                prev_close=prev_close,
                prev_prev_close=prev_prev_close,
                change_percent=change_percent,
                prev_date=prev_date,
                prev_prev_date=prev_prev_date
            )
            
            self.logger.info(
                f"{stock.name}: {prev_prev_date.strftime('%m/%d')}收盘{self.currency}{prev_prev_close:,.2f} → "
                f"{prev_date.strftime('%m/%d')}收盘{self.currency}{prev_close:,.2f} ({stock_change.formatted_change}) [akshare]"
            )
            
            return stock_change
            
        except Exception as e:
            error_msg = str(e)
            # 检查是否是连接错误，支持重试
            if retry_count < MAX_RETRIES and ('Connection' in error_msg or 'RemoteDisconnected' in error_msg or 'timeout' in error_msg.lower()):
                self.logger.warning(f"akshare 获取 {stock.name} ({stock.symbol}) 失败 (第{retry_count + 1}次): {error_msg}，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
                return self._get_akshare_stock_data(stock, days, retry_count + 1)
            
            self.logger.warning(f"akshare 获取 {stock.name} ({stock.symbol}) 失败: {error_msg}")
            return None
    
    def get_market_index(self, days: int = 15) -> Optional[MarketIndex]:
        """
        获取韩股大盘指数（使用 KODEX 200 ETF 作为代理）
        仅适用于韩股市场
        """
        if self.market != MARKET_KR:
            self.logger.warning("get_market_index 仅适用于韩股，美股/港股请使用 get_market_indices")
            return None
        
        try:
            from pykrx import stock as krx
            
            self.logger.debug("正在获取 KOSPI 200 大盘指数...")
            
            # 统一使用中国时区计算日期，确保三个市场日期一致
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            end_date = yesterday.strftime("%Y%m%d")
            start_date = (today - timedelta(days=days)).strftime("%Y%m%d")
            
            df = krx.get_market_ohlcv_by_date(
                fromdate=start_date,
                todate=end_date,
                ticker="069500"  # KODEX 200
            )
            
            if df.empty or len(df) < 2:
                self.logger.warning("无法获取大盘指数数据")
                return None
            
            prev_close = float(df['종가'].iloc[-1])
            prev_date = df.index[-1].to_pydatetime()
            
            prev_prev_close = float(df['종가'].iloc[-2])
            prev_prev_date = df.index[-2].to_pydatetime()
            
            if prev_prev_close == 0:
                return None
                
            change_percent = ((prev_close - prev_prev_close) / prev_prev_close) * 100
            
            market_index = MarketIndex(
                name="KOSPI 200",
                prev_close=prev_close,
                prev_prev_close=prev_prev_close,
                change_percent=change_percent,
                prev_date=prev_date,
                prev_prev_date=prev_prev_date
            )
            
            self.logger.info(
                f"大盘: {prev_prev_date.strftime('%m/%d')}收盘{self.currency}{int(prev_prev_close):,} → "
                f"{prev_date.strftime('%m/%d')}收盘{self.currency}{int(prev_close):,} ({market_index.formatted_change})"
            )
            
            return market_index
            
        except Exception as e:
            self.logger.error(f"获取大盘指数时出错: {str(e)}")
            return None
    
    def get_market_indices(self, days: int = 15) -> List[MarketIndex]:
        """
        获取美股/港股大盘指数列表
        
        Args:
            days: 向前查找天数
            
        Returns:
            MarketIndex 对象列表
        """
        if self.market == MARKET_KR:
            # 韩股返回单个指数
            idx = self.get_market_index(days)
            return [idx] if idx else []
        
        index_list = get_index_list(self.market)
        indices = []
        
        for i, (symbol, name, _) in enumerate(index_list):
            index = self._get_single_index(symbol, name, days)
            if index:
                indices.append(index)
            
            # 添加请求间隔，避免被服务器限流（不在最后一个请求后等待）
            if i < len(index_list) - 1:
                time.sleep(REQUEST_DELAY)
        
        return indices
    
    def _get_single_index(self, symbol: str, name: str, days: int = 15) -> Optional[MarketIndex]:
        """
        获取单个指数数据 - 多数据源备用策略
        
        优先级：yfinance（最稳定）→ akshare（爬虫，易被封）→ 腾讯股票（兜底）
        """
        # 1. 首先尝试 yfinance（最稳定）
        result = self._get_yfinance_index(symbol, name, days)
        if result:
            return result
        
        # 2. yfinance 失败，尝试 akshare 备用
        self.logger.info(f"yfinance 获取指数 {name} 失败，尝试 akshare 备用数据源...")
        result = self._get_akshare_index(symbol, name, days)
        if result:
            return result
        
        # 3. akshare 也失败，最后尝试腾讯股票（兜底）
        self.logger.info(f"akshare 获取指数 {name} 失败，尝试腾讯股票备用数据源...")
        result = self._get_tencent_index(symbol, name, days)
        if result:
            return result
        
        # 三个数据源都失败
        self.logger.error(f"所有数据源都无法获取指数 {name} ({symbol}) 数据")
        return None
    
    def _get_yfinance_index(self, symbol: str, name: str, days: int = 15, retry_count: int = 0) -> Optional[MarketIndex]:
        """获取指数数据 - 使用 yfinance（Yahoo Finance 数据源）"""
        try:
            import yfinance as yf
            
            # 转换指数代码格式（yfinance 使用不同的符号）
            yf_symbol = symbol
            if symbol == '^HSI':
                yf_symbol = '^HSI'  # 恒生指数
            elif symbol == '^GSPC':
                yf_symbol = '^GSPC'  # 标普500
            
            self.logger.debug(f"正在获取 {name} ({yf_symbol}) 指数 (yfinance)...")
            
            # 获取历史数据（使用 period 参数更稳定）
            ticker = yf.Ticker(yf_symbol)
            df = ticker.history(period='1mo')  # 获取最近一个月的数据
            
            if df is None or df.empty:
                self.logger.debug(f"yfinance 无法获取 {name} ({yf_symbol}) 指数数据")
                return None
            
            # 过滤数据截止日期：统一使用中国时区
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            end_date_str = yesterday.strftime('%Y-%m-%d')
            
            # yfinance 返回的索引是 DatetimeIndex
            df = df[df.index.strftime('%Y-%m-%d') <= end_date_str]
            
            # 取最近的数据
            df = df.tail(days)
            
            if len(df) < 2:
                self.logger.debug(f"yfinance {name} 指数数据不足（只有 {len(df)} 条）")
                return None
            
            # 获取收盘价
            prev_close = float(df['Close'].iloc[-1])
            prev_date = df.index[-1].to_pydatetime().replace(tzinfo=None)
            
            prev_prev_close = float(df['Close'].iloc[-2])
            prev_prev_date = df.index[-2].to_pydatetime().replace(tzinfo=None)
            
            if prev_prev_close == 0:
                return None
                
            change_percent = ((prev_close - prev_prev_close) / prev_prev_close) * 100
            
            market_index = MarketIndex(
                name=name,
                prev_close=prev_close,
                prev_prev_close=prev_prev_close,
                change_percent=change_percent,
                prev_date=prev_date,
                prev_prev_date=prev_prev_date
            )
            
            self.logger.info(
                f"指数 {name}: {prev_prev_date.strftime('%m/%d')}收盘{prev_prev_close:,.2f} → "
                f"{prev_date.strftime('%m/%d')}收盘{prev_close:,.2f} ({market_index.formatted_change}) [yfinance]"
            )
            
            return market_index
            
        except Exception as e:
            error_msg = str(e)
            # 检查是否是连接错误，支持重试
            if retry_count < MAX_RETRIES and ('Connection' in error_msg or 'timeout' in error_msg.lower() or 'HTTPError' in error_msg):
                self.logger.warning(f"yfinance 获取 {name} 指数失败 (第{retry_count + 1}次): {error_msg}，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
                return self._get_yfinance_index(symbol, name, days, retry_count + 1)
            
            self.logger.warning(f"yfinance 获取 {name} 指数失败: {error_msg}")
            return None
    
    def _get_akshare_index(self, symbol: str, name: str, days: int = 15, retry_count: int = 0) -> Optional[MarketIndex]:
        """获取指数数据 - 使用 akshare"""
        try:
            import akshare as ak
            
            self.logger.debug(f"正在获取 {name} ({symbol}) 指数 (akshare)...")
            
            df = None
            close_col = 'close'
            date_col = 'date'
            
            if symbol == '^HSI':
                # 恒生指数 - 优先使用新浪接口（更稳定）
                try:
                    df = ak.stock_hk_index_daily_sina(symbol='HSI')
                    close_col = 'close'
                    date_col = 'date'
                    self.logger.debug(f"恒生指数使用新浪接口获取成功")
                except Exception as e1:
                    self.logger.debug(f"新浪接口失败: {e1}, 尝试全球指数接口...")
                    try:
                        # 备用：全球指数接口
                        df = ak.index_global_hist_em(symbol='恒生指数')
                        close_col = '最新价'
                        date_col = '日期'
                        self.logger.debug(f"恒生指数使用全球指数接口获取成功")
                    except Exception as e2:
                        self.logger.debug(f"全球指数接口也失败: {e2}, 尝试东财接口...")
                        # 最后备用：东财接口
                        df = ak.stock_hk_index_daily_em(symbol='HSI')
                        close_col = 'latest'
                        date_col = 'date'
            elif symbol == '^GSPC':
                # 标普500 - 使用全球指数接口
                df = ak.index_global_hist_em(symbol='标普500')
                close_col = '最新价'
                date_col = '日期'
            
            if df is None or df.empty:
                self.logger.debug(f"akshare 无法获取 {name} 指数数据")
                return None
            
            # 过滤数据截止日期：统一使用中国时区，确保三个市场日期一致
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            end_date_str = yesterday.strftime('%Y-%m-%d')
            
            # 将日期列转换为字符串进行比较
            df_dates = df[date_col].astype(str)
            df = df[df_dates <= end_date_str]
            
            df = df.tail(days)
            
            if len(df) < 2:
                self.logger.debug(f"akshare {name} 指数数据不足")
                return None
            
            prev_close = float(df[close_col].iloc[-1])
            prev_date_val = df[date_col].iloc[-1]
            if hasattr(prev_date_val, 'to_pydatetime'):
                prev_date = prev_date_val.to_pydatetime()
            elif isinstance(prev_date_val, str):
                prev_date = datetime.strptime(prev_date_val, '%Y-%m-%d')
            else:
                prev_date = datetime.combine(prev_date_val, datetime.min.time())
            
            prev_prev_close = float(df[close_col].iloc[-2])
            prev_prev_date_val = df[date_col].iloc[-2]
            if hasattr(prev_prev_date_val, 'to_pydatetime'):
                prev_prev_date = prev_prev_date_val.to_pydatetime()
            elif isinstance(prev_prev_date_val, str):
                prev_prev_date = datetime.strptime(prev_prev_date_val, '%Y-%m-%d')
            else:
                prev_prev_date = datetime.combine(prev_prev_date_val, datetime.min.time())
            
            if prev_prev_close == 0:
                return None
                
            change_percent = ((prev_close - prev_prev_close) / prev_prev_close) * 100
            
            market_index = MarketIndex(
                name=name,
                prev_close=prev_close,
                prev_prev_close=prev_prev_close,
                change_percent=change_percent,
                prev_date=prev_date,
                prev_prev_date=prev_prev_date
            )
            
            self.logger.info(
                f"指数 {name}: {prev_prev_date.strftime('%m/%d')}收盘{prev_prev_close:,.2f} → "
                f"{prev_date.strftime('%m/%d')}收盘{prev_close:,.2f} ({market_index.formatted_change}) [akshare]"
            )
            
            return market_index
            
        except Exception as e:
            error_msg = str(e)
            # 检查是否是连接错误，支持重试
            if retry_count < MAX_RETRIES and ('Connection' in error_msg or 'RemoteDisconnected' in error_msg or 'timeout' in error_msg.lower()):
                self.logger.warning(f"akshare 获取 {name} 指数失败 (第{retry_count + 1}次): {error_msg}，{RETRY_DELAY}秒后重试...")
                time.sleep(RETRY_DELAY)
                return self._get_akshare_index(symbol, name, days, retry_count + 1)
            
            self.logger.warning(f"akshare 获取 {name} 指数失败: {error_msg}")
            return None
    
    def _get_tencent_index(self, symbol: str, name: str, days: int = 15) -> Optional[MarketIndex]:
        """获取指数数据 - 使用腾讯股票 API（兜底数据源）"""
        try:
            import requests
            
            # 转换指数代码格式
            # 腾讯股票指数代码格式：港股用 hkHSI，美股使用全球指数需要特殊处理
            if symbol == '^HSI':
                tencent_symbol = 'hkHSI'  # 恒生指数
            elif symbol == '^GSPC':
                # 标普500 在腾讯股票中没有直接支持，使用 SPY ETF 作为代理
                tencent_symbol = 'usSPY'
            else:
                self.logger.debug(f"腾讯股票不支持指数 {symbol}")
                return None
            
            # 腾讯股票日K接口
            url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            
            # 统一使用中国时区计算日期
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            start_date = (today - timedelta(days=days + 10)).strftime('%Y-%m-%d')
            end_date = yesterday.strftime('%Y-%m-%d')
            
            params = {
                "param": f"{tencent_symbol},day,{start_date},{end_date},{days},qfq"
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://gu.qq.com/"
            }
            
            self.logger.debug(f"正在获取 {name} ({tencent_symbol}) 指数 (腾讯股票)...")
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code != 200:
                self.logger.debug(f"腾讯股票 API 返回状态码: {resp.status_code}")
                return None
            
            data = resp.json()
            
            if data.get("code") != 0:
                self.logger.debug(f"腾讯股票 API 返回错误: {data.get('msg')}")
                return None
            
            # 解析数据
            stock_data = data.get("data", {}).get(tencent_symbol, {})
            
            # 优先使用前复权数据(qfqday)，如果没有则使用原始数据(day)
            klines = stock_data.get("qfqday") or stock_data.get("day", [])
            
            if not klines or len(klines) < 2:
                self.logger.debug(f"腾讯股票指数数据不足: {len(klines) if klines else 0} 条")
                return None
            
            # 过滤截止到昨天的数据
            end_date_str = yesterday.strftime('%Y-%m-%d')
            filtered_klines = [k for k in klines if k[0] <= end_date_str]
            
            if len(filtered_klines) < 2:
                self.logger.debug(f"腾讯股票过滤后指数数据不足: {len(filtered_klines)} 条")
                return None
            
            # 取最后两条数据
            prev_kline = filtered_klines[-1]
            prev_prev_kline = filtered_klines[-2]
            
            prev_date = datetime.strptime(prev_kline[0], '%Y-%m-%d')
            prev_close = float(prev_kline[2])  # 收盘价在索引2
            
            prev_prev_date = datetime.strptime(prev_prev_kline[0], '%Y-%m-%d')
            prev_prev_close = float(prev_prev_kline[2])
            
            if prev_close <= 0 or prev_prev_close <= 0:
                self.logger.debug(f"腾讯股票指数价格无效: prev={prev_close}, prev_prev={prev_prev_close}")
                return None
            
            change_percent = ((prev_close - prev_prev_close) / prev_prev_close) * 100
            
            market_index = MarketIndex(
                name=name,
                prev_close=prev_close,
                prev_prev_close=prev_prev_close,
                change_percent=change_percent,
                prev_date=prev_date,
                prev_prev_date=prev_prev_date
            )
            
            self.logger.info(
                f"指数 {name}: {prev_prev_date.strftime('%m/%d')}收盘{prev_prev_close:,.2f} → "
                f"{prev_date.strftime('%m/%d')}收盘{prev_close:,.2f} ({market_index.formatted_change}) [腾讯股票]"
            )
            
            return market_index
            
        except Exception as e:
            self.logger.warning(f"腾讯股票获取 {name} 指数失败: {e}")
            return None
    
    def get_holiday_info(self, days: int = 15) -> Tuple[bool, Optional[datetime], List[datetime]]:
        """
        检查上一交易日和今天之间是否有休市日
        
        数据源优先级（与股票数据获取保持一致）：
        - 韩股：pykrx
        - 港股/美股：yfinance → akshare → 腾讯股票
        
        Returns:
            (是否有休市日, 昨天的日期, 休市日期列表)
        """
        if self.market == MARKET_KR:
            return self._get_kr_holiday_info(days)
        else:
            return self._get_us_hk_holiday_info(days)
    
    def _get_kr_holiday_info(self, days: int = 15) -> Tuple[bool, Optional[datetime], List[datetime]]:
        """获取韩股休市日信息"""
        try:
            from pykrx import stock as krx
            
            # 统一使用中国时区计算日期，确保三个市场日期一致
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            
            end_date = yesterday.strftime("%Y%m%d")
            start_date = (today - timedelta(days=days)).strftime("%Y%m%d")
            
            df = krx.get_market_ohlcv_by_date(
                fromdate=start_date,
                todate=end_date,
                ticker="005930"  # 三星电子
            )
            
            if df.empty:
                return (False, yesterday.replace(tzinfo=None), [])
            
            trading_days = [d.to_pydatetime().replace(tzinfo=None) for d in df.index]
            
            holidays = []
            yesterday_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            
            if len(trading_days) >= 1:
                latest_trading = trading_days[-1]
                latest_trading_date = latest_trading.replace(hour=0, minute=0, second=0, microsecond=0)
                
                check_date = yesterday_date
                while check_date > latest_trading_date:
                    if check_date.weekday() < 5:
                        holidays.append(check_date)
                    check_date -= timedelta(days=1)
            
            holidays.sort()
            has_holidays = len(holidays) > 0
            
            return (has_holidays, yesterday_date, holidays)
            
        except Exception as e:
            self.logger.error(f"检查休市日时出错: {str(e)}")
            return (False, None, [])
    
    def _get_us_hk_holiday_info(self, days: int = 15) -> Tuple[bool, Optional[datetime], List[datetime]]:
        """
        获取美股/港股休市日信息 - 多数据源备用策略
        
        港股优先级：腾讯股票（国内源更稳定）→ yfinance → akshare
        美股优先级：yfinance（最稳定）→ akshare → 腾讯股票（兜底）
        """
        if self.market == MARKET_HK:
            # 港股：腾讯股票优先（国内数据源更新更及时）
            # 1. 首先尝试腾讯股票
            result = self._get_tencent_holiday_info(days)
            if result[1] is not None:
                return result
            
            # 2. 腾讯股票失败，尝试 yfinance
            self.logger.info("腾讯股票获取休市日失败，尝试 yfinance 备用数据源...")
            result = self._get_yfinance_holiday_info(days)
            if result[1] is not None:
                return result
            
            # 3. yfinance 也失败，最后尝试 akshare
            self.logger.info("yfinance 获取休市日失败，尝试 akshare 备用数据源...")
            return self._get_akshare_holiday_info(days)
        else:
            # 美股：yfinance 优先
            # 1. 首先尝试 yfinance
            result = self._get_yfinance_holiday_info(days)
            if result[1] is not None:
                return result
            
            # 2. yfinance 失败，尝试 akshare 备用
            self.logger.info("yfinance 获取休市日失败，尝试 akshare 备用数据源...")
            result = self._get_akshare_holiday_info(days)
            if result[1] is not None:
                return result
            
            # 3. akshare 也失败，最后尝试腾讯股票（兜底）
            self.logger.info("akshare 获取休市日失败，尝试腾讯股票备用数据源...")
            return self._get_tencent_holiday_info(days)
    
    def _get_yfinance_holiday_info(self, days: int = 15) -> Tuple[bool, Optional[datetime], List[datetime]]:
        """获取美股/港股休市日信息 - 使用 yfinance"""
        try:
            import yfinance as yf
            
            # 统一使用中国时区计算日期，确保三个市场日期一致
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            
            # 使用代表性股票获取交易日历
            if self.market == MARKET_US:
                ref_symbol = 'AAPL'  # 苹果
            else:
                ref_symbol = '0700.HK'  # 腾讯
            
            ticker = yf.Ticker(ref_symbol)
            df = ticker.history(period='1mo')
            
            if df is None or df.empty:
                self.logger.debug("yfinance 无法获取交易日历数据")
                return (False, None, [])
            
            # 过滤数据截止日期
            end_date_str = yesterday.strftime('%Y-%m-%d')
            df = df[df.index.strftime('%Y-%m-%d') <= end_date_str]
            
            # 获取最近的交易日
            df = df.tail(days)
            
            trading_days = [d.to_pydatetime().replace(tzinfo=None) for d in df.index]
            
            holidays = []
            yesterday_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            
            if len(trading_days) >= 1:
                latest_trading = trading_days[-1]
                latest_trading_date = latest_trading.replace(hour=0, minute=0, second=0, microsecond=0)
                
                check_date = yesterday_date
                while check_date > latest_trading_date:
                    if check_date.weekday() < 5:
                        holidays.append(check_date)
                    check_date -= timedelta(days=1)
            
            holidays.sort()
            has_holidays = len(holidays) > 0
            
            return (has_holidays, yesterday_date, holidays)
            
        except Exception as e:
            self.logger.warning(f"yfinance 检查休市日时出错: {str(e)}")
            return (False, None, [])
    
    def _get_akshare_holiday_info(self, days: int = 15) -> Tuple[bool, Optional[datetime], List[datetime]]:
        """获取美股/港股休市日信息 - 使用 akshare"""
        try:
            import akshare as ak
            
            # 统一使用中国时区计算日期，确保三个市场日期一致
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            
            # 使用代表性股票获取交易日历
            if self.market == MARKET_US:
                # 美股：使用苹果股票
                df = ak.stock_us_daily(symbol='AAPL')
                date_col = 'date'
            else:
                # 港股：使用腾讯股票
                df = ak.stock_hk_hist(symbol='00700', period='daily', adjust='')
                date_col = '日期'
            
            if df is None or df.empty:
                self.logger.warning("akshare 无法获取交易日历数据")
                return (False, yesterday.replace(tzinfo=None), [])
            
            # 获取最近的交易日
            df = df.tail(days)
            
            trading_days = []
            for date_val in df[date_col]:
                if hasattr(date_val, 'to_pydatetime'):
                    dt = date_val.to_pydatetime()
                elif isinstance(date_val, str):
                    dt = datetime.strptime(date_val, '%Y-%m-%d')
                else:
                    dt = datetime.combine(date_val, datetime.min.time())
                trading_days.append(dt)
            
            holidays = []
            yesterday_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            
            if len(trading_days) >= 1:
                latest_trading = trading_days[-1]
                latest_trading_date = latest_trading.replace(hour=0, minute=0, second=0, microsecond=0)
                
                check_date = yesterday_date
                while check_date > latest_trading_date:
                    if check_date.weekday() < 5:
                        holidays.append(check_date)
                    check_date -= timedelta(days=1)
            
            holidays.sort()
            has_holidays = len(holidays) > 0
            
            return (has_holidays, yesterday_date, holidays)
            
        except Exception as e:
            self.logger.error(f"检查休市日时出错: {str(e)}")
            return (False, None, [])
    
    def _get_tencent_holiday_info(self, days: int = 15) -> Tuple[bool, Optional[datetime], List[datetime]]:
        """获取美股/港股休市日信息 - 使用腾讯股票 API（兜底数据源）"""
        try:
            import requests
            
            # 统一使用中国时区计算日期，确保三个市场日期一致
            china_tz = pytz.timezone('Asia/Shanghai')
            today = datetime.now(china_tz)
            yesterday = today - timedelta(days=1)
            
            # 使用代表性股票获取交易日历
            if self.market == MARKET_US:
                tencent_symbol = 'usAAPL'  # 苹果
            else:
                tencent_symbol = 'hk00700'  # 腾讯
            
            # 腾讯股票日K接口
            url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
            
            start_date = (today - timedelta(days=days + 10)).strftime('%Y-%m-%d')
            end_date = yesterday.strftime('%Y-%m-%d')
            
            params = {
                "param": f"{tencent_symbol},day,{start_date},{end_date},{days},qfq"
            }
            
            headers = {
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://gu.qq.com/"
            }
            
            self.logger.debug(f"正在获取休市日信息 ({tencent_symbol}) (腾讯股票)...")
            
            resp = requests.get(url, params=params, headers=headers, timeout=10)
            
            if resp.status_code != 200:
                self.logger.warning(f"腾讯股票 API 返回状态码: {resp.status_code}")
                return (False, None, [])
            
            data = resp.json()
            
            if data.get("code") != 0:
                self.logger.warning(f"腾讯股票 API 返回错误: {data.get('msg')}")
                return (False, None, [])
            
            # 解析数据
            stock_data = data.get("data", {}).get(tencent_symbol, {})
            
            # 优先使用前复权数据(qfqday)，如果没有则使用原始数据(day)
            klines = stock_data.get("qfqday") or stock_data.get("day", [])
            
            if not klines:
                self.logger.warning(f"腾讯股票休市日数据为空")
                return (False, None, [])
            
            # 过滤截止到昨天的数据
            end_date_str = yesterday.strftime('%Y-%m-%d')
            filtered_klines = [k for k in klines if k[0] <= end_date_str]
            
            if not filtered_klines:
                self.logger.warning(f"腾讯股票过滤后休市日数据为空")
                return (False, None, [])
            
            # 获取交易日列表
            trading_days = [datetime.strptime(k[0], '%Y-%m-%d') for k in filtered_klines]
            
            holidays = []
            yesterday_date = yesterday.replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
            
            if len(trading_days) >= 1:
                latest_trading = trading_days[-1]
                latest_trading_date = latest_trading.replace(hour=0, minute=0, second=0, microsecond=0)
                
                check_date = yesterday_date
                while check_date > latest_trading_date:
                    if check_date.weekday() < 5:
                        holidays.append(check_date)
                    check_date -= timedelta(days=1)
            
            holidays.sort()
            has_holidays = len(holidays) > 0
            
            self.logger.info(f"腾讯股票获取休市日成功: has_holidays={has_holidays}, holidays={[h.strftime('%Y-%m-%d') for h in holidays]}")
            
            return (has_holidays, yesterday_date, holidays)
            
        except Exception as e:
            self.logger.error(f"腾讯股票检查休市日时出错: {str(e)}")
            return (False, None, [])
    
    def get_all_stock_changes(self, stocks: List[StockInfo]) -> List[StockChange]:
        """
        获取所有股票的涨跌情况
        
        Args:
            stocks: 股票信息列表
        
        Returns:
            StockChange 对象列表
        """
        changes = []
        
        for i, stock in enumerate(stocks):
            change = self.get_stock_data(stock)
            if change:
                changes.append(change)
            
            # 添加请求间隔，避免被服务器限流（不在最后一个请求后等待）
            if i < len(stocks) - 1 and self.market in (MARKET_HK, MARKET_US):
                time.sleep(REQUEST_DELAY)
        
        self.logger.info(f"成功获取 {len(changes)}/{len(stocks)} 只股票的数据")
        return changes
    
    def filter_significant_changes(
        self, 
        changes: List[StockChange], 
        threshold: float = 10.0
    ) -> List[StockChange]:
        """
        筛选超过阈值的股票变化
        
        Args:
            changes: 股票变化列表
            threshold: 涨跌幅阈值（百分比）
        
        Returns:
            超过阈值的 StockChange 列表
        """
        significant = [
            c for c in changes 
            if abs(c.change_percent) >= threshold
        ]
        
        significant.sort(key=lambda x: abs(x.change_percent), reverse=True)
        
        if significant:
            self.logger.info(
                f"发现 {len(significant)} 只股票涨跌幅超过 {threshold}%"
            )
        else:
            self.logger.info(f"没有股票涨跌幅超过 {threshold}%")
        
        return significant
