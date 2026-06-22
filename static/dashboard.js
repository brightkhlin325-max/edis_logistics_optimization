// ==========================================
// dashboard.js — EDIS 儀表板頁面渲染與問答看板邏輯
// ==========================================

async function refreshDashboard() {
  try {
    const [p, executive, scenarios, tuning] = await Promise.all([
      fetchPredictions(window.edisState.currentPage),
      fetchExecutiveSummary(),
      fetchScenarioAnalysis(),
      fetchThresholdTuning().catch(() => null)
    ]);
    if (p) {
      window.edisState.totalPredictionsCount = p.count || 0;
      renderBossTable(p.data || []);
      const m = await fetchMetrics();
      if (m) renderMetrics(m);
    }
    if (executive) renderExecutiveSummary(executive);
    if (scenarios) renderBudgetScenarios(scenarios);
    if (tuning) renderThresholdTuning(tuning);
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

  // Actionable Insights 決策 Banner 顯示邏輯
  const banner = document.getElementById('actionableInsightsBanner');
  const bannerText = document.getElementById('actionableInsightsText');
  const savings = (typeof d.net_savings === 'number')
    ? Math.max(0, d.net_savings)
    : Math.max(0, (d.expected_penalty_exposure || 0) - (d.recommended_budget || 0));
    
  if (banner && bannerText) {
    if ((d.recommended_budget || 0) > 0 && savings > 0) {
      banner.style.display = 'flex';
      bannerText.innerHTML = `建議投入物流預算 <strong>$${Math.round(d.recommended_budget).toLocaleString()}</strong>，可挽回 <strong>${d.positive_roi_orders.toLocaleString()}</strong> 筆訂單的延遲罰金損失，預估為公司省下淨額 <strong>$${Math.round(savings).toLocaleString()}</strong>！`;
    } else {
      banner.style.display = 'none';
    }
  }

  // 簡報區數據
  const slaRiskEl = document.getElementById('execSlaRisk');
  if (slaRiskEl) slaRiskEl.textContent = `${serviceLevel}%`;
  const slaRiskNoteEl = document.getElementById('execSlaRiskNote');
  if (slaRiskNoteEl) slaRiskNoteEl.textContent = `目標 90%，目前 ${d.at_risk_orders.toLocaleString()} 筆訂單高於風險門檻。`;
  
  const exposureEl = document.getElementById('execExposure');
  if (exposureEl) exposureEl.textContent = '$' + Math.round(d.expected_penalty_exposure || 0).toLocaleString();
  const exposureNoteEl = document.getElementById('execExposureNote');
  if (exposureNoteEl) exposureNoteEl.textContent = `約 ${atRiskRate}% 訂單可能影響準時交付。`;
  
  const budgetEl = document.getElementById('execBudget');
  if (budgetEl) budgetEl.textContent = '$' + Math.round(d.recommended_budget || 0).toLocaleString();
  const budgetNoteEl = document.getElementById('execBudgetNote');
  if (budgetNoteEl) budgetNoteEl.textContent = `${d.positive_roi_orders.toLocaleString()} 筆高風險訂單升級後有正淨效益。`;
  
  document.getElementById('execDriver').textContent = topRegion ? topRegion.label : (topMode ? topMode.label : '—');
  document.getElementById('execDriverNote').textContent = topRegion && topMode
    ? `${topRegion.label} 與 ${topMode.label} 是目前最主要的風險來源。`
    : '目前沒有明顯集中的區域或運送模式風險。';

  document.getElementById('execActionText').textContent = `${d.recommended_action} ${d.data_quality_note || ''}`;
}

function fillClass(p) {
  const num = typeof p === 'string' ? (p === 'High' ? 0.8 : p === 'Medium' ? 0.5 : 0.2) : p;
  return num >= 0.7 ? 'fill-high' : num >= 0.4 ? 'fill-med' : 'fill-low';
}
function pillClass(p) {
  const str = typeof p === 'number' ? (p >= 0.7 ? 'High' : p >= 0.4 ? 'Medium' : 'Low') : p;
  return str === 'High' ? 'r-high' : str === 'Medium' ? 'r-med' : 'r-low';
}

function getReasonText(o) {
  let factors = [];
  if (o.shipping_mode === "Standard Class") {
    factors.push("Standard Class (運送天數較長，風險高)");
  } else if (o.shipping_mode === "Same Day") {
    factors.push("Same Day (計劃天數緊湊，容錯低)");
  }
  if (o.p_late >= 0.7) {
    factors.push(`目的地區域 (${o.order_region || '未知'}) 風險性高`);
  }
  if (factors.length === 0) {
    factors.push("時效要求高與承諾天數過緊");
  }
  return factors.join(" 且 ");
}

function getActionText(o) {
  const expected_saving = o.expected_penalty - o.upgrade_cost;
  if (o.p_late >= window.edisState.threshold && expected_saving > 0) {
    return `<span class="risk-pill r-high" style="font-weight:600; cursor:pointer;" onclick="openExplainModal('${o.order_id_hash}')">💡 建議升級運送</span>`;
  }
  return `<span class="risk-pill r-low" style="font-weight:500; cursor:pointer;" onclick="openExplainModal('${o.order_id_hash}')">✔ 監控並維持原狀</span>`;
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
    
    const sm = o.shipping_mode || 'Standard Class';
    const reg = o.order_region || 'Western Europe';
    const days = o.days_for_shipment || 4;
    const price = o.product_price || 59.99;
    const qty = o.order_item_quantity || 1;
    const segment = o.customer_segment || 'Consumer';
    const market = o.market || 'Europe';
    const date = o.order_date || '';
    
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
            <div class="prob-bar"><div class="prob-fill ${fillClass(o.p_late)}" style="width:${o.p_late*100}%"></div></div>
            <span class="prob-val">${(o.p_late*100).toFixed(0)}%</span>
          </div>
        </td>
        <td style="font-size:11px; color:var(--muted);">${getReasonText(o)}</td>
        <td style="white-space:nowrap;">
          ${getActionText(o)}
          <button class="run-btn" style="width:auto; padding:2px 6px; font-size:10px; margin-left:6px; background:var(--steel);" onclick="loadOrderIntoSimulator('${sm}','${reg}',${days},${price},${qty},'${segment}','${market}','${date}')">🧪 模擬</button>
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
            <span><strong>${f.label || f.feature}</strong>: <span style="color:var(--muted);">${f.evidence}</span></span>
            <span style="font-weight:600; color:${f.impact === 'raises risk' ? '#c0392b' : '#27ae60'}">${f.impact === 'raises risk' ? '▲ 增加延遲風險' : '▼ 正常/次要'}</span>
          </div>
        `).join('');
        
        content.innerHTML = `
          <div style="display:flex; flex-direction:column; gap:10px;">
            <div style="font-weight:600; color:var(--navy); font-size:13px;">🔎 延遲特徵影響診斷 (LIME)：</div>
            <div style="background:white; border:1px solid var(--border); border-radius:6px; padding:12px; color:var(--text); line-height:1.6; font-weight:500;">
              ${data.manager_summary || '無摘要說明。'}
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
window.renderBossTable = renderBossTable;
window.toggleRowExplanation = toggleRowExplanation;
