#!/usr/bin/env python3
"""
推送日报和月报数据到网页
生成/更新网页数据文件，不发送群消息
使用 DuckDuckGo 网页搜索获取真实新闻（完全免费，无需 API）

使用方法:
    python scripts/push_web_reports.py              # 推送所有市场的昨日日报和上月月报
    python scripts/push_web_reports.py daily        # 只推送昨日日报
    python scripts/push_web_reports.py monthly      # 只推送上月月报
    python scripts/push_web_reports.py kr           # 只推送韩股
    python scripts/push_web_reports.py daily kr     # 只推送韩股昨日日报
    python scripts/push_web_reports.py monthly us   # 只推送美股上月月报
"""

import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta
from typing import List, Optional, Tuple

from config import (
    load_config, MARKET_KR, MARKET_US, MARKET_HK,
    get_stock_list, get_tech_list, get_game_list, get_market_info
)
from models.stock import StockInfo
from services.stock_service import StockService
from services.web_news_service import WebNewsService
from services.monthly_chart_service import MonthlyChartService
from services.web_generator_service import WebGeneratorService
from utils.git_utils import GitUtils


def create_stock_list(market: str) -> List[StockInfo]:
    """从配置创建股票信息列表"""
    stock_list = get_stock_list(market)
    return [
        StockInfo(symbol=symbol, name=name, market=market_type)
        for symbol, name, market_type in stock_list
    ]


def create_tech_game_lists(market: str) -> Tuple[List[StockInfo], List[StockInfo]]:
    """从配置创建科技股和游戏股列表（美股/港股）"""
    market_name = "NASDAQ" if market == MARKET_US else "HKEX"
    
    tech_list = get_tech_list(market)
    game_list = get_game_list(market)
    
    tech_stocks = [
        StockInfo(symbol=symbol, name=name, market=market_name)
        for symbol, name, _ in tech_list
    ]
    
    game_stocks = [
        StockInfo(symbol=symbol, name=name, market=market_name)
        for symbol, name, _ in game_list
    ]
    
    return tech_stocks, game_stocks


def push_daily_report(market: str, config) -> bool:
    """
    推送单个市场的昨日日报到网页
    
    Args:
        market: 市场类型 (kr/us/hk)
        config: 配置对象
        
    Returns:
        是否成功
    """
    market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
    market_name = market_names.get(market, market)
    
    print('=' * 60)
    print(f'开始推送 {market_name} 昨日日报到网页...')
    print('=' * 60)
    
    # 初始化服务
    stock_service = StockService(market=market, timezone=config.timezone)
    news_service = WebNewsService(market=market)
    web_generator = WebGeneratorService()
    
    print(f"✅ 使用 DuckDuckGo 网页搜索获取真实新闻（免费无限制）")
    
    try:
        # 获取休市信息
        has_holidays, yesterday, holidays = stock_service.get_holiday_info()
        
        if holidays:
            holiday_strs = [h.strftime("%Y-%m-%d") for h in holidays]
            print(f"检测到休市日: {', '.join(holiday_strs)}")
        
        # 获取股票数据
        if market == MARKET_KR:
            stocks = create_stock_list(market)
            print(f"监控股票数量: {len(stocks)}")
            
            # 获取大盘指数
            market_index = stock_service.get_market_index()
            if market_index:
                print(f"大盘 {market_index.name}: {market_index.formatted_change}")
            
            # 获取股票变化
            all_changes = stock_service.get_all_stock_changes(stocks)
            
            if not all_changes:
                print(f"⚠️ 未能获取任何股票数据")
                return False
            
            print(f"获取到 {len(all_changes)} 只股票数据")
            
            # 生成摘要分析
            prev_trading_date = all_changes[0].prev_date if all_changes else None
            if prev_trading_date:
                print(f"上一交易日: {prev_trading_date.strftime('%Y-%m-%d')}")
            
            print("搜索新闻并生成分析...")
            # 转换为字典列表
            stock_changes_list = [
                {"name": c.stock.name, "symbol": c.stock.symbol, "change_percent": c.change_percent}
                for c in all_changes
            ]
            analysis = news_service.get_daily_news_analysis(stock_changes_list)
            
            # 生成网页数据
            print("生成网页数据...")
            web_generator.generate_daily_data(
                market=market,
                stock_changes=all_changes,
                market_index=market_index,
                ai_analysis=analysis,
                holidays=holidays
            )
            
        else:
            # 美股/港股
            tech_stocks, game_stocks = create_tech_game_lists(market)
            print(f"监控科技股数量: {len(tech_stocks)}")
            print(f"监控游戏股数量: {len(game_stocks)}")
            
            # 获取大盘指数
            indices = stock_service.get_market_indices()
            if indices:
                for idx in indices:
                    print(f"指数 {idx.name}: {idx.formatted_change}")
            
            # 获取股票变化
            tech_changes = stock_service.get_all_stock_changes(tech_stocks)
            game_changes = stock_service.get_all_stock_changes(game_stocks)
            
            if not tech_changes and not game_changes:
                print(f"⚠️ 未能获取任何股票数据")
                return False
            
            print(f"获取到 {len(tech_changes)} 只科技股数据")
            print(f"获取到 {len(game_changes)} 只游戏股数据")
            
            # 生成摘要分析
            prev_trading_date = None
            if tech_changes:
                prev_trading_date = tech_changes[0].prev_date
            elif game_changes:
                prev_trading_date = game_changes[0].prev_date
            
            if prev_trading_date:
                print(f"上一交易日: {prev_trading_date.strftime('%Y-%m-%d')}")
            
            print("搜索新闻并生成分析...")
            all_changes = tech_changes + game_changes
            # 转换为字典列表
            stock_changes_list = [
                {"name": c.stock.name, "symbol": c.stock.symbol, "change_percent": c.change_percent}
                for c in all_changes
            ]
            analysis = news_service.get_daily_news_analysis(stock_changes_list)
            
            # 生成网页数据
            print("生成网页数据...")
            web_generator.generate_daily_data(
                market=market,
                stock_changes=all_changes,
                indices=indices,
                ai_analysis=analysis,
                holidays=holidays
            )
        
        # 更新元数据
        web_generator.update_meta()
        
        print(f"✅ {market_name}昨日日报推送成功!")
        print()
        return True
        
    except Exception as e:
        print(f"❌ {market_name}日报推送失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def push_monthly_report(market: str, config, year: int = None, month: int = None) -> bool:
    """
    推送单个市场的月报到网页
    
    Args:
        market: 市场类型 (kr/us/hk)
        config: 配置对象
        year: 年份（默认上个月）
        month: 月份（默认上个月）
        
    Returns:
        是否成功
    """
    market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
    market_name = market_names.get(market, market)
    stock_type = 'game' if market == MARKET_KR else 'tech'
    
    # 计算上个月的年月
    if year is None or month is None:
        today = datetime.now()
        if today.month == 1:
            year = today.year - 1
            month = 12
        else:
            year = today.year
            month = today.month - 1
    
    print('=' * 60)
    print(f'开始推送 {year}年{month}月 {market_name}月报到网页...')
    print('=' * 60)
    
    # 初始化服务
    news_service = WebNewsService(market=market)
    chart_service = MonthlyChartService()
    web_generator = WebGeneratorService()
    
    print(f"✅ 使用 DuckDuckGo 网页搜索获取真实新闻（免费无限制）")
    
    try:
        # 1. 生成图表和获取数据
        print("生成月度图表和获取数据...")
        chart_data, stock_data, avg_change, index_data = chart_service.generate_market_monthly_report(
            market=market,
            year=year,
            month=month,
            stock_type=stock_type
        )
        
        if not stock_data:
            print(f'❌ {market_name}数据获取失败')
            return False
        
        print(f'{market_name}数据获取成功，{len(stock_data)} 只股票')
        print(f'平均涨跌幅: {avg_change:+.2f}%')
        
        # 2. 生成新闻汇总
        print(f'正在搜索{market_name}月度新闻...')
        ai_news_summary = None
        try:
            ai_news_summary = news_service.get_monthly_news_summary(
                stock_data=stock_data,
                year=year,
                month=month
            )
            
            if ai_news_summary:
                print(f'新闻汇总生成成功，长度: {len(ai_news_summary)} 字符')
            else:
                print('新闻汇总生成失败')
        except Exception as e:
            print(f'新闻汇总生成异常: {e}')
        
        # 3. 月度分析（复用新闻汇总作为分析内容）
        ai_analysis = ai_news_summary
        
        # 4. 保存到网页
        print(f'保存{market_name}月报到网页...')
        web_generator.generate_monthly_data(
            market=market,
            year=year,
            month=month,
            stock_data=stock_data,
            avg_change=avg_change,
            index_data=index_data,
            ai_analysis=ai_analysis,
            ai_news_summary=ai_news_summary,
            chart_data=chart_data
        )
        
        # 更新元数据
        web_generator.update_meta()
        
        print(f'✅ {market_name}月报推送成功!')
        print()
        return True
        
    except Exception as e:
        print(f"❌ {market_name}月报推送失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def push_all_reports(config, report_type: str = 'all', markets: List[str] = None):
    """
    推送所有报告到网页
    
    Args:
        config: 配置对象
        report_type: 报告类型 ('all'/'daily'/'monthly')
        markets: 市场列表（默认所有市场）
    """
    if markets is None:
        markets = [MARKET_KR, MARKET_US, MARKET_HK]
    
    git_utils = GitUtils()
    
    daily_success = 0
    monthly_success = 0
    
    print()
    print('🚀 开始推送报告到网页...')
    print(f'📋 报告类型: {report_type}')
    print(f'🌍 市场: {", ".join(markets)}')
    print()
    
    # 推送日报
    if report_type in ['all', 'daily']:
        print('=' * 60)
        print('📊 推送昨日日报')
        print('=' * 60)
        print()
        
        for market in markets:
            if push_daily_report(market, config):
                daily_success += 1
    
    # 推送月报
    if report_type in ['all', 'monthly']:
        print('=' * 60)
        print('📈 推送上月月报')
        print('=' * 60)
        print()
        
        for market in markets:
            if push_monthly_report(market, config):
                monthly_success += 1
    
    # 提交到 Git
    print('=' * 60)
    print('📤 提交到 Git')
    print('=' * 60)
    
    now = datetime.now()
    git_utils.setup_git_config()
    
    commit_msg = f"[auto] 推送网页报告 {now.strftime('%Y-%m-%d %H:%M')}"
    git_utils.commit_and_push("docs/", commit_msg)
    
    # 打印总结
    print()
    print('=' * 60)
    print('📋 推送总结')
    print('=' * 60)
    
    if report_type in ['all', 'daily']:
        print(f'📊 日报: {daily_success}/{len(markets)} 个市场成功')
    if report_type in ['all', 'monthly']:
        print(f'📈 月报: {monthly_success}/{len(markets)} 个市场成功')
    
    # 打印网页链接
    web_generator = WebGeneratorService()
    webpage_url = web_generator.get_webpage_url()
    print()
    print(f'🔗 网页地址: {webpage_url}')
    print()


def main():
    """主函数"""
    # 解析命令行参数
    report_type = 'all'  # 默认所有类型
    markets = None  # 默认所有市场
    
    args = sys.argv[1:]
    
    for arg in args:
        arg_lower = arg.lower()
        if arg_lower == 'daily':
            report_type = 'daily'
        elif arg_lower == 'monthly':
            report_type = 'monthly'
        elif arg_lower == 'all':
            report_type = 'all'
        elif arg_lower == 'kr':
            markets = [MARKET_KR] if markets is None else markets + [MARKET_KR]
        elif arg_lower == 'us':
            markets = [MARKET_US] if markets is None else markets + [MARKET_US]
        elif arg_lower == 'hk':
            markets = [MARKET_HK] if markets is None else markets + [MARKET_HK]
        elif arg_lower in ['--help', '-h']:
            print(__doc__)
            sys.exit(0)
        else:
            print(f'未知参数: {arg}')
            print('使用方法: python scripts/push_web_reports.py [daily|monthly|all] [kr|us|hk]')
            sys.exit(1)
    
    # 加载配置
    config = load_config()
    
    # 执行推送
    push_all_reports(config, report_type, markets)


if __name__ == '__main__':
    main()
