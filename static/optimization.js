// ==========================================
// optimization.js — EDIS 最佳化求解與情境分析頁面邏輯
// ==========================================

async function runOptimize() {
  const btn = document.getElementById('runBtn');
  const budget = parseFloat(document.getElementById('budgetInput').value) || 5000;
  if (btn) {
    btn.innerHTML = '<span class="spinner"></span>計算中...';
    btn.disabled = true;
  }
  try {
    const data = await fetchOptimize(budget, 80, 250);
    renderOptResult(data);
  } catch(e) {
    alert(e.message);
  } finally {
    if (btn) {
      btn.innerHTML = '執行最佳化調度';
      btn.disabled = false;
    }
  }
}

async function runPageOptimize() {
  const btn = document.getElementById('optPageRunBtn');
  const placeholder = document.getElementById('optPageResultPlaceholder');
  const resultPanel = document.getElementById('optPageResult');
  
  const budget = parseFloat(document.getElementById('optPageBudgetInput').value) || 5000;
  const upgradeCost = parseFloat(document.getElementById('optPageUpgradeCost').value) || 80;
  const delayPenalty = parseFloat(document.getElementById('optPageDelayPenalty').value) || 250;
  
  if (btn) {
    btn.innerHTML = '<span class="spinner"></span>計算中...';
    btn.disabled = true;
  }
  
  try {
    const data = await fetchOptimize(budget, upgradeCost, delayPenalty);
    
    if (placeholder) placeholder.classList.add('hidden');
    if (resultPanel) resultPanel.classList.remove('hidden');
    
    document.getElementById('optPageSelected').textContent = data.selected_orders.length;
    document.getElementById('optPageSaving').textContent = '$' + data.expected_total_saving.toLocaleString();
    document.getElementById('optPageCost').textContent = '$' + data.total_cost.toLocaleString();
    
    const pct = ((data.total_cost / budget) * 100).toFixed(0);
    document.getElementById('optPageUsage').textContent = pct + '%';
    document.getElementById('optPageUsageFill').style.width = pct + '%';
    renderManagerAnalysis('optPageManagerAnalysisBox', 'optPageManagerAnalysisText', 'optPageManagerAnalysisFactors', data.manager_analysis);

    document.getElementById('optPageOrdList').innerHTML = data.selected_orders.map((o, i) => `
      <div class="ord-item" style="animation-delay:${i*0.03}s">
        <div>
          <div class="ord-id" title="${o.order_id_hash}">${o.display_order_id || displayOrderId(o.order_id_hash)}</div>
          <div class="ord-sub">升級成本 $${o.upgrade_cost} · 延遲機率 ${(o.p_late*100).toFixed(0)}% · ${o.reason || 'positive net benefit'}</div>
        </div>
        <div class="ord-saving">+$${(o.net_benefit ?? o.expected_saving).toLocaleString()}</div>
      </div>
    `).join('');
    
  } catch (e) {
    alert(e.message);
  } finally {
    if (btn) {
      btn.innerHTML = '開始計算最佳化調度方案';
      btn.disabled = false;
    }
  }
}

function renderOptResult(d) {
  const el = document.getElementById('optResult');
  if (el) {
    el.classList.remove('hidden');
    el.style.display = 'flex';
  }
  const _sel = Array.isArray(d.selected_orders) ? d.selected_orders : [];
  document.getElementById('optSelected').textContent = _sel.length;
  document.getElementById('optSaving').textContent = '$' + d.expected_total_saving.toLocaleString();
  document.getElementById('optCost').textContent = '$' + d.total_cost.toLocaleString();
  const pct = ((d.total_cost / d.budget) * 100).toFixed(0);
  document.getElementById('optUsage').textContent = pct + '%';
  document.getElementById('usageFill').style.width = pct + '%';
  renderManagerAnalysis('managerAnalysisBox', 'managerAnalysisText', 'managerAnalysisFactors', d.manager_analysis);

  const list = document.getElementById('ordList');
  if (list) {
    list.innerHTML = _sel.map((o, i) => `
      <div class="ord-item" style="animation-delay:${i*0.07}s">
        <div>
          <div class="ord-id" title="${o.order_id_hash}">${o.display_order_id || displayOrderId(o.order_id_hash)}</div>
          <div class="ord-sub">升級成本 $${o.upgrade_cost} · 延遲率 ${(o.p_late*100).toFixed(0)}% · ${o.reason || 'positive net benefit'}</div>
        </div>
        <div class="ord-saving">+$${(o.net_benefit ?? o.expected_saving).toLocaleString()}</div>
      </div>
    `).join('');
  }
}

function renderBudgetScenarios(d) {
  const scenarios = d.scenarios || [];
  const countTag = document.getElementById('scenarioCount');
  if (countTag) countTag.textContent = `${scenarios.length} 個情境`;
  
  const recommendText = document.getElementById('scenarioRecommendation');
  if (recommendText) recommendText.textContent = d.recommendation || '目前沒有情境建議。';

  const tbody = document.getElementById('scenarioTableBody');
  if (!tbody) return;
  if (!scenarios.length) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:24px;color:var(--muted);font-size:13px">尚無情境資料</td></tr>`;
    return;
  }
  tbody.innerHTML = scenarios.map(s => `
    <tr>
      <td><span class="order-id">$${Math.round(s.budget).toLocaleString()}</span></td>
      <td>${Number(s.selected_count || 0).toLocaleString()} 筆</td>
      <td>$${Math.round(s.total_cost || 0).toLocaleString()}</td>
      <td>$${Math.round(s.expected_total_penalty_avoided || 0).toLocaleString()}</td>
      <td style="font-weight:700;color:${(s.expected_total_saving || 0) >= 0 ? '#15803d' : '#b91c1c'}">$${Math.round(s.expected_total_saving || 0).toLocaleString()}</td>
      <td>${Number(s.budget_usage_pct || 0).toFixed(0)}%</td>
    </tr>
  `).join('');
}

function renderManagerAnalysis(boxId, textId, factorsId, analysis) {
  const box = document.getElementById(boxId);
  const text = document.getElementById(textId);
  const factors = document.getElementById(factorsId);
  if (!box || !text || !factors) return;

  if (!analysis) {
    box.style.display = 'none';
    text.textContent = '';
    factors.innerHTML = '';
    return;
  }

  box.style.display = 'block';
  text.textContent = analysis.headline || analysis.recommended_policy || '目前沒有可顯示的主管分析摘要。';
  renderManagerFactors(factorsId, analysis.sample_order_explanations || []);
}

function renderManagerFactors(containerId, explanations) {
  const container = document.getElementById(containerId);
  if (!container) return;

  const factors = explanations
    .flatMap(e => e.top_x_factors || [])
    .slice(0, 4);

  if (!factors.length) {
    container.innerHTML = '<div style="font-size:12px;color:var(--muted);">尚無可顯示的 X 因子。</div>';
    return;
  }

  container.innerHTML = factors.map(f => `
    <div style="padding:9px 10px;border:1px solid var(--border);border-radius:6px;background:white;">
      <div style="display:flex;justify-content:space-between;gap:10px;align-items:center;">
        <span style="font-size:12px;font-weight:700;color:var(--text);">${f.label || f.feature}</span>
        <span style="font-size:11px;color:var(--muted);font-family:'DM Mono',monospace">${f.impact || 'context'}</span>
      </div>
      <div style="font-size:12px;color:var(--muted);line-height:1.5;margin-top:4px;">${f.evidence || '模型指出此因子會影響延遲風險。'}</div>
    </div>
  `).join('');
}

// Bind to window
window.runOptimize = runOptimize;
window.runPageOptimize = runPageOptimize;
window.renderOptResult = renderOptResult;
window.renderBudgetScenarios = renderBudgetScenarios;
window.renderManagerAnalysis = renderManagerAnalysis;
window.renderManagerFactors = renderManagerFactors;
