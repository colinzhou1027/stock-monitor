"""
网页数据生成服务
负责将日报/月报数据导出为 JSON 格式，供静态网页使用
"""

import json
import os
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from models.stock import StockChange, MarketIndex
from utils.logger import LoggerMixin


class WebGeneratorService(LoggerMixin):
    """网页数据生成服务"""
    
    # 历史数据保留数量
    DAILY_HISTORY_LIMIT = 7   # 日报保留最近 7 天
    MONTHLY_HISTORY_LIMIT = 6  # 月报保留最近 6 个月
    
    def __init__(self, docs_dir: str = None):
        """
        初始化服务
        
        Args:
            docs_dir: docs 目录路径，默认为项目根目录下的 docs
        """
        if docs_dir is None:
            # 获取项目根目录
            current_dir = Path(__file__).parent.parent
            docs_dir = current_dir / "docs"
        
        self.docs_dir = Path(docs_dir)
        self.data_dir = self.docs_dir / "data"
        
        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.logger.info(f"WebGeneratorService 初始化完成，数据目录: {self.data_dir}")
    
    def _load_json(self, filename: str) -> Optional[Dict]:
        """加载 JSON 文件"""
        filepath = self.data_dir / filename
        if not filepath.exists():
            return None
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            self.logger.error(f"加载 {filename} 失败: {e}")
            return None
    
    def _save_json(self, filename: str, data: Dict) -> bool:
        """保存 JSON 文件"""
        filepath = self.data_dir / filename
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            self.logger.info(f"保存 {filename} 成功")
            return True
        except Exception as e:
            self.logger.error(f"保存 {filename} 失败: {e}")
            return False
    
    def _stock_change_to_dict(self, change: StockChange) -> Dict[str, Any]:
        """将 StockChange 转换为字典"""
        return {
            "symbol": change.stock.symbol,
            "name": change.stock.name,
            "prev_close": change.prev_close,
            "prev_prev_close": change.prev_prev_close,
            "change_percent": round(change.change_percent, 2),
            "prev_date": change.prev_date_str,
            "prev_prev_date": change.prev_prev_date_str,
        }
    
    def _market_index_to_dict(self, index: MarketIndex) -> Dict[str, Any]:
        """将 MarketIndex 转换为字典"""
        return {
            "name": index.name,
            "prev_close": index.prev_close,
            "prev_prev_close": index.prev_prev_close,
            "change_percent": round(index.change_percent, 2),
            "prev_date": index.prev_date_str,
            "prev_prev_date": index.prev_prev_date_str,
        }
    
    def generate_daily_data(
        self,
        market: str,
        stock_changes: List[StockChange],
        market_index: Optional[MarketIndex] = None,
        indices: Optional[List[MarketIndex]] = None,
        ai_analysis: Optional[str] = None,
        holidays: Optional[List[datetime]] = None
    ) -> bool:
        """
        生成日报 JSON 数据
        
        Args:
            market: 市场类型 (kr/us/hk)
            stock_changes: 股票变化列表
            market_index: 单一大盘指数（韩股）
            indices: 大盘指数列表（美股/港股）
            ai_analysis: AI 分析内容
            holidays: 休市日期列表
            
        Returns:
            是否成功
        """
        if not stock_changes:
            self.logger.warning(f"没有股票数据，跳过生成 {market} 日报")
            return False
        
        now = datetime.now()
        date_str = now.strftime("%Y-%m-%d")
        update_time = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # 构建当日数据
        daily_data = {
            "date": date_str,
            "update_time": update_time,
            "stocks": [self._stock_change_to_dict(c) for c in stock_changes],
        }
        
        # 添加大盘指数
        if market_index:
            daily_data["market_index"] = self._market_index_to_dict(market_index)
        
        if indices:
            daily_data["indices"] = [self._market_index_to_dict(idx) for idx in indices]
        
        # 添加 AI 分析
        if ai_analysis:
            daily_data["ai_analysis"] = ai_analysis
        
        # 添加休市日期
        if holidays:
            daily_data["holidays"] = [h.strftime("%Y-%m-%d") for h in holidays]
        
        # 加载现有数据
        filename = f"{market}_daily.json"
        existing = self._load_json(filename) or {"latest": None, "history": []}
        
        # 更新历史记录
        history = existing.get("history", [])
        
        # 如果最新数据的日期不同，则将其移入历史
        if existing.get("latest") and existing["latest"].get("date") != date_str:
            history.insert(0, existing["latest"])
        
        # 限制历史记录数量
        history = history[:self.DAILY_HISTORY_LIMIT]
        
        # 保存
        result = {
            "latest": daily_data,
            "history": history
        }
        
        success = self._save_json(filename, result)
        
        if success:
            self.logger.info(f"生成 {market} 日报数据成功: {len(stock_changes)} 只股票")
        
        return success
    
    def generate_monthly_data(
        self,
        market: str,
        year: int,
        month: int,
        stock_data: Dict[str, Dict],
        avg_change: float,
        index_data: Optional[Dict] = None,
        ai_analysis: Optional[str] = None,
        ai_news_summary: Optional[str] = None
    ) -> bool:
        """
        生成月报 JSON 数据
        
        Args:
            market: 市场类型 (kr/us/hk)
            year: 年份
            month: 月份
            stock_data: 股票数据字典 {symbol: {name, change_percent, ...}}
            avg_change: 平均涨跌幅
            index_data: 大盘指数数据
            ai_analysis: AI 月度分析
            ai_news_summary: AI 新闻汇总
            
        Returns:
            是否成功
        """
        now = datetime.now()
        update_time = now.strftime("%Y-%m-%d %H:%M:%S")
        
        # 构建月报数据
        monthly_data = {
            "year": year,
            "month": month,
            "update_time": update_time,
            "avg_change": round(avg_change, 2),
            "stock_data": stock_data,
        }
        
        if index_data:
            monthly_data["index_data"] = index_data
        
        if ai_analysis:
            monthly_data["ai_analysis"] = ai_analysis
        
        if ai_news_summary:
            monthly_data["ai_news_summary"] = ai_news_summary
        
        # 加载现有数据
        filename = f"{market}_monthly.json"
        existing = self._load_json(filename) or {"latest": None, "history": []}
        
        # 检查是否是新月份
        history = existing.get("history", [])
        latest = existing.get("latest")
        
        if latest:
            # 如果月份不同，移入历史
            if latest.get("year") != year or latest.get("month") != month:
                history.insert(0, latest)
        
        # 限制历史记录数量
        history = history[:self.MONTHLY_HISTORY_LIMIT]
        
        # 保存
        result = {
            "latest": monthly_data,
            "history": history
        }
        
        success = self._save_json(filename, result)
        
        if success:
            self.logger.info(f"生成 {market} {year}年{month}月 月报数据成功")
        
        return success
    
    def update_meta(self) -> bool:
        """
        更新元数据文件
        
        Returns:
            是否成功
        """
        now = datetime.now()
        
        meta = {
            "last_update": now.strftime("%Y-%m-%d %H:%M:%S"),
            "version": "1.0.0",
            "markets": ["kr", "us", "hk"]
        }
        
        return self._save_json("meta.json", meta)
    
    def get_webpage_url(self) -> str:
        """
        获取网页链接（GitHub Pages 地址）
        
        Returns:
            网页 URL
        """
        # 从环境变量获取，或使用默认值
        url = os.getenv("WEBPAGE_URL", "")
        if not url:
            # 尝试从 git remote 获取
            try:
                import subprocess
                result = subprocess.run(
                    ["git", "remote", "get-url", "origin"],
                    capture_output=True,
                    text=True,
                    cwd=self.docs_dir.parent
                )
                if result.returncode == 0:
                    remote_url = result.stdout.strip()
                    # 转换 git URL 到 GitHub Pages URL
                    # git@github.com:user/repo.git -> https://user.github.io/repo
                    # https://github.com/user/repo.git -> https://user.github.io/repo
                    if "github.com" in remote_url:
                        if remote_url.startswith("git@"):
                            # git@github.com:user/repo.git
                            parts = remote_url.replace("git@github.com:", "").replace(".git", "").split("/")
                        else:
                            # https://github.com/user/repo.git
                            parts = remote_url.replace("https://github.com/", "").replace(".git", "").split("/")
                        
                        if len(parts) >= 2:
                            user, repo = parts[0], parts[1]
                            url = f"https://{user}.github.io/{repo}/"
            except Exception as e:
                self.logger.warning(f"获取 git remote URL 失败: {e}")
        
        return url or "https://your-username.github.io/stock-monitor/"
