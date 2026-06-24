// ==========================================
// roi_simulator.js — 最佳化ROI模擬器 頁面邏輯
// 防 overflow：圖表先 destroy 再建；篩選只觸發 loadRoiPortfolio（不遞迴 loadRoiSimulator）。
// ==========================================

let _roiScatterChart = null;
let _roiLoaded = false;

const _fmtMoney = (v) => (v < 0 ? '-$' : '$') + Math.abs(Math.round(v)).toLocaleString();
const _fmtPct = (v) => (v * 100).toFixed(1) + '%';

const ROI_INFO = {
  penalty: ['SLA 延遲罰金', '每筆訂單延遲時估計付出的代價（退費/賠償/商譽）。調整它會即時重算「真價值」與相關 KPI。預設 $250，對齊最佳化調度。'],
  nos: ['真價值 Net-of-Service', '真價值 = 帳載利潤 − 實際延遲 × 罰金。用驗證集的「實際是否延遲」回填，揭露帳面賺錢、實際卻因延遲賠錢的訂單。'],
  fp: ['假性賺錢比例', '帳載利潤為正、但扣掉延遲代價後真價值變負的訂單，占所有帳面賺錢訂單的比例。比例越高代表帳面數字越不可信。'],
  epar: ['預期在險利潤 EPAR', 'EPAR = 帳載利潤 × 延遲機率 P(late)。代表「這筆利潤有多少暴露在延遲風險下」，數字越大越該優先介入。'],
  trust: ['Trust Map 校準', '用模型沒看過的「樣本外」測試集，比對預測 vs 實際：延遲看 AUC（0.5=亂猜、1=完美）、收益看 R²。藉「已知」背書「預測」在哪些客群可信。'],
};

function openRoiInfo(key, customTitle, customBody) {
  const modal = document.getElementById('roiInfoModal');
  if (!modal) return;
  if (customTitle) {
    document.getElementById('roiInfoTitle').textContent = customTitle;
    document.getElementById('roiInfoBody').innerHTML = customBody || '';
  } else {
    const info = ROI_INFO[key] || ['說明', ''];
    document.getElementById('roiInfoTitle').textContent = info[0];
    document.getElementById('roiInfoBody').textContent = info[1];
  }
  modal.style.display = 'flex';
}
function closeRoiInfo(e) {
  if (e && e.target && e.target.id && e.target.id !== 'roiInfoModal') return;
  const modal = document.getElementById('roiInfoModal');
  if (modal) modal.style.display = 'none';
}

function _roiPenalty() { return parseFloat(document.getElementById('roiPenalty')?.value) || 250; }

async function loadRoiSimulator() {
  syncRoiSimulatorRole();
  await loadRoiSummary();
  await loadRoiPortfolio();   // 也會在內部填客群/區域下拉
  loadRoiTrustMap();
  populateWhatifRegions();
}

async function loadRoiSummary() {
  try {
    const d = await fetch(`${API_BASE}/api/roi/summary?penalty=${_roiPenalty()}`).then(r => r.json());
    document.getElementById('roiBookProfit').textContent = _fmtMoney(d.book_profit_total);
    const nv = document.getElementById('roiNetValue');
    nv.textContent = _fmtMoney(d.net_of_service_total);
    nv.style.color = d.net_of_service_total < 0 ? 'var(--danger)' : 'var(--success)';
    document.getElementById('roiErosion').textContent = _fmtMoney(d.service_erosion_total);
    document.getElementById('roiFpPct').textContent = _fmtPct(d.false_positive_value_pct);
    document.getElementById('roiEpar').textContent = _fmtMoney(d.epar_total);
  } catch (e) { console.error('roi summary', e); }
}

function _populateOnce(selectId, values) {
  const sel = document.getElementById(selectId);
  if (!sel || sel.dataset.filled) return;
  values.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o); });
  sel.dataset.filled = '1';
}

async function loadRoiPortfolio() {
  const vAxis = document.getElementById('roiValueAxis').value;
  const rAxis = document.getElementById('roiRiskAxis').value;
  const seg = document.getElementById('roiSegFilter').value;
  const region = document.getElementById('roiRegionFilter').value;
  const disc = document.getElementById('roiDiscFilter').value;
  const qs = new URLSearchParams({ value_axis: vAxis, risk_axis: rAxis, penalty: _roiPenalty(), max_points: 1500 });
  if (seg) qs.set('segment', seg);
  if (region) qs.set('region', region);
  if (disc) qs.set('discount_band', disc);

  try {
    const d = await fetch(`${API_BASE}/api/roi/portfolio?${qs.toString()}`).then(r => r.json());
    _populateOnce('roiSegFilter', d.filters?.segments || []);
    _populateOnce('roiRegionFilter', d.filters?.regions || []);
    renderRoiScatter(d, vAxis, rAxis);
    renderAtRisk(d.at_risk_list || []);
    const note = document.getElementById('roiScatterNote');
    if (note) note.textContent = `符合篩選 ${d.total_filtered.toLocaleString()} 筆${d.truncated ? `，散點取樣顯示 ${d.points_returned} 筆（保護效能）` : ''}。`;
  } catch (e) { console.error('roi portfolio', e); }
}

function renderRoiScatter(d, vAxis, rAxis) {
  const canvas = document.getElementById('roiScatter');
  const fb = document.getElementById('roiScatterFallback');
  if (!window.Chart || !canvas) {
    if (canvas) canvas.style.display = 'none';
    if (fb) { fb.style.display = 'block'; fb.textContent = '圖表元件未載入，已改以名單呈現。'; }
    return;
  }
  if (fb) fb.style.display = 'none';
  canvas.style.display = 'block';
  const pts = (d.points || []).map(p => ({ x: p.risk, y: p.value, _p: p }));
  const colors = (d.points || []).map(p => p.fp ? 'rgba(192,57,43,0.65)' : 'rgba(67,112,150,0.5)');
  if (_roiScatterChart) { _roiScatterChart.destroy(); _roiScatterChart = null; }   // 防止重疊/記憶體堆積
  _roiScatterChart = new Chart(canvas.getContext('2d'), {
    type: 'scatter',
    data: { datasets: [{ data: pts, pointRadius: 3, pointHoverRadius: 6, backgroundColor: colors }] },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (c) => { const p = c.raw._p; return `${p.id} · 價值 ${_fmtMoney(p.value)} · 風險 ${p.risk}`; } } },
      },
      scales: {
        x: { title: { display: true, text: rAxis === 'true_label' ? '實際延遲 (0/1)' : '延遲機率 P(late)' } },
        y: { title: { display: true, text: vAxis === 'profit_actual' ? '帳載利潤 $' : '真價值 Net-of-Service $' } },
      },
      onClick: (evt, els) => {
        if (!els || !els.length) return;
        const p = pts[els[0].index]._p;
        openRoiInfo(null, `訂單 ${p.id}`,
          `<div style="line-height:2;">客群：${p.segment}<br>區域：${p.region}<br>價值：<b>${_fmtMoney(p.value)}</b><br>風險：<b>${p.risk}</b><br>EPAR：${_fmtMoney(p.epar)}<br>${p.fp ? '<span style=\"color:#c0392b;font-weight:700;\">⚠ 假性賺錢：帳面賺、實際賠</span>' : '✅ 非假性賺錢'}</div>`);
      },
    },
  });
}

function renderAtRisk(list) {
  document.getElementById('roiAtRiskCount').textContent = `${list.length} 筆`;
  const body = document.getElementById('roiAtRiskBody');
  if (!list.length) { body.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--muted)">無資料</td></tr>`; return; }
  body.innerHTML = list.map(o => `
    <tr>
      <td><span class="order-id">${o.id}</span></td>
      <td style="font-weight:700;">${_fmtMoney(o.epar)}</td>
      <td>${_fmtMoney(o.profit_actual)}</td>
      <td>${_fmtPct(o.p_late)}</td>
      <td>${o.segment}</td>
    </tr>`).join('');
}

async function loadRoiTrustMap() {
  try {
    const d = await fetch(`${API_BASE}/api/roi/trust-map`).then(r => r.json());
    renderTrustRows('trustDelay', d.delay?.by_segment || [], 'delay');
    renderTrustRows('trustProfit', (d.profit?.available ? d.profit.by_segment : []), 'profit');
    const note = document.getElementById('trustNote');
    if (note) note.textContent = d.note || '';
  } catch (e) { console.error('trust map', e); }
}

function _heatColor(t) { // t in 0..1 → red→green
  const r = Math.round(220 * (1 - t) + 39 * t), g = Math.round(64 * (1 - t) + 128 * t), b = 60;
  return `rgba(${r},${g},${b},0.20)`;
}
function renderTrustRows(elId, rows, kind) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!rows.length) { el.innerHTML = '<div style="font-size:12px;color:var(--muted);">無資料</div>'; return; }
  el.innerHTML = rows.map(r => {
    const score = kind === 'delay' ? (r.auc ?? 0) : (r.r2 ?? 0);
    const t = Math.max(0, Math.min(1, (score - 0.5) / 0.5));
    const metric = kind === 'delay' ? `AUC ${r.auc ?? '—'}` : `R² ${r.r2 ?? '—'}`;
    const detail = kind === 'delay'
      ? `延遲率 ${_fmtPct(r.late_rate)}、平均預測 ${_fmtPct(r.mean_p_late)}`
      : `MAE ${r.mae}、RMSE ${r.rmse}`;
    return `<div onclick="openRoiInfo('trust')" style="cursor:pointer; display:flex; justify-content:space-between; align-items:center; padding:9px 12px; border:1px solid var(--border); border-radius:8px; background:${_heatColor(t)};">
      <div><div style="font-weight:700; font-size:13px;">${r.group}</div><div style="font-size:11px; color:var(--muted);">${detail} · n=${r.n.toLocaleString()}</div></div>
      <div style="font-weight:700; font-family:monospace;">${metric}</div></div>`;
  }).join('');
}

function onRoiPenaltyChange() {
  // 罰金改變只重算 summary + portfolio（不重載整頁，避免重複請求堆疊）
  clearTimeout(window._roiPenaltyTimer);
  window._roiPenaltyTimer = setTimeout(() => { loadRoiSummary(); loadRoiPortfolio(); }, 350);
}

function syncRoiSimulatorRole() {
  const role = window.edisState?.currentRole || 'viewer';
  const isMgr = role === 'manager' || role === 'engineer';
  const runBtn = document.getElementById('roiOptRunBtn');
  const lock = document.getElementById('roiOptLockedBox');
  const badge = document.getElementById('roiOptRoleBadge');
  if (runBtn) runBtn.classList.toggle('hidden', !isMgr);
  if (lock) lock.classList.toggle('hidden', isMgr);
  if (badge) { badge.className = isMgr ? 'role-badge badge-manager' : 'role-badge badge-viewer'; badge.textContent = role === 'engineer' ? 'Engineer' : (role === 'manager' ? 'Manager' : 'Viewer'); }
}

async function runRoiOptimize() {
  const btn = document.getElementById('roiOptRunBtn');
  const payload = {
    budget: parseFloat(document.getElementById('roiBudget').value) || 5000,
    upgrade_cost: parseFloat(document.getElementById('roiUpgradeCost').value) || 80,
    delay_penalty: parseFloat(document.getElementById('roiOptPenalty').value) || 250,
    risk_threshold: parseFloat(document.getElementById('roiRiskThreshold').value) || 0.3,
  };
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>計算中...'; }
  try {
    const res = await fetch(`${API_BASE}/api/roi/optimize`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    });
    if (!res.ok) { const e = await res.json().catch(() => ({})); throw new Error(e.detail?.message || e.detail || `HTTP ${res.status}`); }
    const d = await res.json();
    document.getElementById('roiOptResult').classList.remove('hidden');
    document.getElementById('roiOptSelected').textContent = d.selected_count ?? '--';
    document.getElementById('roiOptSaving').textContent = _fmtMoney(d.expected_total_saving || 0);
    document.getElementById('roiOptCost').textContent = _fmtMoney(d.total_cost || 0);
    document.getElementById('roiOptPool').textContent = (d.candidate_pool || 0).toLocaleString();
    document.getElementById('roiCustRollupBody').innerHTML = (d.customer_rollup || []).map(c => `
      <tr><td><span class="order-id">${c.customer}</span></td><td>${c.orders}</td><td style="font-weight:700;">${_fmtMoney(c.epar)}</td><td class="green">${_fmtMoney(c.net_benefit)}</td></tr>`).join('')
      || `<tr><td colspan="4" style="text-align:center;padding:16px;color:var(--muted)">無</td></tr>`;
    document.getElementById('roiSelOrdBody').innerHTML = (d.selected_orders || []).slice(0, 80).map(o => `
      <tr><td><span class="order-id">${o.display_order_id || o.order_id_hash?.slice(0,8)}</span></td><td>${_fmtPct(o.p_late)}</td><td class="green">${_fmtMoney(o.net_benefit ?? o.expected_saving ?? 0)}</td><td>$${o.upgrade_cost}</td></tr>`).join('')
      || `<tr><td colspan="4" style="text-align:center;padding:16px;color:var(--muted)">無</td></tr>`;
  } catch (e) {
    showToast('ROI 最佳化失敗：' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '執行 ROI 最佳化'; }
  }
}

function populateWhatifRegions() {
  const sel = document.getElementById('wfRegion');
  if (!sel || sel.dataset.filled) return;
  const src = document.getElementById('roiRegionFilter');
  const regions = src ? Array.from(src.options).map(o => o.value).filter(Boolean) : [];
  (regions.length ? regions : ['Western Europe', 'Central America', 'South America', 'North America', 'East Asia']).forEach(v => {
    const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o);
  });
  sel.dataset.filled = '1';
}

async function runWhatif() {
  const btn = document.getElementById('wfRunBtn');
  const payload = {
    customer_segment: document.getElementById('wfSegment').value,
    order_region: document.getElementById('wfRegion').value || 'Western Europe',
    category_name: document.getElementById('wfCategory').value || 'Cleats',
    market: document.getElementById('wfMarket').value,
    product_price: parseFloat(document.getElementById('wfPrice').value) || 59.99,
    order_item_quantity: parseInt(document.getElementById('wfQty').value) || 1,
    days_for_shipment: parseFloat(document.getElementById('wfDays').value) || 4,
    discount_grid: [0, 0.05, 0.1, 0.15, 0.2, 0.25],
    mode_grid: ['Standard Class', 'Second Class', 'First Class', 'Same Day'],
    penalty: _roiPenalty(),
  };
  if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>掃描中...'; }
  try {
    const d = await fetch(`${API_BASE}/api/roi/whatif`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
    }).then(r => r.json());
    document.getElementById('wfResult').classList.remove('hidden');
    const b = d.best || {};
    const good = (b.expected_net || 0) > 0;
    document.getElementById('wfBest').innerHTML =
      `<b>建議：${d.decision}</b><br>最佳組合：折扣 <b>${_fmtPct(b.discount_rate || 0)}</b> × <b>${b.shipping_mode}</b> → 預測收益 ${_fmtMoney(b.profit_pred || 0)}、延遲機率 ${_fmtPct(b.p_late || 0)}、<b style="color:${good ? '#15803d' : '#b91c1c'}">預期淨值 ${_fmtMoney(b.expected_net || 0)}</b>`;
    renderWhatifHeatmap(d);
  } catch (e) {
    showToast('What-if 失敗：' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.innerHTML = '執行 What-if 掃描'; }
  }
}

function renderWhatifHeatmap(d) {
  const cells = d.grid || [];
  if (!cells.length) { document.getElementById('wfHeatmap').innerHTML = '無資料'; return; }
  const nets = cells.map(c => c.expected_net);
  const min = Math.min(...nets), max = Math.max(...nets), span = (max - min) || 1;
  const modes = d.modes || [];
  const discounts = d.discounts || [];
  const lookup = {};
  cells.forEach(c => { lookup[`${c.discount_rate}|${c.shipping_mode}`] = c; });
  let html = '<table style="border-collapse:collapse; font-size:12px;"><thead><tr><th style="padding:6px 10px; text-align:left; color:var(--muted);">折扣＼運送</th>';
  modes.forEach(m => html += `<th style="padding:6px 10px; color:var(--muted); font-weight:600;">${m}</th>`);
  html += '</tr></thead><tbody>';
  discounts.forEach(disc => {
    html += `<tr><td style="padding:6px 10px; font-weight:600;">${_fmtPct(disc)}</td>`;
    modes.forEach(m => {
      const c = lookup[`${disc}|${m}`];
      if (!c) { html += '<td></td>'; return; }
      const t = (c.expected_net - min) / span;
      const r = Math.round(220 * (1 - t) + 39 * t), g = Math.round(64 * (1 - t) + 128 * t);
      html += `<td onclick='openRoiInfo(null, "折扣 ${_fmtPct(disc)} × ${m}", "預測收益：${_fmtMoney(c.profit_pred)}<br>延遲機率：${_fmtPct(c.p_late)}<br><b>預期淨值：${_fmtMoney(c.expected_net)}</b>")' style="cursor:pointer; padding:10px 12px; text-align:center; background:rgba(${r},${g},60,0.22); border:1px solid var(--border); font-weight:700;">${_fmtMoney(c.expected_net)}</td>`;
    });
    html += '</tr>';
  });
  html += '</tbody></table>';
  document.getElementById('wfHeatmap').innerHTML = html;
}

// 對外掛載
window.loadRoiSimulator = loadRoiSimulator;
window.loadRoiPortfolio = loadRoiPortfolio;
window.onRoiPenaltyChange = onRoiPenaltyChange;
window.runRoiOptimize = runRoiOptimize;
window.runWhatif = runWhatif;
window.openRoiInfo = openRoiInfo;
window.closeRoiInfo = closeRoiInfo;
window.syncRoiSimulatorRole = syncRoiSimulatorRole;
