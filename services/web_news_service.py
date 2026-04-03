"""
Web 新闻检索服务
使用多种免费渠道获取股票新闻（中文版）：
1. DuckDuckGo 搜索（免费无限制）
2. 百度新闻搜索
3. 网页内容抓取

无需 API Key，完全免费
所有结果使用中文显示
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
    content: str                  # 新闻内容摘要
    source: str                   # 来源网站
    url: str                      # 链接
    published_date: str = ""      # 发布日期
    
    def to_dict(self) -> dict:
        return asdict(self)


class WebNewsService(LoggerMixin):
    """
    Web 新闻检索服务
    使用多种免费方法获取最新新闻，全部中文显示
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
    
    # 公司名称中英文映射
    COMPANY_NAMES_CN = {
        # 韩国游戏股
        "Nexon": "Nexon（纳克森）",
        "NCSoft": "NCSoft（恩希软件）",
        "NCsoft": "NCSoft（恩希软件）",
        "Pearl Abyss": "Pearl Abyss（珍艾碧丝）",
        "Netmarble": "Netmarble（网石）",
        "Krafton": "Krafton（蓝洞）",
        "Kakao Games": "Kakao Games（可可游戏）",
        "Com2uS": "Com2uS",
        "Smilegate": "Smilegate（微笑门）",
        "NHN": "NHN",
        "Webzen": "Webzen（网禅）",
        "Neowiz": "Neowiz",
        "Devsisters": "Devsisters",
        "Gravity": "Gravity（重力）",
        "WeMade": "WeMade（娱美德）",
        "Shift Up": "Shift Up",
        
        # 美国科技股
        "Apple": "苹果",
        "Microsoft": "微软",
        "Google": "谷歌",
        "Alphabet": "谷歌母公司Alphabet",
        "Amazon": "亚马逊",
        "Meta": "Meta（脸书）",
        "Netflix": "奈飞",
        "NVIDIA": "英伟达",
        "Tesla": "特斯拉",
        "AMD": "AMD（超微）",
        "Intel": "英特尔",
        "Qualcomm": "高通",
        "Adobe": "Adobe",
        "Salesforce": "Salesforce",
        
        # 美国游戏股
        "EA": "艺电",
        "Electronic Arts": "艺电",
        "Activision Blizzard": "动视暴雪",
        "Take-Two": "Take-Two",
        "Roblox": "Roblox",
        "Unity": "Unity",
        
        # 港股
        "Tencent": "腾讯",
        "Alibaba": "阿里巴巴",
        "NetEase": "网易",
        "Bilibili": "哔哩哔哩",
        "JD.com": "京东",
        "Baidu": "百度",
        "Xiaomi": "小米",
        "Meituan": "美团",
        "Kuaishou": "快手",
    }
    
    def __init__(self, market: str):
        self.market = market
        self.market_names = {MARKET_KR: "韩国游戏", MARKET_US: "美国科技", MARKET_HK: "港股科技"}
        self._user_agent_index = 0
        self._cache: Dict[str, Tuple[List[WebNewsItem], float]] = {}
        self._cache_ttl = 1800  # 缓存30分钟
        
        self.logger.info(f"Web 新闻服务初始化: {self.market_names.get(market, market)}")
    
    def _get_cn_name(self, name: str) -> str:
        """获取公司的中文名称"""
        return self.COMPANY_NAMES_CN.get(name, name)
    
    def _get_headers(self) -> dict:
        ua = self.USER_AGENTS[self._user_agent_index % len(self.USER_AGENTS)]
        self._user_agent_index += 1
        return {
            "User-Agent": ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
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
    # DuckDuckGo 中文搜索
    # ================================================================
    
    def search_duckduckgo(
        self,
        query: str,
        max_results: int = 10
    ) -> List[WebNewsItem]:
        """
        使用 DuckDuckGo 搜索中文新闻
        
        Args:
            query: 搜索关键词（中文）
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
            # 添加新闻关键词
            search_query = f"{query} 新闻 最新"
            
            self.logger.info(f"DuckDuckGo 中文搜索: {query}")
            
            response = requests.post(
                self.DDG_URL,
                data={"q": search_query, "kl": "cn-zh"},  # 设置中文区域
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
                    
                    # 内容摘要
                    snippet_elem = result.select_one('.result__snippet')
                    content = snippet_elem.get_text(strip=True) if snippet_elem else ""
                    
                    # 来源
                    source = urlparse(url).netloc.replace('www.', '')
                    
                    results.append(WebNewsItem(
                        title=title,
                        content=content,
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
    # 股票新闻搜索（中文）
    # ================================================================
    
    def search_stock_news(
        self,
        stock_name: str,
        stock_symbol: str = "",
        max_results: int = 5
    ) -> List[WebNewsItem]:
        """
        搜索特定股票的中文新闻
        
        Args:
            stock_name: 股票名称
            stock_symbol: 股票代码
            max_results: 最大结果数
            
        Returns:
            新闻列表
        """
        cn_name = self._get_cn_name(stock_name)
        
        # 构建中文搜索查询
        if self.market == MARKET_KR:
            query = f"{stock_name} {cn_name} 韩国游戏 最新消息"
        elif self.market == MARKET_US:
            query = f"{stock_name} {cn_name} 美股 最新消息"
        else:
            query = f"{cn_name} 港股 最新消息"
        
        return self.search_duckduckgo(query, max_results)
    
    def search_market_news(
        self,
        max_results: int = 10
    ) -> List[WebNewsItem]:
        """
        搜索市场整体新闻（中文）
        """
        if self.market == MARKET_KR:
            query = "韩国游戏股 KOSPI 游戏行业 最新动态"
        elif self.market == MARKET_US:
            query = "美股科技股 纳斯达克 科技行业 最新动态"
        else:
            query = "港股科技股 恒生科技 最新动态"
        
        return self.search_duckduckgo(query, max_results)
    
    # ================================================================
    # 批量获取新闻（用于日报/月报）- 中文版
    # ================================================================
    
    def get_daily_news_analysis(
        self,
        stock_changes: List[dict],
        market_indices: List[dict] = None
    ) -> str:
        """
        获取日报新闻分析（中文版，显示详细内容）
        
        Args:
            stock_changes: 股票涨跌列表 [{"name": ..., "symbol": ..., "change_percent": ...}, ...]
            market_indices: 大盘指数数据
            
        Returns:
            格式化的新闻分析文本（中文）
        """
        lines = []
        market_name = self.market_names.get(self.market, self.market)
        
        # 1. 获取市场新闻
        self.logger.info("获取市场整体新闻...")
        market_news = self.search_market_news(max_results=5)
        
        if market_news:
            lines.append("**📰 今日市场要闻**")
            lines.append("")
            for news in market_news[:3]:
                # 标题
                lines.append(f"**{news.title}**")
                # 详细内容
                if news.content:
                    lines.append(f"{news.content}")
                lines.append(f"_来源: {news.source}_")
                lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 2. 获取各公司最新动态（不显示涨跌幅）
        lines.append("**🏢 公司最新动态**")
        lines.append("")
        
        # 按涨跌幅排序，但不显示数值
        sorted_stocks = sorted(
            stock_changes,
            key=lambda x: abs(x.get('change_percent', 0)),
            reverse=True
        )
        
        for stock in sorted_stocks[:6]:
            name = stock.get('name', '')
            if not name:
                continue
            
            cn_name = self._get_cn_name(name)
            
            self.logger.info(f"获取 {name} ({cn_name}) 新闻...")
            time.sleep(self.REQUEST_DELAY)
            
            stock_news = self.search_stock_news(name, max_results=3)
            
            if stock_news:
                lines.append(f"**{cn_name}**")
                for news in stock_news[:2]:
                    # 显示内容，不仅仅是标题
                    if news.content:
                        content = news.content
                        if len(content) > 150:
                            content = content[:150] + "..."
                        lines.append(f"• {content}")
                    else:
                        # 如果没有内容，显示标题
                        lines.append(f"• {news.title}")
                lines.append("")
            else:
                lines.append(f"**{cn_name}**")
                lines.append(f"• 暂无最新消息")
                lines.append("")
        
        return "\n".join(lines)
    
    def get_monthly_news_summary(
        self,
        stock_data: dict,
        year: int,
        month: int
    ) -> str:
        """
        获取月度新闻汇总（中文版，显示详细内容）
        
        Args:
            stock_data: {symbol: {"name": ..., "change_percent": ...}, ...}
            year: 年份
            month: 月份
            
        Returns:
            格式化的月度新闻汇总（中文）
        """
        lines = []
        market_name = self.market_names.get(self.market, self.market)
        
        # 1. 行业大事
        lines.append(f"**📰 {year}年{month}月{market_name}板块要闻**")
        lines.append("")
        
        market_news = self.search_market_news(max_results=8)
        if market_news:
            for news in market_news[:4]:
                lines.append(f"**{news.title}**")
                if news.content:
                    content = news.content
                    if len(content) > 200:
                        content = content[:200] + "..."
                    lines.append(f"{content}")
                lines.append(f"_来源: {news.source}_")
                lines.append("")
        else:
            lines.append(f"{year}年{month}月{market_name}板块整体运行平稳")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 2. 公司动态（不显示涨跌幅）
        lines.append("**🏢 公司重要动态**")
        lines.append("")
        
        # 按涨跌幅排序
        sorted_stocks = sorted(
            stock_data.items(),
            key=lambda x: abs(x[1].get('change_percent', 0)),
            reverse=True
        )
        
        for symbol, data in sorted_stocks[:8]:
            name = data.get('name', symbol)
            cn_name = self._get_cn_name(name)
            
            self.logger.info(f"获取 {name} ({cn_name}) 月度新闻...")
            time.sleep(self.REQUEST_DELAY)
            
            stock_news = self.search_stock_news(name, max_results=3)
            
            if stock_news:
                lines.append(f"**{cn_name}**")
                for news in stock_news[:2]:
                    if news.content:
                        content = news.content
                        if len(content) > 150:
                            content = content[:150] + "..."
                        lines.append(f"• {content}")
                    else:
                        lines.append(f"• {news.title}")
                lines.append("")
            else:
                lines.append(f"**{cn_name}**")
                lines.append(f"• {month}月暂无重要消息披露")
                lines.append("")
        
        return "\n".join(lines)


# ================================================================
# 测试
# ================================================================

if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO)
    
    service = WebNewsService(MARKET_KR)
    
    # 测试中文搜索
    print("\n=== 测试中文新闻搜索 ===")
    results = service.search_duckduckgo("Nexon 韩国游戏", max_results=5)
    for r in results:
        print(f"标题: {r.title}")
        print(f"内容: {r.content}")
        print(f"来源: {r.source}")
        print()
    
    # 测试股票新闻
    print("\n=== 测试股票中文新闻 ===")
    news = service.search_stock_news("Pearl Abyss", max_results=3)
    for n in news:
        print(f"标题: {n.title}")
        print(f"内容: {n.content}")
        print()
