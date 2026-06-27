// ==========================================
// roi_simulator.js — 最佳化ROI模擬器 頁面邏輯
// 防 overflow：圖表先 destroy 再建；篩選只觸發 loadRoiPortfolio（不遞迴 loadRoiSimulator）。
// ==========================================

let _roiScatterChart = null;
let _roiLoaded = false;
let _roiViewMode = 'scatter';
let _roiAtRiskPage = 1;
const ROI_COMPONENT_VERSION = 'roi-kpi-vertical-v2';

function normalizeRoiKpiCards() {
  const row = document.getElementById('roiKpiRow');
  if (!row) return;

  if (!document.getElementById('roiKpiRuntimeStyle')) {
    const style = document.createElement('style');
    style.id = 'roiKpiRuntimeStyle';
    style.textContent = `
      #roiKpiRow {
        display: grid !important;
        grid-template-columns: repeat(5, minmax(0, 1fr)) !important;
        gap: 14px !important;
        margin-bottom: 18px !important;
      }
      #roiKpiRow > .kpi-card,
      #roiKpiRow > .roi-kpi-card {
        display: flex !important;
        flex-direction: column !important;
        align-items: flex-start !important;
        justify-content: center !important;
        gap: 0 !important;
        min-height: 142px !important;
        padding: 28px 30px !important;
      }
      #roiKpiRow .kpi-icon-wrap { display: none !important; }
      #roiKpiRow .kpi-info,
      #roiKpiRow .roi-kpi-info { width: 100% !important; min-width: 0 !important; }
      #roiKpiRow .kpi-label,
      #roiKpiRow .roi-kpi-label {
        display: block !important;
        margin: 0 0 8px 0 !important;
        line-height: 1.35 !important;
        font-size: 12px !important;
        color: var(--muted) !important;
      }
      #roiKpiRow .kpi-value,
      #roiKpiRow .roi-kpi-value {
        display: block !important;
        width: 100% !important;
        margin: 0 !important;
        font-size: clamp(22px, 1.9vw, 28px) !important;
        line-height: 1.05 !important;
        white-space: nowrap !important;
      }
      #roiKpiRow .kpi-foot,
      #roiKpiRow .roi-kpi-foot {
        display: block !important;
        margin-top: 8px !important;
        font-size: 11px !important;
        line-height: 1.4 !important;
        color: var(--muted) !important;
      }
    `;
    document.head.appendChild(style);
  }

  row.querySelectorAll(':scope > .kpi-card').forEach(card => {
    card.classList.add('roi-kpi-card');
  });
}

function changeRoiViewMode(mode) {
  _roiViewMode = mode;
  const scatterBtn = document.getElementById('roiViewModeScatter');
  const quadBtn = document.getElementById('roiViewModeQuadrant');
  if (scatterBtn && quadBtn) {
    if (mode === 'scatter') {
      scatterBtn.style.background = 'var(--primary)';
      scatterBtn.style.color = 'white';
      quadBtn.style.background = 'transparent';
      quadBtn.style.color = 'var(--muted)';
    } else {
      quadBtn.style.background = 'var(--primary)';
      quadBtn.style.color = 'white';
      scatterBtn.style.background = 'transparent';
      scatterBtn.style.color = 'var(--muted)';
    }
  }
  loadRoiPortfolio();
}

const _fmtMoney = (v) => (v < 0 ? '-$' : '$') + Math.abs(Math.round(v)).toLocaleString();
const _fmtPct = (v) => (v * 100).toFixed(1) + '%';
function _numberFromInput(id, fallback) {
  const n = parseFloat(document.getElementById(id)?.value);
  return Number.isFinite(n) ? n : fallback;
}

function renderRoiScope(scope) {
  const el = document.getElementById('roiDataScopeNote');
  if (!el || !scope) return;
  el.textContent = scope.note || '';
}

const ROI_INFO = {
  penalty: ['SLA 延遲罰金', '每筆訂單延遲時估計付出的代價（退費/賠償/商譽）。調整它會即時重算「真價值」與相關 KPI。預設 $250，對齊最佳化調度。'],
  nos: ['真價值 Net-of-Service', '真價值 = 帳載利潤 − 實際延遲 × 罰金。用驗證集的「實際是否延遲」回填，揭露帳面賺錢、實際卻因延遲賠錢的訂單。'],
  fp: ['假性賺錢比例', '帳載利潤為正、但扣掉延遲代價後真價值變負的訂單，占所有帳面賺錢訂單的比例。比例越高代表帳面數字越不可信。'],
  epar: ['預估風險暴露金額', '利潤暴露在延遲機率下的風險值，即 EPAR = 帳載利潤 × 延遲機率。代表「這筆利潤有多少暴露在延遲風險下」，數字越大越該優先介入。'],
  trust: ['Trust Map 校準說明', '以模型未看過的測試集比對預測 vs 實際。將機器學習指標轉譯為白話的信心等級，綠色為「高度可信」，黃色為「中度可信」，紅色代表「需謹慎參考」。'],
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

function _roiPenalty() { return _numberFromInput('roiPenalty', 250); }

function setRoiPenalty(v) {
  const el = document.getElementById('roiPenalty');
  if (!el) return;
  el.value = v;
  onRoiPenaltyChange();
}
window.setRoiPenalty = setRoiPenalty;

async function loadRoiSimulator() {
  // 項目2/6：ROI 最佳化求解與 What-if 前端已移除，相關呼叫停用（後端保留）。
  normalizeRoiKpiCards();
  await loadRoiSummary();
  await loadRoiPortfolio();   // 也會在內部填客群/區域下拉
  loadRoiTrustMap();
}

// 項目4：把 ROI 分析區動態載入「最佳化調度」頁的 #optRoiAnalysis（只載一次）
async function loadEmbeddedRoi() {
  const host = document.getElementById('optRoiAnalysis');
  if (!host) return;
  if (!host.dataset.loaded || host.dataset.roiVersion !== ROI_COMPONENT_VERSION || host.querySelector('#roiKpiRow > .kpi-card')) {
    try {
      const r = await fetch(`/static/components/roi_simulator.html?v=${ROI_COMPONENT_VERSION}`, { cache: 'no-store' });
      host.innerHTML = await r.text();
      // 移除內嵌 page-header（避免與最佳化調度頁標題重複）
      const hdr = host.querySelector('.page-header');
      if (hdr) hdr.remove();
      host.dataset.loaded = '1';
      host.dataset.roiVersion = ROI_COMPONENT_VERSION;
    } catch (e) {
      host.innerHTML = `<div style="color:red;padding:20px;">ROI 分析載入失敗：${e.message}</div>`;
      return;
    }
  }
  normalizeRoiKpiCards();
  loadRoiSimulator();
}
window.loadEmbeddedRoi = loadEmbeddedRoi;

async function loadRoiSummary() {
  try {
    const d = await fetch(`${API_BASE}/api/roi/summary?penalty=${_roiPenalty()}`).then(r => r.json());
    document.getElementById('roiBookProfit').textContent = _fmtMoney(d.book_profit_total);
    const nv = document.getElementById('roiNetValue');
    nv.textContent = _fmtMoney(d.net_of_service_total);
    nv.style.color = d.net_of_service_total < 0 ? 'var(--danger)' : 'var(--success)';
    document.getElementById('roiErosion').textContent = _fmtMoney(d.service_erosion_total);
    document.getElementById('roiFpPct').textContent = d.false_positive_available === false ? 'N/A' : _fmtPct(d.false_positive_value_pct);
    document.getElementById('roiEpar').textContent = _fmtMoney(d.epar_total);
    renderRoiScope(d.data_scope);
  } catch (e) { console.error('roi summary', e); }
}

function _populateOnce(selectId, values) {
  const sel = document.getElementById(selectId);
  if (!sel) return;
  const signature = JSON.stringify(values || []);
  if (sel.dataset.signature === signature) return;
  const current = sel.value;
  const first = sel.options[0] ? sel.options[0].cloneNode(true) : null;
  sel.innerHTML = '';
  if (first) sel.appendChild(first);
  values.forEach(v => { const o = document.createElement('option'); o.value = v; o.textContent = v; sel.appendChild(o); });
  sel.value = (values || []).includes(current) ? current : '';
  sel.dataset.signature = signature;
}

async function loadRoiPortfolio() {
  const vAxis = document.getElementById('roiValueAxis').value;
  const rAxis = document.getElementById('roiRiskAxis').value;
  const seg = document.getElementById('roiSegFilter').value;
  const region = document.getElementById('roiRegionFilter').value;
  const disc = document.getElementById('roiDiscFilter').value;
  const qs = new URLSearchParams({ value_axis: vAxis, risk_axis: rAxis, penalty: _roiPenalty(), max_points: 1500, at_risk_page: _roiAtRiskPage, at_risk_limit: 50 });
  if (seg) qs.set('segment', seg);
  if (region) qs.set('region', region);
  if (disc) qs.set('discount_band', disc);

  try {
    const d = await fetch(`${API_BASE}/api/roi/portfolio?${qs.toString()}`).then(r => r.json());
    _populateOnce('roiSegFilter', d.filters?.segments || []);
    _populateOnce('roiRegionFilter', d.filters?.regions || []);
    renderRoiScope(d.data_scope);
    renderRoiScatter(d, vAxis, rAxis);
    renderAtRisk(d.at_risk_list || [], d);
    const note = document.getElementById('roiScatterNote');
    if (note) {
      const fallbackRisk = d.risk_axis !== d.risk_axis_effective ? '；此資料沒有實際延遲答案，風險軸已改用 P(late)' : '';
      note.textContent = `符合篩選 ${d.total_filtered.toLocaleString()} 筆${d.truncated ? `，散點取樣顯示 ${d.points_returned} 筆（保護效能）` : ''}${fallbackRisk}。`;
    }
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

  let colors;
  let datasets = [];

  if (_roiViewMode === 'quadrant') {
    const minX = 0, maxX = 1;
    const yValues = pts.map(p => p.y);
    const minY = yValues.length ? Math.min(...yValues) : -500;
    const maxY = yValues.length ? Math.max(...yValues) : 500;

    colors = (d.points || []).map(p => {
      const isHighRisk = p.risk >= 0.5;
      const isHighProfit = p.value >= 0;
      if (isHighProfit && isHighRisk) return 'rgba(230, 126, 34, 0.75)'; // Orange: High Profit, High Risk
      if (!isHighProfit && isHighRisk) return 'rgba(192, 57, 43, 0.8)'; // Red: Low Profit, High Risk
      if (isHighProfit && !isHighRisk) return 'rgba(46, 204, 113, 0.75)'; // Green: High Profit, Low Risk
      return 'rgba(127, 140, 141, 0.65)'; // Gray: Low Profit, Low Risk
    });

    datasets.push({
      label: '訂單',
      data: pts,
      pointRadius: 3.5,
      pointHoverRadius: 6,
      backgroundColor: colors
    });

    // Horizontal line at y=0
    datasets.push({
      label: '價值分界線',
      data: [{ x: minX, y: 0 }, { x: maxX, y: 0 }],
      borderColor: 'rgba(15, 23, 42, 0.45)',
      borderWidth: 1.5,
      borderDash: [5, 5],
      pointRadius: 0,
      showLine: true,
      type: 'line'
    });

    // Vertical line at x=0.5
    datasets.push({
      label: '風險分界線',
      data: [{ x: 0.5, y: minY }, { x: 0.5, y: maxY }],
      borderColor: 'rgba(15, 23, 42, 0.45)',
      borderWidth: 1.5,
      borderDash: [5, 5],
      pointRadius: 0,
      showLine: true,
      type: 'line'
    });
  } else {
    colors = (d.points || []).map(p => p.fp ? 'rgba(192,57,43,0.65)' : 'rgba(67,112,150,0.5)');
    datasets.push({
      data: pts,
      pointRadius: 3,
      pointHoverRadius: 6,
      backgroundColor: colors
    });
  }

  if (_roiScatterChart) { _roiScatterChart.destroy(); _roiScatterChart = null; }

  const riskTitle = (d.risk_axis_effective || rAxis) === 'true_label' ? '實際延遲 (0/1)' : '延遲機率 P(late)';
  _roiScatterChart = new Chart(canvas.getContext('2d'), {
    type: 'scatter',
    data: { datasets: datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (c) => {
              if (c.datasetIndex !== 0) return '';
              const p = c.raw._p;
              return `${p.id} · 價值 ${_fmtMoney(p.value)} · 風險 ${p.risk}`;
            }
          }
        },
      },
      scales: {
        x: { min: 0, max: 1, title: { display: true, text: riskTitle } },
        y: { title: { display: true, text: vAxis === 'profit_actual' ? '帳載利潤 $' : '真價值 Net-of-Service $' } },
      },
      onClick: (evt, els) => {
        if (!els || !els.length) return;
        if (els[0].datasetIndex !== 0) return; // Only trigger click on order points dataset
        const p = pts[els[0].index]._p;
        openRoiInfo(null, `訂單 ${p.id}`,
          `<div style="line-height:2;">客群：${p.segment}<br>區域：${p.region}<br>價值：<b>${_fmtMoney(p.value)}</b><br>風險：${p.risk}<br>在險利潤：${_fmtMoney(p.epar)}<br>${p.fp ? '<span style=\"color:#c0392b;font-weight:700;\">⚠ 假性賺錢：帳面賺、實際賠</span>' : '✅ 非假性賺錢'}</div>`);
      },
    },
  });
}

function renderAtRisk(list, d) {
  const total = d?.at_risk_total ?? list.length;
  const page = d?.at_risk_page ?? 1;
  const pages = d?.at_risk_pages ?? 1;
  document.getElementById('roiAtRiskCount').textContent = `${total.toLocaleString()} 筆`;
  const body = document.getElementById('roiAtRiskBody');
  if (!list.length) { body.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--muted)">無資料</td></tr>`; }
  else {
    body.innerHTML = list.map(o => `
      <tr>
        <td><span class="order-id">${o.id}</span></td>
        <td style="font-weight:700;">${_fmtMoney(o.epar)}</td>
        <td>${_fmtMoney(o.profit_actual)}</td>
        <td>${_fmtPct(o.p_late)}</td>
        <td>${o.segment}</td>
      </tr>`).join('');
  }
  const ind = document.getElementById('roiAtRiskPageIndicator');
  if (ind) ind.textContent = `第 ${page} / ${pages} 頁`;
  const prev = document.getElementById('roiAtRiskPrev');
  const next = document.getElementById('roiAtRiskNext');
  if (prev) { prev.disabled = page <= 1; prev.style.opacity = page <= 1 ? 0.5 : 1; }
  if (next) { next.disabled = page >= pages; next.style.opacity = page >= pages ? 0.5 : 1; }
}

function changeAtRiskPage(delta) {
  _roiAtRiskPage = Math.max(1, _roiAtRiskPage + delta);
  loadRoiPortfolio();
}
window.changeAtRiskPage = changeAtRiskPage;

async function loadRoiTrustMap() {
  try {
    const d = await fetch(`${API_BASE}/api/roi/trust-map`).then(r => r.json());
    renderTrustRows('trustDelay', d.delay?.by_segment || [], 'delay');
    renderTrustRows('trustProfit', (d.profit?.available ? d.profit.by_segment : []), 'profit');
    const note = document.getElementById('trustNote');
    if (note) note.textContent = d.note || '';
  } catch (e) { console.error('trust map', e); }
}

function renderTrustRows(elId, rows, kind) {
  const el = document.getElementById(elId);
  if (!el) return;
  if (!rows.length) { el.innerHTML = '<div style="font-size:12px;color:var(--muted);">無資料</div>'; return; }
  el.innerHTML = rows.map(r => {
    const score = kind === 'delay' ? (r.auc ?? 0) : (r.r2 ?? 0);

    // Determine semantic confidence status
    let confidenceText = '高度可信 (Very Reliable)';
    let borderStyle = '1px solid var(--success)';
    let bg = 'rgba(46, 204, 113, 0.12)';

    if (kind === 'delay') {
      if (score < 0.70) {
        confidenceText = '需謹慎參考 (Use Caution)';
        borderStyle = '1px solid var(--danger)';
        bg = 'rgba(231, 76, 60, 0.12)';
      } else if (score < 0.80) {
        confidenceText = '中度可信 (Reliable)';
        borderStyle = '1px solid var(--warning)';
        bg = 'rgba(241, 196, 15, 0.12)';
      }
    } else {
      if (score < 0.40) {
        confidenceText = '需謹慎參考 (Use Caution)';
        borderStyle = '1px solid var(--danger)';
        bg = 'rgba(231, 76, 60, 0.12)';
      } else if (score < 0.60) {
        confidenceText = '中度可信 (Reliable)';
        borderStyle = '1px solid var(--warning)';
        bg = 'rgba(241, 196, 15, 0.12)';
      }
    }

    const metric = kind === 'delay' ? `AUC ${r.auc ?? '—'}` : `R² ${r.r2 ?? '—'}`;
    const detail = kind === 'delay'
      ? `延遲率 ${_fmtPct(r.late_rate)} · 平均預測 ${_fmtPct(r.mean_p_late)} · n=${r.n.toLocaleString()}`
      : `MAE ${r.mae} · RMSE ${r.rmse} · n=${r.n.toLocaleString()}`;
    return `<div onclick="openRoiInfo('trust')" style="cursor:pointer; display:grid; grid-template-columns:minmax(0, 1fr) auto; gap:12px; align-items:center; min-height:64px; padding:10px 14px; border:${borderStyle}; border-radius:8px; background:${bg}; transition:all 0.2s;" onmouseover="this.style.transform='translateY(-1px)';" onmouseout="this.style.transform='none';">
      <div style="min-width:0;"><div style="font-weight:700; font-size:13px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${r.group}</div><div style="font-size:11px; color:var(--muted); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${detail}</div></div>
      <div style="font-weight:700; font-family:monospace; white-space:nowrap;">${metric}</div></div>`;
  }).join('');
}

function onRoiPenaltyChange() {
  // 罰金改變只重算 summary + portfolio（不重載整頁，避免重複請求堆疊）
  clearTimeout(window._roiPenaltyTimer);
  window._roiPenaltyTimer = setTimeout(() => { loadRoiSummary(); loadRoiPortfolio(); }, 350);
}

function jumpToOptimization() {
  const budget = _numberFromInput('roiBudget', 5000);
  const penalty = _numberFromInput('roiOptPenalty', 250);
  const threshold = _numberFromInput('roiRiskThreshold', 0.3);

  // Set global state or simply update the DOM elements in optimization page
  const optBudget = document.getElementById('optPageBudgetInput');
  const optPenalty = document.getElementById('optPageDelayPenalty');
  const optThreshold = document.getElementById('optPageRiskThreshold');

  if (optBudget) optBudget.value = budget;
  if (optPenalty) optPenalty.value = penalty;
  if (optThreshold) optThreshold.value = threshold;

  showPage('optimization');
}

function syncRoiSimulatorRole() {
  const role = window.edisState?.currentRole || 'viewer';
  const isMgr = role === 'manager' || role === 'engineer';
  const runBtn = document.getElementById('roiOptRunBtn');
  const pubBtn = document.getElementById('roiOptPublishBtn');
  const lock = document.getElementById('roiOptLockedBox');
  const badge = document.getElementById('roiOptRoleBadge');
  if (runBtn) runBtn.classList.toggle('hidden', !isMgr);
  if (pubBtn) pubBtn.classList.toggle('hidden', !isMgr);
  if (lock) lock.classList.add('hidden');
  if (badge) { badge.className = isMgr ? 'role-badge badge-manager' : 'role-badge badge-viewer'; badge.textContent = role === 'engineer' ? 'Engineer' : (role === 'manager' ? 'Manager' : 'Viewer'); }
}

async function runRoiOptimize() {
  const btn = document.getElementById('roiOptRunBtn');
  const payload = {
    budget: _numberFromInput('roiBudget', 5000),
    upgrade_cost: _numberFromInput('roiUpgradeCost', 80),
    delay_penalty: _numberFromInput('roiOptPenalty', 250),
    risk_threshold: _numberFromInput('roiRiskThreshold', 0.3),
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
      <tr><td><span class="order-id">${o.display_order_id || o.order_id_hash?.slice(0, 8)}</span></td><td>${_fmtPct(o.p_late)}</td><td class="green">${_fmtMoney(o.net_benefit ?? o.expected_saving ?? 0)}</td><td>$${o.upgrade_cost}</td></tr>`).join('')
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

    // Generate Consultant Advisory Card
    const card = document.getElementById('wfAdvisoryCard');
    if (card) {
      card.style.display = 'block';
      let statusColor = 'var(--warning)';
      let borderLeftColor = 'var(--warning)';
      let background = 'linear-gradient(135deg, #fffcf5 0%, #fff6e0 100%)';
      let fontColor = '#5c3e00';
      let icon = '⚠️ 建議監控/升級';
      let title = '顧問決策建議';

      const nos = b.expected_net || 0;
      const erosion = (b.profit_pred || 0) - nos;
      const erosionPct = b.profit_pred > 0 ? (erosion / b.profit_pred * 100) : 0;

      let advText = '';
      if (nos < 0) {
        statusColor = 'var(--danger)';
        borderLeftColor = 'var(--danger)';
        background = 'linear-gradient(135deg, #fdf2f2 0%, #fde8e8 100%)';
        fontColor = '#9b1c1c';
        icon = '❌ 建議拒單';
        advText = `此折扣組合預期淨利潤為負 (${_fmtMoney(nos)})。主要是延遲機率高達 ${_fmtPct(b.p_late)}，預期服務代價侵蝕利潤達 ${_fmtMoney(erosion)} (${erosionPct.toFixed(1)}%)，嚴重破壞訂單價值。建議調整運送承諾或提高價格。`;
      } else if (b.p_late > 0.40) {
        icon = '⚠️ 建議監控/升級';
        advText = `本單雖有淨值 (${_fmtMoney(nos)})，但延遲風險達 ${_fmtPct(b.p_late)}。此類合約在實務上隨時可能因罰金發生侵蝕。若要接單，建議在出貨時使用快捷物流，或將折扣降低 5-10% 以保留利潤安全邊際。`;
      } else {
        statusColor = 'var(--success)';
        borderLeftColor = 'var(--success)';
        background = 'linear-gradient(135deg, #f3faf7 0%, #e6f6f0 100%)';
        fontColor = '#03543f';
        icon = '✅ 建議接單';
        advText = `本單具有良好的利潤結構，且預估延遲機率極低 (${_fmtPct(b.p_late)})。預估真價值達 ${_fmtMoney(nos)}。這屬於高回報、低風險的優質訂單，建議立即依此條件進行簽約與排產。`;
      }

      card.style.background = background;
      card.style.borderLeft = `4px solid ${borderLeftColor}`;
      card.style.color = fontColor;
      card.innerHTML = `<div style="font-weight:700; font-size:14px; margin-bottom:4px;">${icon} - ${title}</div><div>${advText}</div>`;
    }

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
window.changeRoiViewMode = changeRoiViewMode;
