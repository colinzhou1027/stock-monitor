#!/usr/bin/env python3
"""
重新生成月报数据（含新闻汇总和月度分析）
仅更新网页数据，不发送群消息

使用方法:
    python scripts/regenerate_monthly.py           # 生成所有市场
    python scripts/regenerate_monthly.py kr        # 只生成韩股
    python scripts/regenerate_monthly.py us        # 只生成美股
    python scripts/regenerate_monthly.py hk        # 只生成港股
"""

import sys
import os

# 添加项目根目录到 path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from config import load_config, MARKET_KR, MARKET_US, MARKET_HK
from services.summary_service import SummaryService
from services.monthly_chart_service import MonthlyChartService
from services.web_generator_service import WebGeneratorService


def generate_monthly_report(market: str, year: int, month: int, config) -> bool:
    """生成单个市场的月报"""
    market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
    market_name = market_names.get(market, market)
    stock_type = 'game' if market == MARKET_KR else 'tech'
    
    print('=' * 60)
    print(f'开始生成 {year}年{month}月 {market_name}月报...')
    print('=' * 60)
    
    # 初始化服务
    summary_service = SummaryService(market=market)
    chart_service = MonthlyChartService()
    web_generator = WebGeneratorService()
    
    # 1. 生成图表和获取数据
    chart_data, stock_data, avg_change, index_data = chart_service.generate_market_monthly_report(
        market=market,
        year=year,
        month=month,
        stock_type=stock_type
    )
    
    if not stock_data:
        print(f'{market_name}数据获取失败')
        return False
    
    print(f'{market_name}数据获取成功，{len(stock_data)} 只股票')
    print(f'平均涨跌幅: {avg_change:+.2f}%')
    
    # 2. 生成新闻汇总
    print(f'正在生成{market_name}月度新闻汇总...')
    ai_news_summary = None
    try:
        ai_news_summary = summary_service.analyze_monthly_news_summary(
            year=year,
            month=month,
            stock_data=stock_data,
            market=market
        )
        
        if ai_news_summary:
            print(f'新闻汇总生成成功，长度: {len(ai_news_summary)} 字符')
        else:
            print(f'新闻汇总生成失败')
            ai_news_summary = None
    except Exception as e:
        print(f'新闻汇总生成异常: {e}')
        ai_news_summary = None
    
    # 3. 生成月度分析
    print(f'正在生成{market_name}月度分析...')
    ai_analysis = None
    try:
        ai_analysis = summary_service.analyze_monthly_report(
            year=year,
            month=month,
            stock_data=stock_data,
            index_data=index_data,
            stock_type=stock_type
        )
        
        if ai_analysis:
            print(f'月度分析生成成功，长度: {len(ai_analysis)} 字符')
        else:
            print(f'月度分析生成失败')
            ai_analysis = None
    except Exception as e:
        print(f'月度分析生成异常: {e}')
        ai_analysis = None
    
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
    print(f'{market_name}月报保存完成!')
    print()
    
    return True


def main():
    # 解析命令行参数
    markets_to_generate = []
    
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
        if arg == 'kr':
            markets_to_generate = [MARKET_KR]
        elif arg == 'us':
            markets_to_generate = [MARKET_US]
        elif arg == 'hk':
            markets_to_generate = [MARKET_HK]
        elif arg == 'all':
            markets_to_generate = [MARKET_KR, MARKET_US, MARKET_HK]
        else:
            print(f'未知参数: {arg}')
            print('使用方法: python scripts/regenerate_monthly.py [kr|us|hk|all]')
            sys.exit(1)
    else:
        markets_to_generate = [MARKET_KR, MARKET_US, MARKET_HK]
    
    # 加载配置
    config = load_config()
    
    # 生成月报（2026年3月）
    year = 2026
    month = 3
    
    success_count = 0
    for market in markets_to_generate:
        if generate_monthly_report(market, year, month, config):
            success_count += 1
    
    print('=' * 60)
    print(f'完成! 成功生成 {success_count}/{len(markets_to_generate)} 个市场的月报')
    print('=' * 60)


if __name__ == '__main__':
    main()
