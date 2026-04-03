"""
新闻获取服务
使用免费的RSS源和网页抓取获取股票相关新闻
无需API配置，完全免费

数据源：
1. Google News RSS - 通过关键词搜索新闻
2. Yahoo Finance RSS - 按股票代码获取新闻
3. 财经网站抓取 - 作为备用方案
"""

import re
import time
import hashlib
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass
from urllib.parse import quote_plus
import pytz

import feedparser
import requests
from bs4 import BeautifulSoup

from utils.logger import LoggerMixin
from config import MARKET_KR, MARKET_US, MARKET_HK


@dataclass
class NewsItem:
    """新闻条目"""
    title: str                    # 新闻标题
    summary: str                  # 新闻摘要
    source: str                   # 来源
    url: str                      # 链接
    published_date: datetime      # 发布日期
    stock_symbol: str = None      # 关联的股票代码
    stock_name: str = None        # 关联的股票名称
    
    def __hash__(self):
        return hash(self.url)
    
    def __eq__(self, other):
        return self.url == other.url


class NewsService(LoggerMixin):
    """新闻获取服务 - 完全免费，无需配置"""
    
    # Google News RSS 基础 URL
    GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
    
    # Yahoo Finance RSS 基础 URL
    YAHOO_FINANCE_RSS = "https://finance.yahoo.com/rss/headline"
    
    # 请求配置
    REQUEST_TIMEOUT = 15
    REQUEST_DELAY = 1.0  # 请求间隔
    MAX_RETRIES = 3
    
    # 用户代理
    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]
    
    def __init__(self, market: str):
        """
        初始化新闻服务
        
        Args:
            market: 市场类型 (kr/us/hk)
        """
        self.market = market
        self.market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
        self._user_agent_index = 0
        self._news_cache: Dict[str, List[NewsItem]] = {}  # 缓存
        self._cache_ttl = 3600  # 缓存1小时
        self._cache_timestamps: Dict[str, float] = {}
        
        self.logger.info(f"新闻服务初始化完成: {self.market_names.get(market, market)}（免费RSS源）")
    
    def _get_headers(self) -> dict:
        """获取请求头"""
        ua = self.USER_AGENTS[self._user_agent_index % len(self.USER_AGENTS)]
        self._user_agent_index += 1
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7,ko;q=0.6",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
    
    def _cache_key(self, query: str, days: int) -> str:
        """生成缓存键"""
        return hashlib.md5(f"{query}:{days}:{self.market}".encode()).hexdigest()
    
    def _is_cache_valid(self, key: str) -> bool:
        """检查缓存是否有效"""
        if key not in self._cache_timestamps:
            return False
        return time.time() - self._cache_timestamps[key] < self._cache_ttl
    
    # ============================================================
    # Google News RSS - 主要新闻源
    # ============================================================
    
    def get_google_news(
        self,
        query: str,
        language: str = "en",
        days: int = 7,
        max_results: int = 10
    ) -> List[NewsItem]:
        """
        从 Google News RSS 获取新闻
        
        Args:
            query: 搜索关键词
            language: 语言代码 (en/ko/zh-CN)
            days: 获取最近几天的新闻
            max_results: 最大返回数量
            
        Returns:
            新闻列表
        """
        cache_key = self._cache_key(f"google:{query}:{language}", days)
        if self._is_cache_valid(cache_key) and cache_key in self._news_cache:
            self.logger.debug(f"使用缓存的 Google News 数据: {query}")
            return self._news_cache[cache_key][:max_results]
        
        try:
            # 构建 RSS URL
            encoded_query = quote_plus(query)
            
            # 根据语言设置地区
            if language == "ko":
                hl = "ko"
                gl = "KR"
                ceid = "KR:ko"
            elif language == "zh-CN":
                hl = "zh-CN"
                gl = "CN"
                ceid = "CN:zh-Hans"
            else:
                hl = "en"
                gl = "US"
                ceid = "US:en"
            
            url = f"{self.GOOGLE_NEWS_RSS}?q={encoded_query}&hl={hl}&gl={gl}&ceid={ceid}"
            
            self.logger.debug(f"获取 Google News: {query}")
            
            # 使用 feedparser 解析 RSS
            feed = feedparser.parse(url)
            
            if not feed.entries:
                self.logger.warning(f"Google News 未返回结果: {query}")
                return []
            
            news_list = []
            cutoff_date = datetime.now(pytz.UTC) - timedelta(days=days)
            
            for entry in feed.entries[:max_results * 2]:  # 获取更多以便过滤
                try:
                    # 解析发布日期
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        pub_date = datetime(*entry.published_parsed[:6], tzinfo=pytz.UTC)
                    else:
                        pub_date = datetime.now(pytz.UTC)
                    
                    # 过滤旧新闻
                    if pub_date < cutoff_date:
                        continue
                    
                    # 提取来源
                    source = "Google News"
                    if hasattr(entry, 'source') and hasattr(entry.source, 'title'):
                        source = entry.source.title
                    
                    # 清理标题（移除来源部分）
                    title = entry.title
                    if " - " in title:
                        title = title.rsplit(" - ", 1)[0]
                    
                    # 清理摘要
                    summary = ""
                    if hasattr(entry, 'summary'):
                        # 移除 HTML 标签
                        summary = BeautifulSoup(entry.summary, 'html.parser').get_text()
                        summary = summary[:200] if len(summary) > 200 else summary
                    
                    news_item = NewsItem(
                        title=title,
                        summary=summary,
                        source=source,
                        url=entry.link,
                        published_date=pub_date
                    )
                    news_list.append(news_item)
                    
                except Exception as e:
                    self.logger.debug(f"解析新闻条目失败: {e}")
                    continue
            
            # 更新缓存
            self._news_cache[cache_key] = news_list
            self._cache_timestamps[cache_key] = time.time()
            
            self.logger.info(f"获取到 {len(news_list)} 条 Google News: {query}")
            return news_list[:max_results]
            
        except Exception as e:
            self.logger.error(f"获取 Google News 失败: {e}")
            return []
    
    # ============================================================
    # 按股票获取新闻
    # ============================================================
    
    def get_stock_news(
        self,
        stock_name: str,
        stock_symbol: str = None,
        days: int = 3,
        max_results: int = 5
    ) -> List[NewsItem]:
        """
        获取特定股票的新闻
        
        Args:
            stock_name: 股票名称（如 "Nexon", "腾讯"）
            stock_symbol: 股票代码（可选）
            days: 获取最近几天的新闻
            max_results: 最大返回数量
            
        Returns:
            新闻列表
        """
        # 根据市场选择搜索关键词和语言
        if self.market == MARKET_KR:
            # 韩股：使用英文名搜索（更容易找到国际新闻）
            query = f"{stock_name} stock game"
            language = "en"
        elif self.market == MARKET_US:
            # 美股：直接搜索公司名
            query = f"{stock_name} stock"
            language = "en"
        else:
            # 港股：使用英文搜索
            query = f"{stock_name} stock Hong Kong"
            language = "en"
        
        news_list = self.get_google_news(
            query=query,
            language=language,
            days=days,
            max_results=max_results
        )
        
        # 标记股票信息
        for news in news_list:
            news.stock_symbol = stock_symbol
            news.stock_name = stock_name
        
        return news_list
    
    def get_market_news(
        self,
        days: int = 3,
        max_results: int = 10
    ) -> List[NewsItem]:
        """
        获取市场整体新闻
        
        Args:
            days: 获取最近几天的新闻
            max_results: 最大返回数量
            
        Returns:
            新闻列表
        """
        if self.market == MARKET_KR:
            queries = [
                ("Korean game stocks", "en"),
                ("KOSPI game companies", "en"),
            ]
        elif self.market == MARKET_US:
            queries = [
                ("US tech stocks NASDAQ", "en"),
                ("gaming stocks market", "en"),
            ]
        else:  # MARKET_HK
            queries = [
                ("Hong Kong tech stocks", "en"),
                ("Hang Seng tech", "en"),
            ]
        
        all_news = []
        for query, lang in queries:
            news = self.get_google_news(
                query=query,
                language=lang,
                days=days,
                max_results=max_results // 2
            )
            all_news.extend(news)
            time.sleep(self.REQUEST_DELAY)
        
        # 去重
        seen = set()
        unique_news = []
        for n in all_news:
            if n.url not in seen:
                seen.add(n.url)
                unique_news.append(n)
        
        return unique_news[:max_results]
    
    # ============================================================
    # 批量获取新闻（用于日报/月报）
    # ============================================================
    
    def get_daily_news(
        self,
        stock_list: List[dict],
        prev_trading_date: datetime = None
    ) -> Dict[str, List[NewsItem]]:
        """
        获取日报所需的新闻（昨日新闻）
        
        Args:
            stock_list: 股票列表 [{"symbol": "...", "name": "...", "change_percent": ...}, ...]
            prev_trading_date: 上一交易日日期
            
        Returns:
            {stock_name: [NewsItem, ...], "market": [NewsItem, ...]}
        """
        result = {}
        
        # 计算新闻时间范围（获取前3天的新闻以确保覆盖）
        days = 3
        
        # 先获取市场整体新闻
        self.logger.info("获取市场整体新闻...")
        result["market"] = self.get_market_news(days=days, max_results=5)
        
        # 按涨跌幅排序，优先获取波动大的股票新闻
        sorted_stocks = sorted(
            stock_list, 
            key=lambda x: abs(x.get('change_percent', 0)), 
            reverse=True
        )
        
        # 获取各股票新闻（只获取波动较大的）
        for stock in sorted_stocks[:8]:  # 最多获取8只股票的新闻
            stock_name = stock.get('name', '')
            stock_symbol = stock.get('symbol', '')
            
            if not stock_name:
                continue
            
            self.logger.info(f"获取 {stock_name} 的新闻...")
            news = self.get_stock_news(
                stock_name=stock_name,
                stock_symbol=stock_symbol,
                days=days,
                max_results=3
            )
            
            if news:
                result[stock_name] = news
            
            time.sleep(self.REQUEST_DELAY)  # 避免请求过快
        
        return result
    
    def get_monthly_news(
        self,
        stock_list: List[dict],
        year: int,
        month: int
    ) -> Dict[str, List[NewsItem]]:
        """
        获取月报所需的新闻（整月新闻汇总）
        
        Args:
            stock_list: 股票列表
            year: 年份
            month: 月份
            
        Returns:
            {stock_name: [NewsItem, ...], "market": [NewsItem, ...], "industry": [NewsItem, ...]}
        """
        result = {}
        
        # 月度新闻获取更长时间范围
        days = 35  # 获取一个多月的新闻
        
        # 市场新闻
        self.logger.info("获取月度市场新闻...")
        result["market"] = self.get_market_news(days=days, max_results=10)
        
        # 行业新闻
        if self.market == MARKET_KR:
            industry_query = "Korean mobile game industry"
        elif self.market == MARKET_US:
            industry_query = "US tech gaming industry"
        else:
            industry_query = "Hong Kong tech gaming industry"
        
        self.logger.info("获取行业新闻...")
        result["industry"] = self.get_google_news(
            query=industry_query,
            language="en",
            days=days,
            max_results=8
        )
        
        # 按涨跌幅排序
        sorted_stocks = sorted(
            stock_list, 
            key=lambda x: abs(x.get('change_percent', 0)), 
            reverse=True
        )
        
        # 获取主要股票新闻
        for stock in sorted_stocks[:10]:  # 获取前10只股票的新闻
            stock_name = stock.get('name', '')
            stock_symbol = stock.get('symbol', '')
            
            if not stock_name:
                continue
            
            self.logger.info(f"获取 {stock_name} 的月度新闻...")
            news = self.get_stock_news(
                stock_name=stock_name,
                stock_symbol=stock_symbol,
                days=days,
                max_results=5
            )
            
            if news:
                result[stock_name] = news
            
            time.sleep(self.REQUEST_DELAY)
        
        return result
    
    # ============================================================
    # 新闻格式化输出
    # ============================================================
    
    def format_news_for_stock(
        self,
        stock_name: str,
        news_list: List[NewsItem],
        max_items: int = 2
    ) -> str:
        """
        格式化单只股票的新闻为文本
        
        Args:
            stock_name: 股票名称
            news_list: 新闻列表
            max_items: 最大显示条数
            
        Returns:
            格式化的文本
        """
        if not news_list:
            return "暂无相关新闻"
        
        lines = []
        for news in news_list[:max_items]:
            # 简化标题
            title = news.title[:60] + "..." if len(news.title) > 60 else news.title
            lines.append(f"• {title}")
        
        return " ".join(lines)
    
    def format_daily_news_table(
        self,
        stock_changes: List[dict],
        news_data: Dict[str, List[NewsItem]]
    ) -> str:
        """
        格式化日报新闻表格
        
        Args:
            stock_changes: 股票涨跌数据列表
            news_data: 新闻数据字典
            
        Returns:
            Markdown 表格
        """
        lines = []
        lines.append("| 公司 | 新闻内容 |")
        lines.append("|:----:|:-----|")
        
        # 市场新闻
        market_news = news_data.get("market", [])
        if market_news:
            market_summary = self.format_news_for_stock("市场", market_news, max_items=1)
            lines.append(f"| 🌐 大盘 | {market_summary} |")
        
        # 各股票新闻
        for stock in stock_changes:
            name = stock.get('name', '')
            symbol = stock.get('symbol', '')
            change = stock.get('change_percent', 0)
            
            # 选择emoji
            if self.market == MARKET_KR:
                emoji = "🎮"
            elif change > 0:
                emoji = "📈"
            else:
                emoji = "📉"
            
            # 获取新闻
            stock_news = news_data.get(name, [])
            if stock_news:
                news_text = self.format_news_for_stock(name, stock_news, max_items=2)
            else:
                # 没有新闻时显示涨跌情况
                direction = "上涨" if change > 0 else "下跌"
                news_text = f"{direction}{abs(change):.2f}%，暂无相关新闻"
            
            lines.append(f"| {emoji} {name} | {news_text} |")
        
        return "\n".join(lines)
    
    def format_monthly_news_summary(
        self,
        news_data: Dict[str, List[NewsItem]],
        stock_data: dict,
        year: int,
        month: int
    ) -> str:
        """
        格式化月度新闻汇总
        
        Args:
            news_data: 新闻数据
            stock_data: 股票数据
            year: 年份
            month: 月份
            
        Returns:
            格式化的月度新闻汇总文本
        """
        market_name = self.market_names.get(self.market, self.market)
        lines = []
        
        # 行业大事
        lines.append("**📰 行业大事**")
        industry_news = news_data.get("industry", []) + news_data.get("market", [])
        if industry_news:
            for news in industry_news[:3]:
                title = news.title[:80] + "..." if len(news.title) > 80 else news.title
                lines.append(f"• {title}")
        else:
            lines.append(f"• {year}年{month}月{market_name}板块整体运行平稳")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 公司动态
        lines.append("**🏢 公司动态**")
        
        # 按涨跌幅排序
        sorted_stocks = sorted(
            stock_data.items(),
            key=lambda x: abs(x[1].get('change_percent', 0)),
            reverse=True
        )
        
        for symbol, data in sorted_stocks:
            name = data.get('name', symbol)
            change = data.get('change_percent', 0)
            stock_news = news_data.get(name, [])
            
            if stock_news:
                # 有新闻时显示新闻标题
                news_title = stock_news[0].title
                if len(news_title) > 60:
                    news_title = news_title[:60] + "..."
                lines.append(f"• **{name}** ({change:+.2f}%): {news_title}")
            else:
                # 没有新闻时显示涨跌情况
                if change > 5:
                    desc = f"{month}月股价大涨{change:.2f}%"
                elif change > 0:
                    desc = f"{month}月股价上涨{change:.2f}%"
                elif change > -5:
                    desc = f"{month}月股价小幅下跌{abs(change):.2f}%"
                else:
                    desc = f"{month}月股价下跌{abs(change):.2f}%"
                lines.append(f"• **{name}**: {desc}")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 市场热点
        lines.append("**🔥 市场热点**")
        
        # 找出涨跌最大的股票
        gainers = [(s, d) for s, d in sorted_stocks if d.get('change_percent', 0) > 0][:2]
        losers = [(s, d) for s, d in sorted_stocks if d.get('change_percent', 0) < 0][-2:]
        
        hot_topics = []
        if gainers:
            gainer_names = [d['name'] for _, d in gainers]
            hot_topics.append(f"{', '.join(gainer_names)}等表现抢眼")
        if losers:
            loser_names = [d['name'] for _, d in losers]
            hot_topics.append(f"{', '.join(loser_names)}等承压调整")
        
        if hot_topics:
            lines.append(f"• {month}月投资者关注焦点：" + "；".join(hot_topics))
        else:
            lines.append(f"• {month}月{market_name}板块整体波动平稳")
        
        return "\n".join(lines)
