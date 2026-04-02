#!/bin/bash
# 股票监控定时任务脚本（多市场版本）
# 用于 macOS launchd 定时执行
# 功能：自动检测今天是否已执行，避免重复执行，支持补执行
# 执行时间：北京时间每天 10:30
#
# 日报发送说明：
# - 韩股（kr）：发送前一交易日的日报（首尔 15:30 收盘 = 北京 14:30）
# - 港股（hk）：发送前一交易日的日报（香港 16:00 收盘）
# - 美股（us）：发送当天凌晨刚收盘的日报（美东 16:00 收盘 = 北京次日 05:00）
#   例如：北京时间周三 10:30 发送的美股日报 = 美东周二收盘数据

# 设置工作目录
cd /Users/colinzhou/CodeBuddy/20260228101529/stock-monitor

# 设置日志文件和状态文件
LOG_FILE="/Users/colinzhou/CodeBuddy/20260228101529/stock-monitor/logs/stock_check.log"
LAST_RUN_FILE="/Users/colinzhou/CodeBuddy/20260228101529/stock-monitor/logs/last_run.txt"
mkdir -p "$(dirname "$LOG_FILE")"

# 获取当前日期和时间信息
TODAY=$(date '+%Y-%m-%d')
CURRENT_HOUR=$(date '+%H')
CURRENT_WEEKDAY=$(date '+%u')  # 1=周一, 7=周日

# 检查是否是工作日（周一到周五）
if [ "$CURRENT_WEEKDAY" -gt 5 ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 今天是周末，不执行" >> "$LOG_FILE"
    exit 0
fi

# 检查今天是否已经成功执行过
if [ -f "$LAST_RUN_FILE" ]; then
    LAST_RUN_DATE=$(cat "$LAST_RUN_FILE")
else
    LAST_RUN_DATE=""
fi

# 判断是否需要执行
SHOULD_RUN=false
RUN_REASON=""

# 如果今天还没执行过
if [ "$LAST_RUN_DATE" != "$TODAY" ]; then
    # 检查是否在执行时间窗口内（10:30 - 14:00）
    if [ "$CURRENT_HOUR" -ge 10 ] && [ "$CURRENT_HOUR" -lt 14 ]; then
        SHOULD_RUN=true
        if [ "$CURRENT_HOUR" -eq 10 ]; then
            RUN_REASON="正常执行"
        else
            RUN_REASON="补执行（错过了10:30的执行时间）"
        fi
    elif [ "$CURRENT_HOUR" -ge 14 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 已超过执行时间窗口（14:00），跳过今天的执行" >> "$LOG_FILE"
        exit 0
    fi
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 今天 ($TODAY) 已执行过，跳过" >> "$LOG_FILE"
    exit 0
fi

# 执行股票检查
if [ "$SHOULD_RUN" = true ]; then
    echo "========================================" >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 开始执行多市场股票检查..." >> "$LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 执行原因: $RUN_REASON" >> "$LOG_FILE"
    
    # 激活虚拟环境（如果有的话）
    if [ -d "venv" ]; then
        source venv/bin/activate
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 已激活虚拟环境" >> "$LOG_FILE"
    fi
    
    # 加载环境变量
    if [ -f ".env" ]; then
        export $(cat .env | grep -v '^#' | xargs)
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] 已加载环境变量" >> "$LOG_FILE"
    fi
    
    # 记录执行结果
    ALL_SUCCESS=true
    
    # 执行韩股检查（前一交易日日报）
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📈 开始韩股日报..." >> "$LOG_FILE"
    python3 main.py kr >> "$LOG_FILE" 2>&1
    KR_EXIT=$?
    if [ $KR_EXIT -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 韩股日报发送成功" >> "$LOG_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 韩股日报发送失败 (退出码: $KR_EXIT)" >> "$LOG_FILE"
        ALL_SUCCESS=false
    fi
    
    # 间隔 5 秒，避免发送过快
    sleep 5
    
    # 执行港股检查（前一交易日日报）
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📈 开始港股日报..." >> "$LOG_FILE"
    python3 main.py hk >> "$LOG_FILE" 2>&1
    HK_EXIT=$?
    if [ $HK_EXIT -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 港股日报发送成功" >> "$LOG_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 港股日报发送失败 (退出码: $HK_EXIT)" >> "$LOG_FILE"
        ALL_SUCCESS=false
    fi
    
    # 间隔 5 秒
    sleep 5
    
    # 执行美股检查（当天凌晨收盘的日报 = 美东前一天）
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 📈 开始美股日报（美东前一天收盘数据）..." >> "$LOG_FILE"
    python3 main.py us >> "$LOG_FILE" 2>&1
    US_EXIT=$?
    if [ $US_EXIT -eq 0 ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 美股日报发送成功" >> "$LOG_FILE"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ 美股日报发送失败 (退出码: $US_EXIT)" >> "$LOG_FILE"
        ALL_SUCCESS=false
    fi
    
    # 如果全部执行成功，记录执行日期
    if [ "$ALL_SUCCESS" = true ]; then
        echo "$TODAY" > "$LAST_RUN_FILE"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ 所有市场日报执行成功，已记录执行日期" >> "$LOG_FILE"
        EXIT_CODE=0
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚠️ 部分市场执行失败，下次触发时将重试" >> "$LOG_FILE"
        EXIT_CODE=1
    fi
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 执行完成" >> "$LOG_FILE"
    echo "========================================" >> "$LOG_FILE"
    echo "" >> "$LOG_FILE"
    
    exit $EXIT_CODE
fi
