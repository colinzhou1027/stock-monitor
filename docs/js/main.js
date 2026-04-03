/**
 * 股票监控网页 - 主逻辑
 * 加载 JSON 数据并渲染页面
 */

// 数据基础路径
const DATA_BASE = './data';

// 市场配置
const MARKETS = {
  kr: { name: '韩股', currency: '₩', flag: '🇰🇷' },
  us: { name: '美股', currency: '$', flag: '🇺🇸' },
  hk: { name: '港股', currency: 'HK$', flag: '🇭🇰' }
};

// 格式化数字
function formatNumber(num, decimals = 2) {
  if (num === null || num === undefined) return '-';
  return num.toLocaleString('zh-CN', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals
  });
}

// 格式化货币
function formatCurrency(num, currency, decimals = 0) {
  if (num === null || num === undefined) return '-';
  return currency + formatNumber(num, decimals);
}

// 格式化涨跌幅
function formatChange(percent) {
  if (percent === null || percent === undefined) return '-';
  const sign = percent >= 0 ? '+' : '';
  return sign + percent.toFixed(2) + '%';
}

// 获取涨跌 CSS 类
function getChangeClass(percent) {
  if (percent === null || percent === undefined) return '';
  return percent >= 0 ? 'up' : 'down';
}

// 获取涨跌图标
function getChangeIcon(percent) {
  if (percent === null || percent === undefined) return '';
  return percent >= 0 ? '🟢' : '🔴';
}

// 加载 JSON 数据
async function loadData(path) {
  try {
    const response = await fetch(`${DATA_BASE}/${path}?t=${Date.now()}`);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return await response.json();
  } catch (error) {
    console.error(`加载数据失败: ${path}`, error);
    return null;
  }
}

// 加载元数据
async function loadMeta() {
  return await loadData('meta.json');
}

// 加载日报数据
async function loadDaily(market) {
  return await loadData(`${market}_daily.json`);
}

// 加载月报数据
async function loadMonthly(market) {
  return await loadData(`${market}_monthly.json`);
}

// 渲染首页市场卡片
async function renderMarketCards() {
  const container = document.getElementById('market-cards');
  if (!container) return;

  // 显示骨架屏
  container.innerHTML = `
    <div class="card skeleton" style="height: 180px;"></div>
    <div class="card skeleton" style="height: 180px;"></div>
    <div class="card skeleton" style="height: 180px;"></div>
  `;

  const meta = await loadMeta();
  
  let html = '';
  for (const [market, info] of Object.entries(MARKETS)) {
    const daily = await loadDaily(market);
    
    if (daily && daily.latest) {
      const data = daily.latest;
      const upCount = data.stocks ? data.stocks.filter(s => s.change_percent >= 0).length : 0;
      const downCount = data.stocks ? data.stocks.filter(s => s.change_percent < 0).length : 0;
      
      // 计算平均涨跌幅
      let avgChange = 0;
      if (data.stocks && data.stocks.length > 0) {
        avgChange = data.stocks.reduce((sum, s) => sum + s.change_percent, 0) / data.stocks.length;
      }
      
      html += `
        <div class="card market-card fade-in" onclick="location.href='${market}.html'">
          <div class="card-header">
            <div class="card-title">
              <span>${info.flag}</span>
              <span>${info.name}</span>
            </div>
            <span class="card-badge ${getChangeClass(avgChange)}">${formatChange(avgChange)}</span>
          </div>
          <div class="market-name">${market === 'kr' ? '游戏股票' : '科技/游戏股'}日报</div>
          <div class="market-stats">
            <div class="market-stat">
              <span class="market-stat-label">上涨</span>
              <span class="market-stat-value up">${upCount}</span>
            </div>
            <div class="market-stat">
              <span class="market-stat-label">下跌</span>
              <span class="market-stat-value down">${downCount}</span>
            </div>
            <div class="market-stat">
              <span class="market-stat-label">更新时间</span>
              <span class="market-stat-value" style="font-size: 0.875rem; color: var(--text-secondary);">
                ${data.update_time ? data.update_time.split(' ')[0] : '-'}
              </span>
            </div>
          </div>
        </div>
      `;
    } else {
      html += `
        <div class="card market-card fade-in" onclick="location.href='${market}.html'">
          <div class="card-header">
            <div class="card-title">
              <span>${info.flag}</span>
              <span>${info.name}</span>
            </div>
          </div>
          <div class="empty-state">
            <div>暂无数据</div>
          </div>
        </div>
      `;
    }
  }
  
  container.innerHTML = html;
}

// 渲染首页月报卡片
async function renderMonthlyCards() {
  const container = document.getElementById('monthly-cards');
  if (!container) return;

  // 显示骨架屏
  container.innerHTML = `
    <div class="card skeleton" style="height: 150px;"></div>
    <div class="card skeleton" style="height: 150px;"></div>
    <div class="card skeleton" style="height: 150px;"></div>
  `;
  
  let html = '';
  for (const [market, info] of Object.entries(MARKETS)) {
    const monthly = await loadMonthly(market);
    
    if (monthly && monthly.latest) {
      const data = monthly.latest;
      
      html += `
        <div class="card monthly-card fade-in" onclick="location.href='${market}.html#monthly'">
          <div class="card-header">
            <div class="card-title">
              <span>${info.flag}</span>
              <span>${info.name}</span>
            </div>
            <span class="card-badge ${getChangeClass(data.avg_change)}">${formatChange(data.avg_change)}</span>
          </div>
          <div class="market-name">${data.year}年${data.month}月 月报</div>
          <div class="market-stats">
            <div class="market-stat">
              <span class="market-stat-label">平均涨跌</span>
              <span class="market-stat-value ${getChangeClass(data.avg_change)}">${formatChange(data.avg_change)}</span>
            </div>
            <div class="market-stat">
              <span class="market-stat-label">股票数量</span>
              <span class="market-stat-value">${data.stock_data ? Object.keys(data.stock_data).length : '-'}</span>
            </div>
          </div>
        </div>
      `;
    } else {
      html += `
        <div class="card monthly-card fade-in" onclick="location.href='${market}.html#monthly'">
          <div class="card-header">
            <div class="card-title">
              <span>${info.flag}</span>
              <span>${info.name}</span>
            </div>
          </div>
          <div class="empty-state">
            <div>暂无月报</div>
          </div>
        </div>
      `;
    }
  }
  
  container.innerHTML = html;
}

// 渲染 Shift Up 快讯
async function renderShiftUpAlert() {
  const container = document.getElementById('shiftup-alert');
  if (!container) return;

  const daily = await loadDaily('kr');
  
  if (!daily || !daily.latest || !daily.latest.stocks) {
    container.style.display = 'none';
    return;
  }
  
  const shiftup = daily.latest.stocks.find(s => s.name && s.name.includes('Shift Up'));
  
  if (!shiftup) {
    container.style.display = 'none';
    return;
  }
  
  const isAlert = Math.abs(shiftup.change_percent) >= 10;
  const changeClass = getChangeClass(shiftup.change_percent);
  
  container.className = `alert-section ${isAlert ? `alert-${changeClass}` : ''}`;
  container.innerHTML = `
    <div class="alert-title">
      <span>🎮</span>
      <span>Shift Up 最新动态</span>
      ${isAlert ? '<span class="tag tag-holiday">⚠️ 异常波动</span>' : ''}
    </div>
    <div class="alert-change ${changeClass}">${formatChange(shiftup.change_percent)}</div>
    <div class="alert-content">
      <span>${shiftup.prev_prev_date || '-'} → ${shiftup.prev_date || '-'}</span>
      <span style="margin-left: 16px;">
        ₩${formatNumber(shiftup.prev_prev_close, 0)} → ₩${formatNumber(shiftup.prev_close, 0)}
      </span>
    </div>
  `;
}

// 渲染股票表格
function renderStockTable(stocks, currency, containerId) {
  const container = document.getElementById(containerId);
  if (!container || !stocks) return;
  
  // 默认按涨跌幅降序排序
  let sortedStocks = [...stocks].sort((a, b) => b.change_percent - a.change_percent);
  
  const decimals = currency === '₩' ? 0 : 2;
  
  let html = `
    <table class="stock-table" id="table-${containerId}">
      <thead>
        <tr>
          <th class="sortable" data-sort="name">股票名称</th>
          <th class="sortable" data-sort="prev_prev_close">${stocks[0]?.prev_prev_date || '前日'}</th>
          <th class="sortable" data-sort="prev_close">${stocks[0]?.prev_date || '昨日'}</th>
          <th class="sortable sort-desc" data-sort="change_percent">涨跌幅</th>
        </tr>
      </thead>
      <tbody>
  `;
  
  for (const stock of sortedStocks) {
    html += `
      <tr>
        <td class="stock-name">${getChangeIcon(stock.change_percent)} ${stock.name}</td>
        <td class="stock-price">${formatCurrency(stock.prev_prev_close, currency, decimals)}</td>
        <td class="stock-price">${formatCurrency(stock.prev_close, currency, decimals)}</td>
        <td class="stock-change ${getChangeClass(stock.change_percent)}">${formatChange(stock.change_percent)}</td>
      </tr>
    `;
  }
  
  html += '</tbody></table>';
  container.innerHTML = html;
  
  // 添加排序功能
  const table = document.getElementById(`table-${containerId}`);
  const headers = table.querySelectorAll('th.sortable');
  
  headers.forEach(header => {
    header.addEventListener('click', () => {
      const sortKey = header.dataset.sort;
      const isAsc = header.classList.contains('sort-asc');
      
      // 清除其他列的排序状态
      headers.forEach(h => {
        h.classList.remove('sort-asc', 'sort-desc');
      });
      
      // 设置当前列排序状态
      if (isAsc) {
        header.classList.add('sort-desc');
        sortedStocks.sort((a, b) => {
          if (sortKey === 'name') return b.name.localeCompare(a.name);
          return b[sortKey] - a[sortKey];
        });
      } else {
        header.classList.add('sort-asc');
        sortedStocks.sort((a, b) => {
          if (sortKey === 'name') return a.name.localeCompare(b.name);
          return a[sortKey] - b[sortKey];
        });
      }
      
      // 重新渲染表格内容
      const tbody = table.querySelector('tbody');
      tbody.innerHTML = sortedStocks.map(stock => `
        <tr>
          <td class="stock-name">${getChangeIcon(stock.change_percent)} ${stock.name}</td>
          <td class="stock-price">${formatCurrency(stock.prev_prev_close, currency, decimals)}</td>
          <td class="stock-price">${formatCurrency(stock.prev_close, currency, decimals)}</td>
          <td class="stock-change ${getChangeClass(stock.change_percent)}">${formatChange(stock.change_percent)}</td>
        </tr>
      `).join('');
    });
  });
}

// 渲染大盘指数
function renderMarketIndex(index, containerId) {
  const container = document.getElementById(containerId);
  if (!container || !index) {
    if (container) container.innerHTML = '<div class="empty-state">暂无指数数据</div>';
    return;
  }
  
  container.innerHTML = `
    <div class="index-card">
      <div class="index-name">📈 ${index.name}</div>
      <div class="index-change ${getChangeClass(index.change_percent)}">
        ${formatChange(index.change_percent)}
      </div>
    </div>
    <div style="color: var(--text-secondary); font-size: 0.875rem;">
      ${index.prev_prev_date || '-'}: ${formatNumber(index.prev_prev_close)} → 
      ${index.prev_date || '-'}: ${formatNumber(index.prev_close)}
    </div>
  `;
}

// 简单的 Markdown 表格解析器
function parseMarkdownTable(text) {
  const lines = text.trim().split('\n');
  let html = '';
  let tableLines = [];
  let nonTableLines = [];
  
  // 收集连续的表格行
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    
    // 检测表格行（以 | 开头和结尾）
    if (line.startsWith('|') && line.endsWith('|')) {
      // 如果之前有非表格内容，先输出
      if (nonTableLines.length > 0) {
        nonTableLines.forEach(l => {
          if (l) html += `<p>${l}</p>`;
        });
        nonTableLines = [];
      }
      tableLines.push(line);
    } else {
      // 非表格内容
      if (tableLines.length > 0) {
        // 渲染之前的表格
        html += renderTable(tableLines);
        tableLines = [];
      }
      nonTableLines.push(line);
    }
  }
  
  // 处理剩余内容
  if (tableLines.length > 0) {
    html += renderTable(tableLines);
  }
  if (nonTableLines.length > 0) {
    nonTableLines.forEach(l => {
      if (l) html += `<p>${l}</p>`;
    });
  }
  
  // 添加免责声明
  html += `<p class="ai-disclaimer">⚠️ 由于AI联网搜索覆盖范围有限、API调用不稳定、响应时间限制等原因，新闻汇总可能有信息遗漏，如有需要请人工验证。</p>`;
  
  return html || text;
}

// 解析月报内容（新闻汇总和月度分析）
// 支持格式：
// - 📰 行业大事 / 🏢 公司动态 / 🔥 市场热点
// - 📌 月度总结 / 📌 要点回顾 / 📌 后市展望
function parseMonthlyContent(text) {
  if (!text) return '';
  
  // 按分隔符 --- 分割内容
  const sections = text.split(/\n---\n|\n-{3,}\n/);
  let html = '';
  
  for (const section of sections) {
    const trimmed = section.trim();
    if (!trimmed) continue;
    
    // 检查是否有标题行（**📰 xxx** 或 **📌 xxx** 格式）
    const titleMatch = trimmed.match(/^\*\*([📰🏢🔥📌][^\*]+)\*\*/);
    
    if (titleMatch) {
      const title = titleMatch[1].trim();
      const content = trimmed.slice(titleMatch[0].length).trim();
      
      html += `<div class="monthly-section">`;
      html += `<div class="monthly-section-title">${title}</div>`;
      html += `<div class="monthly-section-body">${parseMonthlyBody(content)}</div>`;
      html += `</div>`;
    } else {
      // 无标题的段落
      html += `<div class="monthly-section">`;
      html += `<div class="monthly-section-body">${parseMonthlyBody(trimmed)}</div>`;
      html += `</div>`;
    }
  }
  
  return html;
}

// 解析月报正文内容
function parseMonthlyBody(text) {
  if (!text) return '';
  
  const lines = text.split('\n');
  let html = '';
  
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    
    // 处理列表项（• 开头）
    if (trimmed.startsWith('•')) {
      const content = trimmed.slice(1).trim();
      // 处理粗体 **xxx**
      const formatted = content.replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>');
      html += `<div class="monthly-item">• ${formatted}</div>`;
    }
    // 处理粗体公司名称行（**公司名**: 内容）
    else if (trimmed.match(/^\*\*[^:]+\*\*:/)) {
      const formatted = trimmed
        .replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>')
        .replace(/^(<strong>[^<]+<\/strong>:)/, '$1 ');
      html += `<div class="monthly-company-item">${formatted}</div>`;
    }
    // 普通段落
    else {
      const formatted = trimmed.replace(/\*\*([^\*]+)\*\*/g, '<strong>$1</strong>');
      html += `<p>${formatted}</p>`;
    }
  }
  
  return html;
}

// 渲染单个表格
function renderTable(lines) {
  if (lines.length === 0) return '';
  
  let html = '<table class="ai-table"><thead>';
  let headerDone = false;
  
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    
    // 跳过分隔行（如 |:----:|:-----|）
    if (line.match(/^\|[\s:\-|]+\|$/)) {
      if (!headerDone) {
        html += '</thead><tbody>';
        headerDone = true;
      }
      continue;
    }
    
    // 解析单元格
    const cells = line.slice(1, -1).split('|').map(cell => cell.trim());
    
    // 第一行是表头
    if (i === 0) {
      html += '<tr>';
      cells.forEach(cell => {
        html += `<th>${cell}</th>`;
      });
      html += '</tr>';
    } else {
      html += '<tr>';
      cells.forEach(cell => {
        html += `<td>${cell}</td>`;
      });
      html += '</tr>';
    }
  }
  
  if (!headerDone) {
    html += '</thead><tbody>';
  }
  html += '</tbody></table>';
  
  return html;
}

// 渲染 AI 分析面板
function renderAIPanel(analysis, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  
  if (!analysis) {
    container.innerHTML = `
      <div class="ai-panel">
        <div class="ai-panel-header" onclick="toggleAIPanel(this)">
          <div class="ai-panel-title">
            <span>🤖</span>
            <span>AI 分析</span>
          </div>
          <span class="ai-panel-toggle">▼</span>
        </div>
        <div class="ai-panel-content">
          <div class="ai-panel-body">
            <p style="color: var(--text-muted);">暂无 AI 分析内容</p>
          </div>
        </div>
      </div>
    `;
    return;
  }
  
  // 处理分析内容，解析 Markdown 表格
  const formattedAnalysis = parseMarkdownTable(analysis);
  
  container.innerHTML = `
    <div class="ai-panel open">
      <div class="ai-panel-header" onclick="toggleAIPanel(this)">
        <div class="ai-panel-title">
          <span>🤖</span>
          <span>AI 分析</span>
        </div>
        <span class="ai-panel-toggle">▼</span>
      </div>
      <div class="ai-panel-content">
        <div class="ai-panel-body">
          ${formattedAnalysis}
        </div>
      </div>
    </div>
  `;
}

// 切换 AI 面板展开/收起
function toggleAIPanel(header) {
  const panel = header.closest('.ai-panel');
  panel.classList.toggle('open');
}

// 渲染月报区块
async function renderMonthlySection(market, containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  
  const monthly = await loadMonthly(market);
  const marketInfo = MARKETS[market];
  
  if (!monthly || !monthly.latest) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon">📊</div>
        <div>暂无月报数据</div>
      </div>
    `;
    return;
  }
  
  const data = monthly.latest;
  
  let html = `
    <div class="section-title">
      <span>📊</span>
      <span>${data.year}年${data.month}月 月报</span>
    </div>
  `;
  
  // 月度图表
  if (data.chart_url) {
    html += `
      <div class="monthly-chart">
        <img src="${data.chart_url}" alt="${data.year}年${data.month}月 股票走势图" loading="lazy">
      </div>
    `;
  }
  
  // 月度统计
  html += `
    <div class="monthly-summary">
      <div class="monthly-stat">
        <div class="monthly-stat-label">平均涨跌幅</div>
        <div class="monthly-stat-value ${getChangeClass(data.avg_change)}">${formatChange(data.avg_change)}</div>
      </div>
  `;
  
  if (data.index_data) {
    html += `
      <div class="monthly-stat">
        <div class="monthly-stat-label">${data.index_data.name || '大盘指数'}</div>
        <div class="monthly-stat-value ${getChangeClass(data.index_data.change_percent)}">
          ${formatChange(data.index_data.change_percent)}
        </div>
      </div>
    `;
  }
  
  if (data.stock_data) {
    const stockCount = Object.keys(data.stock_data).length;
    html += `
      <div class="monthly-stat">
        <div class="monthly-stat-label">股票数量</div>
        <div class="monthly-stat-value">${stockCount}</div>
      </div>
    `;
  }
  
  html += '</div>';
  
  // 个股月度表现
  if (data.stock_data) {
    const stocks = Object.entries(data.stock_data)
      .map(([symbol, info]) => ({ symbol, ...info }))
      .sort((a, b) => b.change_percent - a.change_percent);
    
    html += `
      <div style="margin-top: var(--spacing-lg);">
        <h4 style="margin-bottom: var(--spacing-md); color: var(--text-secondary);">个股表现</h4>
        <table class="stock-table">
          <thead>
            <tr>
              <th>股票名称</th>
              <th>月度涨跌幅</th>
            </tr>
          </thead>
          <tbody>
    `;
    
    for (const stock of stocks) {
      html += `
        <tr>
          <td class="stock-name">${getChangeIcon(stock.change_percent)} ${stock.name}</td>
          <td class="stock-change ${getChangeClass(stock.change_percent)}">${formatChange(stock.change_percent)}</td>
        </tr>
      `;
    }
    
    html += '</tbody></table></div>';
  }
  
  // AI 月度分析
  if (data.ai_analysis) {
    html += `
      <div style="margin-top: var(--spacing-lg);">
        <h4 style="margin-bottom: var(--spacing-md); color: var(--text-secondary);">📝 月度分析</h4>
        <div class="monthly-analysis-content">
          ${parseMonthlyContent(data.ai_analysis)}
        </div>
      </div>
    `;
  }
  
  // AI 新闻汇总
  if (data.ai_news_summary) {
    html += `
      <div style="margin-top: var(--spacing-lg);">
        <h4 style="margin-bottom: var(--spacing-md); color: var(--text-secondary);">📰 新闻汇总</h4>
        <div class="monthly-news-content">
          ${parseMonthlyContent(data.ai_news_summary)}
        </div>
      </div>
    `;
  }
  
  container.innerHTML = html;
}

// 渲染详情页日报区块
async function renderDailySection(market) {
  const marketInfo = MARKETS[market];
  const daily = await loadDaily(market);
  
  // 渲染大盘指数
  if (daily && daily.latest) {
    const data = daily.latest;
    
    // 单一指数或多指数
    if (data.market_index) {
      renderMarketIndex(data.market_index, 'market-index');
    } else if (data.indices && data.indices.length > 0) {
      const container = document.getElementById('market-index');
      if (container) {
        container.innerHTML = data.indices.map(idx => `
          <div class="index-card">
            <div class="index-name">📈 ${idx.name}</div>
            <div class="index-change ${getChangeClass(idx.change_percent)}">
              ${formatChange(idx.change_percent)}
            </div>
          </div>
        `).join('');
      }
    }
    
    // 渲染股票表格
    if (data.stocks) {
      renderStockTable(data.stocks, marketInfo.currency, 'stock-table');
    }
    
    // 休市提醒
    const holidayContainer = document.getElementById('holiday-notice');
    if (holidayContainer && data.holidays && data.holidays.length > 0) {
      holidayContainer.innerHTML = `
        <div class="alert-section" style="border-color: #ffc107; background: rgba(255, 193, 7, 0.1);">
          <div class="alert-title">
            <span>🔴</span>
            <span>休市提醒</span>
          </div>
          <div class="alert-content">${data.holidays.join('、')} 为法定假日，股市休市。以下为最近交易日数据。</div>
        </div>
      `;
    }
    
    // 渲染 AI 分析
    renderAIPanel(data.ai_analysis, 'ai-analysis');
    
    // 更新时间
    const updateTimeEl = document.getElementById('update-time');
    if (updateTimeEl) {
      updateTimeEl.textContent = data.update_time || '-';
    }
  }
}

// 渲染历史数据选项卡
async function renderHistoryTabs(market) {
  const daily = await loadDaily(market);
  const container = document.getElementById('history-tabs');
  
  if (!container || !daily || !daily.history || daily.history.length === 0) {
    if (container) container.style.display = 'none';
    return;
  }
  
  let html = '<div class="history-tabs">';
  html += `<button class="history-tab active" data-index="latest">最新</button>`;
  
  daily.history.forEach((item, index) => {
    html += `<button class="history-tab" data-index="${index}">${item.date}</button>`;
  });
  
  html += '</div>';
  container.innerHTML = html;
  
  // 添加点击事件
  const tabs = container.querySelectorAll('.history-tab');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      
      const index = tab.dataset.index;
      const data = index === 'latest' ? daily.latest : daily.history[parseInt(index)];
      
      // 更新股票表格
      if (data && data.stocks) {
        renderStockTable(data.stocks, MARKETS[market].currency, 'stock-table');
      }
      
      // 更新 AI 分析
      renderAIPanel(data?.ai_analysis, 'ai-analysis');
    });
  });
}

// 页面初始化
document.addEventListener('DOMContentLoaded', async () => {
  // 检测当前页面类型
  const path = window.location.pathname;
  
  if (path.endsWith('index.html') || path.endsWith('/')) {
    // 首页
    await renderMarketCards();
    await renderMonthlyCards();
    await renderShiftUpAlert();
  } else if (path.includes('kr.html')) {
    await renderDailySection('kr');
    await renderMonthlySection('kr', 'monthly-section');
    await renderHistoryTabs('kr');
  } else if (path.includes('us.html')) {
    await renderDailySection('us');
    await renderMonthlySection('us', 'monthly-section');
    await renderHistoryTabs('us');
  } else if (path.includes('hk.html')) {
    await renderDailySection('hk');
    await renderMonthlySection('hk', 'monthly-section');
    await renderHistoryTabs('hk');
  }
  
  // 更新页脚时间
  const footerTime = document.getElementById('footer-time');
  if (footerTime) {
    const meta = await loadMeta();
    if (meta && meta.last_update) {
      footerTime.textContent = meta.last_update;
    }
  }
});

// 暴露函数到全局
window.toggleAIPanel = toggleAIPanel;
