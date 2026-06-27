// ==========================================
// dashboard.js — SLIDE 儀表板頁面渲染與問答看板邏輯
// ==========================================

// LIME 因子的「來源」小標：True=本訂單實際值；False=模型整體性因子（資料無逐筆數值）
function factorScopeTag(f) {
  return f && f.order_specific
    ? '<span style="font-size:10px;background:#e0f2fe;color:#0369a1;border-radius:8px;padding:1px 6px;margin-left:6px;">本訂單實際值</span>'
    : '<span style="font-size:10px;background:#f1f5f9;color:#64748b;border-radius:8px;padding:1px 6px;margin-left:6px;">模型整體因子</span>';
}

// ── 月份 flipper（問答看板）：'' = 全部月份，置於清單最前 ───────────────────────
function currentFlipperMonth() {
  const list = window.edisState.monthList;
  return list ? (list[window.edisState.monthIdx || 0] || '') : '';
}

function syncMonthFlipper(months) {
  if (!Array.isArray(months)) return;
  const desired = [''].concat(months);
  const existing = window.edisState.monthList;
  // 僅在清單尚未建立或長度變動時重建，避免每次載入都重置使用者選擇
  if (!existing || existing.length !== desired.length) {
    window.edisState.monthList = desired;
    if ((window.edisState.monthIdx || 0) >= desired.length) window.edisState.monthIdx = 0;
    updateMonthFlipperLabel();
  }
}

function updateMonthFlipperLabel() {
  const label = document.getElementById('monthFlipperLabel');
  if (label) label.textContent = currentFlipperMonth() || '全部月份';
}

function flipMonth(delta) {
  const list = window.edisState.monthList;
  if (!list || list.length === 0) return;
  let idx = (window.edisState.monthIdx || 0) + delta;
  idx = Math.max(0, Math.min(list.length - 1, idx));  // 邊界夾擠，無溢位、無遞迴
  if (idx === (window.edisState.monthIdx || 0)) return;
  window.edisState.monthIdx = idx;
  updateMonthFlipperLabel();
  window.edisState.currentPage = 1;
  reloadBossBoard();
}
window.flipMonth = flipMonth;

// 依目前 flipper 月份重新載入老闆直觀問答看板（緊急度排序由後端負責）
async function reloadBossBoard() {
  const p = await fetchPredictions(window.edisState.currentPage || 1, '', '', '', '', currentFlipperMonth());
  if (!p) return;
  syncMonthFlipper(p.available_months);
  window.edisState.totalPredictionsCount = p.count || 0;
  renderBossTable(p.data || []);
}

// LIME 歸因彈窗：元件化重構時此函式遺失（原本只存在於 index_original.html），
// 在此補回，並加入因子來源小標（本訂單實際值 / 模型整體因子）。
async function openExplainModal(orderId) {
  const modal = document.getElementById('explainModal');
  if (!modal) return;
  document.getElementById('modalOrderId').textContent = displayOrderId(orderId);
  document.getElementById('modalOrderId').title = orderId;
  document.getElementById('modalProb').textContent = '讀取中...';
  document.getElementById('modalPenalty').textContent = '讀取中...';
  document.getElementById('modalSummaryText').textContent = '讀取中...';
  document.getElementById('modalFactorsList').innerHTML = '讀取中...';
  modal.style.display = 'flex';

  try {
    const res = await fetch(`${API_BASE}/api/explain/${orderId}`, {
      headers: { 'X-Role': window.edisState.currentRole === 'manager' ? 'Logistics_Manager' : 'Viewer' }
    });
    if (!res.ok) throw new Error('分析資料讀取失敗');
    const data = await res.json();

    document.getElementById('modalProb').textContent = pLateText(data.p_late);
    document.getElementById('modalPenalty').textContent = '$' + Math.round(data.expected_penalty).toLocaleString();
    document.getElementById('modalSummaryText').textContent = buildManagerSummary(data);

    const factors = data.top_x_factors || [];
    document.getElementById('modalFactorsList').innerHTML = factors.map(f => `
      <div style="padding:10px 14px; border:1px solid var(--border); border-radius:8px; background:#fcfcfc; display:flex; justify-content:space-between; align-items:center; gap:12px;">
        <div>
          <div style="font-size:12px; font-weight:600; color:var(--text);">${f.label || f.feature}${factorScopeTag(f)}</div>
          <div style="font-size:11.5px; color:var(--muted); margin-top:2px;">${f.evidence}</div>
        </div>
        <span class="risk-pill ${f.impact === 'raises risk' ? 'r-high' : 'r-low'}" style="font-size:10px; font-weight:600; white-space:nowrap;">
          ${f.impact === 'raises risk' ? '▲ 增加延遲風險' : '▼ 正常或次要因子'}
        </span>
      </div>
    `).join('');
  } catch (e) {
    document.getElementById('modalSummaryText').textContent = '載入分析失敗: ' + e.message;
  }
}
window.openExplainModal = openExplainModal;

function closeExplainModal() {
  const modal = document.getElementById('explainModal');
  if (modal) modal.style.display = 'none';
}
window.closeExplainModal = closeExplainModal;

async function refreshDashboard() {
  try {
    const [p, executive, scenarios] = await Promise.all([
      fetchPredictions(window.edisState.currentPage, '', '', '', '', currentFlipperMonth()),
      fetchExecutiveSummary(),
      fetchScenarioAnalysis()
    ]);
    if (p) {
      syncMonthFlipper(p.available_months);
      window.edisState.totalPredictionsCount = p.count || 0;
      renderBossTable(p.data || []);
      const m = await fetchMetrics();
      if (m) renderMetrics(m);
    }
    if (executive) renderExecutiveSummary(executive);
    if (scenarios) renderBudgetScenarios(scenarios);
    // 項目5：門檻校正 UI 已移除，相關渲染呼叫一併移除（原為未定義函式）。
  } catch (e) {
    console.error('Failed to refresh dashboard', e);
  }
}

function renderMetrics(d) {
  const countSpan = document.getElementById('kpiTotalOrders');
  const descSpan = document.getElementById('kpiTotalDesc');
  if (countSpan) countSpan.textContent = window.edisState.totalPredictionsCount.toLocaleString();
  if (descSpan) {
    descSpan.textContent = d.is_active
      ? (d.has_ground_truth ? "已載入回填資料" : "已載入待預測資料（尚未回填 Y）")
      : "預設驗證集";
  }
}

function renderExecutiveSummary(d) {
  const serviceLevel = ((d.estimated_service_level || 0) * 100).toFixed(1);
  const atRiskRate = ((d.at_risk_rate || 0) * 100).toFixed(1);
  const topRegion = (d.top_regions && d.top_regions[0]) ? d.top_regions[0] : null;
  const topMode = (d.top_shipping_modes && d.top_shipping_modes[0]) ? d.top_shipping_modes[0] : null;

  // 更新 Dashboard 看板 KPI 卡片
  if (d.total_orders !== undefined) {
    document.getElementById('kpiTotalOrders').textContent = d.total_orders.toLocaleString();
  }
  document.getElementById('kpiPredictedLateOrders').textContent = d.at_risk_orders.toLocaleString();
  
  const predictedDesc = document.getElementById('kpiPredictedDesc');
  if (predictedDesc) {
    predictedDesc.textContent = `延遲機率 ≥ ${(window.edisState.threshold * 100).toFixed(0)}%`;
  }
  
  document.getElementById('kpiExpectedPenaltyLoss').textContent = '$' + Math.round(d.expected_penalty_exposure || 0).toLocaleString();
  
  const expectedDesc = document.getElementById('kpiExpectedDesc');
  if (expectedDesc) {
    expectedDesc.textContent = `建議升級預算: $${Math.round(d.recommended_budget || 0).toLocaleString()}`;
  }
  window.edisState.dashboardOptimizationBudget = Number(d.recommended_budget || 0);

  // Actionable Insights 決策 Banner 顯示邏輯
  const banner = document.getElementById('actionableInsightsBanner');
  const bannerText = document.getElementById('actionableInsightsText');
  const savings = (typeof d.net_savings === 'number')
    ? Math.max(0, d.net_savings)
    : Math.max(0, (d.expected_penalty_exposure || 0) - (d.recommended_budget || 0));
    
  if (banner && bannerText) {
    if ((d.recommended_budget || 0) > 0 && savings > 0) {
      banner.style.display = 'flex';
      bannerText.innerHTML = `最佳化建議投入物流預算 <strong>$${Math.round(d.recommended_budget).toLocaleString()}</strong>，升級 <strong>${d.positive_roi_orders.toLocaleString()}</strong> 筆訂單，預估為公司省下淨額 <strong>$${Math.round(savings).toLocaleString()}</strong>。`;
    } else {
      banner.style.display = 'none';
    }
  }

  // 簡報區數據
  const slaRiskEl = document.getElementById('execSlaRisk');
  if (slaRiskEl) slaRiskEl.textContent = `${serviceLevel}%`;
  const slaRiskNoteEl = document.getElementById('execSlaRiskNote');
  if (slaRiskNoteEl) slaRiskNoteEl.textContent = `目標 90%，目前 ${d.at_risk_orders.toLocaleString()} 筆高於預警門檻。`;
  
  const exposureEl = document.getElementById('execExposure');
  if (exposureEl) exposureEl.textContent = '$' + Math.round(d.expected_penalty_exposure || 0).toLocaleString();
  const exposureNoteEl = document.getElementById('execExposureNote');
  if (exposureNoteEl) exposureNoteEl.textContent = `約 ${atRiskRate}% 訂單可能延遲。`;
  
  const budgetEl = document.getElementById('execBudget');
  if (budgetEl) budgetEl.textContent = '$' + Math.round(d.recommended_budget || 0).toLocaleString();
  const budgetNoteEl = document.getElementById('execBudgetNote');
  if (budgetNoteEl) budgetNoteEl.textContent = `最佳化建議升級 ${d.positive_roi_orders.toLocaleString()} 筆訂單。`;
  
  document.getElementById('execDriver').textContent = topRegion && topMode
    ? topRegion.label + ' / ' + topMode.label
    : (topRegion ? topRegion.label : (topMode ? topMode.label : '—'));
  document.getElementById('execDriverNote').textContent = topRegion && topMode
    ? '高風險訂單較集中於此區域與配送方式；這是統計關聯，不代表單一因果。'
    : '資料量不足，無法判斷高風險集中組合。';

  document.getElementById('execActionText').textContent = `${d.recommended_action} ${d.data_quality_note || ''}`;
}

function fillClass(p) {
  const num = typeof p === 'string' ? (p === 'High' ? 0.8 : p === 'Medium' ? 0.5 : 0.2) : p;
  return num >= 0.7 ? 'fill-high' : num >= 0.3 ? 'fill-med' : 'fill-low';
}
function pillClass(p) {
  const str = typeof p === 'number' ? (p >= 0.7 ? 'High' : p >= 0.3 ? 'Medium' : 'Low') : p;
  return str === 'High' ? 'r-high' : str === 'Medium' ? 'r-med' : 'r-low';
}

function riskBucket(o) {
  if (o.risk_bucket) return String(o.risk_bucket);
  const p = Number(o.p_late || 0);
  return p >= 0.7 ? 'High' : p >= 0.3 ? 'Medium' : 'Low';
}

function riskLabel(o) {
  return riskBucket(o).toUpperCase();
}

function riskBadgeHtml(o, extraStyle = '') {
  return `<span class="risk-pill risk-text-only ${pillClass(riskBucket(o))}" style="font-weight:700; ${extraStyle}">${riskLabel(o)}</span>`;
}

function pLateText(pLate) {
  const p = Number(pLate || 0);
  return `${(p * 100).toFixed(1)}%`;
}

function buildManagerSummary(data) {
  const risk = String(data.risk_bucket || riskBucket(data)).toUpperCase();
  const pLate = pLateText(data.p_late);
  const penalty = Math.round(Number(data.expected_penalty || 0)).toLocaleString();
  const cost = Math.round(Number(data.upgrade_cost || 0)).toLocaleString();
  const net = Math.round(Number(data.net_benefit || 0)).toLocaleString();
  const factors = (data.top_x_factors || [])
    .slice(0, 4)
    .map(f => `${f.label || f.feature}（${f.evidence || '模型指出此因子會影響延遲風險'}）`)
    .join('、');
  const action = data.recommended_action || '依延遲風險與淨效益決定是否升級。';
  return (
    `此訂單延遲風險為 ${risk}（p_late=${pLate}），` +
    `若升級運送，原罰款 USD $${penalty}，` +
    `扣除升級成本 USD $${cost} 後，可省下 USD $${net}的懲罰成本(淨效益)。` +
    `可能導致延遲的主要因子為：${factors || '目前無明顯特徵影響'}。建議：${action}。`
  );
}

function getReasonText(o) {
  const mode = o.shipping_mode || 'Unknown';
  const region = o.order_region || '未知區域';
  const pLate = Number(o.p_late || 0);

  if (mode === 'First Class') {
    return `First Class 歷史延遲率偏高，可能與承諾時效較短有關；目的地：${region}`;
  }
  if (mode === 'Second Class') {
    return `Second Class 在高風險清單中集中出現；需搭配區域與承諾天數判讀`;
  }
  if (mode === 'Same Day') {
    return `Same Day 承諾時效最緊，容錯時間低`;
  }
  if (mode === 'Standard Class') {
    return `Standard Class 承諾天數較長，通常不是主要風險訊號`;
  }
  if (pLate >= 0.7) {
    return `模型判定為高風險；目的地：${region}`;
  }
  return `風險訊號較分散，建議展開查看特徵影響`;
}

function simulatorOrderPayload(order) {
  return encodeURIComponent(JSON.stringify(order || {}));
}

function openDashboardSimulator(orderOrPayload) {
  if (window.edisState.currentRole === 'viewer') return;
  if (window.openOrderSimulation) {
    const order = typeof orderOrPayload === 'string' ? JSON.parse(decodeURIComponent(orderOrPayload)) : orderOrPayload;
    window.openOrderSimulation(order);
  }
}

function openRecommendedOptimization() {
  showPage('optimization');
  setTimeout(() => {
    const budget = Math.round(Number(window.edisState.dashboardOptimizationBudget || 0));
    const input = document.getElementById('optPageBudgetInput');
    if (input && budget > 0) input.value = String(budget);
    if (window.edisState.currentRole !== 'viewer' && window.runPageOptimize) {
      window.runPageOptimize();
    }
  }, 250);
}

function getActionText(o) {
  const expected_saving = o.expected_penalty - o.upgrade_cost;
  const actionText = o.p_late >= window.edisState.threshold && expected_saving > 0
    ? '建議升級運送'
    : '監控並維持原狀';
  if (o.p_late >= window.edisState.threshold && expected_saving > 0) {
    return `<span class="risk-pill r-high" style="font-weight:600; cursor:pointer;" onclick="openExplainModal('${o.order_id_hash}')">💡 ${actionText}</span>`;
  }
  return `<span class="risk-pill r-low" style="font-weight:500; cursor:pointer;" onclick="openExplainModal('${o.order_id_hash}')">✔ ${actionText}</span>`;
}

function renderBossTable(data) {
  const tbody = document.getElementById('bossTableBody');
  if (!tbody) return;
  const delayed = data.filter(o => o.p_late >= window.edisState.threshold);
  
  const countText = document.getElementById('bossDelayCount');
  if (countText) countText.textContent = `${delayed.length} 筆預估延遲`;
  
  if (delayed.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:32px;color:var(--muted);font-size:13px">沒有判定為延遲的訂單 (門檻值 = ${window.edisState.threshold.toFixed(2)})</td></tr>`;
    return;
  }
  
  tbody.innerHTML = delayed.map(o => {
    const hash = o.order_id_hash;
    
    const simulatorPayload = simulatorOrderPayload(o);
    
    return `
      <tr>
        <td>
          <span id="explain-btn-${hash}" style="cursor:pointer; display:inline-block; width:12px; margin-right:4px; font-size:10px; color:var(--navy);" onclick="toggleRowExplanation('${hash}')">▶</span>
          <span class="order-id" title="${hash}" style="cursor:pointer; text-decoration:underline;" onclick="toggleRowExplanation('${hash}')">${o.display_order_id || displayOrderId(hash)}</span>
        </td>
        <td>${o.shipping_mode || 'Unknown'}</td>
        <td style="color:var(--muted)">${o.order_region || 'Unknown'}</td>
        <td>
          <div class="prob-wrap">
            <div class="prob-bar"><div class="prob-fill ${fillClass(riskBucket(o))}" style="width:${Math.max(0, Math.min(100, Number(o.p_late || 0) * 100))}%"></div></div>
            <span class="prob-val">${pLateText(o.p_late)}</span>
          </div>
        </td>
        <td style="font-size:11px; color:var(--muted); line-height:1.5;">${getReasonText(o)}</td>
        <td style="white-space:nowrap;">
          ${getActionText(o)}
          ${window.edisState.currentRole === 'viewer'
            ? ``
            : `<button class="run-btn" title="分析單筆訂單調度風險" style="width:auto; padding:2px 8px; font-size:10px; margin-left:6px; background:#dbeafe !important; color:#1e3a8a !important; border:1px solid #bfdbfe;" onclick="openDashboardSimulator('${simulatorPayload}')">分析單筆訂單調度風險</button>`}
        </td>
      </tr>
      <tr id="explain-row-${hash}" class="hidden">
        <td colspan="6" style="padding:0; background:#f9faf9;">
          <div id="explain-content-${hash}" style="padding:14px 20px; border-top:1px solid var(--border); border-bottom:1px solid var(--border); font-size:12.5px; line-height:1.5; color:var(--text);">載入中...</div>
        </td>
      </tr>
    `;
  }).join('');
}

async function toggleRowExplanation(orderId) {
  const row = document.getElementById(`explain-row-${orderId}`);
  const btn = document.getElementById(`explain-btn-${orderId}`);
  const content = document.getElementById(`explain-content-${orderId}`);
  if (!row || !content) return;
  
  if (row.classList.contains('hidden')) {
    row.classList.remove('hidden');
    if (btn) btn.textContent = '▼';
    
    if (content.textContent === '載入中...') {
      try {
        const res = await fetch(`${API_BASE}/api/explain/${orderId}`);
        if (!res.ok) throw new Error('讀取歸因失敗');
        const data = await res.json();
        
        const factors = data.top_x_factors || [];
        const factorsHtml = factors.map(f => `
          <div style="display:flex; justify-content:space-between; margin-bottom:6px; font-size:12px; border-bottom:1px dashed #dde0de; padding-bottom:4px;">
            <span><strong>${f.label || f.feature}</strong>${factorScopeTag(f)}: <span style="color:var(--muted);">${f.evidence}</span></span>
            <span style="font-weight:600; color:${f.impact === 'raises risk' ? '#c0392b' : '#27ae60'}">${f.impact === 'raises risk' ? '▲ 增加延遲風險' : '▼ 正常/次要'}</span>
          </div>
        `).join('');
        
        content.innerHTML = `
          <div style="display:flex; flex-direction:column; gap:10px;">
            <div style="font-weight:600; color:var(--navy); font-size:13px;">🔎 延遲特徵影響診斷 (LIME)：</div>
            <div style="background:white; border:1px solid var(--border); border-radius:6px; padding:12px; color:var(--text); line-height:1.6; font-weight:500;">
              ${buildManagerSummary(data)}
            </div>
            <div style="margin-top:6px;">
              <div style="font-weight:600; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:8px;">特徵對機率的影響權重：</div>
              <div style="display:flex; flex-direction:column; gap:6px;">
                ${factorsHtml || '<div style="color:var(--muted); font-size:12px;">無明顯特徵影響</div>'}
              </div>
            </div>
          </div>
        `;
      } catch (e) {
        content.textContent = '分析載入失敗：' + e.message;
      }
    }
  } else {
    row.classList.add('hidden');
    if (btn) btn.textContent = '▶';
  }
}

// Bind to window
window.refreshDashboard = refreshDashboard;
window.renderMetrics = renderMetrics;
window.renderExecutiveSummary = renderExecutiveSummary;
window.fillClass = fillClass;
window.pillClass = pillClass;
window.getReasonText = getReasonText;
window.getActionText = getActionText;
window.openDashboardSimulator = openDashboardSimulator;
window.openRecommendedOptimization = openRecommendedOptimization;
window.renderBossTable = renderBossTable;
window.toggleRowExplanation = toggleRowExplanation;
