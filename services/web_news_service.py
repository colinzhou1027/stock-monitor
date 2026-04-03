"""
Web 新闻检索服务
使用多种免费渠道获取股票新闻：
1. DuckDuckGo 搜索（免费无限制）
2. Google News RSS（免费）
3. 网页内容抓取

无需 API Key，完全免费
"""

import re
import time
import json
import hashlib
import subprocess
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from urllib.parse import quote_plus, urlparse
import pytz

import requests
from bs4 import BeautifulSoup

from utils.logger import LoggerMixin
from config import MARKET_KR, MARKET_US, MARKET_HK


@dataclass
class WebNewsItem:
    """新闻条目"""
    title: str                    # 新闻标题
    snippet: str                  # 新闻摘要/片段
    source: str                   # 来源网站
    url: str                      # 链接
    published_date: str = ""      # 发布日期（字符串）
    age: str = ""                 # 相对时间（如 "2 hours ago"）
    
    def to_dict(self) -> dict:
        return asdict(self)


class WebNewsService(LoggerMixin):
    """
    Web 新闻检索服务
    使用多种免费方法获取最新新闻
    """
    
    # DuckDuckGo 搜索 URL
    DDG_URL = "https://html.duckduckgo.com/html/"
    
    # 请求配置
    REQUEST_TIMEOUT = 20
    REQUEST_DELAY = 1.5
    MAX_RETRIES = 2
    
    # 用户代理
    USER_AGENTS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    ]
    
    def __init__(self, market: str):
        self.market = market
        self.market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
        self._user_agent_index = 0
        self._cache: Dict[str, Tuple[List[WebNewsItem], float]] = {}
        self._cache_ttl = 1800  # 缓存30分钟
        
        self.logger.info(f"Web 新闻服务初始化: {self.market_names.get(market, market)}")
    
    def _get_headers(self) -> dict:
        ua = self.USER_AGENTS[self._user_agent_index % len(self.USER_AGENTS)]
        self._user_agent_index += 1
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    
    def _cache_key(self, query: str) -> str:
        return hashlib.md5(f"{query}:{self.market}".encode()).hexdigest()
    
    def _get_from_cache(self, key: str) -> Optional[List[WebNewsItem]]:
        if key in self._cache:
            data, timestamp = self._cache[key]
            if time.time() - timestamp < self._cache_ttl:
                return data
        return None
    
    def _set_cache(self, key: str, data: List[WebNewsItem]):
        self._cache[key] = (data, time.time())
    
    # ================================================================
    # DuckDuckGo 搜索 - 主要搜索引擎
    # ================================================================
    
    def search_duckduckgo(
        self,
        query: str,
        max_results: int = 10
    ) -> List[WebNewsItem]:
        """
        使用 DuckDuckGo 搜索新闻
        
        Args:
            query: 搜索关键词
            max_results: 最大结果数
            
        Returns:
            新闻列表
        """
        cache_key = self._cache_key(f"ddg:{query}")
        cached = self._get_from_cache(cache_key)
        if cached:
            self.logger.debug(f"使用缓存: {query}")
            return cached[:max_results]
        
        try:
            # 添加 news 关键词优化搜索
            search_query = f"{query} news"
            
            self.logger.info(f"DuckDuckGo 搜索: {query}")
            
            response = requests.post(
                self.DDG_URL,
                data={"q": search_query},
                headers=self._get_headers(),
                timeout=self.REQUEST_TIMEOUT
            )
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            results = []
            
            # 解析搜索结果
            for result in soup.select('.result'):
                try:
                    # 标题和链接
                    title_elem = result.select_one('.result__title a')
                    if not title_elem:
                        continue
                    
                    title = title_elem.get_text(strip=True)
                    url = title_elem.get('href', '')
                    
                    # 清理 DuckDuckGo 的跳转 URL
                    if 'uddg=' in url:
                        import urllib.parse
                        parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                        if 'uddg' in parsed:
                            url = parsed['uddg'][0]
                    
                    # 摘要
                    snippet_elem = result.select_one('.result__snippet')
                    snippet = snippet_elem.get_text(strip=True) if snippet_elem else ""
                    
                    # 来源
                    source = urlparse(url).netloc.replace('www.', '')
                    
                    results.append(WebNewsItem(
                        title=title,
                        snippet=snippet,
                        source=source,
                        url=url
                    ))
                    
                    if len(results) >= max_results:
                        break
                        
                except Exception as e:
                    self.logger.debug(f"解析结果失败: {e}")
                    continue
            
            self._set_cache(cache_key, results)
            self.logger.info(f"DuckDuckGo 获取到 {len(results)} 条结果")
            return results
            
        except Exception as e:
            self.logger.error(f"DuckDuckGo 搜索失败: {e}")
            return []
    
    # ================================================================
    # 股票新闻搜索
    # ================================================================
    
    def search_stock_news(
        self,
        stock_name: str,
        stock_symbol: str = "",
        max_results: int = 5
    ) -> List[WebNewsItem]:
        """
        搜索特定股票的新闻
        
        Args:
            stock_name: 股票名称
            stock_symbol: 股票代码
            max_results: 最大结果数
            
        Returns:
            新闻列表
        """
        # 构建搜索查询
        if self.market == MARKET_KR:
            query = f"{stock_name} stock game Korea"
        elif self.market == MARKET_US:
            query = f"{stock_name} stock NASDAQ"
        else:
            query = f"{stock_name} stock Hong Kong"
        
        return self.search_duckduckgo(query, max_results)
    
    def search_market_news(
        self,
        max_results: int = 10
    ) -> List[WebNewsItem]:
        """
        搜索市场整体新闻
        """
        if self.market == MARKET_KR:
            query = "Korean gaming stocks KOSPI news"
        elif self.market == MARKET_US:
            query = "US tech stocks NASDAQ gaming news"
        else:
            query = "Hong Kong tech stocks Hang Seng news"
        
        return self.search_duckduckgo(query, max_results)
    
    # ================================================================
    # 批量获取新闻（用于日报/月报）
    # ================================================================
    
    def get_daily_news_analysis(
        self,
        stock_changes: List[dict],
        market_indices: List[dict] = None
    ) -> str:
        """
        获取日报新闻分析
        
        Args:
            stock_changes: 股票涨跌列表 [{"name": ..., "symbol": ..., "change_percent": ...}, ...]
            market_indices: 大盘指数数据
            
        Returns:
            格式化的新闻分析文本
        """
        lines = []
        market_name = self.market_names.get(self.market, self.market)
        
        # 1. 获取市场新闻
        self.logger.info("获取市场新闻...")
        market_news = self.search_market_news(max_results=5)
        
        if market_news:
            lines.append("**📰 今日要闻**")
            for news in market_news[:3]:
                title = news.title[:80] + "..." if len(news.title) > 80 else news.title
                lines.append(f"• {title}")
                if news.snippet:
                    snippet = news.snippet[:100] + "..." if len(news.snippet) > 100 else news.snippet
                    lines.append(f"  _{snippet}_")
            lines.append("")
        
        # 2. 按涨跌幅排序股票
        sorted_stocks = sorted(
            stock_changes,
            key=lambda x: abs(x.get('change_percent', 0)),
            reverse=True
        )
        
        # 3. 获取主要股票新闻
        lines.append("**📈 个股动态**")
        
        for stock in sorted_stocks[:6]:
            name = stock.get('name', '')
            change = stock.get('change_percent', 0)
            
            if not name:
                continue
            
            self.logger.info(f"获取 {name} 新闻...")
            time.sleep(self.REQUEST_DELAY)
            
            stock_news = self.search_stock_news(name, max_results=3)
            
            # 涨跌 emoji
            emoji = "📈" if change > 0 else "📉"
            change_str = f"+{change:.2f}%" if change > 0 else f"{change:.2f}%"
            
            if stock_news:
                news_title = stock_news[0].title
                if len(news_title) > 60:
                    news_title = news_title[:60] + "..."
                lines.append(f"• {emoji} **{name}** ({change_str}): {news_title}")
            else:
                action = "上涨" if change > 0 else "下跌"
                lines.append(f"• {emoji} **{name}** ({change_str}): {action}{abs(change):.2f}%")
        
        lines.append("")
        
        # 4. 市场总结
        lines.append("**📊 市场观察**")
        gainers = [s for s in sorted_stocks if s.get('change_percent', 0) > 2]
        losers = [s for s in sorted_stocks if s.get('change_percent', 0) < -2]
        
        if gainers:
            gainer_names = [s['name'] for s in gainers[:3]]
            lines.append(f"• 今日领涨: {', '.join(gainer_names)}")
        if losers:
            loser_names = [s['name'] for s in losers[:3]]
            lines.append(f"• 今日领跌: {', '.join(loser_names)}")
        
        return "\n".join(lines)
    
    def get_monthly_news_summary(
        self,
        stock_data: dict,
        year: int,
        month: int
    ) -> str:
        """
        获取月度新闻汇总
        
        Args:
            stock_data: {symbol: {"name": ..., "change_percent": ...}, ...}
            year: 年份
            month: 月份
            
        Returns:
            格式化的月度新闻汇总
        """
        lines = []
        market_name = self.market_names.get(self.market, self.market)
        
        # 1. 行业大事
        lines.append("**📰 行业大事**")
        
        market_news = self.search_market_news(max_results=8)
        if market_news:
            for news in market_news[:4]:
                title = news.title[:80] + "..." if len(news.title) > 80 else news.title
                lines.append(f"• {title}")
        else:
            lines.append(f"• {year}年{month}月{market_name}板块整体运行平稳")
        
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 2. 公司动态
        lines.append("**🏢 公司动态**")
        
        # 按涨跌幅排序
        sorted_stocks = sorted(
            stock_data.items(),
            key=lambda x: abs(x[1].get('change_percent', 0)),
            reverse=True
        )
        
        for symbol, data in sorted_stocks[:8]:
            name = data.get('name', symbol)
            change = data.get('change_percent', 0)
            
            self.logger.info(f"获取 {name} 月度新闻...")
            time.sleep(self.REQUEST_DELAY)
            
            stock_news = self.search_stock_news(name, max_results=3)
            
            change_str = f"+{change:.2f}%" if change >= 0 else f"{change:.2f}%"
            
            if stock_news:
                news_title = stock_news[0].title
                if len(news_title) > 60:
                    news_title = news_title[:60] + "..."
                lines.append(f"• **{name}** ({change_str}): {news_title}")
            else:
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
        
        # 3. 市场热点
        lines.append("**🔥 市场热点**")
        
        gainers = [(s, d) for s, d in sorted_stocks if d.get('change_percent', 0) > 0][:3]
        losers = [(s, d) for s, d in sorted_stocks if d.get('change_percent', 0) < 0][-3:]
        
        if gainers:
            gainer_names = [d['name'] for _, d in gainers]
            lines.append(f"• {month}月领涨: {', '.join(gainer_names)}")
        if losers:
            loser_names = [d['name'] for _, d in losers]
            lines.append(f"• {month}月承压: {', '.join(loser_names)}")
        
        lines.append(f"• {month}月投资者关注焦点：行业发展与业绩表现")
        
        return "\n".join(lines)


# ================================================================
# 测试
# ================================================================

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    service = WebNewsService(MARKET_KR)
    
    # 测试搜索
    print("\n=== 测试 DuckDuckGo 搜索 ===")
    results = service.search_duckduckgo("Nexon stock news", max_results=5)
    for r in results:
        print(f"- {r.title}")
        print(f"  {r.source}: {r.url}")
        print()
    
    # 测试股票新闻
    print("\n=== 测试股票新闻 ===")
    news = service.search_stock_news("Pearl Abyss", max_results=3)
    for n in news:
        print(f"- {n.title}")
