#!/bin/bash
# MacBook 本地定时任务安装脚本

echo "🚀 安装股票监控定时任务..."

# 设置变量
SCRIPT_DIR="/Users/colinzhou/CodeBuddy/20260228101529/stock-monitor/scripts"
PLIST_FILE="com.colinzhou.stockmonitor.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"

# 1. 创建日志目录
echo "📁 创建日志目录..."
mkdir -p /Users/colinzhou/CodeBuddy/20260228101529/stock-monitor/logs

# 2. 设置脚本执行权限
echo "🔧 设置脚本权限..."
chmod +x "$SCRIPT_DIR/run_stock_check.sh"

# 3. 创建 LaunchAgents 目录（如果不存在）
mkdir -p "$LAUNCH_AGENTS_DIR"

# 4. 复制 plist 文件到 LaunchAgents
echo "📋 复制配置文件..."
cp "$SCRIPT_DIR/$PLIST_FILE" "$LAUNCH_AGENTS_DIR/"

# 5. 卸载旧任务（如果存在）
echo "🔄 卸载旧任务..."
launchctl unload "$LAUNCH_AGENTS_DIR/$PLIST_FILE" 2>/dev/null

# 6. 加载新任务
echo "✅ 加载定时任务..."
launchctl load "$LAUNCH_AGENTS_DIR/$PLIST_FILE"

# 7. 检查任务状态
echo ""
echo "📊 任务状态："
launchctl list | grep stockmonitor

echo ""
echo "✅ 安装完成！"
echo ""
echo "📝 使用说明："
echo "   - 查看任务状态: launchctl list | grep stockmonitor"
echo "   - 手动触发测试: launchctl start com.colinzhou.stockmonitor"
echo "   - 停止任务: launchctl unload ~/Library/LaunchAgents/$PLIST_FILE"
echo "   - 查看日志: tail -f /Users/colinzhou/CodeBuddy/20260228101529/stock-monitor/logs/stock_check.log"
echo ""
echo "⚠️  注意：电脑需要保持开机状态，10:00 时如果电脑休眠，唤醒后会立即执行"
