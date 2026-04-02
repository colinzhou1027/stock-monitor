"""
股票监控机器人 - 主程序入口
支持韩股、美股、港股市场
适用于 GitHub Actions 定时运行

使用方法:
    python main.py             # 运行所有市场监控（默认）
    python main.py all         # 运行所有市场监控
    python main.py kr          # 运行韩股监控
    python main.py us          # 运行美股监控
    python main.py hk          # 运行港股监控
    python main.py --help      # 显示帮助
"""

import sys
import argparse
from datetime import datetime
from typing import List

from config import (
    load_config, validate_config, Config,
    MARKET_KR, MARKET_US, MARKET_HK,
    get_stock_list, get_tech_list, get_game_list, get_market_info
)
from models.stock import StockInfo
from services.stock_service import StockService
from services.ai_service import AIService
from services.notify_service import NotifyService
from services.monthly_chart_service import MonthlyChartService
from services.web_generator_service import WebGeneratorService
from utils.logger import setup_logger, get_logger
from utils.git_utils import GitUtils


logger = get_logger(__name__)


def generate_and_send_monthly_report(
    market: str,
    config: Config,
    ai_service: AIService,
    notify_service: NotifyService,
    monthly_chart_service: MonthlyChartService,
    stock_type: str = 'game',
    reuse_data: dict = None  # 复用已生成的数据（用于韩股专用 webhook）
) -> tuple:
    """
    统一的月报生成和发送逻辑
    
    Args:
        market: 市场类型 (kr/us/hk)
        config: 配置对象
        ai_service: AI 服务实例
        notify_service: 通知服务实例
        monthly_chart_service: 月报图表服务实例
        stock_type: 股票类型 ('tech'/'game')
        reuse_data: 复用的数据（避免重复生成 AI 分析）
        
    Returns:
        (是否成功发送, 生成的数据字典) - 数据字典包含 chart_year, chart_month, chart_data, stock_data, avg_change, index_data, ai_analysis, ai_news_summary
    """
    market_names = {MARKET_KR: "韩股", MARKET_US: "美股", MARKET_HK: "港股"}
    market_name = market_names.get(market, market)
    type_name = "科技股" if stock_type == 'tech' else "游戏股"
    
    # 如果有复用数据，直接使用
    if reuse_data:
        logger.info(f"复用已生成的月报数据发送到{market_name}专用 webhook")
        success = notify_service.send_monthly_report(
            year=reuse_data['chart_year'],
            month=reuse_data['chart_month'],
            monthly_chart_data=reuse_data['chart_data'],
            stock_data=reuse_data['stock_data'],
            avg_change=reuse_data['avg_change'],
            stock_type=stock_type,
            index_data=reuse_data['index_data'],
            ai_analysis=reuse_data['ai_analysis'],
            ai_news_summary=reuse_data['ai_news_summary']
        )
        if success:
            logger.info(f"{market_name}{type_name}月报（专用 webhook）发送成功")
        else:
            logger.error(f"{market_name}{type_name}月报（专用 webhook）发送失败")
        return (success, reuse_data)
    
    # 判断是否需要发送（传入 market 参数以区分不同市场）
    should_send, chart_month, chart_year = monthly_chart_service.should_send_monthly_chart(market=market)
    if not should_send:
        return (False, None)
    
    logger.info(f"需要发送 {chart_year}年{chart_month}月 {market_name}{type_name}月报")
    
    # 生成图表数据
    chart_data, stock_data, avg_change, index_data = monthly_chart_service.generate_market_monthly_report(
        market=market,
        year=chart_year,
        month=chart_month,
        stock_type=stock_type
    )
    
    if not chart_data:
        logger.error(f"{market_name}{type_name}月报图表生成失败")
        return (False, None)
    
    logger.info(f"生成 {chart_year}年{chart_month}月 月度趋势图，平均涨跌幅: {avg_change:+.2f}%")
    
    # 生成 AI 分析（如果配置了 API Key）
    ai_news_summary = None
    ai_analysis = None
    
    if config.ai_api_key:
        # 生成新闻汇总（带安全检查）
        logger.info(f"生成 {market_name}{type_name}月度新闻汇总...")
        try:
            ai_news_summary = ai_service.analyze_monthly_news_summary(
                year=chart_year,
                month=chart_month,
                stock_data=stock_data,
                market=market
            )
            # 安全检查：如果返回的是错误信息，设为 None
            if ai_news_summary and ai_news_summary.startswith("⚠️"):
                logger.warning(f"新闻汇总生成失败: {ai_news_summary[:80]}")
                ai_news_summary = None
        except Exception as e:
            logger.error(f"新闻汇总生成异常: {e}")
            ai_news_summary = None
        
        # 生成月度分析（带安全检查）
        logger.info(f"生成 {market_name}{type_name}月度分析...")
        try:
            ai_analysis = ai_service.analyze_monthly_report(
                year=chart_year,
                month=chart_month,
                stock_data=stock_data,
                index_data=index_data,
                stock_type=stock_type
            )
            # 安全检查：如果返回的是错误信息，设为 None
            if ai_analysis and ai_analysis.startswith("⚠️"):
                logger.warning(f"月度分析生成失败: {ai_analysis[:80]}")
                ai_analysis = None
        except Exception as e:
            logger.error(f"月度分析生成异常: {e}")
            ai_analysis = None
    
    # 发送月报
    success = notify_service.send_monthly_report(
        year=chart_year,
        month=chart_month,
        monthly_chart_data=chart_data,
        stock_data=stock_data,
        avg_change=avg_change,
        stock_type=stock_type,
        index_data=index_data,
        ai_analysis=ai_analysis,
        ai_news_summary=ai_news_summary
    )
    
    # 构建返回的数据字典
    generated_data = {
        'chart_year': chart_year,
        'chart_month': chart_month,
        'chart_data': chart_data,
        'stock_data': stock_data,
        'avg_change': avg_change,
        'index_data': index_data,
        'ai_analysis': ai_analysis,
        'ai_news_summary': ai_news_summary
    }
    
    if success:
        logger.info(f"{market_name}{type_name}月报发送成功")
        # 记录该市场的发送状态（避免重复发送）
        monthly_chart_service._save_sent_month(chart_year, chart_month, market)
    else:
        logger.error(f"{market_name}{type_name}月报发送失败")
    
    return (success, generated_data)


def create_stock_list(market: str) -> List[StockInfo]:
    """从配置创建股票信息列表"""
    stock_list = get_stock_list(market)
    market_info = get_market_info(market)
    
    return [
        StockInfo(symbol=symbol, name=name, market=market_type)
        for symbol, name, market_type in stock_list
    ]


def create_tech_game_lists(market: str) -> tuple:
    """从配置创建科技股和游戏股列表（美股/港股）"""
    market_info = get_market_info(market)
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


def is_likely_non_trading_day(market: str) -> bool:
    """检查当前是否可能是非交易日"""
    import pytz
    
    market_info = get_market_info(market)
    tz = pytz.timezone(market_info["timezone"])
    now = datetime.now(tz)
    
    # 周末
    if now.weekday() >= 5:
        return True
    return False


def run_kr_check(config: Config) -> None:
    """运行韩股检查"""
    logger.info("=" * 50)
    logger.info("开始执行韩股每日检查任务")
    logger.info("=" * 50)
    
    stock_service = StockService(market=MARKET_KR, timezone=config.timezone)
    ai_service = AIService(
        market=MARKET_KR,
        api_key=config.ai_api_key,
        model=config.ai_model,
        provider=config.ai_provider
    )
    notify_service = NotifyService(market=MARKET_KR, webhook_urls=config.wecom_webhook_urls)
    monthly_chart_service = MonthlyChartService()
    web_generator = WebGeneratorService()
    git_utils = GitUtils()
    
    try:
        has_holidays, yesterday, holidays = stock_service.get_holiday_info()
        
        if holidays:
            holiday_strs = [h.strftime("%Y-%m-%d") for h in holidays]
            logger.info(f"检测到休市日: {', '.join(holiday_strs)}")
        
        stocks = create_stock_list(MARKET_KR)
        logger.info(f"监控股票数量: {len(stocks)}")
        
        market_index = stock_service.get_market_index()
        if market_index:
            logger.info(f"大盘 {market_index.name}: {market_index.formatted_change}")
        
        all_changes = stock_service.get_all_stock_changes(stocks)
        
        if not all_changes:
            logger.warning("未能获取任何股票数据")
            if is_likely_non_trading_day(MARKET_KR):
                logger.info("今天可能是非交易日，跳过发送错误通知")
                return
            notify_service.send_error_notification(
                "⚠️ 韩股数据获取失败",
                "无法从 KRX 获取股票数据，可能是网络问题或非交易日。"
            )
            return
        
        # 检查是否需要生成月报并发送
        monthly_sent, monthly_data = generate_and_send_monthly_report(
            market=MARKET_KR,
            config=config,
            ai_service=ai_service,
            notify_service=notify_service,
            monthly_chart_service=monthly_chart_service,
            stock_type='game'
        )
        
        # 生成月报网页数据
        if monthly_sent and monthly_data:
            web_generator.generate_monthly_data(
                market=MARKET_KR,
                year=monthly_data['chart_year'],
                month=monthly_data['chart_month'],
                stock_data=monthly_data['stock_data'],
                avg_change=monthly_data['avg_change'],
                index_data=monthly_data['index_data'],
                ai_analysis=monthly_data['ai_analysis'],
                ai_news_summary=monthly_data['ai_news_summary']
            )
        
        if monthly_sent:
            import time
            time.sleep(2)
        
        # 生成日报 AI 分析
        logger.info(f"获取到 {len(all_changes)} 只股票数据，开始 AI 分析")
        
        prev_trading_date = all_changes[0].prev_date if all_changes else None
        if prev_trading_date:
            logger.info(f"上一交易日: {prev_trading_date.strftime('%Y-%m-%d')}")
        
        analysis = ai_service.analyze_stock_changes(
            changes=all_changes,
            prev_trading_date=prev_trading_date
        )
        
        if not analysis or not analysis.strip():
            logger.warning("AI 分析返回空结果，使用备用提示")
            analysis = "⚠️ AI 分析暂时不可用，请关注相关公司的最新公告和行业新闻。"
        
        # === 生成网页数据 ===
        logger.info("生成韩股日报网页数据...")
        web_generator.generate_daily_data(
            market=MARKET_KR,
            stock_changes=all_changes,
            market_index=market_index,
            ai_analysis=analysis,
            holidays=holidays
        )
        web_generator.update_meta()
        
        # === 检查是否需要发送 Shift Up 异常推送 ===
        should_alert, shiftup_change = notify_service.should_send_shiftup_alert(
            all_changes, config.change_threshold
        )
        
        webpage_url = web_generator.get_webpage_url()
        
        if should_alert and shiftup_change:
            # 只有 Shift Up 大涨大跌时才推送群消息
            logger.info(f"Shift Up 异常波动，发送预警到群...")
            notify_service.send_shiftup_alert(
                shiftup_change=shiftup_change,
                threshold=config.change_threshold,
                webpage_url=webpage_url
            )
        else:
            logger.info(f"Shift Up 涨跌正常，不发送群消息。详情请查看网页: {webpage_url}")
        
        # === Git 提交更新 ===
        logger.info("提交网页数据更新到 Git...")
        git_utils.setup_git_config()
        git_utils.commit_and_push("docs/", f"[auto] 更新韩股日报 {datetime.now().strftime('%Y-%m-%d')}")
        
        logger.info("韩股日报处理完成")
        
    except Exception as e:
        logger.error(f"韩股检查任务执行失败: {str(e)}", exc_info=True)
        sys.exit(1)


def run_us_hk_check(config: Config, market: str) -> None:
    """运行美股/港股检查（只生成网页数据，不发送群消息）"""
    market_info = get_market_info(market)
    market_name = market_info["name"]
    
    logger.info("=" * 50)
    logger.info(f"开始执行{market_name}每日检查任务")
    logger.info("=" * 50)
    
    stock_service = StockService(market=market, timezone=config.timezone)
    ai_service = AIService(
        market=market,
        api_key=config.ai_api_key,
        model=config.ai_model,
        provider=config.ai_provider
    )
    notify_service = NotifyService(market=market, webhook_urls=config.wecom_webhook_urls)
    monthly_chart_service = MonthlyChartService()
    web_generator = WebGeneratorService()
    git_utils = GitUtils()
    
    try:
        has_holidays, yesterday, holidays = stock_service.get_holiday_info()
        
        if holidays:
            holiday_strs = [h.strftime("%Y-%m-%d") for h in holidays]
            logger.info(f"检测到休市日: {', '.join(holiday_strs)}")
        
        tech_stocks, game_stocks = create_tech_game_lists(market)
        logger.info(f"监控科技股数量: {len(tech_stocks)}")
        logger.info(f"监控游戏股数量: {len(game_stocks)}")
        
        indices = stock_service.get_market_indices()
        if indices:
            for idx in indices:
                logger.info(f"指数 {idx.name}: {idx.formatted_change}")
        else:
            logger.warning("无法获取大盘指数")
        
        tech_changes = stock_service.get_all_stock_changes(tech_stocks)
        logger.info(f"获取到 {len(tech_changes)} 只科技股数据")
        
        game_changes = stock_service.get_all_stock_changes(game_stocks)
        logger.info(f"获取到 {len(game_changes)} 只游戏股数据")
        
        if not tech_changes and not game_changes:
            logger.warning("未能获取任何股票数据")
            if is_likely_non_trading_day(market):
                logger.info("今天可能是非交易日，跳过处理")
                return
            logger.warning(f"无法获取{market_name}数据，可能是网络问题或非交易日。")
            return
        
        # 检查是否需要生成月报（只生成数据，不发送群消息）
        should_send, chart_month, chart_year = monthly_chart_service.should_send_monthly_chart(market=market)
        
        if should_send:
            logger.info(f"需要生成 {chart_year}年{chart_month}月 {market_name}月报")
            
            # 生成图表数据
            chart_data, stock_data, avg_change, index_data = monthly_chart_service.generate_market_monthly_report(
                market=market,
                year=chart_year,
                month=chart_month,
                stock_type='tech'
            )
            
            if chart_data:
                # 生成 AI 分析
                ai_news_summary = None
                ai_analysis = None
                
                if config.ai_api_key:
                    logger.info(f"生成 {market_name}月度新闻汇总...")
                    try:
                        ai_news_summary = ai_service.analyze_monthly_news_summary(
                            year=chart_year,
                            month=chart_month,
                            stock_data=stock_data,
                            market=market
                        )
                        if ai_news_summary and ai_news_summary.startswith("⚠️"):
                            ai_news_summary = None
                    except Exception as e:
                        logger.error(f"新闻汇总生成异常: {e}")
                    
                    logger.info(f"生成 {market_name}月度分析...")
                    try:
                        ai_analysis = ai_service.analyze_monthly_report(
                            year=chart_year,
                            month=chart_month,
                            stock_data=stock_data,
                            index_data=index_data,
                            stock_type='tech'
                        )
                        if ai_analysis and ai_analysis.startswith("⚠️"):
                            ai_analysis = None
                    except Exception as e:
                        logger.error(f"月度分析生成异常: {e}")
                
                # 生成月报网页数据（不发送群消息）
                web_generator.generate_monthly_data(
                    market=market,
                    year=chart_year,
                    month=chart_month,
                    stock_data=stock_data,
                    avg_change=avg_change,
                    index_data=index_data,
                    ai_analysis=ai_analysis,
                    ai_news_summary=ai_news_summary
                )
                
                # 记录发送状态（避免重复生成）
                monthly_chart_service._save_sent_month(chart_year, chart_month, market)
                logger.info(f"{market_name}月报网页数据生成成功")
        
        # 生成日报 AI 分析
        logger.info("开始 AI 分析...")
        
        prev_trading_date = None
        if tech_changes:
            prev_trading_date = tech_changes[0].prev_date
        elif game_changes:
            prev_trading_date = game_changes[0].prev_date
        
        if prev_trading_date:
            logger.info(f"上一交易日: {prev_trading_date.strftime('%Y-%m-%d')}")
        
        analysis = ai_service.analyze_stock_changes(
            tech_changes=tech_changes,
            game_changes=game_changes,
            indices=indices,
            prev_trading_date=prev_trading_date
        )
        
        if not analysis or not analysis.strip():
            logger.warning("AI 分析返回空结果，使用备用提示")
            analysis = "⚠️ AI 分析暂时不可用，请关注相关公司的最新公告和行业新闻。"
        
        # === 生成网页数据（不发送群消息）===
        logger.info(f"生成{market_name}日报网页数据...")
        all_changes = tech_changes + game_changes
        web_generator.generate_daily_data(
            market=market,
            stock_changes=all_changes,
            indices=indices,
            ai_analysis=analysis,
            holidays=holidays
        )
        web_generator.update_meta()
        
        webpage_url = web_generator.get_webpage_url()
        logger.info(f"{market_name}日报数据已生成，不发送群消息。详情请查看网页: {webpage_url}")
        
        # === Git 提交更新 ===
        logger.info("提交网页数据更新到 Git...")
        git_utils.setup_git_config()
        git_utils.commit_and_push("docs/", f"[auto] 更新{market_name}日报 {datetime.now().strftime('%Y-%m-%d')}")
        
        logger.info(f"{market_name}日报处理完成")
        
    except Exception as e:
        logger.error(f"{market_name}检查任务执行失败: {str(e)}", exc_info=True)
        sys.exit(1)


def run_all_markets(config: Config) -> None:
    """运行所有市场的日报"""
    import time
    
    markets = [MARKET_KR, MARKET_HK, MARKET_US]
    market_names = ["韩股", "港股", "美股"]
    
    logger.info("=" * 50)
    logger.info("开始执行所有市场日报")
    logger.info("=" * 50)
    
    all_success = True
    
    for i, market in enumerate(markets):
        logger.info(f"\n{'='*30} {market_names[i]} {'='*30}")
        
        try:
            if market == MARKET_KR:
                run_kr_check(config)
            else:
                run_us_hk_check(config, market)
            logger.info(f"✅ {market_names[i]}日报发送成功")
        except SystemExit as e:
            if e.code != 0:
                all_success = False
                logger.error(f"❌ {market_names[i]}日报发送失败")
        except Exception as e:
            all_success = False
            logger.error(f"❌ {market_names[i]}日报发送失败: {str(e)}")
        
        # 市场之间间隔 5 秒，避免发送过快
        if i < len(markets) - 1:
            logger.info(f"等待 5 秒后发送下一个市场...")
            time.sleep(5)
    
    logger.info("\n" + "=" * 50)
    if all_success:
        logger.info("✅ 所有市场日报执行完成")
    else:
        logger.warning("⚠️ 部分市场执行失败")
        sys.exit(1)
    logger.info("=" * 50)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="股票监控机器人 - 支持韩股、美股、港股"
    )
    parser.add_argument(
        'market',
        nargs='?',
        choices=['kr', 'us', 'hk', 'all'],
        default='all',
        help='市场类型: kr(韩股), us(美股), hk(港股), all(所有市场)，默认为所有市场'
    )
    
    args = parser.parse_args()
    market = args.market
    
    # 加载配置
    config = load_config()
    
    # 设置日志
    setup_logger(level=config.log_level)
    
    # 验证配置
    errors = validate_config(config)
    if errors:
        logger.error("配置验证失败:")
        for error in errors:
            logger.error(f"  - {error}")
        sys.exit(1)
    
    logger.info("配置验证通过")
    logger.info(f"监控阈值: {config.change_threshold}%")
    logger.info(f"AI 提供商: {config.ai_provider}")
    logger.info(f"AI 模型: {config.ai_model}")
    
    if not config.ai_api_key:
        logger.warning("⚠️  未配置 AI API Key，将不会进行 AI 分析")
    
    # 执行股票检查
    if market == 'all':
        logger.info("=" * 50)
        logger.info("股票监控机器人 - 所有市场")
        logger.info("=" * 50)
        run_all_markets(config)
    elif market == MARKET_KR:
        market_info = get_market_info(market)
        logger.info("=" * 50)
        logger.info(f"{market_info['full_name']}监控机器人")
        logger.info("=" * 50)
        stocks = create_stock_list(market)
        logger.info(f"监控股票列表 ({len(stocks)}只):")
        for stock in stocks:
            logger.info(f"  - {stock}")
        run_kr_check(config)
    else:
        market_info = get_market_info(market)
        logger.info("=" * 50)
        logger.info(f"{market_info['full_name']}监控机器人")
        logger.info("=" * 50)
        tech_stocks, game_stocks = create_tech_game_lists(market)
        logger.info(f"监控科技股列表 ({len(tech_stocks)}只):")
        for stock in tech_stocks:
            logger.info(f"  - {stock}")
        logger.info(f"监控游戏股列表 ({len(game_stocks)}只):")
        for stock in game_stocks:
            logger.info(f"  - {stock}")
        run_us_hk_check(config, market)


if __name__ == "__main__":
    main()
