"""
AI 分析服务
支持通义千问（阿里云百炼）和 Google Gemini API
支持韩股、美股、港股市场分析
"""

from typing import List, Optional
from datetime import datetime, timedelta
import requests
import time

from models.stock import StockChange, MarketIndex
from utils.logger import LoggerMixin
from config import MARKET_KR, MARKET_US, MARKET_HK


class AIService(LoggerMixin):
    """统一 AI 分析服务类 - 支持多市场"""
    
    def __init__(
        self, 
        market: str,
        api_key: str, 
        model: str = "qwen-plus",
        provider: str = "qwen"
    ):
        """
        初始化 AI 服务
        
        Args:
            market: 市场类型 (kr/us/hk)
            api_key: API 密钥
            model: 模型名称
            provider: 服务提供商 ("qwen" 或 "gemini")
        """
        self.market = market
        self.api_key = api_key
        self.model = model
        self.provider = provider
        
        if provider == "qwen":
            self.base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
        else:
            self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        
        market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
        self.logger.info(f"{market_names.get(market, market)} AI 服务初始化完成，提供商: {provider}，模型: {model}")
    
    def analyze_stock_changes(
        self, 
        changes: List[StockChange] = None,
        tech_changes: List[StockChange] = None,
        game_changes: List[StockChange] = None,
        indices: List[MarketIndex] = None,
        prev_trading_date: Optional[datetime] = None
    ) -> str:
        """
        分析股票昨日涨跌原因
        
        Args:
            changes: 股票变化列表（韩股使用）
            tech_changes: 科技股变化列表（美股/港股使用）
            game_changes: 游戏股变化列表（美股/港股使用）
            indices: 大盘指数列表
            prev_trading_date: 上一交易日日期
        """
        if self.market == MARKET_KR:
            return self._analyze_kr_stocks(changes or [], prev_trading_date)
        else:
            return self._analyze_us_hk_stocks(
                tech_changes or [], 
                game_changes or [], 
                indices or [],
                prev_trading_date
            )
    
    def _analyze_kr_stocks(
        self, 
        changes: List[StockChange],
        prev_trading_date: Optional[datetime] = None
    ) -> str:
        """分析韩股"""
        if not changes:
            return "没有需要分析的股票变化。"
        
        if not self.api_key:
            self.logger.warning("未配置 API_KEY，使用备用分析")
            return self._generate_fallback_analysis_kr(changes, "未配置 API_KEY")
        
        stock_count = len(changes)
        
        # 识别需要强化搜索的股票：
        # 1. Shift Up（始终需要强化搜索）
        # 2. 涨跌幅超过10%的股票
        stocks_need_enhanced = {}  # {股票名: 涨跌幅}
        large_change_stocks = []
        
        for c in changes:
            # Shift Up 始终需要强化搜索
            if "Shift Up" in c.stock.name or "시프트업" in c.stock.name:
                stocks_need_enhanced[c.stock.name] = c.change_percent
                self.logger.info(f"🔥 Shift Up 标记为需要强化搜索: {c.change_percent:+.2f}%")
            
            # 涨跌超过10%的股票也需要强化搜索
            if abs(c.change_percent) >= 10:
                large_change_stocks.append(c.stock.name)
                if c.stock.name not in stocks_need_enhanced:
                    stocks_need_enhanced[c.stock.name] = c.change_percent
                self.logger.info(f"🔥 标记大幅波动股票需加强搜索: {c.stock.name} ({c.change_percent:+.2f}%)")
        
        # 生成股票列表文本，标记大涨跌股票
        stocks_lines = []
        for c in changes:
            line = f"{c.stock.name}: {'涨' if c.is_rising else '跌'}{abs(c.change_percent):.2f}%"
            if abs(c.change_percent) >= 10:
                line += " 🔥【大幅波动，必须加强搜索！】"
            stocks_lines.append(line)
        stocks_text = "\n".join(stocks_lines)
        
        # 计算新闻时间范围：只获取昨天的新闻
        news_end_date = datetime.now() - timedelta(days=1)
        news_date_str = news_end_date.strftime("%Y年%m月%d日")
        
        if prev_trading_date:
            analysis_date_str = prev_trading_date.strftime("%Y年%m月%d日")
        else:
            analysis_date_str = "上一交易日"
        
        # 生成加强搜索提示
        enhanced_search_notice = ""
        if large_change_stocks:
            enhanced_search_notice = f"""
🔥🔥🔥 **特别重要：加强搜索提醒** 🔥🔥🔥

以下股票涨跌幅超过10%，必须进行加强搜索：
{chr(10).join([f"- **{name}**" for name in large_change_stocks])}

⚠️ 对于这些大幅波动的股票：
1. **必须多次尝试不同关键词搜索**（中文、英文、韩文、游戏名）
2. **必须搜索多个新闻源**（韩联社、Bloomberg、IGN、4Gamer等）
3. **不能轻易写"无重大公开报道"** - 10%以上的涨跌必有原因！
4. 如果实在找不到直接新闻，也要分析：是否受大盘影响？是否有行业消息？

"""
        
        prompt = f"""你是韩国游戏股票分析师。

**任务：搜索昨日新闻**
{enhanced_search_notice}
⚠️ 时间范围（严格执行，非常重要）：
- 新闻收录范围：仅限 {news_date_str}（昨天）的新闻
- ❌ 严禁收录超出此范围的旧闻！
- ❌ 特别注意：必须是{news_end_date.year}年的新闻，去年同期({news_end_date.year - 1}年)的新闻绝对不能收录！

待分析股票：
{stocks_text}

🔍 各公司搜索关键词（请使用这些关键词搜索最新新闻）：

1. **Shift Up（시프트업）** 🔥⚠️ 请务必仔细搜索！必须多次尝试！
   - 游戏IP：NIKKE/胜利女神妮姬/勝利女神、Stellar Blade/剑星、GODDESS OF VICTORY
   - 搜索词（必须全部尝试）：
     * 英文：Shift Up、ShiftUp、"Shift Up" news、"Shift Up" stock
     * 韩文：시프트업、시프트업 주가、시프트업 뉴스
     * 游戏相关：NIKKE update、NIKKE联动、NIKKE collaboration、剑星销量、Stellar Blade sales
     * 公司动态：Shift Up earnings、Shift Up revenue、시프트업 실적、시프트업 매출
   - 新闻来源建议：4Gamer、Inven、韩联社、매일경제、한국경제、Bloomberg Asia
   - ⚠️ 如果搜索"Shift Up"无结果，请尝试搜索"시프트업"或"NIKKE"

2. **Krafton（크래프톤）**
   - 游戏IP：PUBG/绝地求生、PUBG Mobile、PUBG New State、inZOI、Dark and Darker、暗与暗
   - 搜索词：Krafton、크래프톤、PUBG更新、绝地求生新赛季、inZOI发售

3. **NCsoft（엔씨소프트）**
   - 游戏IP：Lineage/天堂系列、天堂M、天堂W、Blade & Soul/剑灵、AION/永恒之塔、Throne and Liberty/TL
   - 搜索词：NCsoft、엔씨소프트、天堂更新、TL新内容、리니지

4. **Netmarble（넷마블）**
   - 游戏IP：七骑士、神之领域、MARVEL Future Revolution、第二国度、石器时代、A3 Still Alive
   - 搜索词：Netmarble、넷마블、七骑士更新、漫威手游

5. **Nexon Games（넥슨게임즈）**
   - 游戏IP：Blue Archive/蓝色档案、V4、HIT2、碧蓝档案
   - 搜索词：Nexon Games、넥슨게임즈、Blue Archive更新、蓝档联动、블루아카이브

6. **Pearl Abyss（펄어비스）**
   - 游戏IP：Black Desert/黑色沙漠、黑沙Mobile、Crimson Desert/红色沙漠、DokeV
   - 搜索词：Pearl Abyss、펄어비스、黑色沙漠更新、红色沙漠发售、검은사막

📰 新闻来源（优先使用，但不严格限定）：

✅ **优先推荐的来源**：
- 顶级国际财经媒体：Bloomberg、Reuters、Wall Street Journal、Financial Times、Barron's、MarketWatch
- 权威韩国媒体：韩联社（Yonhap）、매일경제（Maeil Business）、한국경제（Korea Economic Daily）、조선일보、KBS、MBC
- 权威游戏媒体：IGN、GameSpot、4Gamer（日本）、Inven（韩国官方）、Polygon、GamesIndustry.biz
- 权威科技媒体：The Verge、TechCrunch、Wired、Engadget
- 官方渠道：公司官网、公司IR页面、公司官方Twitter/X/Facebook、公司新闻稿

❌ **明确禁止的来源（出现即扣分）**：
- 聚合/翻译类网站：钜亨网、新浪财经、搜狐财经、网易财经、腾讯财经、东方财富
- 社交/论坛：Reddit帖子、Discord、Twitter/X个人账号、个人博客、论坛帖子、雪球
- 其他低质量来源：来源不明的网站、纯聚合类新闻网站、机器翻译内容

📋 **输出格式（严格遵守，使用两列表格，直接输出，不要开头介绍语）**：

| 公司 | 新闻内容 |
|:----:|:-----|
| 🌐 大盘 | (来源1) 新闻1；(来源2) 新闻2 |
| 🏛️ 财阀动态 | (来源1) 三星/SK/LG/现代等动态 |
| 🎮 Shift Up | (来源1) 公司/游戏新闻 |
| 🎮 Krafton | (来源1) 公司/游戏新闻 |
| 🎮 NCsoft | (来源1) 公司/游戏新闻 |
| 🎮 Netmarble | (来源1) 公司/游戏新闻 |
| 🎮 Nexon Games | (来源1) 公司/游戏新闻 |
| 🎮 Pearl Abyss | (来源1) 公司/游戏新闻 |

⚠️ **必须遵守的规则**：

1. **🚨无新闻不输出（最重要！）**：如果某公司昨日无新闻，直接跳过该行，不要输出
2. **🚨🚨🚨时效性**：
   - 昨日新闻：仅限 {news_date_str} 这1天的新闻
   - ❌ 去年({news_end_date.year - 1}年)的新闻绝对禁止！
   - ❌ 超过1天（早于{news_date_str}）的旧闻绝对禁止！
3. **🚨两列表格格式**：
   - 左列：emoji + 公司名
   - 右列：该公司新闻，**最多2条**，用分号(；)分隔
   - **每条新闻格式**：(来源) 新闻内容
   - 示例：| 🌐 大盘 | (韩联社) 韩国央行维持基准利率；(Bloomberg) 韩元走强 |
   - ❌ 不要输出"无重大公开报道"
4. **财阀动态**：搜索三星、SK、LG、现代、乐天等韩国财阀的重大新闻
5. **🚨新闻数量**：每个公司**最多2条新闻**，每条必须标明来源
6. **字数限制**：每条新闻≤40字，总输出不超过1000字
7. **推测标注**：不确定的内容必须标注"（推测）"
8. **顺序固定**：大盘 → 财阀动态 → Shift Up → Krafton → NCsoft → Netmarble → Nexon Games → Pearl Abyss"""

        # 第一次调用 API 获取分析结果
        analysis = self._call_api_with_retry(prompt, stock_count + 1)
        
        # 强化搜索逻辑
        if analysis:
            # 1. 大盘强化搜索（韩股大盘也需要强化搜索）
            has_market_news = self._check_market_has_news(analysis)
            if not has_market_news:
                self.logger.info(f"🔥 韩股大盘无新闻，启动强化搜索...")
                enhanced_market = self._enhanced_search_for_market(
                    market=MARKET_KR,
                    indices=None,  # 韩股大盘信息在 prompt 中已包含
                    prev_trading_date=prev_trading_date,
                    max_retries=3
                )
                if enhanced_market:
                    analysis = self._replace_market_analysis(analysis, enhanced_market)
                    self.logger.info(f"✅ 韩股大盘强化搜索成功")
            
            # 2. 个股强化搜索
            if stocks_need_enhanced:
                # 检查是否需要跳过强化搜索（大盘涨跌超过10%且有综述内容）
                should_skip = self._should_skip_enhanced_search_for_market(analysis, changes)
                
                if should_skip:
                    self.logger.info(f"📊 大盘涨跌超过10%且有综述内容，跳过个股强化搜索")
                else:
                    # 对每个需要强化搜索的股票进行检查
                    for stock_name, change_pct in stocks_need_enhanced.items():
                        # 检查该股票的分析是否有新闻
                        has_news = self._check_stock_has_news(analysis, stock_name)
                        
                        if not has_news:
                            self.logger.info(f"🔥 {stock_name} 无新闻，启动强化搜索...")
                            enhanced_result = self._enhanced_search_for_stock(
                                stock_name=stock_name,
                                change_percent=change_pct,
                                prev_trading_date=prev_trading_date,
                                max_retries=3
                            )
                            
                            if enhanced_result:
                                # 将强化搜索结果替换到原分析中
                                analysis = self._replace_stock_analysis(analysis, stock_name, enhanced_result)
                                self.logger.info(f"✅ {stock_name} 强化搜索成功，已更新分析结果")
                            else:
                                self.logger.warning(f"❌ {stock_name} 强化搜索失败，保留原结果")
                        else:
                            self.logger.info(f"✅ {stock_name} 已有新闻内容，无需强化搜索")
        
        return analysis
    
    def _analyze_us_hk_stocks(
        self, 
        tech_changes: List[StockChange],
        game_changes: List[StockChange],
        indices: List[MarketIndex],
        prev_trading_date: Optional[datetime] = None
    ) -> str:
        """
        分析美股/港股 - 分批调用 API 提高成功率
        科技股和游戏股分开调用 API，然后合并结果
        包含强化搜索机制：大盘 + 涨跌幅超10%的个股
        """
        if not tech_changes and not game_changes:
            return "没有需要分析的股票变化。"
        
        if not self.api_key:
            self.logger.warning("未配置 API_KEY，使用备用分析")
            return self._generate_fallback_analysis_us_hk(tech_changes, game_changes, "未配置 API_KEY")
        
        # 根据市场设置不同参数
        is_us = self.market == MARKET_US
        market_name = "美股" if is_us else "港股"
        
        # 识别需要强化搜索的股票（涨跌超过10%）
        all_changes = tech_changes + game_changes
        stocks_need_enhanced = {}  # {股票名: 涨跌幅}
        large_change_stocks = []
        
        for c in all_changes:
            if abs(c.change_percent) >= 10:
                large_change_stocks.append(c.stock.name)
                stocks_need_enhanced[c.stock.name] = c.change_percent
                self.logger.info(f"🔥 标记大幅波动股票需强化搜索: {c.stock.name} ({c.change_percent:+.2f}%)")
        
        # 检查大盘是否需要强化搜索
        market_need_enhanced = False
        for idx in indices:
            if abs(idx.change_percent) >= 3:  # 大盘涨跌超过3%就需要强化搜索
                market_need_enhanced = True
                self.logger.info(f"🔥 大盘波动较大，需强化搜索: {idx.name} ({idx.change_percent:+.2f}%)")
                break
        
        # 构建大盘指数文本
        indices_text = "\n".join([
            f"{idx.name}: {'涨' if idx.is_rising else '跌'}{abs(idx.change_percent):.2f}%"
            for idx in indices
        ]) if indices else "暂无大盘数据"
        
        # 计算新闻时间范围：只获取昨天的新闻
        news_end_date = datetime.now() - timedelta(days=1)
        news_date_str = news_end_date.strftime("%Y年%m月%d日")
        
        if prev_trading_date:
            analysis_date_str = prev_trading_date.strftime("%Y年%m月%d日")
        else:
            analysis_date_str = "上一交易日"
        
        results = []
        
        # 第一步：分析科技股（包含大盘综述）
        if tech_changes:
            self.logger.info(f"📊 开始分析{market_name}科技股 ({len(tech_changes)}只)...")
            
            # 生成科技股文本，标记大涨跌股票
            tech_lines = []
            for c in tech_changes:
                line = f"{c.stock.name}: {'涨' if c.is_rising else '跌'}{abs(c.change_percent):.2f}%"
                if abs(c.change_percent) >= 10:
                    line += " 🔥【大幅波动，必须加强搜索！】"
                tech_lines.append(line)
            tech_text = "\n".join(tech_lines)
            
            # 筛选科技股中的大涨跌股票
            tech_large_change = [c.stock.name for c in tech_changes if abs(c.change_percent) >= 10]
            
            if is_us:
                tech_prompt = self._build_us_tech_prompt(
                    indices_text, tech_text,
                    news_date_str, news_end_date,
                    len(tech_changes),
                    tech_large_change
                )
            else:
                tech_prompt = self._build_hk_tech_prompt(
                    indices_text, tech_text,
                    news_date_str, news_end_date,
                    len(tech_changes),
                    tech_large_change
                )
            
            # 科技股分析：大盘 + 科技股 = len(tech_changes) + 1
            tech_analysis = self._call_api_with_retry(tech_prompt, len(tech_changes) + 1)
            if tech_analysis and not tech_analysis.startswith("⚠️"):
                results.append(tech_analysis)
                self.logger.info(f"✅ {market_name}科技股分析完成")
            else:
                self.logger.warning(f"❌ {market_name}科技股分析失败")
        
        # 第二步：分析游戏股（不含大盘综述）
        if game_changes:
            self.logger.info(f"🎮 开始分析{market_name}游戏股 ({len(game_changes)}只)...")
            
            # 生成游戏股文本，标记大涨跌股票
            game_lines = []
            for c in game_changes:
                line = f"{c.stock.name}: {'涨' if c.is_rising else '跌'}{abs(c.change_percent):.2f}%"
                if abs(c.change_percent) >= 10:
                    line += " 🔥【大幅波动，必须加强搜索！】"
                game_lines.append(line)
            game_text = "\n".join(game_lines)
            
            # 筛选游戏股中的大涨跌股票
            game_large_change = [c.stock.name for c in game_changes if abs(c.change_percent) >= 10]
            
            if is_us:
                game_prompt = self._build_us_game_prompt(
                    indices_text, game_text,
                    news_date_str, news_end_date,
                    len(game_changes),
                    game_large_change
                )
            else:
                game_prompt = self._build_hk_game_prompt(
                    indices_text, game_text,
                    news_date_str, news_end_date,
                    len(game_changes),
                    game_large_change
                )
            
            # 游戏股分析：只有游戏股 = len(game_changes)
            game_analysis = self._call_api_with_retry(game_prompt, len(game_changes))
            if game_analysis and not game_analysis.startswith("⚠️"):
                results.append(game_analysis)
                self.logger.info(f"✅ {market_name}游戏股分析完成")
            else:
                self.logger.warning(f"❌ {market_name}游戏股分析失败")
        
        # 合并结果
        if not results:
            return self._generate_fallback_analysis_us_hk(tech_changes, game_changes, "分批分析均失败")
        
        analysis = "\n\n".join(results)
        
        # 第三步：强化搜索逻辑
        # 3.1 大盘强化搜索
        if market_need_enhanced and indices:
            has_market_news = self._check_market_has_news(analysis)
            if not has_market_news:
                self.logger.info(f"🔥 {market_name}大盘无新闻，启动强化搜索...")
                enhanced_market = self._enhanced_search_for_market(
                    market=self.market,
                    indices=indices,
                    prev_trading_date=prev_trading_date,
                    max_retries=3
                )
                if enhanced_market:
                    analysis = self._replace_market_analysis(analysis, enhanced_market)
                    self.logger.info(f"✅ {market_name}大盘强化搜索成功")
        
        # 3.2 个股强化搜索（涨跌幅超10%）
        if stocks_need_enhanced:
            for stock_name, change_pct in stocks_need_enhanced.items():
                has_news = self._check_stock_has_news(analysis, stock_name)
                if not has_news:
                    self.logger.info(f"🔥 {stock_name} 无新闻，启动强化搜索...")
                    enhanced_result = self._enhanced_search_for_stock_general(
                        stock_name=stock_name,
                        change_percent=change_pct,
                        market=self.market,
                        prev_trading_date=prev_trading_date,
                        max_retries=3
                    )
                    if enhanced_result:
                        analysis = self._replace_stock_analysis_table(analysis, stock_name, enhanced_result)
                        self.logger.info(f"✅ {stock_name} 强化搜索成功")
                    else:
                        self.logger.warning(f"❌ {stock_name} 强化搜索失败")
                else:
                    self.logger.info(f"✅ {stock_name} 已有新闻内容，无需强化搜索")
        
        return analysis
    
    def _build_us_prompt(
        self, indices_text, tech_text, game_text,
        news_start_str, news_end_str, news_end_date,
        analysis_date_str, tech_count, game_count
    ) -> str:
        """构建美股分析 prompt"""
        return f"""你是美股分析师，专注于科技股和游戏股分析。

**任务：搜索指定时间范围内新闻 + 分析上一交易日股价**

⚠️ 时间范围（严格执行，非常重要）：
- 新闻收录范围：仅限 {news_start_str} 至 {news_end_str}（这3天内的新闻）
- 股价分析日期：{analysis_date_str}
- ❌ 严禁收录超出此范围的旧闻！
- ❌ 必须是{news_end_date.year}年的新闻，去年的新闻绝对不能收录！

待分析数据：

【大盘指数】
{indices_text}

【科技股】
{tech_text}

【游戏股】
{game_text}

🔍 搜索关键词：

**科技股**：
- 苹果/Apple：iPhone、iPad、Mac、Vision Pro、Apple Intelligence、App Store
- 微软/Microsoft：Azure、Office 365、Copilot、Xbox、GitHub
- 谷歌/Google/Alphabet：Search、YouTube、Cloud、Gemini AI、Android
- 亚马逊/Amazon：AWS、Prime、电商、Alexa
- 英伟达/NVIDIA：GPU、AI芯片、CUDA、数据中心、Blackwell
- Meta：Facebook、Instagram、WhatsApp、Quest VR、Threads
- 特斯拉/Tesla：电动车、FSD自动驾驶、Cybertruck、能源

**游戏股**：
- 动视暴雪/Activision：COD使命召唤、魔兽世界、暗黑破坏神、守望先锋
- 艺电/EA：FIFA/EA Sports FC、Madden、Apex Legends、战地
- Take-Two：GTA、NBA 2K、Red Dead、Borderlands
- Roblox：用户增长、创作者经济、元宇宙
- Unity：游戏引擎、广告业务、AI工具

📰 新闻来源（优先使用，但不严格限定）：

✅ **优先推荐的来源**：
- 顶级财经媒体：Bloomberg、Reuters、CNBC、Wall Street Journal、Financial Times、Barron's、MarketWatch、Yahoo Finance、Investor's Business Daily
- 权威科技媒体：The Verge、TechCrunch、The Information、Wired、Ars Technica、Engadget、Gizmodo、ZDNet、VentureBeat
- 权威游戏媒体：IGN、GameSpot、Polygon、Kotaku、PC Gamer、GamesIndustry.biz、VGC（Video Games Chronicle）
- 综合科技新闻：9to5Mac、9to5Google、MacRumors、Android Authority、Tom's Hardware、AnandTech、Digital Trends
- 行业分析：Seeking Alpha、The Motley Fool、Benzinga、InvestorPlace（分析观点需标注来源）
- 官方渠道：公司官网、SEC文件（10-K/10-Q/8-K）、公司官方Twitter/X、公司新闻稿（Press Release）
- 通讯社/综合新闻：AP News、AFP、USA Today、New York Times、Washington Post

⚠️ **翻译要求**：
- 所有英文新闻必须翻译成中文输出
- 来源名可保留英文原名

❌ **明确禁止的来源（出现即扣分）**：
- 中文科技自媒体：量子位、36氪、虎嗅、钛媒体、IT之家、快科技、雷锋网、PingWest、爱范儿
- 聚合/翻译类网站：钜亨网、新浪财经、搜狐财经、网易财经、腾讯财经、东方财富
- 社交/论坛：Reddit帖子、Twitter/X个人账号、Discord、个人博客、论坛帖子、雪球
- 韩国/台湾媒体：매일경제、钜亨網等（美股不需要）
- 其他低质量来源：来源不明的网站、纯聚合类网站、机器翻译内容

📋 **输出格式（严格遵守，使用表格格式输出，直接输出，不要开头介绍语）**：

**首先输出大盘分析（使用表格格式）：**
### 【大盘综述】

| 类型 | 内容 |
|:----:|:-----|
| 3日内要闻 | (M/D 来源) 影响美股的最重大1-2条新闻，如(3/10 Bloomberg)（≤80字） |
| 科技巨头动态 | (M/D 来源) 仅限3日内的科技巨头重要新闻，如(3/11 CNBC)（≤100字） |
| 昨日表现 | 标普500/纳斯达克/道琼斯表现、资金流向（≤80字） |

**然后输出科技股分析（使用表格格式）：**
### 【公司名】

| 类型 | 内容 |
|:----:|:-----|
| 3日内要闻 | (M/D 来源) 新闻内容简述，如(3/10 The Verge)（≤100字） |
| 昨日分析 | 涨跌幅及原因（≤80字） |

**最后输出游戏股分析（使用表格格式）：**
### 【公司名】

| 类型 | 内容 |
|:----:|:-----|
| 3日内要闻 | (M/D 来源) 新闻内容简述，如(3/10 IGN)（≤100字） |
| 昨日分析 | 涨跌幅及原因（≤80字） |

⚠️ **必须遵守的规则**：

1. **完整性**：必须先输出【大盘综述】，再输出全部{tech_count}只科技股，最后输出全部{game_count}只游戏股
2. **🚨🚨🚨时效性（最最最重要！违反此条视为失败！）**：
   - 3日内要闻和科技巨头动态：仅限 {news_start_str} 至 {news_end_str} 这3天的新闻
   - ❌ 去年({news_end_date.year - 1}年)的新闻绝对禁止！
   - ❌ 超过3天（早于{news_start_str}）的旧闻绝对禁止！
   - ❌ 如果新闻日期不在这3天内，宁可不写也不要写旧闻！
3. **🚨格式统一（非常重要）**：
   - 3日内要闻格式必须是：**(M/D 来源) 新闻内容**
   - 示例：(3/10 Bloomberg) 美联储主席表示将维持当前利率
   - ❌ 错误格式：新闻内容(来源)、新闻内容 —— 来源、(来源)新闻内容
4. **无新闻标准语**：搜索后确无3日内新闻，统一写"近3日无重大公开报道"
5. **字数限制（严格执行！表格内容要简洁！）**：
   - 每行内容：≤100字
   - ⚠️ 总输出不超过2000字！
6. **🚨昨日分析要求**：必须结合【大盘综述】中的大盘表现和该公司的3日内要闻来分析涨跌原因
7. **推测标注**：不确定的分析必须标注"（推测）"
8. **避免重复**：大盘因素在【大盘综述】中说明后，个股分析中可简要引用但不要重复展开
9. **顺序固定**：大盘综述 → 科技股（按列表顺序）→ 游戏股（按列表顺序）
10. **表格格式（非常重要！）**：
   - 每个分析块必须用"### 【】"作为标题
   - 标题和表格之间空一行
   - 表格必须包含表头行、分隔行、内容行
   - **表格分隔行格式必须是 |:----:|:-----| （第一列居中，第二列左对齐）**
   - 表格内容不要换行，保持在一行内"""
    
    def _build_hk_prompt(
        self, indices_text, tech_text, game_text,
        news_start_str, news_end_str, news_end_date,
        analysis_date_str, tech_count, game_count
    ) -> str:
        """构建港股分析 prompt"""
        return f"""你是港股分析师，专注于科技股和游戏股分析。

**任务：搜索指定时间范围内新闻 + 分析上一交易日股价**

⚠️ 时间范围（严格执行，非常重要）：
- 新闻收录范围：仅限 {news_start_str} 至 {news_end_str}（这3天内的新闻）
- 股价分析日期：{analysis_date_str}
- ❌ 严禁收录超出此范围的旧闻！
- ❌ 必须是{news_end_date.year}年的新闻，去年的新闻绝对不能收录！

待分析数据：

【大盘指数】
{indices_text}

【科技股】
{tech_text}

【游戏股】
{game_text}

🔍 搜索关键词：

**科技股**：
- 腾讯/Tencent：微信、QQ、腾讯云、腾讯游戏、视频号、企业微信
- 阿里巴巴/Alibaba：淘宝、天猫、阿里云、支付宝、菜鸟、1688
- 网易/NetEase：网易游戏、网易云音乐、有道、网易邮箱
- 小米/Xiaomi：手机、IoT、小米汽车、MIUI、红米
- 百度/Baidu：搜索、百度云、文心一言、Apollo自动驾驶
- MiniMax：AI大模型、智能助手、海螺AI、星野
- 智谱AI/Zhipu：AI大模型、GLM、ChatGLM、清言

**游戏股**：
- 中手游：仙剑奇侠传、轩辕剑、传奇世界、新射雕群侠传
- 心动公司：TapTap、香肠派对、火炬之光、派对之星
- 哔哩哔哩/B站：视频平台、游戏发行、直播、电商
- 创梦天地：手游发行、IP运营
- IGG：王国纪元、Lords Mobile

📰 新闻来源（严格限定，其他来源一律禁止）：

✅ **允许的来源**：
- 顶级国际财经媒体：Bloomberg、Reuters、Financial Times、南华早报（SCMP）
- 权威中文财经媒体：财联社、第一财经、证券时报、香港经济日报、信报财经、明报财经
- 权威科技媒体：36氪（仅限原创深度报道）、The Information
- 垂直游戏媒体：GameLook、游戏葡萄（仅限游戏股分析时）
- 官方渠道：公司官网、港交所公告（HKEX）、公司官方微博/微信、公司新闻稿

⚠️ **翻译要求**：
- 所有英文新闻必须翻译成中文输出
- 来源名可保留英文原名

❌ **明确禁止的来源（出现即扣分）**：
- 低质量科技自媒体：量子位、虎嗅、钛媒体、IT之家、快科技、雷锋网、PingWest、爱范儿
- 聚合/翻译类网站：钜亨网、新浪财经、搜狐财经、网易财经、腾讯财经、东方财富
- 社交/论坛：雪球用户帖子、微博个人账号、知乎、个人博客、论坛帖子
- 韩国/台湾媒体：韩国媒体、台湾媒体（如鉅亨網）
- 其他低质量来源：来源不明的网站、聚合类新闻网站

📋 **输出格式（严格遵守，使用表格格式输出，直接输出，不要开头介绍语）**：

**首先输出大盘分析（使用表格格式）：**
### 【大盘综述】

| 类型 | 内容 |
|:----:|:-----|
| 3日内要闻 | (M/D 来源) 影响港股的最重大1-2条新闻，如(3/10 财联社)（≤80字） |
| 中概股动态 | (M/D 来源) 仅限3日内的中概科技股重要新闻，如(3/11 南华早报)（≤100字） |
| 昨日表现 | 恒生指数/恒生科技表现、资金流向（≤80字） |

**然后输出科技股分析（使用表格格式）：**
### 【公司名】

| 类型 | 内容 |
|:----:|:-----|
| 3日内要闻 | (M/D 来源) 新闻内容简述，如(3/10 Bloomberg)（≤100字） |
| 昨日分析 | 涨跌幅及原因（≤80字） |

**最后输出游戏股分析（使用表格格式）：**
### 【公司名】

| 类型 | 内容 |
|:----:|:-----|
| 3日内要闻 | (M/D 来源) 新闻内容简述，如(3/10 GameLook)（≤100字） |
| 昨日分析 | 涨跌幅及原因（≤80字） |

⚠️ **必须遵守的规则**：

1. **完整性**：必须先输出【大盘综述】，再输出全部{tech_count}只科技股，最后输出全部{game_count}只游戏股
2. **🚨🚨🚨时效性（最最最重要！违反此条视为失败！）**：
   - 3日内要闻和中概股动态：仅限 {news_start_str} 至 {news_end_str} 这3天的新闻
   - ❌ 去年({news_end_date.year - 1}年)的新闻绝对禁止！
   - ❌ 超过3天（早于{news_start_str}）的旧闻绝对禁止！
   - ❌ 如果新闻日期不在这3天内，宁可不写也不要写旧闻！
3. **🚨格式统一（非常重要）**：
   - 3日内要闻格式必须是：**(M/D 来源) 新闻内容**
   - 示例：(3/10 财联社) 港股通南向资金净流入超百亿
   - ❌ 错误格式：新闻内容(来源)、新闻内容 —— 来源、(来源)新闻内容
4. **无新闻标准语**：搜索后确无3日内新闻，统一写"近3日无重大公开报道"
5. **字数限制（严格执行！表格内容要简洁！）**：
   - 每行内容：≤100字
   - ⚠️ 总输出不超过2000字！
6. **🚨昨日分析要求**：必须结合【大盘综述】中的大盘表现和该公司的3日内要闻来分析涨跌原因
7. **推测标注**：不确定的分析必须标注"（推测）"
8. **避免重复**：大盘因素在【大盘综述】中说明后，个股分析中可简要引用但不要重复展开
9. **顺序固定**：大盘综述 → 科技股（按列表顺序）→ 游戏股（按列表顺序）
10. **表格格式（非常重要！）**：
   - 每个分析块必须用"### 【】"作为标题
   - 标题和表格之间空一行
   - 表格必须包含表头行、分隔行、内容行
   - **表格分隔行格式必须是 |:----:|:-----| （第一列居中，第二列左对齐）**
   - 表格内容不要换行，保持在一行内"""
    
    def _build_us_tech_prompt(
        self, indices_text, tech_text,
        news_date_str, news_end_date,
        tech_count,
        large_change_stocks: List[str] = None
    ) -> str:
        """构建美股科技股分析 prompt（包含大盘综述）"""
        # 生成加强搜索提示
        enhanced_search_notice = ""
        if large_change_stocks:
            enhanced_search_notice = f"""
🔥🔥🔥 **特别重要：加强搜索提醒** 🔥🔥🔥

以下股票涨跌幅超过10%，必须进行加强搜索：
{chr(10).join([f"- **{name}**" for name in large_change_stocks])}

⚠️ 对于这些大幅波动的股票：
1. **必须多次尝试不同关键词搜索**（公司名、产品名、CEO名）
2. **必须搜索多个新闻源**（Bloomberg、Reuters、CNBC、WSJ等）
3. **不能轻易写"无重大公开报道"** - 10%以上的涨跌必有原因！
4. 如果实在找不到直接新闻，也要分析：是否受大盘影响？是否有行业消息？

"""
        
        return f"""你是美股分析师，专注于科技股分析。

**任务：搜索昨日新闻**
{enhanced_search_notice}
⚠️ 时间范围（严格执行，非常重要）：
- 新闻收录范围：仅限 {news_date_str}（昨天）的新闻
- ❌ 严禁收录超出此范围的旧闻！
- ❌ 必须是{news_end_date.year}年的新闻，去年的新闻绝对不能收录！

待分析数据：

【大盘指数】
{indices_text}

【科技股】
{tech_text}

🔍 搜索关键词：

**科技股**：
- 苹果/Apple：iPhone、iPad、Mac、Vision Pro、Apple Intelligence、App Store
- 微软/Microsoft：Azure、Office 365、Copilot、Xbox、GitHub
- 谷歌/Google/Alphabet：Search、YouTube、Cloud、Gemini AI、Android
- 亚马逊/Amazon：AWS、Prime、电商、Alexa
- 英伟达/NVIDIA：GPU、AI芯片、CUDA、数据中心、Blackwell
- Meta：Facebook、Instagram、WhatsApp、Quest VR、Threads
- 特斯拉/Tesla：电动车、FSD自动驾驶、Cybertruck、能源

📰 新闻来源（优先使用）：
- 顶级财经媒体：Bloomberg、Reuters、CNBC、Wall Street Journal、Financial Times
- 权威科技媒体：The Verge、TechCrunch、Wired、Engadget
- 官方渠道：公司官网、SEC文件、公司新闻稿

⚠️ 所有英文新闻必须翻译成中文输出

📋 **输出格式（严格遵守，使用两列表格，直接输出，不要开头介绍语）**：

| 公司 | 新闻内容 |
|:----:|:-----|
| 🌐 大盘 | (来源1) 新闻1；(来源2) 新闻2 |
| 💻 苹果 | (来源1) 公司新闻 |
| 💻 微软 | (来源1) 公司新闻 |
...（其他科技股）

⚠️ **必须遵守的规则**：

1. **🚨无新闻不输出**：如果某公司昨日无新闻，直接跳过该行
2. **时效性**：昨日新闻仅限 {news_date_str}
3. **两列表格格式**：左列公司名，右列该公司新闻（**最多2条**，用分号分隔）
4. **🚨新闻数量**：每个公司**最多2条新闻**，每条必须标明来源，格式：(来源) 新闻内容
5. **字数限制**：每条新闻≤40字，总输出不超过1000字
6. **完整性**：大盘 + 全部{tech_count}只科技股（无新闻的跳过）"""
    
    def _build_us_game_prompt(
        self, indices_text, game_text,
        news_date_str, news_end_date,
        game_count,
        large_change_stocks: List[str] = None
    ) -> str:
        """构建美股游戏股分析 prompt（不含大盘综述）"""
        # 生成加强搜索提示
        enhanced_search_notice = ""
        if large_change_stocks:
            enhanced_search_notice = f"""
🔥🔥🔥 **特别重要：加强搜索提醒** 🔥🔥🔥

以下股票涨跌幅超过10%，必须进行加强搜索：
{chr(10).join([f"- **{name}**" for name in large_change_stocks])}

⚠️ 对于这些大幅波动的股票：
1. **必须多次尝试不同关键词搜索**（公司名、游戏名、工作室名）
2. **必须搜索多个新闻源**（IGN、GameSpot、Bloomberg等）
3. **不能轻易写"无重大公开报道"** - 10%以上的涨跌必有原因！
4. 如果实在找不到直接新闻，也要分析：是否受大盘影响？是否有行业消息？

"""
        
        return f"""你是美股分析师，专注于游戏股分析。

**任务：搜索昨日新闻**
{enhanced_search_notice}
⚠️ 时间范围（严格执行，非常重要）：
- 新闻收录范围：仅限 {news_date_str}（昨天）的新闻
- ❌ 严禁收录超出此范围的旧闻！
- ❌ 必须是{news_end_date.year}年的新闻，去年的新闻绝对不能收录！

大盘背景（仅供参考，不需要输出大盘综述）：
{indices_text}

待分析数据：

【游戏股】
{game_text}

🔍 搜索关键词：

**游戏股**：
- 艺电/EA：FIFA/EA Sports FC、Madden、Apex Legends、战地
- Take-Two：GTA、NBA 2K、Red Dead、Borderlands
- Roblox：用户增长、创作者经济、元宇宙
- Unity：游戏引擎、广告业务、AI工具

📰 新闻来源（优先使用）：
- 顶级财经媒体：Bloomberg、Reuters、CNBC
- 权威游戏媒体：IGN、GameSpot、Polygon、GamesIndustry.biz
- 官方渠道：公司官网、SEC文件、公司新闻稿

⚠️ 所有英文新闻必须翻译成中文输出

📋 **输出格式（严格遵守，使用两列表格，直接输出，不要开头介绍语）**：

| 公司 | 新闻内容 |
|:----:|:-----|
| 🎮 EA | (来源) 公司/游戏新闻 |
| 🎮 Take-Two | (来源) 公司/游戏新闻 |
...（其他游戏股）

⚠️ **必须遵守的规则**：

1. **🚨无新闻不输出**：如果某公司昨日无新闻，直接跳过该行
2. **时效性**：昨日新闻仅限 {news_date_str}
3. **两列表格格式**：左列公司名，右列该公司所有新闻（多条用分号分隔）
4. **新闻数量**：每个公司最多2条新闻，合并在一行
5. **字数限制**：每行新闻内容≤80字，总输出不超过500字
6. **完整性**：全部{game_count}只游戏股（无新闻的跳过），不需要大盘综述"""
    
    def _build_hk_tech_prompt(
        self, indices_text, tech_text,
        news_date_str, news_end_date,
        tech_count,
        large_change_stocks: List[str] = None
    ) -> str:
        """构建港股科技股分析 prompt（包含大盘综述）"""
        # 生成加强搜索提示
        enhanced_search_notice = ""
        if large_change_stocks:
            enhanced_search_notice = f"""
🔥🔥🔥 **特别重要：加强搜索提醒** 🔥🔥🔥

以下股票涨跌幅超过10%，必须进行加强搜索：
{chr(10).join([f"- **{name}**" for name in large_change_stocks])}

⚠️ 对于这些大幅波动的股票：
1. **必须多次尝试不同关键词搜索**（公司名、产品名、CEO名）
2. **必须搜索多个新闻源**（财联社、Bloomberg、南华早报等）
3. **不能轻易写"无重大公开报道"** - 10%以上的涨跌必有原因！
4. 如果实在找不到直接新闻，也要分析：是否受大盘影响？是否有行业消息？

"""
        
        return f"""你是港股分析师，专注于科技股分析。

**任务：搜索昨日新闻**
{enhanced_search_notice}
⚠️ 时间范围（严格执行，非常重要）：
- 新闻收录范围：仅限 {news_date_str}（昨天）的新闻
- ❌ 严禁收录超出此范围的旧闻！
- ❌ 必须是{news_end_date.year}年的新闻，去年的新闻绝对不能收录！

待分析数据：

【大盘指数】
{indices_text}

【科技股】
{tech_text}

🔍 搜索关键词：

**科技股**：
- 腾讯/Tencent：微信、QQ、腾讯云、腾讯游戏、视频号、企业微信
- 阿里巴巴/Alibaba：淘宝、天猫、阿里云、支付宝、菜鸟、1688
- 网易/NetEase：网易游戏、网易云音乐、有道、网易邮箱
- 小米/Xiaomi：手机、IoT、小米汽车、MIUI、红米
- 百度/Baidu：搜索、百度云、文心一言、Apollo自动驾驶
- MiniMax：AI大模型、智能助手、海螺AI、星野
- 智谱AI/Zhipu：AI大模型、GLM、ChatGLM、清言

📰 新闻来源（优先使用）：
- 顶级国际财经媒体：Bloomberg、Reuters、Financial Times、南华早报（SCMP）
- 权威中文财经媒体：财联社、第一财经、证券时报、香港经济日报
- 官方渠道：公司官网、港交所公告（HKEX）、公司新闻稿

⚠️ 所有英文新闻必须翻译成中文输出

📋 **输出格式（严格遵守，使用两列表格，直接输出，不要开头介绍语）**：

| 公司 | 新闻内容 |
|:----:|:-----|
| 🌐 大盘 | (来源1) 新闻1；(来源2) 新闻2 |
| 💻 腾讯 | (来源1) 公司新闻 |
| 💻 阿里 | (来源1) 公司新闻 |
...（其他科技股）

⚠️ **必须遵守的规则**：

1. **🚨无新闻不输出**：如果某公司昨日无新闻，直接跳过该行
2. **时效性**：昨日新闻仅限 {news_date_str}
3. **两列表格格式**：左列公司名，右列该公司新闻（**最多2条**，用分号分隔）
4. **🚨新闻数量**：每个公司**最多2条新闻**，每条必须标明来源，格式：(来源) 新闻内容
5. **字数限制**：每条新闻≤40字，总输出不超过1000字
6. **完整性**：大盘 + 全部{tech_count}只科技股（无新闻的跳过）"""
    
    def _build_hk_game_prompt(
        self, indices_text, game_text,
        news_date_str, news_end_date,
        game_count,
        large_change_stocks: List[str] = None
    ) -> str:
        """构建港股游戏股分析 prompt（不含大盘综述）"""
        # 生成加强搜索提示
        enhanced_search_notice = ""
        if large_change_stocks:
            enhanced_search_notice = f"""
🔥🔥🔥 **特别重要：加强搜索提醒** 🔥🔥🔥

以下股票涨跌幅超过10%，必须进行加强搜索：
{chr(10).join([f"- **{name}**" for name in large_change_stocks])}

⚠️ 对于这些大幅波动的股票：
1. **必须多次尝试不同关键词搜索**（公司名、游戏名、工作室名）
2. **必须搜索多个新闻源**（财联社、GameLook、Bloomberg等）
3. **不能轻易写"无重大公开报道"** - 10%以上的涨跌必有原因！
4. 如果实在找不到直接新闻，也要分析：是否受大盘影响？是否有行业消息？

"""
        
        return f"""你是港股分析师，专注于游戏股分析。

**任务：搜索昨日新闻**
{enhanced_search_notice}
⚠️ 时间范围（严格执行，非常重要）：
- 新闻收录范围：仅限 {news_date_str}（昨天）的新闻
- ❌ 严禁收录超出此范围的旧闻！
- ❌ 必须是{news_end_date.year}年的新闻，去年的新闻绝对不能收录！

大盘背景（仅供参考，不需要输出大盘综述）：
{indices_text}

待分析数据：

【游戏股】
{game_text}

🔍 搜索关键词：

**游戏股**：
- 中手游：仙剑奇侠传、轩辕剑、传奇世界、新射雕群侠传
- 心动公司：TapTap、香肠派对、火炬之光、派对之星
- 哔哩哔哩/B站：视频平台、游戏发行、直播、电商
- 创梦天地：手游发行、IP运营
- IGG：王国纪元、Lords Mobile

📰 新闻来源（优先使用）：
- 顶级国际财经媒体：Bloomberg、Reuters、南华早报（SCMP）
- 权威中文财经媒体：财联社、第一财经、证券时报
- 垂直游戏媒体：GameLook、游戏葡萄
- 官方渠道：公司官网、港交所公告（HKEX）、公司新闻稿

⚠️ 所有英文新闻必须翻译成中文输出

📋 **输出格式（严格遵守，使用两列表格，直接输出，不要开头介绍语）**：

| 公司 | 新闻内容 |
|:----:|:-----|
| 🎮 中手游 | (来源) 公司/游戏新闻 |
| 🎮 心动 | (来源) 公司/游戏新闻 |
...（其他游戏股）

⚠️ **必须遵守的规则**：

1. **🚨无新闻不输出**：如果某公司昨日无新闻，直接跳过该行
2. **时效性**：昨日新闻仅限 {news_date_str}
3. **两列表格格式**：左列公司名，右列该公司所有新闻（多条用分号分隔）
4. **新闻数量**：每个公司最多2条新闻，合并在一行
5. **字数限制**：每行新闻内容≤80字，总输出不超过500字
6. **完整性**：全部{game_count}只游戏股（无新闻的跳过），不需要大盘综述"""
    
    # ============================================================
    # 强化搜索相关方法
    # ============================================================
    
    def _should_skip_enhanced_search_for_market(self, analysis: str, changes: List[StockChange]) -> bool:
        """
        判断是否应该跳过强化搜索
        
        条件：大盘（KOSPI）涨跌超过10% 且 大盘综述有实质性内容
        
        Args:
            analysis: 完整的分析文本
            changes: 股票变化列表（用于检查是否有大盘指数）
            
        Returns:
            True: 应该跳过强化搜索（大盘行情导致的波动）
            False: 应该执行强化搜索
        """
        import re
        
        # 先检查大盘是否涨跌超过10%
        # 从分析文本中提取大盘综述的涨跌幅
        market_section_match = re.search(
            r'### 【大盘综述】.*?(?=### 【|$)', 
            analysis, 
            re.DOTALL
        )
        
        if not market_section_match:
            return False
        
        market_section = market_section_match.group(0)
        
        # 检查大盘综述中是否有超过10%的涨跌描述
        # 匹配如 "涨10.5%" 或 "跌12.3%" 的模式
        large_market_change = re.search(r'[涨跌]\s*(\d+\.?\d*)%', market_section)
        if large_market_change:
            change_val = float(large_market_change.group(1))
            if change_val >= 10:
                self.logger.info(f"📊 检测到大盘涨跌幅 {change_val}% >= 10%")
                
                # 检查大盘综述的 3日内要闻 是否有实质内容
                if "无重大公开报道" in market_section or "无重大" in market_section:
                    self.logger.info(f"📊 但大盘综述无实质内容，不跳过强化搜索")
                    return False
                
                # 检查是否有新闻内容（日期和来源）
                news_content_match = re.search(r'\(\d+/\d+\s+[^)]+\)\s*\S+', market_section)
                if news_content_match:
                    self.logger.info(f"📊 大盘综述有实质内容，跳过个股强化搜索")
                    return True
        
        return False
    
    def _check_stock_has_news(self, analysis: str, stock_name: str) -> bool:
        """
        检查特定股票的分析结果是否有新闻
        
        Args:
            analysis: 完整的分析文本
            stock_name: 股票名称
            
        Returns:
            True: 有新闻内容
            False: 无新闻（未找到该股票行或标记为无新闻）
        """
        import re
        
        # 检测是否是新的两列表格格式
        is_two_col_table = "| 公司 |" in analysis or "| 公司 | 新闻内容 |" in analysis or "|:----:|:-----|" in analysis
        is_single_col_table = "| 📰 新闻内容 |" in analysis
        has_table_rows = "| 🎮" in analysis or "| 🌐" in analysis or "| 🏛️" in analysis or "| 💻" in analysis
        
        if is_two_col_table or has_table_rows:
            # 两列表格格式：查找包含股票名的行
            stock_name_short = stock_name.split()[0] if stock_name else ""
            
            for line in analysis.split('\n'):
                if stock_name_short in line and '|' in line:
                    # 新格式中，AI 不输出无新闻的行
                    # 如果找到该股票的行，说明有新闻
                    # 检查是否有实质内容（来源）
                    if re.search(r'\([^)]+\)\s*\S+', line):
                        return True
            
            # 未找到该股票的行 = 没有新闻
            self.logger.info(f"📭 {stock_name} 在表格中无对应行（无新闻）")
            return False
        
        # 旧格式：提取该股票的分析部分
        # 支持多种匹配模式：完整名称或部分名称
        patterns = [
            rf'### 【{re.escape(stock_name)}】.*?(?=### 【|$)',
            rf'### 【[^】]*{re.escape(stock_name.split()[0])}[^】]*】.*?(?=### 【|$)'  # 匹配包含股票名第一个词的标题
        ]
        
        stock_section = None
        for pattern in patterns:
            match = re.search(pattern, analysis, re.DOTALL)
            if match:
                stock_section = match.group(0)
                break
        
        if not stock_section:
            self.logger.warning(f"未找到 {stock_name} 的分析部分")
            return False
        
        # 检查是否包含"无重大公开报道"（支持新旧格式）
        if "无重大公开报道" in stock_section or "无新闻" in stock_section:
            return False
        
        # 检查是否有实质内容（支持新格式：• (来源) 内容 或 旧格式：(M/D 来源) 内容）
        # 新格式：• (来源) 新闻内容
        new_format_match = re.search(r'•\s*\([^)]+\)\s*\S+', stock_section)
        # 旧格式：(M/D 来源) 新闻内容
        old_format_match = re.search(r'\(\d+/\d+\s+[^)]+\)\s*\S+', stock_section)
        
        return new_format_match is not None or old_format_match is not None
    
    def _enhanced_search_for_stock(
        self, 
        stock_name: str, 
        change_percent: float,
        prev_trading_date: Optional[datetime] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        对单只股票进行强化搜索
        
        Args:
            stock_name: 股票名称
            change_percent: 涨跌幅
            prev_trading_date: 上一交易日
            max_retries: 最大重试次数
            
        Returns:
            成功时返回新的分析内容，失败时返回 None
        """
        # 计算新闻时间范围：昨日
        news_end_date = datetime.now() - timedelta(days=1)
        news_date_str = news_end_date.strftime("%Y年%m月%d日")
        
        if prev_trading_date:
            analysis_date_str = prev_trading_date.strftime("%Y年%m月%d日")
        else:
            analysis_date_str = "上一交易日"
        
        direction = "涨" if change_percent > 0 else "跌"
        
        # 根据股票名称生成不同的搜索关键词
        if "Shift Up" in stock_name or "시프트업" in stock_name:
            search_keywords = """
🔍 **必须尝试的搜索关键词**（请逐一尝试，至少尝试5个）：

1. 公司名搜索：
   - "Shift Up" news
   - "ShiftUp" stock
   - "시프트업" (韩文)
   - "시프트업 주가" (韩文：Shift Up 股价)
   - "시프트업 뉴스" (韩文：Shift Up 新闻)

2. 游戏相关搜索：
   - "NIKKE" news 2026
   - "胜利女神妮姬" 更新
   - "NIKKE collaboration" / "NIKKE 联动"
   - "Stellar Blade" news
   - "剑星" 销量

3. 财务相关搜索：
   - "Shift Up earnings"
   - "Shift Up revenue"
   - "시프트업 실적" (韩文：业绩)

📰 推荐新闻源：
- 韩国：Inven、4Gamer、韩联社、매일경제、한국경제
- 国际：Bloomberg Asia、IGN、GameSpot、Reuters
- 游戏：GamesIndustry.biz、Pocket Gamer"""
        else:
            # 其他股票的通用搜索关键词
            search_keywords = f"""
🔍 **必须尝试的搜索关键词**：

1. 公司名搜索：
   - "{stock_name}" news
   - "{stock_name}" stock price
   - "{stock_name}" 최근 뉴스 (韩文：最近新闻)

2. 相关搜索：
   - "{stock_name}" earnings
   - "{stock_name}" 업데이트 (韩文：更新)
   - "{stock_name}" 게임 (韩文：游戏)

📰 推荐新闻源：
- 韩国：Inven、韩联社、매일경제、한국경제
- 国际：Bloomberg Asia、Reuters"""

        prompt = f"""你是韩国游戏股票分析师，专门搜索 {stock_name} 的新闻。

🔥🔥🔥 **紧急任务** 🔥🔥🔥

{stock_name} 昨日{direction}{abs(change_percent):.2f}%，这是重大波动！必须找出原因！

⚠️ 搜索时间范围：昨日 {news_date_str}
- 股价分析日期：{analysis_date_str}
{search_keywords}

📋 **输出格式**（严格遵守）：

### 【{stock_name}】

| 类型 | 内容 |
|:----:|:-----|
| 昨日要闻 | (来源) 新闻内容（如有多条可用分号分隔）（≤150字） |
| 昨日分析 | {direction}{abs(change_percent):.2f}%，分析原因（≤100字） |

⚠️ **重要规则**：
1. 如果搜索到新闻，必须注明日期和来源
2. 如果真的搜索不到任何新闻，分析是否受大盘/板块影响
3. 不能轻易说"无新闻"——大幅涨跌必有原因！
4. 如果是游戏活动、联动、更新等导致的，也要写出来"""

        for attempt in range(max_retries):
            try:
                self.logger.info(f"🔥 {stock_name} 强化搜索 (尝试 {attempt + 1}/{max_retries})...")
                
                if self.provider == "qwen":
                    result = self._call_qwen_api(prompt, attempt, max_retries, timeout=120)
                else:
                    result = self._call_gemini_api(prompt, attempt, max_retries, timeout=120)
                
                if result and stock_name.split()[0] in result:  # 检查结果中是否包含股票名
                    # 检查是否真的找到了新闻
                    if "无重大公开报道" not in result and "无新闻" not in result:
                        self.logger.info(f"✅ {stock_name} 强化搜索成功找到新闻！")
                        return result
                    elif "无重大公开报道" in result and attempt < max_retries - 1:
                        self.logger.info(f"⚠️ {stock_name} 仍未找到新闻，再次尝试...")
                        time.sleep(3)
                        continue
                    else:
                        # 最后一次尝试，即使没找到也返回结果
                        return result
                        
                time.sleep(3)
                
            except Exception as e:
                self.logger.warning(f"{stock_name} 强化搜索异常: {e}")
                time.sleep(3)
        
        return None
    
    def _replace_stock_analysis(self, analysis: str, stock_name: str, new_content: str) -> str:
        """
        替换分析中特定股票的内容
        
        Args:
            analysis: 完整的分析文本
            stock_name: 股票名称
            new_content: 新的分析内容
            
        Returns:
            替换后的分析文本
        """
        import re
        
        # 找到该股票的分析部分
        # 支持多种匹配模式
        patterns = [
            rf'(### 【{re.escape(stock_name)}】.*?)(?=### 【|$)',
            rf'(### 【[^】]*{re.escape(stock_name.split()[0])}[^】]*】.*?)(?=### 【|$)'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, analysis, re.DOTALL)
            if match:
                # 从新内容中提取该股票的部分
                new_patterns = [
                    rf'### 【{re.escape(stock_name)}】.*?(?=### 【|$)',
                    rf'### 【[^】]*{re.escape(stock_name.split()[0])}[^】]*】.*?(?=### 【|$)'
                ]
                
                for new_pattern in new_patterns:
                    new_section_match = re.search(new_pattern, new_content, re.DOTALL)
                    if new_section_match:
                        new_section = new_section_match.group(0).strip()
                        # 替换
                        result = re.sub(pattern, new_section + '\n\n', analysis, flags=re.DOTALL)
                        return result
        
        return analysis
    
    def _check_market_has_news(self, analysis: str) -> bool:
        """
        检查大盘分析是否有新闻
        
        Args:
            analysis: 完整的分析文本
            
        Returns:
            True: 有新闻内容
            False: 无新闻
        """
        import re
        
        # 查找大盘相关的行
        for line in analysis.split('\n'):
            if '大盘' in line or '🌐' in line:
                # 检查是否有实质内容（来源）
                if re.search(r'\([^)]+\)\s*\S+', line):
                    return True
        
        # 检查是否有"大盘综述"部分
        market_section_match = re.search(
            r'### 【大盘综述】.*?(?=### 【|$)', 
            analysis, 
            re.DOTALL
        )
        
        if market_section_match:
            market_section = market_section_match.group(0)
            if "无重大公开报道" in market_section or "无重大" in market_section:
                return False
            # 检查是否有新闻内容
            if re.search(r'\(\d+/\d+\s+[^)]+\)\s*\S+', market_section):
                return True
        
        return False
    
    def _enhanced_search_for_market(
        self, 
        market: str,
        indices: List[MarketIndex] = None,
        prev_trading_date: Optional[datetime] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        对大盘进行强化搜索
        
        Args:
            market: 市场类型 (kr/us/hk)
            indices: 大盘指数列表（可选）
            prev_trading_date: 上一交易日
            max_retries: 最大重试次数
            
        Returns:
            成功时返回新的大盘分析内容，失败时返回 None
        """
        # 计算新闻时间范围：昨日
        news_end_date = datetime.now() - timedelta(days=1)
        news_date_str = news_end_date.strftime("%Y年%m月%d日")
        
        if prev_trading_date:
            analysis_date_str = prev_trading_date.strftime("%Y年%m月%d日")
        else:
            analysis_date_str = "上一交易日"
        
        # 根据市场构建不同的 prompt
        if market == MARKET_KR:
            market_name = "韩股"
            search_keywords = """
🔍 **必须尝试的搜索关键词**：

1. 指数相关：
   - "KOSPI" news
   - "KOSDAQ" index
   - "韩国股市" 新闻
   - "코스피" (韩文：KOSPI)
   - "코스닥" (韩文：KOSDAQ)

2. 宏观经济：
   - "韩国央行" 利率
   - "韩元" 汇率
   - "한국은행" (韩文：韩国央行)
   - "South Korea economy"

3. 地缘政治：
   - "韩国" 政治
   - "朝鲜" 新闻

📰 推荐新闻源：韩联社、Bloomberg、Reuters、매일경제、한국경제"""
        elif market == MARKET_US:
            market_name = "美股"
            search_keywords = """
🔍 **必须尝试的搜索关键词**：

1. 指数相关：
   - "S&P 500" news
   - "Nasdaq" index
   - "Dow Jones" news
   - "美股" 大盘

2. 宏观经济：
   - "Fed" interest rate
   - "美联储" 决议
   - "US economy" news
   - "非农" 数据

3. 市场情绪：
   - "Wall Street" news
   - "美股" 走势

📰 推荐新闻源：Bloomberg、Reuters、CNBC、Wall Street Journal"""
        else:  # MARKET_HK
            market_name = "港股"
            search_keywords = """
🔍 **必须尝试的搜索关键词**：

1. 指数相关：
   - "恒生指数" 新闻
   - "Hang Seng" index
   - "恒生科技" 指数
   - "港股通" 资金

2. 宏观经济：
   - "香港" 经济
   - "中国" 经济数据
   - "人民币" 汇率
   - "港币" 汇率

3. 政策相关：
   - "中国政策" 港股
   - "南向资金" 流入

📰 推荐新闻源：财联社、南华早报、Bloomberg、香港经济日报"""

        # 构建指数文本
        indices_text = ""
        if indices:
            indices_text = "\n".join([
                f"- {idx.name}: {'涨' if idx.is_rising else '跌'}{abs(idx.change_percent):.2f}%"
                for idx in indices
            ])

        prompt = f"""你是{market_name}分析师，专门搜索大盘新闻。

🔥🔥🔥 **紧急任务** 🔥🔥🔥

{market_name}大盘昨日出现波动，必须找出影响大盘的重要新闻！

{f"**大盘指数表现**：{chr(10)}{indices_text}" if indices_text else ""}

⚠️ 搜索时间范围：昨日 {news_date_str}
- 股价分析日期：{analysis_date_str}
{search_keywords}

📋 **输出格式**（两列表格，严格遵守）：

| 公司 | 新闻内容 |
|:----:|:-----|
| 🌐 大盘 | (来源1) 新闻1；(来源2) 新闻2 |

⚠️ **重要规则**：
1. 如果搜索到新闻，必须注明来源
2. 每条新闻≤40字，最多2条，用分号分隔
3. 不能轻易说"无新闻"——大盘波动必有原因！
4. 关注宏观经济、央行政策、地缘政治等"""

        for attempt in range(max_retries):
            try:
                self.logger.info(f"🔥 {market_name}大盘强化搜索 (尝试 {attempt + 1}/{max_retries})...")
                
                if self.provider == "qwen":
                    result = self._call_qwen_api(prompt, attempt, max_retries, timeout=120)
                else:
                    result = self._call_gemini_api(prompt, attempt, max_retries, timeout=120)
                
                if result and "大盘" in result:
                    # 检查是否真的找到了新闻
                    if "无重大公开报道" not in result and "无新闻" not in result:
                        self.logger.info(f"✅ {market_name}大盘强化搜索成功找到新闻！")
                        return result
                    elif attempt < max_retries - 1:
                        self.logger.info(f"⚠️ {market_name}大盘仍未找到新闻，再次尝试...")
                        time.sleep(3)
                        continue
                    else:
                        return result
                        
                time.sleep(3)
                
            except Exception as e:
                self.logger.warning(f"{market_name}大盘强化搜索异常: {e}")
                time.sleep(3)
        
        return None
    
    def _replace_market_analysis(self, analysis: str, new_market_content: str) -> str:
        """
        替换分析中大盘的内容
        
        Args:
            analysis: 完整的分析文本
            new_market_content: 新的大盘分析内容
            
        Returns:
            替换后的分析文本
        """
        import re
        
        # 从新内容中提取大盘行
        new_market_line = None
        for line in new_market_content.split('\n'):
            if '大盘' in line or '🌐' in line:
                if '|' in line and re.search(r'\([^)]+\)', line):
                    new_market_line = line
                    break
        
        if not new_market_line:
            return analysis
        
        # 在原分析中替换大盘行
        lines = analysis.split('\n')
        new_lines = []
        replaced = False
        
        for line in lines:
            if ('大盘' in line or '🌐' in line) and '|' in line and not replaced:
                new_lines.append(new_market_line)
                replaced = True
            else:
                new_lines.append(line)
        
        if replaced:
            return '\n'.join(new_lines)
        
        return analysis
    
    def _enhanced_search_for_stock_general(
        self, 
        stock_name: str, 
        change_percent: float,
        market: str,
        prev_trading_date: Optional[datetime] = None,
        max_retries: int = 3
    ) -> Optional[str]:
        """
        对单只股票进行强化搜索（通用版本，支持美股/港股）
        
        Args:
            stock_name: 股票名称
            change_percent: 涨跌幅
            market: 市场类型
            prev_trading_date: 上一交易日
            max_retries: 最大重试次数
            
        Returns:
            成功时返回新的分析内容（表格行格式），失败时返回 None
        """
        # 计算新闻时间范围：昨日
        news_end_date = datetime.now() - timedelta(days=1)
        news_date_str = news_end_date.strftime("%Y年%m月%d日")
        
        if prev_trading_date:
            analysis_date_str = prev_trading_date.strftime("%Y年%m月%d日")
        else:
            analysis_date_str = "上一交易日"
        
        direction = "涨" if change_percent > 0 else "跌"
        
        # 根据市场设置不同的新闻源
        if market == MARKET_US:
            market_name = "美股"
            news_sources = "Bloomberg、Reuters、CNBC、Wall Street Journal、The Verge、TechCrunch"
        else:  # MARKET_HK
            market_name = "港股"
            news_sources = "财联社、南华早报、Bloomberg、香港经济日报、第一财经"
        
        # 判断是科技股还是游戏股
        game_keywords = ['游戏', 'EA', 'Take-Two', 'Roblox', 'Unity', '中手游', '心动', '哔哩哔哩', 'B站', '创梦天地', 'IGG']
        is_game_stock = any(kw in stock_name for kw in game_keywords)
        
        if is_game_stock:
            emoji = "🎮"
            news_sources += "、IGN、GameSpot、GameLook"
        else:
            emoji = "💻"
        
        prompt = f"""你是{market_name}分析师，专门搜索 {stock_name} 的新闻。

🔥🔥🔥 **紧急任务** 🔥🔥🔥

{stock_name} 昨日{direction}{abs(change_percent):.2f}%，这是重大波动！必须找出原因！

⚠️ 搜索时间范围：昨日 {news_date_str}
- 股价分析日期：{analysis_date_str}

🔍 **必须尝试的搜索关键词**：

1. 公司名搜索：
   - "{stock_name}" news
   - "{stock_name}" stock price
   - "{stock_name}" 新闻

2. 相关搜索：
   - "{stock_name}" earnings
   - "{stock_name}" 业绩
   - "{stock_name}" 财报

📰 推荐新闻源：{news_sources}

📋 **输出格式**（两列表格行，严格遵守）：

| {emoji} {stock_name.split()[0]} | (来源1) 新闻1；(来源2) 新闻2 |

⚠️ **重要规则**：
1. 只输出一行表格数据，格式必须是 | emoji 公司名 | 新闻内容 |
2. 如果搜索到新闻，必须注明来源
3. 每条新闻≤40字，最多2条，用分号分隔
4. 不能轻易说"无新闻"——10%以上的涨跌必有原因！
5. 如果实在找不到直接新闻，分析是否受大盘/板块影响"""

        for attempt in range(max_retries):
            try:
                self.logger.info(f"🔥 {stock_name} 强化搜索 (尝试 {attempt + 1}/{max_retries})...")
                
                if self.provider == "qwen":
                    result = self._call_qwen_api(prompt, attempt, max_retries, timeout=120)
                else:
                    result = self._call_gemini_api(prompt, attempt, max_retries, timeout=120)
                
                if result:
                    # 检查是否真的找到了新闻
                    if "无重大公开报道" not in result and "无新闻" not in result:
                        self.logger.info(f"✅ {stock_name} 强化搜索成功找到新闻！")
                        return result
                    elif attempt < max_retries - 1:
                        self.logger.info(f"⚠️ {stock_name} 仍未找到新闻，再次尝试...")
                        time.sleep(3)
                        continue
                    else:
                        return result
                        
                time.sleep(3)
                
            except Exception as e:
                self.logger.warning(f"{stock_name} 强化搜索异常: {e}")
                time.sleep(3)
        
        return None
    
    def _replace_stock_analysis_table(self, analysis: str, stock_name: str, new_content: str) -> str:
        """
        替换分析表格中特定股票的行
        
        Args:
            analysis: 完整的分析文本
            stock_name: 股票名称
            new_content: 新的分析内容（包含表格行）
            
        Returns:
            替换后的分析文本
        """
        import re
        
        # 从新内容中提取该股票的表格行
        stock_name_short = stock_name.split()[0]
        new_line = None
        
        for line in new_content.split('\n'):
            if stock_name_short in line and '|' in line:
                if re.search(r'\([^)]+\)', line):  # 包含来源
                    new_line = line
                    break
        
        if not new_line:
            return analysis
        
        # 在原分析中替换该股票的行
        lines = analysis.split('\n')
        new_lines = []
        replaced = False
        
        for line in lines:
            if stock_name_short in line and '|' in line and not replaced:
                new_lines.append(new_line)
                replaced = True
            else:
                new_lines.append(line)
        
        if replaced:
            return '\n'.join(new_lines)
        
        # 如果原分析中没有该股票的行，则在适当位置添加
        # 找到表格的位置，在最后一个表格行后添加
        lines = analysis.split('\n')
        insert_index = -1
        
        for i, line in enumerate(lines):
            if '|' in line and ('🎮' in line or '💻' in line or '🌐' in line):
                insert_index = i
        
        if insert_index >= 0:
            lines.insert(insert_index + 1, new_line)
            return '\n'.join(lines)
        
        return analysis
    
    # ============================================================
    # 内容清理方法
    # ============================================================
    
    def _clean_ai_response(self, content: str) -> str:
        """
        清理 AI 返回内容中的内部标记
        
        移除：
        - @image:xxx.png 图片引用标记
        - [cite: xx, xx] 或 【cite: xx, xx】引用标记
        - [cite：xx，xx] 中文标点引用标记
        
        Args:
            content: AI 返回的原始内容
            
        Returns:
            清理后的内容
        """
        import re
        
        if not content:
            return content
        
        # 移除 @image:xxx.png 格式的图片引用
        content = re.sub(r'@image:\S+\.(?:png|jpg|jpeg|gif|webp)\s*', '', content, flags=re.IGNORECASE)
        
        # 移除 [cite: xx, xx] 格式的引用（包括中英文标点）
        content = re.sub(r'\[cite[：:]\s*[\d,，\s]+\]', '', content, flags=re.IGNORECASE)
        
        # 移除 【cite: xx, xx】格式的引用
        content = re.sub(r'【cite[：:]\s*[\d,，\s]+】', '', content, flags=re.IGNORECASE)
        
        # 移除可能残留的 [cite] 或 【cite】
        content = re.sub(r'\[cite\]', '', content, flags=re.IGNORECASE)
        content = re.sub(r'【cite】', '', content, flags=re.IGNORECASE)
        
        # 清理多余的空格（但保留换行）
        content = re.sub(r'[ \t]+', ' ', content)
        
        # 清理行末多余空格
        content = re.sub(r' +\n', '\n', content)
        
        # 清理多余的空行（3个以上变成2个）
        content = re.sub(r'\n{3,}', '\n\n', content)
        
        return content.strip()
    
    # ============================================================
    # API 调用方法
    # ============================================================
    
    def _call_api_with_retry(self, prompt: str, expected_count: int) -> str:
        """
        调用 API 并重试直到获取完整结果
        
        增强稳定性改进：
        - 超时递增机制
        - 更详细的错误日志
        - 连接错误等待重试
        - 配额/限流特殊处理
        """
        max_attempts = 5
        base_timeout = 90  # 初始超时时间
        
        for attempt in range(max_attempts):
            # 计算当前超时时间（每次重试增加 30 秒）
            current_timeout = min(base_timeout + attempt * 30, 180)
            
            try:
                self.logger.info(f"调用 AI API (尝试 {attempt + 1}/{max_attempts}, 超时 {current_timeout}s)...")
                
                if self.provider == "qwen":
                    analysis = self._call_qwen_api(prompt, attempt, max_attempts, timeout=current_timeout)
                else:
                    analysis = self._call_gemini_api(prompt, attempt, max_attempts, timeout=current_timeout)
                
                if analysis is None:
                    self.logger.warning(f"API 返回空结果，等待 3 秒后重试...")
                    time.sleep(3)
                    continue
                
                # 检测内容完整性
                # 新单列表格格式：检测 | 🎮 | 🌐 | 🏛️ | 💻 等 emoji 开头的行
                # 旧格式：【】标记数量检测
                is_two_col_table = "| 公司 |" in analysis or "| 公司 | 新闻内容 |" in analysis or "|:----:|:-----|" in analysis
                is_single_col_table = "| 📰 新闻内容 |" in analysis
                has_table_rows = "| 🎮" in analysis or "| 🌐" in analysis or "| 🏛️" in analysis or "| 💻" in analysis
                
                if is_two_col_table or has_table_rows:
                    # 两列表格格式：统计表格数据行数
                    import re
                    # 匹配所有以 | emoji 开头的数据行
                    table_rows = len(re.findall(r'\| [🎮🌐🏛️💻]', analysis))
                    self.logger.info(f"分析内容包含 {table_rows} 个表格行，长度: {len(analysis)} 字符")
                    
                    # 新格式下，AI 不输出无新闻的行，所以行数可能较少
                    # 只要有至少 1 行数据就认为成功（因为可能所有股票都没新闻）
                    if analysis and table_rows >= 1:
                        self.logger.info(f"✅ AI 分析完成，表格内容有效 ({table_rows} 行)")
                        return analysis
                    elif analysis and "无新闻" not in analysis and "无重大" not in analysis:
                        # 有内容但没有表格行，可能是格式问题
                        self.logger.warning(f"分析格式可能有问题 (只有 {table_rows} 行)，继续重试...")
                        time.sleep(2)
                        continue
                    elif analysis:
                        # 可能真的没有新闻
                        self.logger.info(f"✅ AI 分析完成（可能无新闻）")
                        return analysis
                else:
                    # 旧格式：【】标记数量
                    bracket_count = analysis.count("【")
                    self.logger.info(f"分析内容包含 {bracket_count} 个【】标记，长度: {len(analysis)} 字符")
                    
                    if analysis and bracket_count >= expected_count:
                        self.logger.info(f"✅ AI 分析完成，内容完整 ({bracket_count}/{expected_count})")
                        return analysis
                    elif analysis:
                        self.logger.warning(f"分析不完整 (只有 {bracket_count}/{expected_count} 条)，继续重试...")
                        time.sleep(2)
                        continue
                    else:
                        self.logger.warning("响应为空，继续重试...")
                        time.sleep(2)
                        continue
                    
            except requests.exceptions.Timeout:
                self.logger.warning(f"⏱️ 请求超时 ({current_timeout}s)，等待 5 秒后重试...")
                time.sleep(5)
                continue
            except requests.exceptions.ConnectionError as e:
                self.logger.warning(f"🔌 连接错误: {e}，等待 5 秒后重试...")
                time.sleep(5)
                continue
            except Exception as e:
                error_msg = str(e).lower()
                if "quota" in error_msg or "rate" in error_msg or "429" in error_msg:
                    self.logger.warning(f"⚠️ API 配额/限流问题: {e}，等待 10 秒后重试...")
                    time.sleep(10)
                else:
                    self.logger.warning(f"❌ 请求异常: {e}，等待 3 秒后重试...")
                    time.sleep(3)
                continue
        
        self.logger.error(f"❌ {max_attempts}次尝试均未获得完整分析")
        if self.market == MARKET_KR:
            return self._generate_fallback_analysis_kr([], f"{max_attempts}次尝试均未成功")
        else:
            return self._generate_fallback_analysis_us_hk([], [], f"{max_attempts}次尝试均未成功")
    
    def _call_qwen_api(self, prompt: str, attempt: int, max_attempts: int, timeout: int = 90) -> Optional[str]:
        """调用通义千问 API"""
        self.logger.info(f"调用通义千问 + 联网搜索 (尝试 {attempt + 1}/{max_attempts}, 超时 {timeout}s)...")
        
        url = f"{self.base_url}/chat/completions"
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": 4096,
            "enable_search": True
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        
        self.logger.info(f"API 状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "").strip()
                return self._clean_ai_response(content)
            return None
        else:
            error_text = response.text[:300]
            self.logger.warning(f"API 错误: {error_text}")
            if "quota" in error_text.lower() or response.status_code == 429:
                raise Exception("API 配额超限")
            return None
    
    def _call_gemini_api(self, prompt: str, attempt: int, max_attempts: int, timeout: int = 60) -> Optional[str]:
        """调用 Gemini API"""
        self.logger.info(f"调用 Gemini AI + Google Search (尝试 {attempt + 1}/{max_attempts}, 超时 {timeout}s)...")
        
        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096
            }
        }
        
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        
        self.logger.info(f"API 状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            content = "".join([p.get("text", "") for p in parts]).strip()
            return self._clean_ai_response(content)
        else:
            error_text = response.text[:300]
            self.logger.warning(f"API 错误: {error_text}")
            if "quota" in error_text.lower() or response.status_code == 429:
                raise Exception("API 配额超限")
            return None
    
    def _generate_fallback_analysis_kr(self, changes: List[StockChange], reason: str = "未知原因") -> str:
        """生成韩股备用分析"""
        lines = [f"⚠️ AI 分析服务暂时不可用（{reason}），以下为股票变化概况：", ""]
        
        rising = [c for c in changes if c.is_rising]
        falling = [c for c in changes if not c.is_rising]
        
        if rising:
            lines.append(f"📈 上涨股票（{len(rising)}只）：")
            for c in rising:
                lines.append(f"  - {c.stock.name}: +{c.change_percent:.2f}%")
            lines.append("")
        
        if falling:
            lines.append(f"📉 下跌股票（{len(falling)}只）：")
            for c in falling:
                lines.append(f"  - {c.stock.name}: {c.change_percent:.2f}%")
            lines.append("")
        
        lines.append("请关注相关公司的最新公告和行业新闻以了解具体原因。")
        
        return "\n".join(lines)
    
    def _generate_fallback_analysis_us_hk(
        self, 
        tech_changes: List[StockChange], 
        game_changes: List[StockChange],
        reason: str = "未知原因"
    ) -> str:
        """生成美股/港股备用分析"""
        lines = [f"⚠️ AI 分析服务暂时不可用（{reason}），以下为股票变化概况：", ""]
        
        if tech_changes:
            lines.append("📊 科技股：")
            for c in tech_changes:
                emoji = "📈" if c.is_rising else "📉"
                lines.append(f"  {emoji} {c.stock.name}: {c.formatted_change}")
            lines.append("")
        
        if game_changes:
            lines.append("🎮 游戏股：")
            for c in game_changes:
                emoji = "📈" if c.is_rising else "📉"
                lines.append(f"  {emoji} {c.stock.name}: {c.formatted_change}")
            lines.append("")
        
        lines.append("请关注相关公司的最新公告和行业新闻以了解具体原因。")
        
        return "\n".join(lines)
    
    def analyze_monthly_news_summary(
        self,
        year: int,
        month: int,
        stock_data: dict,
        market: str = None
    ) -> str:
        """
        生成月度新闻汇总（带重试机制）
        
        Args:
            year: 年份
            month: 月份
            stock_data: 股票数据 {symbol: {name, change_percent, ...}}
            market: 市场类型（可选，默认使用 self.market）
            
        Returns:
            AI生成的月度重大新闻汇总文本
        """
        if not self.api_key:
            return "⚠️ 新闻汇总服务暂不可用（未配置 API_KEY）"
        
        if not stock_data:
            return "没有股票数据可供分析。"
        
        target_market = market or self.market
        market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
        market_name = market_names.get(target_market, target_market)
        
        # 构建股票列表文本
        stocks_text = "\n".join([f"- {data['name']}" for symbol, data in stock_data.items()])
        
        # 根据市场构建不同的 prompt
        if target_market == MARKET_KR:
            source_hint = "韩联社、Bloomberg、Reuters、IGN、4Gamer、公司官方公告"
        elif target_market == MARKET_US:
            source_hint = "Bloomberg、Reuters、CNBC、The Verge、IGN、公司官方公告"
        else:  # MARKET_HK
            source_hint = "财联社、南华早报、Bloomberg、GameLook、公司官方公告"
        
        # 计算月份的起止日期
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        
        prompt = f"""你是{market_name}分析师，请汇总{year}年{month}月影响以下股票的重大新闻。

⚠️ **时间范围（严格执行，非常重要）**：
- 新闻时间范围：仅限 **{year}年{month}月1日 至 {year}年{month}月{last_day}日**
- ❌ 严禁收录{year}年{month}月以外的新闻！
- ❌ 必须是{year}年的新闻，其他年份的新闻绝对不能收录！

**股票列表（共{len(stock_data)}只，必须全部输出）**：
{stocks_text}

📋 **输出要求（严格遵守）**：

**📰 行业大事**
列出本月影响行业的2-3条重大新闻：
• 新闻1内容 (M/D 来源名)
• 新闻2内容 (M/D 来源名)

---

**🏢 公司动态**
**⚠️ 必须为上面列出的每只股票（共{len(stock_data)}只）都输出，不能遗漏任何一只！**
**⚠️ 每家公司精选1-2条最重要的新闻，整合成一段简洁描述！**
**🚨🚨🚨 每家公司的描述严格控制在100-150字以内，绝对不能超过200字！超过200字视为失败！🚨🚨🚨**

**🚨🚨🚨 字数硬性限制 🚨🚨🚨**
- 每家公司：严格 80-120 字，绝对不超过 150 字
- 输出前请自行计算每家公司字数，超过 150 字必须删减！
- 宁可精简也不要超字！新闻太多就只保留最重要的1条！

格式示例（严格字数控制）：
• **腾讯控股**: 2月初股价连续下跌，市值跌破5万亿港元，受美股下行及AI红包竞争影响。腾讯推出混元大模型新版本，马化腾强调AI是唯一值得大投入的领域。
• **网易**: 2月发布财报，全年营收1126亿元增7%，游戏业务921亿元增11%。AI原生管线大规模部署，效率提升超300%。

请按此格式输出每只股票的公司动态（共{len(stock_data)}只，每家100-150字，不超过200字）。
**⚠️ 禁止在输出中显示字数统计！不要写"(xx字)"、"约xx字"等字数标注！**

---

**🔥 市场热点**
• 本月投资者关注的热点话题（50字以内）

⚠️ **格式要求（非常重要）**：
1. 直接输出内容，不要开头介绍语
2. **必须使用上面的标题格式（📰 行业大事、🏢 公司动态、🔥 市场热点）**
3. **每个版块之间必须用 --- 分隔符隔开！**
4. **所有正文内容必须使用 • 符号作为项目符号开头**
5. **🚨 公司动态：每家公司100-150字，严禁超过200字！写完后请自行检查字数！**
6. 日期必须在{year}年{month}月内！
7. 优先引用权威来源：{source_hint}
8. **公司动态必须包含全部{len(stock_data)}只股票，不能遗漏！**
9. **禁止使用斜体（单星号包裹），只使用粗体（双星号包裹）**"""

        # 使用重试机制调用 API
        return self._call_api_extended_with_retry(
            prompt=prompt,
            max_tokens=6000,
            max_retries=3,
            initial_timeout=180,
            fallback_message="⚠️ 月度新闻汇总生成失败，已重试多次仍未成功。"
        )
    
    def _call_api_extended_with_retry(
        self,
        prompt: str,
        max_tokens: int = 6000,
        max_retries: int = 3,
        initial_timeout: int = 180,
        fallback_message: str = "⚠️ AI 分析生成失败，已重试多次仍未成功。"
    ) -> str:
        """
        带重试机制的 API 调用（用于月度汇总等长内容）
        
        Args:
            prompt: 提示词
            max_tokens: 最大输出 token
            max_retries: 最大重试次数
            initial_timeout: 初始超时时间（秒）
            fallback_message: 失败时的备用消息
            
        Returns:
            AI 生成的内容或失败提示
        """
        timeout = initial_timeout
        
        for attempt in range(max_retries):
            try:
                self.logger.info(f"📡 调用 AI API (尝试 {attempt + 1}/{max_retries}, 超时 {timeout}s)...")
                
                if self.provider == "qwen":
                    result = self._call_qwen_api_extended(prompt, max_tokens, timeout)
                else:
                    result = self._call_gemini_api_extended(prompt, max_tokens, timeout)
                
                if result and len(result.strip()) > 100:
                    self.logger.info(f"✅ API 调用成功，内容长度: {len(result)} 字符")
                    return result.strip()
                else:
                    self.logger.warning(f"⚠️ 返回内容过短或为空 (长度: {len(result) if result else 0})，重试...")
                    time.sleep(3)
                    
            except requests.exceptions.Timeout:
                self.logger.warning(f"⏱️ 请求超时 ({timeout}s)，增加超时时间后重试...")
                timeout = min(timeout + 60, 300)  # 每次重试增加 60 秒，最大 5 分钟
                time.sleep(5)
                
            except requests.exceptions.ConnectionError as e:
                self.logger.warning(f"🔌 连接错误: {e}，等待 5 秒后重试...")
                time.sleep(5)
                
            except Exception as e:
                error_msg = str(e).lower()
                if "quota" in error_msg or "rate" in error_msg or "429" in error_msg:
                    self.logger.warning(f"⚠️ 配额/限流问题: {e}，等待 15 秒后重试...")
                    time.sleep(15)
                else:
                    self.logger.error(f"❌ API 调用异常: {e}")
                    time.sleep(3)
        
        self.logger.error(f"❌ {max_retries} 次尝试均失败")
        return fallback_message
    
    def _call_qwen_api_extended(self, prompt: str, max_tokens: int = 6000, timeout: int = 120) -> Optional[str]:
        """调用通义千问 API（支持自定义 max_tokens 和 timeout）"""
        self.logger.info(f"调用通义千问 + 联网搜索 (max_tokens={max_tokens}, timeout={timeout}s)...")
        
        url = f"{self.base_url}/chat/completions"
        
        payload = {
            "model": self.model,
            "messages": [
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "enable_search": True
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        
        self.logger.info(f"API 状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            choices = result.get("choices", [])
            if choices:
                content = choices[0].get("message", {}).get("content", "").strip()
                return self._clean_ai_response(content)
            return None
        elif response.status_code == 429:
            raise Exception("API 配额超限或请求过频")
        else:
            error_text = response.text[:500]
            self.logger.warning(f"API 错误: {error_text}")
            return None
    
    def _call_gemini_api_extended(self, prompt: str, max_tokens: int = 6000, timeout: int = 120) -> Optional[str]:
        """调用 Gemini API（支持自定义 max_tokens 和 timeout）"""
        self.logger.info(f"调用 Gemini AI + Google Search (max_tokens={max_tokens}, timeout={timeout}s)...")
        
        url = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"
        
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": max_tokens
            }
        }
        
        response = requests.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=timeout)
        
        self.logger.info(f"API 状态码: {response.status_code}")
        
        if response.status_code == 200:
            result = response.json()
            parts = result.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            content = "".join([p.get("text", "") for p in parts]).strip()
            return self._clean_ai_response(content)
        elif response.status_code == 429:
            raise Exception("API 配额超限或请求过频")
        else:
            error_text = response.text[:500]
            self.logger.warning(f"API 错误: {error_text}")
            return None
    
    def analyze_monthly_report(
        self,
        year: int,
        month: int,
        stock_data: dict,
        index_data: dict = None,
        stock_type: str = 'all'
    ) -> str:
        """
        生成月度报告AI分析（带重试机制）
        
        Args:
            year: 年份
            month: 月份
            stock_data: 股票数据 {symbol: {name, change_percent, start_price, end_price}}
            index_data: 指数数据 {name, change_percent}（可选）
            stock_type: 股票类型 ('all'/'tech'/'game')
            
        Returns:
            AI分析文本
        """
        if not self.api_key:
            return "⚠️ AI 分析服务暂不可用（未配置 API_KEY）"
        
        if not stock_data:
            return "没有股票数据可供分析。"
        
        # 构建股票数据文本
        sorted_stocks = sorted(stock_data.items(), key=lambda x: x[1]['change_percent'], reverse=True)
        stocks_text = "\n".join([
            f"- {data['name']}: {'+' if data['change_percent'] >= 0 else ''}{data['change_percent']:.2f}%"
            for symbol, data in sorted_stocks
        ])
        
        # 计算平均涨跌幅
        avg_change = sum(d['change_percent'] for d in stock_data.values()) / len(stock_data)
        
        # 指数文本
        index_text = ""
        if index_data:
            idx_change = index_data['change_percent']
            index_text = f"大盘指数（{index_data['name']}）：{'+' if idx_change >= 0 else ''}{idx_change:.2f}%"
        
        # 根据市场设置不同的 prompt
        market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
        market_name = market_names.get(self.market, self.market)
        
        type_text = {'all': '股票', 'tech': '科技股', 'game': '游戏股'}.get(stock_type, '股票')
        
        # 计算月份的起止日期
        from calendar import monthrange
        last_day = monthrange(year, month)[1]
        
        prompt = f"""你是{market_name}分析师，请对{year}年{month}月的{type_text}表现进行简要总结分析。

⚠️ **时间范围（严格执行）**：
- 分析时间范围：仅限 **{year}年{month}月1日 至 {year}年{month}月{last_day}日**
- 后市展望中可以涉及下月预期

**📊 月度数据**：
{index_text}
股票平均涨跌幅：{'+' if avg_change >= 0 else ''}{avg_change:.2f}%

**📈 个股表现**：
{stocks_text}

📋 **输出要求（严格遵守）**：

**📌 月度总结**
• 简述本月整体市场环境和{type_text}板块表现，点评涨幅最高和跌幅最大的股票。（80字以内）

---

**📌 要点回顾**
列出本月影响{type_text}的2-3个关键事件或趋势：
• 要点1（一句话概括）
• 要点2（一句话概括）
• 要点3（一句话概括，可选）

---

**📌 后市展望**
• 简述下月可能的走势和关注点。（50字以内）

⚠️ **格式要求（非常重要）**：
1. 直接输出分析内容，不要开头介绍语
2. **必须使用上面的标题格式（📌 月度总结、📌 要点回顾、📌 后市展望）**
3. **每个版块之间必须用 --- 分隔符隔开！**
4. **所有正文内容必须使用 • 符号作为项目符号开头**
5. **禁止使用斜体（单星号包裹），只允许使用粗体（双星号包裹）**
6. 使用简洁的表达，总字数控制在300字以内
7. 不确定的内容标注（推测）"""

        # 使用重试机制调用 API
        return self._call_api_extended_with_retry(
            prompt=prompt,
            max_tokens=4096,
            max_retries=3,
            initial_timeout=120,
            fallback_message="⚠️ AI 月度分析生成失败，已重试多次仍未成功。"
        )
