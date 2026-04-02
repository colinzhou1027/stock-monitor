"""
企业微信通知服务
封装 Webhook 消息发送功能
支持韩股、美股、港股市场
"""

import base64
import hashlib
import time
import re
from datetime import datetime
from typing import List, Optional
import requests

from models.stock import StockChange, MarketIndex
from utils.logger import LoggerMixin
from config import MARKET_KR, MARKET_US, MARKET_HK, get_market_info


class NotifyService(LoggerMixin):
    """统一企业微信通知服务类 - 支持多市场"""
    
    def __init__(self, market: str, webhook_urls: List[str]):
        """
        初始化通知服务
        
        Args:
            market: 市场类型 (kr/us/hk)
            webhook_urls: 企业微信群机器人 Webhook URL 列表
        """
        self.market = market
        self.webhook_urls = webhook_urls
        self.market_info = get_market_info(market)
        self.currency = self.market_info["currency"]
        
        self.logger.info(f"{self.market_info['name']}通知服务初始化完成，配置了 {len(webhook_urls)} 个群聊")
    
    def send_markdown(self, content: str, mention_all: bool = False) -> bool:
        """发送 Markdown 格式消息到所有群"""
        if mention_all:
            content = f"<@all>\n\n{content}"
        
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": content}
        }
        
        return self._send_to_all(payload)
    
    def send_markdown_v2(self, content: str) -> bool:
        """发送 Markdown V2 格式消息到所有群（支持表格，但不支持@和颜色）"""
        payload = {
            "msgtype": "markdown_v2",
            "markdown_v2": {
                "content": content,
                "attachments": []
            }
        }
        
        return self._send_to_all(payload)
    
    def send_text(self, content: str, mentioned_list: Optional[List[str]] = None) -> bool:
        """发送文本消息到所有群"""
        payload = {
            "msgtype": "text",
            "text": {"content": content}
        }
        
        if mentioned_list:
            payload["text"]["mentioned_list"] = mentioned_list
        
        return self._send_to_all(payload)
    
    def _send_to_all(self, payload: dict) -> bool:
        """发送消息到所有配置的群"""
        if not self.webhook_urls:
            self.logger.error("未配置任何 Webhook URL")
            return False
        
        success_count = 0
        for i, webhook_url in enumerate(self.webhook_urls, 1):
            self.logger.info(f"正在发送消息到群 {i}...")
            if self._send_request_to_url(payload, webhook_url):
                success_count += 1
                self.logger.info(f"群 {i} 发送成功")
            else:
                self.logger.error(f"群 {i} 发送失败")
        
        self.logger.info(f"消息发送完成：{success_count}/{len(self.webhook_urls)} 个群成功")
        return success_count > 0
    
    def _send_request_to_url(self, payload: dict, webhook_url: str) -> bool:
        """发送请求到指定的企业微信 Webhook URL"""
        try:
            response = requests.post(webhook_url, json=payload, timeout=10)
            result = response.json()
            
            if result.get("errcode") == 0:
                return True
            else:
                self.logger.error(f"消息发送失败: {result}")
                return False
                
        except requests.exceptions.Timeout:
            self.logger.error("消息发送超时")
            return False
        except requests.exceptions.RequestException as e:
            self.logger.error(f"消息发送异常: {str(e)}")
            return False
    
    def send_daily_report(
        self,
        # 韩股参数
        all_changes: List[StockChange] = None,
        market_index: Optional[MarketIndex] = None,
        # 美股/港股参数
        tech_changes: List[StockChange] = None,
        game_changes: List[StockChange] = None,
        indices: Optional[List[MarketIndex]] = None,
        # 通用参数
        analysis: str = "",
        threshold: float = 10.0,
        holidays: Optional[List[datetime]] = None
    ) -> bool:
        """
        发送每日报告
        
        Args:
            all_changes: 所有股票变化（韩股使用）
            market_index: 大盘指数（韩股使用）
            tech_changes: 科技股变化（美股/港股使用）
            game_changes: 游戏股变化（美股/港股使用）
            indices: 大盘指数列表（美股/港股使用）
            analysis: AI分析
            threshold: 阈值
            holidays: 休市日期列表
        """
        if self.market == MARKET_KR:
            return self._send_kr_daily_report(
                all_changes or [], analysis, threshold, market_index, holidays
            )
        else:
            return self._send_us_hk_daily_report(
                tech_changes or [], game_changes or [], analysis, threshold, indices, holidays
            )
    
    def _send_kr_daily_report(
        self,
        all_changes: List[StockChange],
        analysis: str,
        threshold: float,
        market_index: Optional[MarketIndex] = None,
        holidays: Optional[List[datetime]] = None
    ) -> bool:
        """发送韩股每日报告"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        # 检查 Shift Up 是否超过阈值
        shiftup_changes = [c for c in all_changes if "Shift Up" in c.stock.name]
        has_alert = any(abs(c.change_percent) >= threshold for c in shiftup_changes)
        mention_all = has_alert
        
        title = "🚨 韩股游戏股票日报" if has_alert else "📊 韩股游戏股票日报"
        
        lines = [
            f"## {title}",
            f"> 📅 数据日期：{now}",
            f"> ⚠️ 预警规则：Shift Up 涨跌超过{threshold:.0f}%时预警",
        ]
        lines.append("")
        
        # 休市提醒
        if holidays:
            holiday_strs = [h.strftime("%-m月%-d日") for h in holidays]
            lines.append("### 🔴 股市休市提醒")
            lines.append(f"{', '.join(holiday_strs)}为韩国法定假日，股市休市。")
            lines.append("")
            lines.append("> 📌 以下为最近交易日数据，供参考：")
            lines.append("")
        
        # 大盘变化
        if market_index:
            emoji = "🟢" if market_index.is_rising else "🔴"
            lines.append("### 📈 大盘指数")
            lines.append(f"**{market_index.name}** {emoji}")
            lines.append(f"> {market_index.prev_prev_date_str} → {market_index.prev_date_str}：{market_index.formatted_change}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 股票变化 - 使用表格格式
        lines.append("### 📊 个股变化")
        lines.append("")
        
        sorted_changes = sorted(all_changes, key=lambda x: x.change_percent, reverse=True)
        
        # 获取日期字符串（从第一个股票获取）
        if sorted_changes:
            prev_prev_date = sorted_changes[0].prev_prev_date_str
            prev_date = sorted_changes[0].prev_date_str
            lines.append(f"| 股票 | {prev_prev_date} | {prev_date} | 涨跌 |")
            lines.append("|:-----|-----:|-----:|-----:|")
            
            for c in sorted_changes:
                emoji = "🟢" if c.is_rising else "🔴"
                change_str = f"{'+' if c.change_percent >= 0 else ''}{c.change_percent:.2f}%"
                lines.append(f"| {c.stock.name} {emoji} | {self.currency}{int(c.prev_prev_close):,} | {self.currency}{int(c.prev_close):,} | {change_str} |")
        
        lines.append("")
        
        content1 = "\n".join(lines)
        # 使用 markdown_v2 发送表格
        result1 = self.send_markdown_v2(content1)
        
        time.sleep(1)
        
        # 传递涨跌幅数据，用于判断大涨跌股票
        market_indices = [market_index] if market_index else None
        result2 = self._send_analysis_in_chunks(analysis, all_changes, market_indices)
        
        return result1 and result2
    
    def _send_us_hk_daily_report(
        self,
        tech_changes: List[StockChange],
        game_changes: List[StockChange],
        analysis: str,
        threshold: float,
        indices: Optional[List[MarketIndex]] = None,
        holidays: Optional[List[datetime]] = None
    ) -> bool:
        """发送美股/港股每日报告"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        is_us = self.market == MARKET_US
        market_name = "美股" if is_us else "港股"
        country_name = "美国" if is_us else "香港"
        
        title = f"📊 {market_name}游戏股票日报"
        
        lines = [
            f"## {title}",
            f"> 📅 数据日期：{now}",
        ]
        lines.append("")
        
        # 休市提醒
        if holidays:
            holiday_strs = [h.strftime("%-m月%-d日") for h in holidays]
            lines.append("### 🔴 股市休市提醒")
            lines.append(f"{', '.join(holiday_strs)}为{country_name}法定假日，股市休市。")
            lines.append("")
            lines.append("> 📌 以下为最近交易日数据，供参考：")
            lines.append("")
        
        # 大盘指数
        if indices:
            lines.append("### 📈 大盘指数")
            for idx in indices:
                emoji = "🟢" if idx.is_rising else "🔴"
                lines.append(f"**{idx.name}** {emoji}")
                lines.append(f"> {idx.prev_prev_date_str} → {idx.prev_date_str}：{idx.formatted_change}")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 科技股变化 - 使用表格格式
        if tech_changes:
            lines.append("### 💻 科技股")
            lines.append("")
            
            sorted_tech = sorted(tech_changes, key=lambda x: x.change_percent, reverse=True)
            
            # 获取日期字符串
            if sorted_tech:
                prev_prev_date = sorted_tech[0].prev_prev_date_str
                prev_date = sorted_tech[0].prev_date_str
                lines.append(f"| 股票 | {prev_prev_date} | {prev_date} | 涨跌 |")
                lines.append("|:-----|-----:|-----:|-----:|")
                
                for c in sorted_tech:
                    emoji = "🟢" if c.is_rising else "🔴"
                    change_str = f"{'+' if c.change_percent >= 0 else ''}{c.change_percent:.2f}%"
                    lines.append(f"| {c.stock.name} {emoji} | {self.currency}{c.prev_prev_close:,.2f} | {self.currency}{c.prev_close:,.2f} | {change_str} |")
            
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        # 游戏股变化 - 使用表格格式
        if game_changes:
            lines.append("### 🎮 游戏股")
            lines.append("")
            
            sorted_game = sorted(game_changes, key=lambda x: x.change_percent, reverse=True)
            
            # 获取日期字符串
            if sorted_game:
                prev_prev_date = sorted_game[0].prev_prev_date_str
                prev_date = sorted_game[0].prev_date_str
                lines.append(f"| 股票 | {prev_prev_date} | {prev_date} | 涨跌 |")
                lines.append("|:-----|-----:|-----:|-----:|")
                
                for c in sorted_game:
                    emoji = "🟢" if c.is_rising else "🔴"
                    change_str = f"{'+' if c.change_percent >= 0 else ''}{c.change_percent:.2f}%"
                    lines.append(f"| {c.stock.name} {emoji} | {self.currency}{c.prev_prev_close:,.2f} | {self.currency}{c.prev_close:,.2f} | {change_str} |")
            
            lines.append("")
        
        content1 = "\n".join(lines)
        # 使用 markdown_v2 发送表格
        result1 = self.send_markdown_v2(content1)
        
        time.sleep(1)
        
        # 合并所有股票变化，传递涨跌幅数据
        all_stock_changes = tech_changes + game_changes
        result2 = self._send_analysis_in_chunks(analysis, all_stock_changes, indices)
        
        return result1 and result2
    
    def _filter_no_news_companies(
        self, 
        analysis: str,
        stock_changes: Optional[List[StockChange]] = None,
        market_indices: Optional[List[MarketIndex]] = None
    ) -> str:
        """
        过滤掉无新闻的行（新表格格式）
        保留大盘、财阀动态，过滤无新闻的个股行
        
        特殊规则：
        1. 涨跌超过10%的股票必须保留
        2. 大盘和财阀动态必须保留
        
        Args:
            analysis: 完整的AI分析文本
            stock_changes: 股票涨跌幅数据
            market_indices: 大盘指数数据
            
        Returns:
            过滤后的分析文本
        """
        # 构建股票名称到涨跌幅的映射
        change_map = {}
        large_change_stocks = set()  # 涨跌超过10%的股票名
        if stock_changes:
            for c in stock_changes:
                change_map[c.stock.name] = c.change_percent
                if abs(c.change_percent) >= 10:
                    large_change_stocks.add(c.stock.name)
                    self.logger.info(f"🔥 检测到大幅波动: {c.stock.name} ({c.change_percent:+.2f}%)")
        
        # 检查大盘是否有大幅波动
        large_index_change = False
        if market_indices:
            for idx in market_indices:
                if abs(idx.change_percent) >= 5:  # 大盘5%以上算大波动
                    large_index_change = True
                    self.logger.info(f"📊 大盘大幅波动: {idx.name} ({idx.change_percent:+.2f}%)")
        
        # 检查是否是新的两列表格格式（包含 "| 公司 |" 或 "|:----:|:-----" 等）
        is_two_col_table = "| 公司 |" in analysis or "| 公司 | 新闻内容 |" in analysis or "|:----:|:-----|" in analysis
        # 旧的单列表格格式
        is_single_col_table = "| 📰 新闻内容 |" in analysis or "| 📰 " in analysis
        # 旧的双列表格格式（分类 | 新闻内容）
        is_old_double_col_table = "| 分类 |" in analysis
        
        if is_two_col_table:
            # 新两列表格格式：AI 已经不输出无新闻的行，所以不需要过滤
            # 但仍需检查空表格的情况
            lines = analysis.split('\n')
            data_rows = [l for l in lines if l.startswith('|') and '公司' not in l and ':----' not in l and '新闻内容' not in l]
            
            if not data_rows:
                self.logger.info("📭 表格无数据行")
            else:
                self.logger.info(f"✅ 表格有 {len(data_rows)} 行新闻数据")
            
            return analysis
        
        if is_single_col_table:
            # 新单列表格格式：AI 已经不输出无新闻的行，所以不需要过滤
            # 但仍需检查空表格的情况
            lines = analysis.split('\n')
            data_rows = [l for l in lines if l.startswith('|') and '📰' not in l and ':----' not in l and '新闻内容' not in l]
            
            if not data_rows:
                self.logger.info("📭 表格无数据行")
            else:
                self.logger.info(f"✅ 表格有 {len(data_rows)} 行新闻数据")
            
            return analysis
        
        if is_old_double_col_table:
            # 旧双列表格格式：按行过滤
            lines = analysis.split('\n')
            filtered_lines = []
            removed_companies = []
            
            for line in lines:
                # 保留标题行、表头、分隔行
                if not line.startswith('|') or '分类' in line or ':----' in line or '新闻内容' in line:
                    filtered_lines.append(line)
                    continue
                
                # 检查是否是表格数据行
                if '|' in line:
                    # 大盘和财阀行必须保留
                    if '大盘' in line or '财阀' in line:
                        filtered_lines.append(line)
                        continue
                    
                    # 检查股票是否涨跌超过10%
                    is_large_change = any(name in line for name in large_change_stocks)
                    if is_large_change:
                        self.logger.info(f"🔥 保留大幅波动股票行")
                        filtered_lines.append(line)
                        continue
                    
                    # 检查是否包含"无重大公开报道"
                    if "无重大公开报道" in line or "无新闻" in line:
                        # 从行中提取公司名
                        parts = line.split('|')
                        if len(parts) >= 2:
                            company_part = parts[1].strip()
                            removed_companies.append(company_part)
                        self.logger.info(f"📭 过滤掉无新闻行: {line[:50]}...")
                        continue
                    
                    # 有新闻的行保留
                    filtered_lines.append(line)
                else:
                    filtered_lines.append(line)
            
            if removed_companies:
                self.logger.info(f"📭 共过滤 {len(removed_companies)} 行无新闻内容")
            
            return '\n'.join(filtered_lines)
        
        # 旧格式：按 "### 【" 分割
        blocks = re.split(r'(?=### 【[^】]+】)', analysis)
        filtered_blocks = []
        removed_companies = []
        has_large_change_stock = len(large_change_stocks) > 0
        
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            
            # 提取公司名
            title_match = re.search(r'### 【([^】]+)】', block)
            company_name = title_match.group(1) if title_match else ""
            
            # 大盘综述：如果有股票大涨跌或大盘有大波动，则必须保留
            if "大盘综述" in company_name or "大盘" in company_name:
                if has_large_change_stock or large_index_change:
                    self.logger.info(f"📊 保留大盘综述（存在大幅波动股票或大盘波动）")
                filtered_blocks.append(block)
                continue
            
            # 检查股票是否涨跌超过10%
            is_large_change = any(name in company_name for name in large_change_stocks)
            if is_large_change:
                self.logger.info(f"🔥 保留大幅波动股票: {company_name}")
                filtered_blocks.append(block)
                continue
            
            # 检查是否包含"近3日无重大公开报道"
            if "近3日无重大公开报道" in block or "无重大公开报道" in block:
                removed_companies.append(company_name)
                self.logger.info(f"📭 过滤掉无新闻的公司: {company_name}")
                continue
            
            # 有新闻的公司保留
            filtered_blocks.append(block)
        
        if removed_companies:
            self.logger.info(f"📭 共过滤 {len(removed_companies)} 家无新闻公司: {', '.join(removed_companies)}")
        
        return "\n\n".join(filtered_blocks)
    
    def _send_analysis_in_chunks(
        self, 
        analysis: str,
        stock_changes: Optional[List[StockChange]] = None,
        market_indices: Optional[List[MarketIndex]] = None
    ) -> bool:
        """将 AI 分析分割成多条消息发送（使用 markdown_v2 支持表格）"""
        # 如果没有 AI 分析，直接返回成功
        if not analysis:
            self.logger.info("无 AI 分析内容，跳过发送")
            return True
        
        MAX_BYTES = 4000  # 增加单条消息最大字节数，减少分割
        
        # 检测格式类型
        is_two_col_table = "| 公司 |" in analysis or "| 公司 | 新闻内容 |" in analysis or "|:----:|:-----|" in analysis
        is_single_col_table = "| 📰 新闻内容 |" in analysis or "| 📰 " in analysis
        is_old_double_col_table = "| 分类 |" in analysis
        is_old_format = "### 【" in analysis
        
        # 记录过滤前的数量
        if is_two_col_table:
            # 新两列表格格式：统计数据行数（排除表头和分隔行）
            original_count = len([l for l in analysis.split('\n') if l.startswith('|') and '公司' not in l and ':----' not in l and '新闻内容' not in l])
        elif is_single_col_table:
            # 单列表格格式：统计数据行数
            original_count = len([l for l in analysis.split('\n') if l.startswith('|') and '📰' not in l and ':----' not in l])
        elif is_double_col_table:
            original_count = len([l for l in analysis.split('\n') if l.startswith('|') and '分类' not in l and ':----' not in l])
        else:
            original_count = analysis.count("### 【")
        
        # 先过滤掉无新闻的公司（传递涨跌幅数据）
        analysis = self._filter_no_news_companies(analysis, stock_changes, market_indices)
        
        # 统计过滤后的数量
        if is_two_col_table:
            filtered_count = len([l for l in analysis.split('\n') if l.startswith('|') and '公司' not in l and ':----' not in l and '新闻内容' not in l])
        elif is_single_col_table:
            filtered_count = len([l for l in analysis.split('\n') if l.startswith('|') and '📰' not in l and ':----' not in l])
        elif is_double_col_table:
            filtered_count = len([l for l in analysis.split('\n') if l.startswith('|') and '分类' not in l and ':----' not in l])
        else:
            filtered_count = analysis.count("### 【")
        
        removed_count = original_count - filtered_count
        
        # 添加备注（新格式直接在最后添加）
        disclaimer = "\n\n> ⚠️ 由于AI联网搜索覆盖范围有限、API调用不稳定、响应时间限制等原因，新闻汇总可能有信息遗漏，如有需要请人工验证。"
        
        if is_two_col_table or is_single_col_table or is_old_double_col_table:
            # 表格格式：检查是否有数据行
            if filtered_count == 0:
                self.logger.info("过滤后无有效新闻内容")
                analysis = analysis + "\n\n> 📭 各股票均未获取到相关新闻信息，可能原因包括：AI联网搜索覆盖范围有限、API调用不稳定、响应时间限制，或近期确无重大公开披露事件。" + disclaimer
            else:
                # 有新闻数据，添加备注
                analysis = analysis + disclaimer
        else:
            # 旧格式
            if not analysis.strip() or filtered_count <= 1:
                self.logger.info("过滤后无有效新闻内容")
                if "大盘综述" in analysis:
                    if removed_count > 0 and filtered_count > 1:
                        analysis = analysis + "\n\n---\n\n> 📭 其余股票均未获取到相关新闻信息。" + disclaimer
                    else:
                        analysis = analysis + "\n\n---\n\n> 📭 各股票均未获取到相关新闻信息。" + disclaimer
            elif removed_count > 0:
                analysis = analysis + "\n\n---\n\n> 📭 其余股票均未获取到相关新闻信息。" + disclaimer
            else:
                analysis = analysis + disclaimer
        
        # 清理多余换行，统一格式
        analysis = re.sub(r'\n{3,}', '\n\n', analysis)  # 3个以上换行变成2个
        analysis = re.sub(r'---\s*\n{2,}', '---\n\n', analysis)  # "---"后保留合适的换行
        
        def get_utf8_len(text: str) -> int:
            return len(text.encode('utf-8'))
        
        header = "## 📰 昨日新闻汇总\n\n"
        
        self.logger.info(f"AI 分析内容: {len(analysis)} 字符, {get_utf8_len(analysis)} 字节")
        
        if get_utf8_len(header + analysis) <= MAX_BYTES:
            self.logger.info("内容未超长，直接发送（使用 markdown_v2）")
            return self.send_markdown_v2(header + analysis)
        
        self.logger.info("内容超长，开始分割...")
        
        # 根据格式选择分割方式
        if is_two_col_table or is_single_col_table or is_old_double_col_table:
            # 表格格式：不分割表格，作为整体发送
            # 如果太长，按行分割但保持表头
            lines = analysis.split('\n')
            table_header_lines = []
            data_lines = []
            footer_lines = []
            in_table = False
            passed_table = False
            
            for line in lines:
                if line.startswith('|'):
                    in_table = True
                    if '📰' in line or '分类' in line or ':----' in line:
                        table_header_lines.append(line)
                    else:
                        data_lines.append(line)
                elif in_table and not line.startswith('|'):
                    passed_table = True
                    footer_lines.append(line)
                elif passed_table:
                    footer_lines.append(line)
                else:
                    table_header_lines.append(line)
            
            table_header = '\n'.join(table_header_lines) + '\n'
            footer = '\n'.join(footer_lines)
            
            # 尝试整体发送
            full_content = header + table_header + '\n'.join(data_lines) + '\n' + footer
            if get_utf8_len(full_content) <= MAX_BYTES:
                return self.send_markdown_v2(full_content)
            
            # 需要分割数据行
            chunks = []
            current_data = []
            for line in data_lines:
                test_content = header + table_header + '\n'.join(current_data + [line]) + '\n' + footer
                if get_utf8_len(test_content) > MAX_BYTES and current_data:
                    # 发送当前块
                    chunk_content = header + table_header + '\n'.join(current_data)
                    chunks.append(chunk_content)
                    current_data = [line]
                    header = "## 📰 昨日新闻汇总（续）\n\n"
                else:
                    current_data.append(line)
            
            # 最后一块包含 footer
            if current_data:
                final_content = header + table_header + '\n'.join(current_data) + '\n' + footer
                chunks.append(final_content)
            
            self.logger.info(f"表格分割成 {len(chunks)} 个消息块")
        else:
            # 旧格式：按 "### 【" 分割
            stock_blocks = re.split(r'(?=### 【[^】]+】)', analysis)
            stock_blocks = [b.strip() for b in stock_blocks if b.strip()]
            
            self.logger.info(f"分割出 {len(stock_blocks)} 个分析块")
            
            chunks = []
            current_chunk = header
            
            for block in stock_blocks:
                block_with_newline = block + "\n\n"
                
                if get_utf8_len(block_with_newline) > MAX_BYTES - 200:
                    self.logger.warning(f"单块内容较长，尝试智能处理")
                    table_end = block.rfind('\n\n---')
                    if table_end > 0 and get_utf8_len(block[:table_end]) <= MAX_BYTES - 200:
                        block_with_newline = block[:table_end] + "\n\n"
                    else:
                        max_chars = (MAX_BYTES - 200) // 2
                        block_with_newline = block_with_newline[:max_chars] + "...\n\n"
                
                if get_utf8_len(current_chunk + block_with_newline) > MAX_BYTES:
                    if current_chunk.strip() != header.strip():
                        chunks.append(current_chunk.strip())
                    current_chunk = "## 📰 昨日新闻汇总（续）\n\n" + block_with_newline
                else:
                    current_chunk += block_with_newline
            
            if current_chunk.strip() and current_chunk.strip() not in [header.strip(), "## 📰 昨日新闻汇总（续）"]:
                chunks.append(current_chunk.strip())
        
        self.logger.info(f"最终分割成 {len(chunks)} 个消息块")
        
        all_success = True
        for i, chunk in enumerate(chunks):
            self.logger.info(f"发送 AI 分析第 {i+1}/{len(chunks)} 部分（使用 markdown_v2），{get_utf8_len(chunk)} 字节")
            success = self.send_markdown_v2(chunk)
            if not success:
                all_success = False
            if i < len(chunks) - 1:
                time.sleep(1)
        
        return all_success
    
    def send_error_notification(self, title: str, message: str) -> bool:
        """发送错误通知"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        content = f"""## {title}

> 时间：{now}

{message}
"""
        return self.send_markdown(content, mention_all=False)
    
    def _split_news_summary(self, news_summary: str, max_bytes: int = 3800) -> List[str]:
        """
        将新闻汇总按 --- 分隔符分段，确保每段不超过企业微信限制
        
        Args:
            news_summary: 完整的新闻汇总文本
            max_bytes: 每段最大字节数（留余量，默认3800）
            
        Returns:
            分段后的文本列表
        """
        # 按 --- 分隔符分割（这是新闻汇总中的版块分隔符）
        sections = news_summary.split('\n---\n')
        
        result = []
        current_part = ""
        
        for i, section in enumerate(sections):
            # 如果不是第一个section，需要加上分隔符
            section_with_sep = section if i == 0 else f"\n---\n{section}"
            
            # 检查添加这个section后是否会超过限制
            test_content = current_part + section_with_sep
            if len(test_content.encode('utf-8')) > max_bytes and current_part:
                # 当前部分已经有内容，且加上新section会超限，先保存当前部分
                result.append(current_part.strip())
                current_part = section  # 新section作为新部分的开始
            else:
                # 可以添加到当前部分
                current_part = test_content
        
        # 保存最后一部分
        if current_part.strip():
            result.append(current_part.strip())
        
        # 如果只有一部分但仍然超长，需要进一步分割（按段落）
        final_result = []
        for part in result:
            if len(part.encode('utf-8')) > max_bytes:
                # 按段落分割
                paragraphs = part.split('\n\n')
                sub_part = ""
                for para in paragraphs:
                    test = sub_part + ("\n\n" if sub_part else "") + para
                    if len(test.encode('utf-8')) > max_bytes and sub_part:
                        final_result.append(sub_part.strip())
                        sub_part = para
                    else:
                        sub_part = test
                if sub_part.strip():
                    final_result.append(sub_part.strip())
            else:
                final_result.append(part)
        
        return final_result if final_result else [news_summary]
    
    def send_image(self, image_data: bytes) -> bool:
        """发送图片到所有群"""
        image_base64 = base64.b64encode(image_data).decode('utf-8')
        image_md5 = hashlib.md5(image_data).hexdigest()
        
        payload = {
            "msgtype": "image",
            "image": {
                "base64": image_base64,
                "md5": image_md5
            }
        }
        
        self.logger.info(f"发送图片，大小: {len(image_data) / 1024:.1f} KB")
        return self._send_to_all(payload)
    
    def send_monthly_chart_report(
        self,
        all_changes: List[StockChange],
        threshold: float,
        market_index: Optional[MarketIndex] = None,
        holidays: Optional[List[datetime]] = None,
        monthly_chart_data: Optional[bytes] = None,
        monthly_chart_info: Optional[tuple] = None
    ) -> bool:
        """
        发送带月度趋势图的每日报告（韩股专用）
        """
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        shiftup_changes = [c for c in all_changes if "Shift Up" in c.stock.name]
        has_alert = any(abs(c.change_percent) >= threshold for c in shiftup_changes)
        
        title = "🚨 韩股游戏股票日报" if has_alert else "📊 韩股游戏股票日报"
        
        lines = [
            f"## {title}",
            f"> 📅 数据日期：{now}",
            f"> ⚠️ 预警规则：Shift Up 涨跌超过{threshold:.0f}%时预警",
        ]
        lines.append("")
        
        if holidays:
            holiday_strs = [h.strftime("%-m月%-d日") for h in holidays]
            lines.append("### 🔴 股市休市提醒")
            lines.append(f"{', '.join(holiday_strs)}为韩国法定假日，股市休市。")
            lines.append("")
            lines.append("> 📌 以下为最近交易日数据，供参考：")
            lines.append("")
        
        if market_index:
            emoji = "🟢" if market_index.is_rising else "🔴"
            color = "info" if market_index.is_rising else "warning"
            lines.append("### 📈 大盘指数")
            lines.append(f"**{market_index.name}**")
            lines.append(f"> {market_index.prev_prev_date_str}收盘：{market_index.prev_prev_close:,.2f}")
            lines.append(f"> {market_index.prev_date_str}收盘：{market_index.prev_close:,.2f}")
            lines.append(f"> {emoji} 变化：<font color=\"{color}\">{market_index.formatted_change}</font>")
            lines.append("")
        
        lines.append("---")
        lines.append("")
        
        lines.append("### 📊 个股变化")
        lines.append("")
        
        sorted_changes = sorted(all_changes, key=lambda x: x.change_percent, reverse=True)
        for c in sorted_changes:
            emoji = "🟢" if c.is_rising else "🔴"
            color = "info" if c.is_rising else "warning"
            
            lines.append(f"**{c.stock.name}** {emoji}")
            lines.append(f"> {c.prev_prev_date_str}：{self.currency}{int(c.prev_prev_close):,}")
            lines.append(f"> {c.prev_date_str}：{self.currency}{int(c.prev_close):,}")
            lines.append(f"> 涨跌：<font color=\"{color}\">{c.formatted_change}</font>")
            lines.append("")
        
        if monthly_chart_data and monthly_chart_info:
            month, year, change_percent = monthly_chart_info
            change_symbol = '+' if change_percent >= 0 else ''
            trend_emoji = '📈' if change_percent >= 0 else '📉'
            
            lines.append("---")
            lines.append("")
            lines.append(f"### {trend_emoji} 韩股{year}年{month}月游戏股票月报")
            lines.append(f"> 月度涨跌幅：**{change_symbol}{change_percent:.2f}%**")
            lines.append("")
        
        content = "\n".join(lines)
        result1 = self.send_markdown(content, mention_all=False)
        
        if monthly_chart_data:
            time.sleep(1)
            result_chart = self.send_image(monthly_chart_data)
            self.logger.info(f"月度趋势图发送: {'成功' if result_chart else '失败'}")
        
        return result1
    
    def send_monthly_report(
        self,
        year: int,
        month: int,
        monthly_chart_data: bytes,
        stock_data: dict,
        avg_change: float,
        stock_type: str = 'game',
        index_data: Optional[dict] = None,
        ai_analysis: Optional[str] = None,
        ai_news_summary: Optional[str] = None
    ) -> bool:
        """
        统一的月度报告发送方法（支持所有市场）
        分段发送以避免企业微信消息长度限制（4096字节）
        
        Args:
            year: 年份
            month: 月份
            monthly_chart_data: 月度趋势图图片数据
            stock_data: 股票数据字典 {symbol: {name, change_percent, ...}}
            avg_change: 平均涨跌幅
            stock_type: 股票类型 ('tech'=科技股, 'game'=游戏股)
            index_data: 大盘指数数据（可选）
            ai_analysis: AI 月度分析（可选）
            ai_news_summary: AI 新闻汇总（可选）
            
        Returns:
            是否成功
        """
        # 根据市场和股票类型确定标题
        market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
        market_name = market_names.get(self.market, self.market)
        type_name = "科技股" if stock_type == 'tech' else "游戏股"
        
        change_symbol = '+' if avg_change >= 0 else ''
        trend_emoji = '📈' if avg_change >= 0 else '📉'
        
        all_success = True
        
        # === 第一部分：标题 + 大盘指数 + 个股表现 ===
        lines = [
            f"## {trend_emoji} {market_name}{year}年{month}月{type_name}月报",
            "",
            "### 📊 大盘指数（月度）",
        ]
        
        # 添加大盘指数信息
        if index_data:
            idx_name = index_data.get('name', '')
            idx_change = index_data.get('change_percent', 0)
            idx_symbol = '+' if idx_change >= 0 else ''
            idx_emoji = '📈' if idx_change >= 0 else '📉'
            lines.append(f"> {idx_emoji} **{idx_name}**: {idx_symbol}{idx_change:.2f}%")
        
        lines.append(f"> 股票平均涨跌幅：**{change_symbol}{avg_change:.2f}%**")
        if stock_data:
            lines.append(f"> 股票数量：**{len(stock_data)}** 只")
        lines.append("")
        
        # 添加个股表现
        if stock_data:
            lines.append("### 📊 个股表现")
            sorted_stocks = sorted(stock_data.items(), key=lambda x: x[1]['change_percent'], reverse=True)
            for symbol, data in sorted_stocks:
                s_change = data['change_percent']
                s_symbol = '+' if s_change >= 0 else ''
                s_emoji = '🟢' if s_change >= 0 else '🔴'
                lines.append(f"> {s_emoji} {data['name']}: {s_symbol}{s_change:.2f}%")
        
        # 发送第一部分
        content1 = "\n".join(lines)
        self.logger.info(f"发送月报第1部分（基本信息），{len(content1.encode('utf-8'))} 字节")
        result1 = self.send_markdown(content1, mention_all=False)
        if not result1:
            self.logger.error("月报第1部分发送失败")
            all_success = False
        
        time.sleep(1)
        
        # === 第二部分：AI 新闻汇总（如果有） ===
        if ai_news_summary:
            # 企业微信 Markdown 限制 4096 字节，需要分段发送
            news_parts = self._split_news_summary(ai_news_summary)
            for i, part in enumerate(news_parts):
                if i == 0:
                    part_content = f"### 📰 月度新闻汇总\n\n{part}"
                else:
                    part_content = part
                self.logger.info(f"发送月报第2部分（新闻汇总-{i+1}/{len(news_parts)}），{len(part_content.encode('utf-8'))} 字节")
                result_news = self.send_markdown(part_content, mention_all=False)
                if not result_news:
                    self.logger.error(f"月报第2部分（新闻汇总-{i+1}）发送失败")
                    all_success = False
                time.sleep(1)
        
        # === 第三部分：AI 月度分析（如果有）===
        # 注意：备注和趋势图提示直接附在后市展望后面，不单独发送
        if ai_analysis:
            # 在后市展望后面添加备注和趋势图提示
            disclaimer = "\n\n> ⚠️ 由于AI联网搜索覆盖范围有限、API调用不稳定、响应时间限制等原因，新闻汇总与对应分析可能有信息遗漏，如有需要需人工验证。"
            chart_intro = "\n\n📈 以下为月度股价走势图："
            analysis_content = f"### 📝 月度分析\n\n{ai_analysis}{disclaimer}{chart_intro}"
            self.logger.info(f"发送月报第3部分（月度分析+备注+趋势图提示），{len(analysis_content.encode('utf-8'))} 字节")
            result_analysis = self.send_markdown(analysis_content, mention_all=False)
            if not result_analysis:
                self.logger.error("月报第3部分（月度分析）发送失败")
                all_success = False
            time.sleep(1)
        else:
            # 如果没有 AI 分析，只发送备注和趋势图提示
            disclaimer_with_chart = "> ⚠️ 由于AI联网搜索覆盖范围有限、API调用不稳定、响应时间限制等原因，新闻汇总与对应分析可能有信息遗漏，如有需要需人工验证。\n\n📈 以下为月度股价走势图："
            self.logger.info("发送月报备注+趋势图提示")
            result_disclaimer = self.send_markdown(disclaimer_with_chart, mention_all=False)
            if not result_disclaimer:
                self.logger.error("月报备注发送失败")
                all_success = False
            time.sleep(1)
        
        # === 第四部分：趋势图图片 ===
        
        result_image = self.send_image(monthly_chart_data)
        self.logger.info(f"{market_name}{type_name}月度趋势图发送: {'成功' if result_image else '失败'}")
        if not result_image:
            all_success = False
        
        return all_success
    
    # 保留旧方法名作为别名，保持向后兼容
    def send_us_hk_monthly_chart_report(self, year: int, month: int, stock_type: str,
                                         monthly_chart_data: bytes, avg_change: float,
                                         index_data: Optional[dict] = None,
                                         stock_data: Optional[dict] = None,
                                         ai_analysis: Optional[str] = None,
                                         ai_news_summary: Optional[str] = None) -> bool:
        """发送美股/港股月度报告（向后兼容别名）"""
        return self.send_monthly_report(year, month, monthly_chart_data, stock_data or {},
                                        avg_change, stock_type, index_data, ai_analysis, ai_news_summary)
    
    def send_kr_monthly_report_v2(self, year: int, month: int, monthly_chart_data: bytes,
                                   stock_data: dict, avg_change: float,
                                   index_data: Optional[dict] = None,
                                   ai_analysis: Optional[str] = None,
                                   ai_news_summary: Optional[str] = None) -> bool:
        """发送韩股月度报告（向后兼容别名）"""
        return self.send_monthly_report(year, month, monthly_chart_data, stock_data,
                                        avg_change, 'game', index_data, ai_analysis, ai_news_summary)
    
    def send_shiftup_alert(
        self,
        shiftup_change: 'StockChange',
        threshold: float,
        webpage_url: str = ""
    ) -> bool:
        """
        发送 Shift Up 异常涨跌推送
        仅当 Shift Up 涨跌幅超过阈值时调用
        
        Args:
            shiftup_change: Shift Up 股票的涨跌数据
            threshold: 涨跌阈值（百分比）
            webpage_url: 网页详情链接
            
        Returns:
            是否成功
        """
        if abs(shiftup_change.change_percent) < threshold:
            self.logger.info(f"Shift Up 涨跌幅 {shiftup_change.change_percent:.2f}% 未超过阈值 {threshold}%，不推送")
            return True
        
        # 判断涨跌
        is_up = shiftup_change.change_percent >= 0
        emoji = "🚀" if is_up else "📉"
        action = "大涨" if is_up else "大跌"
        color = "info" if is_up else "warning"
        
        change_str = f"{'+' if is_up else ''}{shiftup_change.change_percent:.2f}%"
        
        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        
        lines = [
            f"## {emoji} Shift Up {action}预警",
            "",
            f"> 📅 {now}",
            "",
            f"**Shift Up** 股价{action} <font color=\"{color}\">{change_str}</font>",
            "",
            f"- {shiftup_change.prev_prev_date_str}：{self.currency}{int(shiftup_change.prev_prev_close):,}",
            f"- {shiftup_change.prev_date_str}：{self.currency}{int(shiftup_change.prev_close):,}",
        ]
        
        if webpage_url:
            lines.append("")
            lines.append(f"📊 [查看详情]({webpage_url}kr.html)")
        
        content = "\n".join(lines)
        
        self.logger.info(f"发送 Shift Up {action}预警: {change_str}")
        return self.send_markdown(content, mention_all=True)
    
    def should_send_shiftup_alert(
        self,
        all_changes: List[StockChange],
        threshold: float = 10.0
    ) -> tuple:
        """
        检查是否需要发送 Shift Up 异常推送
        
        Args:
            all_changes: 所有股票变化
            threshold: 涨跌阈值（百分比）
            
        Returns:
            (是否需要推送, Shift Up 的 StockChange 对象或 None)
        """
        for change in all_changes:
            if "Shift Up" in change.stock.name:
                if abs(change.change_percent) >= threshold:
                    self.logger.info(f"检测到 Shift Up 异常波动: {change.change_percent:+.2f}%")
                    return True, change
                else:
                    self.logger.info(f"Shift Up 涨跌幅正常: {change.change_percent:+.2f}%")
                    return False, change
        
        self.logger.warning("未找到 Shift Up 股票数据")
        return False, None
