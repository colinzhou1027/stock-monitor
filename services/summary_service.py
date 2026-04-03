"""
摘要服务
集成新闻获取服务，生成包含真实新闻的日报和月报
无需外部 AI API，完全免费
"""

from typing import List, Optional, Dict
from datetime import datetime, timedelta
from calendar import monthrange

from models.stock import StockChange, MarketIndex
from utils.logger import LoggerMixin
from config import MARKET_KR, MARKET_US, MARKET_HK


class SummaryService(LoggerMixin):
    """摘要服务 - 集成真实新闻数据"""
    
    def __init__(self, market: str):
        """
        初始化摘要服务
        
        Args:
            market: 市场类型 (kr/us/hk)
        """
        self.market = market
        self.market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
        self._news_service = None  # 延迟初始化
        self.logger.info(f"{self.market_names.get(market, market)} 摘要服务初始化完成")
    
    @property
    def news_service(self):
        """延迟加载新闻服务"""
        if self._news_service is None:
            from services.news_service import NewsService
            self._news_service = NewsService(market=self.market)
        return self._news_service
    
    def analyze_stock_changes(
        self, 
        changes: List[StockChange] = None,
        tech_changes: List[StockChange] = None,
        game_changes: List[StockChange] = None,
        indices: List[MarketIndex] = None,
        prev_trading_date: Optional[datetime] = None
    ) -> str:
        """
        生成股票昨日涨跌摘要（日报 - 昨日新闻部分）
        
        Args:
            changes: 股票变化列表（韩股使用）
            tech_changes: 科技股变化列表（美股/港股使用）
            game_changes: 游戏股变化列表（美股/港股使用）
            indices: 大盘指数列表
            prev_trading_date: 上一交易日日期
        """
        if self.market == MARKET_KR:
            return self._generate_kr_daily_summary(changes or [], prev_trading_date)
        else:
            return self._generate_us_hk_daily_summary(
                tech_changes or [], 
                game_changes or [], 
                indices or [],
                prev_trading_date
            )
    
    def _generate_kr_daily_summary(
        self, 
        changes: List[StockChange],
        prev_trading_date: Optional[datetime] = None
    ) -> str:
        """生成韩股日报摘要 - 包含真实新闻"""
        if not changes:
            return "没有股票数据可供分析。"
        
        # 计算日期
        if prev_trading_date:
            date_str = prev_trading_date.strftime("%Y年%m月%d日")
        else:
            date_str = "上一交易日"
        
        # 构建股票列表用于新闻查询
        stock_list = []
        for c in changes:
            stock_list.append({
                'symbol': c.stock.symbol,
                'name': c.stock.name,
                'change_percent': c.change_percent
            })
        
        # 获取新闻
        self.logger.info("获取日报新闻数据...")
        try:
            news_data = self.news_service.get_daily_news(
                stock_list=stock_list,
                prev_trading_date=prev_trading_date
            )
        except Exception as e:
            self.logger.error(f"获取新闻失败: {e}")
            news_data = {}
        
        # 分析涨跌情况
        rising = [c for c in changes if c.is_rising]
        falling = [c for c in changes if not c.is_rising]
        avg_change = sum(c.change_percent for c in changes) / len(changes) if changes else 0
        
        # 生成表格
        lines = []
        lines.append("| 公司 | 新闻内容 |")
        lines.append("|:----:|:-----|")
        
        # 大盘行情分析
        market_news = news_data.get("market", [])
        if market_news:
            market_desc = self.news_service.format_news_for_stock("市场", market_news, max_items=1)
        else:
            market_desc = self._get_market_trend_desc(avg_change, len(rising), len(falling))
        lines.append(f"| 🌐 大盘 | {market_desc} |")
        
        # 各股票摘要
        for c in changes:
            emoji = "🎮"
            company_name = c.stock.name
            
            # 获取该股票的新闻
            stock_news = news_data.get(company_name, [])
            if stock_news:
                news_content = self.news_service.format_news_for_stock(
                    company_name, stock_news, max_items=2
                )
            else:
                # 没有新闻时显示涨跌信息
                news_content = self._generate_stock_change_desc(c, date_str)
            
            lines.append(f"| {emoji} {company_name} | {news_content} |")
        
        return "\n".join(lines)
    
    def _generate_us_hk_daily_summary(
        self, 
        tech_changes: List[StockChange],
        game_changes: List[StockChange],
        indices: List[MarketIndex],
        prev_trading_date: Optional[datetime] = None
    ) -> str:
        """生成美股/港股日报摘要 - 包含真实新闻"""
        all_changes = tech_changes + game_changes
        
        if not all_changes:
            return "没有股票数据可供分析。"
        
        # 计算日期
        if prev_trading_date:
            date_str = prev_trading_date.strftime("%Y年%m月%d日")
        else:
            date_str = "上一交易日"
        
        # 市场名称
        market_name = "美股" if self.market == MARKET_US else "港股"
        
        # 构建股票列表用于新闻查询
        stock_list = []
        for c in all_changes:
            stock_list.append({
                'symbol': c.stock.symbol,
                'name': c.stock.name,
                'change_percent': c.change_percent
            })
        
        # 获取新闻
        self.logger.info("获取日报新闻数据...")
        try:
            news_data = self.news_service.get_daily_news(
                stock_list=stock_list,
                prev_trading_date=prev_trading_date
            )
        except Exception as e:
            self.logger.error(f"获取新闻失败: {e}")
            news_data = {}
        
        # 大盘分析
        index_desc = ""
        if indices:
            idx = indices[0]
            direction = "上涨" if idx.is_rising else "下跌"
            index_desc = f"{idx.name}{direction}{abs(idx.change_percent):.2f}%"
        
        # 生成表格
        lines = []
        lines.append("| 公司 | 新闻内容 |")
        lines.append("|:----:|:-----|")
        
        # 大盘
        market_news = news_data.get("market", [])
        if market_news:
            market_content = self.news_service.format_news_for_stock("市场", market_news, max_items=1)
            if index_desc:
                market_content = f"{index_desc}。{market_content}"
        elif index_desc:
            market_content = f"{date_str}，{index_desc}"
        else:
            market_content = f"{date_str}市场波动"
        lines.append(f"| 🌐 大盘 | {market_content} |")
        
        # 科技股
        for c in tech_changes:
            emoji = "💻"
            stock_news = news_data.get(c.stock.name, [])
            if stock_news:
                news_content = self.news_service.format_news_for_stock(
                    c.stock.name, stock_news, max_items=2
                )
            else:
                news_content = self._generate_stock_change_desc(c, date_str)
            lines.append(f"| {emoji} {c.stock.name} | {news_content} |")
        
        # 游戏股
        for c in game_changes:
            emoji = "🎮"
            stock_news = news_data.get(c.stock.name, [])
            if stock_news:
                news_content = self.news_service.format_news_for_stock(
                    c.stock.name, stock_news, max_items=2
                )
            else:
                news_content = self._generate_stock_change_desc(c, date_str)
            lines.append(f"| {emoji} {c.stock.name} | {news_content} |")
        
        return "\n".join(lines)
    
    def _get_market_trend_desc(self, avg_change: float, rising_count: int, falling_count: int) -> str:
        """根据平均涨跌幅生成市场趋势描述"""
        if avg_change > 3:
            trend = "板块整体强势上涨"
        elif avg_change > 1:
            trend = "板块整体表现良好"
        elif avg_change > 0:
            trend = "板块整体小幅上涨"
        elif avg_change > -1:
            trend = "板块整体小幅下跌"
        elif avg_change > -3:
            trend = "板块整体走弱"
        else:
            trend = "板块整体大幅回调"
        
        return f"{trend}，{rising_count}涨{falling_count}跌"
    
    def _generate_stock_change_desc(self, change: StockChange, date_str: str) -> str:
        """生成单只股票的涨跌描述（没有新闻时使用）"""
        direction = "上涨" if change.is_rising else "下跌"
        pct = abs(change.change_percent)
        
        if pct >= 10:
            intensity = "大幅"
        elif pct >= 5:
            intensity = "明显"
        elif pct >= 2:
            intensity = "小幅"
        else:
            intensity = "微幅"
        
        return f"{date_str}{intensity}{direction}{pct:.2f}%"
    
    # ============================================================
    # 月报相关方法
    # ============================================================
    
    def analyze_monthly_news_summary(
        self,
        year: int,
        month: int,
        stock_data: dict,
        market: str = None
    ) -> str:
        """
        生成月度新闻汇总（行业大事、公司动态、市场热点）
        
        Args:
            year: 年份
            month: 月份
            stock_data: 股票数据 {symbol: {name, change_percent, ...}}
            market: 市场类型（可选，默认使用 self.market）
        """
        if not stock_data:
            return "没有股票数据可供分析。"
        
        target_market = market or self.market
        market_name = self.market_names.get(target_market, target_market)
        
        # 构建股票列表
        stock_list = []
        for symbol, data in stock_data.items():
            stock_list.append({
                'symbol': symbol,
                'name': data.get('name', symbol),
                'change_percent': data.get('change_percent', 0)
            })
        
        # 获取月度新闻
        self.logger.info(f"获取{year}年{month}月新闻数据...")
        try:
            news_data = self.news_service.get_monthly_news(
                stock_list=stock_list,
                year=year,
                month=month
            )
        except Exception as e:
            self.logger.error(f"获取月度新闻失败: {e}")
            news_data = {}
        
        # 使用新闻服务格式化输出
        if news_data:
            return self.news_service.format_monthly_news_summary(
                news_data=news_data,
                stock_data=stock_data,
                year=year,
                month=month
            )
        else:
            # 没有新闻时使用备用生成方式
            return self._generate_fallback_monthly_news(
                year=year,
                month=month,
                stock_data=stock_data,
                market_name=market_name
            )
    
    def _generate_fallback_monthly_news(
        self,
        year: int,
        month: int,
        stock_data: dict,
        market_name: str
    ) -> str:
        """生成备用月度新闻（无法获取真实新闻时使用）"""
        # 按涨跌幅排序
        sorted_stocks = sorted(stock_data.items(), key=lambda x: x[1]['change_percent'], reverse=True)
        
        # 找出涨跌最大的
        top_gainers = [(s, d) for s, d in sorted_stocks if d['change_percent'] > 0][:3]
        top_losers = [(s, d) for s, d in sorted_stocks if d['change_percent'] < 0][-3:]
        
        # 计算平均涨跌幅
        avg_change = sum(d['change_percent'] for d in stock_data.values()) / len(stock_data)
        
        lines = []
        
        # 行业大事
        lines.append("**📰 行业大事**")
        if avg_change > 5:
            trend = "板块整体表现强劲"
        elif avg_change > 0:
            trend = "板块整体表现稳健"
        elif avg_change > -5:
            trend = "板块整体承压调整"
        else:
            trend = "板块整体回调明显"
        lines.append(f"• {year}年{month}月{market_name}{trend}，平均涨跌幅{avg_change:+.2f}%")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 公司动态
        lines.append("**🏢 公司动态**")
        for symbol, data in sorted_stocks:
            change = data['change_percent']
            name = data['name']
            
            if change > 10:
                desc = f"{month}月股价大涨{change:.2f}%，表现亮眼"
            elif change > 5:
                desc = f"{month}月股价上涨{change:.2f}%，表现良好"
            elif change > 0:
                desc = f"{month}月股价小幅上涨{change:.2f}%"
            elif change > -5:
                desc = f"{month}月股价小幅下跌{abs(change):.2f}%"
            elif change > -10:
                desc = f"{month}月股价下跌{abs(change):.2f}%，表现承压"
            else:
                desc = f"{month}月股价大跌{abs(change):.2f}%，走势疲弱"
            lines.append(f"• **{name}**: {desc}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 市场热点
        lines.append("**🔥 市场热点**")
        topics = []
        if top_gainers:
            gainer_names = [d['name'] for _, d in top_gainers[:2]]
            topics.append(f"{', '.join(gainer_names)}等表现抢眼")
        if top_losers:
            loser_names = [d['name'] for _, d in top_losers[:2]]
            topics.append(f"{', '.join(loser_names)}等承压调整")
        
        if topics:
            lines.append(f"• {month}月投资者关注焦点：" + "；".join(topics))
        else:
            lines.append(f"• {month}月{market_name}板块整体波动平稳")
        
        return "\n".join(lines)
    
    def analyze_monthly_report(
        self,
        year: int,
        month: int,
        stock_data: dict,
        index_data: dict = None,
        stock_type: str = 'all'
    ) -> str:
        """
        生成月度分析报告（月度总结、要点回顾、后市展望）
        
        Args:
            year: 年份
            month: 月份
            stock_data: 股票数据 {symbol: {name, change_percent, start_price, end_price}}
            index_data: 指数数据 {name, change_percent}（可选）
            stock_type: 股票类型 ('all'/'tech'/'game')
        """
        if not stock_data:
            return "没有股票数据可供分析。"
        
        # 排序
        sorted_stocks = sorted(stock_data.items(), key=lambda x: x[1]['change_percent'], reverse=True)
        
        # 计算统计数据
        avg_change = sum(d['change_percent'] for d in stock_data.values()) / len(stock_data)
        rising_count = sum(1 for d in stock_data.values() if d['change_percent'] > 0)
        falling_count = len(stock_data) - rising_count
        
        # 最佳和最差表现
        best_stock = sorted_stocks[0] if sorted_stocks else None
        worst_stock = sorted_stocks[-1] if sorted_stocks else None
        
        # 类型名称
        type_name = {'all': '股票', 'tech': '科技股', 'game': '游戏股'}.get(stock_type, '股票')
        
        lines = []
        
        # 月度总结
        lines.append("**📌 月度总结**")
        summary = self._generate_monthly_summary(
            year, month, avg_change, rising_count, falling_count,
            best_stock, worst_stock, index_data, type_name
        )
        lines.append(f"• {summary}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 要点回顾
        lines.append("**📌 要点回顾**")
        key_points = self._generate_key_points(
            year, month, sorted_stocks, avg_change, type_name
        )
        for point in key_points:
            lines.append(f"• {point}")
        lines.append("")
        lines.append("---")
        lines.append("")
        
        # 后市展望
        lines.append("**📌 后市展望**")
        outlook = self._generate_outlook(year, month, avg_change, type_name)
        lines.append(f"• {outlook}")
        
        return "\n".join(lines)
    
    def _generate_monthly_summary(
        self, year: int, month: int,
        avg_change: float, rising_count: int, falling_count: int,
        best_stock: tuple, worst_stock: tuple,
        index_data: dict, type_name: str
    ) -> str:
        """生成月度总结"""
        # 整体趋势
        if avg_change > 5:
            trend = "表现强劲"
        elif avg_change > 0:
            trend = "整体上涨"
        elif avg_change > -5:
            trend = "小幅回调"
        else:
            trend = "明显下跌"
        
        summary_parts = []
        summary_parts.append(f"{year}年{month}月{type_name}板块{trend}")
        summary_parts.append(f"平均涨跌幅{avg_change:+.2f}%")
        summary_parts.append(f"{rising_count}涨{falling_count}跌")
        
        if best_stock:
            _, best_data = best_stock
            summary_parts.append(f"涨幅最高的是{best_data['name']}({best_data['change_percent']:+.2f}%)")
        
        if worst_stock and worst_stock[1]['change_percent'] < 0:
            _, worst_data = worst_stock
            summary_parts.append(f"跌幅最大的是{worst_data['name']}({worst_data['change_percent']:.2f}%)")
        
        return "，".join(summary_parts) + "。"
    
    def _generate_key_points(
        self, year: int, month: int,
        sorted_stocks: list, avg_change: float, type_name: str
    ) -> List[str]:
        """生成要点回顾"""
        points = []
        
        # 趋势判断
        if avg_change > 3:
            points.append(f"{type_name}板块整体走强，市场情绪偏乐观")
        elif avg_change > 0:
            points.append(f"{type_name}板块稳中有升，个股分化明显")
        elif avg_change > -3:
            points.append(f"{type_name}板块震荡调整，投资者观望情绪浓厚")
        else:
            points.append(f"{type_name}板块整体承压，建议关注估值回调机会")
        
        # 头部股票表现
        if sorted_stocks:
            top_stock = sorted_stocks[0]
            points.append(f"领涨个股{top_stock[1]['name']}涨幅达{top_stock[1]['change_percent']:+.2f}%")
        
        # 尾部股票表现
        if len(sorted_stocks) > 1 and sorted_stocks[-1][1]['change_percent'] < 0:
            bottom_stock = sorted_stocks[-1]
            points.append(f"跌幅较大的{bottom_stock[1]['name']}下跌{abs(bottom_stock[1]['change_percent']):.2f}%")
        
        return points[:3]  # 最多3个要点
    
    def _generate_outlook(self, year: int, month: int, avg_change: float, type_name: str) -> str:
        """生成后市展望"""
        next_month = month + 1 if month < 12 else 1
        next_year = year if month < 12 else year + 1
        
        if avg_change > 5:
            outlook = f"关注{type_name}高位震荡风险，建议适当锁定利润"
        elif avg_change > 0:
            outlook = f"{type_name}走势稳健，可继续持有优质标的"
        elif avg_change > -5:
            outlook = f"关注{type_name}超跌反弹机会，建议分批布局"
        else:
            outlook = f"{type_name}短期仍需谨慎，等待企稳信号"
        
        return f"{next_month}月展望：{outlook}。"
