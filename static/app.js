// ==========================================
// app.js — EDIS 前端核心業務與邏輯模組
// ==========================================

const API_BASE = window.location.origin;

// ── 1. 全域狀態管理 (Global State) ───────────────────────────────────────────
window.edisState = {
  currentRole: 'viewer',
  threshold: 0.50,               // 全域同步門檻值
  sopDefaultThreshold: 0.50,     // 公司 SOP 基準門檻
  isSandboxMode: false,          // Viewer 的沙盒模擬狀態
  totalPredictionsCount: 0,
  currentPage: 1,
  limit: 50,
  currentRiskListPage: 1,
  totalRiskListCount: 0,
  lastThresholdTuning: null,
  cachedRegions: null,
  cachedScenarios: null,
  monthlyAllData: [],
  flipperPageStart: 0,
  FLIPPER_PAGE_SIZE: 6,
  flipThreshold: 0.05,
  pendingRetrainSession: null,
  diagCurrentMonth: null,
  diagCurrentFactors: []
};

// ── 2. Fetch 攔截器 (夾帶 Auth Token, Session ID & 403 異常偵測) ───────────────
const originalFetch = window.fetch;
window.fetch = function (url, options) {
  options = options || {};
  options.headers = options.headers || {};
  
  const token = sessionStorage.getItem('edis_token');
  if (token) {
    options.headers['Authorization'] = 'Bearer ' + token;
  }
  const sessionId = sessionStorage.getItem('edis_session_id');
  if (sessionId) {
    options.headers['X-Session-ID'] = sessionId;
  }
  
  // 注入當前角色請求標頭，支援 RBAC 權限控管
  if (!options.headers['X-Role']) {
    options.headers['X-Role'] = window.edisState.currentRole === 'manager' ? 'Logistics_Manager' : 'Viewer';
  }

  return originalFetch(url, options).then(response => {
    // 403 Forbidden 偵測：當 Manager 功能被 Viewer 存取或權限失效時攔截
    if (response.status === 403 && window.edisState.currentRole === 'manager') {
      showToast('❌ 登入逾期或權限不足，請重新登入管理員帳號。', 'error');
      sessionStorage.removeItem('edis_token');
      window._managerAuthenticated = false;
      setRole('viewer');
    }
    return response;
  });
};

// ── 3. 頁面切換機制 (SPA SPA Routing) ──────────────────────────────────────────
function showPage(pageId) {
  // 更新側邊欄 Active 狀態
  document.querySelectorAll('.sidebar-nav .nav-item').forEach(el => {
    el.classList.remove('active');
  });
  const activeNav = document.getElementById(`nav-${pageId}`);
  if (activeNav) activeNav.classList.add('active');

  // 切換頁面區塊可見度
  document.querySelectorAll('.page-section').forEach(el => {
    el.classList.add('hidden');
  });
  const targetPage = document.getElementById(`page-${pageId}`);
  if (targetPage) targetPage.classList.remove('hidden');

  // 各頁面載入特定模組資料
  if (pageId === 'dashboard') {
    refreshDashboard();
  } else if (pageId === 'risk-list') {
    populateRegionDropdown();
    applyFilters();
    // 同時載入區域風險熱力圖與地圖
    loadRegionalRisk();
  } else if (pageId === 'optimization') {
    loadMonthlyChart();
  } else if (pageId === 'model-perf') {
    loadModelPerformance();
  } else if (pageId === 'region-map') {
    loadRegionalRisk();
  } else if (pageId === 'llm-settings') {
    loadLLMSettings();
  }
}

// ── 4. API 通訊端點 ─────────────────────────────────────────────────────────
async function fetchMetrics() {
  return fetch(`${API_BASE}/api/metrics?threshold=${window.edisState.threshold}`).then(r => r.json());
}

async function fetchThresholdTuning() {
  const url = `${API_BASE}/api/threshold-tuning?current_threshold=${window.edisState.threshold}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('門檻校準功能目前不可用。');
  return res.json();
}

async function fetchRegions() {
  if (window.edisState.cachedRegions) return window.edisState.cachedRegions;
  window.edisState.cachedRegions = await fetch(`${API_BASE}/api/regions`).then(r => r.json());
  return window.edisState.cachedRegions;
}

async function fetchExecutiveSummary() {
  return fetch(`${API_BASE}/api/executive-summary?threshold=${window.edisState.threshold}`).then(r => r.json());
}

async function fetchScenarioAnalysis() {
  if (window.edisState.cachedScenarios) return window.edisState.cachedScenarios;
  window.edisState.cachedScenarios = await fetch(`${API_BASE}/api/scenario-analysis?budgets=1000,3000,5000,10000`).then(r => r.json());
  return window.edisState.cachedScenarios;
}

async function fetchPredictions(page = 1, search = '', risk = '', shipping = '', region = '') {
  let url = `${API_BASE}/api/predict?page=${page}&limit=${window.edisState.limit}&threshold=${window.edisState.threshold}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (risk) url += `&risk=${encodeURIComponent(risk)}`;
  if (shipping) url += `&shipping=${encodeURIComponent(shipping)}`;
  if (region) url += `&region=${encodeURIComponent(region)}`;
  return fetch(url).then(r => r.json());
}

async function fetchOptimize(budget, upgradeCost, delayPenalty) {
  const response = await fetch(`${API_BASE}/api/optimize`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      budget,
      upgrade_cost: upgradeCost,
      delay_penalty: delayPenalty,
      risk_threshold: window.edisState.threshold
    })
  });
  if (!response.ok) {
    const err = await response.json().catch(() => ({}));
    throw new Error(err.detail?.message || err.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

// ── 5. 全域 Threshold 狀態同步 ───────────────────────────────────────────────
function updateThreshold(val) {
  const num = parseFloat(val);
  window.edisState.threshold = num;
  
  // 同步所有存在於頁面中的 Slider 與數值顯示
  const slider1 = document.getElementById('thresholdSlider');
  const display1 = document.getElementById('thresholdValDisplay');
  if (slider1) slider1.value = num.toFixed(2);
  if (display1) display1.textContent = num.toFixed(2);

  const slider2 = document.getElementById('perfThresholdSlider');
  const display2 = document.getElementById('perfThresholdDisplay');
  if (slider2) slider2.value = num.toFixed(2);
  if (display2) display2.textContent = num.toFixed(2);

  refreshDashboard();
  if (!document.getElementById('page-model-perf').classList.contains('hidden')) {
    loadModelPerformance();
  }
}

// ── 6. SOP 與沙盒模擬控制 (Viewer & Manager 權限防禦) ──────────────────────────
function updateSopUI() {
  const slider = document.getElementById('thresholdSlider');
  const lockWrap = document.getElementById('sopStatusLockWrap');
  const badge = document.getElementById('sopRoleBadge');
  if (!slider) return;

  const badgeSpan = (bg, color, border, text) =>
    `<span style="background:${bg}; color:${color}; border:1px solid ${border}; border-radius:20px; padding:3px 12px; font-size:11px; font-weight:700; display:inline-block;">${text}</span>`;

  if (window.edisState.currentRole === 'manager') {
    window.edisState.isSandboxMode = false;
    slider.disabled = false;
    if (badge) badge.innerHTML = badgeSpan('rgba(5,150,105,0.1)', '#059669', 'rgba(5,150,105,0.3)', '● 管理者模式');
    if (lockWrap) {
      lockWrap.innerHTML = `
        <button onclick="publishSopThreshold()" class="run-btn" style="width:auto; padding:2px 8px; font-size:10px; font-weight:bold; background:var(--navy);">發佈為公司 SOP 基準</button>
      `;
    }
  } else {
    // Viewer 唯讀，除非啟動沙盒模擬
    if (window.edisState.isSandboxMode) {
      slider.disabled = false;
      if (badge) badge.innerHTML = badgeSpan('rgba(217,119,6,0.1)', '#d97706', 'rgba(217,119,6,0.3)', '🔓 沙盒模擬中（不影響正式 SOP）');
      if (lockWrap) {
        lockWrap.innerHTML = `
          <button onclick="toggleSandboxMode()" style="background:#dc2626; color:white; border:none; border-radius:4px; padding:2px 8px; cursor:pointer; font-size:10px; font-weight:bold;">恢復 SOP</button>
        `;
      }
    } else {
      slider.disabled = true;
      slider.value = window.edisState.sopDefaultThreshold.toFixed(2);
      const display = document.getElementById('thresholdValDisplay');
      if (display) display.textContent = window.edisState.sopDefaultThreshold.toFixed(2);
      window.edisState.threshold = window.edisState.sopDefaultThreshold;
      if (badge) badge.innerHTML = badgeSpan('rgba(220,38,38,0.08)', '#dc2626', 'rgba(220,38,38,0.2)', '🔒 SOP 已鎖定');
      if (lockWrap) {
        lockWrap.innerHTML = `
          <button onclick="toggleSandboxMode()" style="background:var(--steel); color:white; border:none; border-radius:4px; padding:2px 8px; cursor:pointer; font-size:10px; font-weight:bold;">啟動沙盒模擬</button>
        `;
      }
    }
  }
}

function toggleSandboxMode() {
  window.edisState.isSandboxMode = !window.edisState.isSandboxMode;
  updateSopUI();
  refreshDashboard();
}

function publishSopThreshold() {
  const newSop = parseFloat(document.getElementById('thresholdSlider').value);
  window.edisState.sopDefaultThreshold = newSop;
  showToast(`已將門檻值 ${newSop.toFixed(2)} 發佈為公司新季度 SOP 基準門檻！`, 'success');
  updateSopUI();
  refreshDashboard();
}

// ── 7. What-if 單筆訂單模擬器 (手動輸入與列表點擊模擬融合) ──────────────────────
async function runInstantPredict() {
  const btn = document.getElementById('predictRunBtn');
  const btnIcon = document.getElementById('predictBtnIcon');
  const btnText = document.getElementById('predictBtnText');
  if (!btn) return;

  const payload = {
    shipping_mode:       document.getElementById('pf-shipping-mode').value,
    order_region:        document.getElementById('pf-order-region').value,
    days_for_shipment:   parseFloat(document.getElementById('pf-days').value)   || 4,
    product_price:       parseFloat(document.getElementById('pf-price').value)  || 59.99,
    order_item_quantity: parseInt(document.getElementById('pf-qty').value)       || 1,
    customer_segment:    document.getElementById('pf-segment').value,
    market:              document.getElementById('pf-market').value,
    order_date:          document.getElementById('pf-date').value || null,
  };

  if (payload.days_for_shipment < 1 || payload.days_for_shipment > 7) {
    alert('預計配送天數請填 1–7 天。'); return;
  }
  if (payload.product_price < 0) {
    alert('商品單價不可為負數。'); return;
  }
  if (payload.order_item_quantity < 1) {
    alert('訂購數量至少為 1。'); return;
  }

  btn.disabled = true;
  if (btnIcon) btnIcon.innerHTML = '<span class="spinner" style="border-color:rgba(255,255,255,0.3);border-top-color:white;"></span>';
  if (btnText) btnText.textContent = '計算預測中...';

  try {
    const resp = await fetch('/api/predict-single', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail || `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    renderPredictResult(data);
  } catch (e) {
    const card = document.getElementById('predictResultCard');
    card.classList.add('has-result');
    document.getElementById('predictPlaceholder').style.display = 'none';
    const content = document.getElementById('predictResultContent');
    content.style.display = 'flex';
    content.innerHTML = `
      <div style="text-align:center;color:#c0392b;padding:20px 0;">
        <div style="font-size:32px;margin-bottom:8px;">⚠️</div>
        <div style="font-size:13px;font-weight:600;">預測失敗</div>
        <div style="font-size:12px;color:var(--muted);margin-top:6px;line-height:1.6;">${e.message}</div>
      </div>`;
  } finally {
    btn.disabled = false;
    if (btnIcon) { btnIcon.innerHTML = ''; btnIcon.textContent = '🔮'; }
    if (btnText) btnText.textContent = '立即預測延遲機率';
  }
}

function renderPredictResult(data) {
  const pLate = data.p_late || 0;
  const risk = data.risk_bucket || 'Low';
  const penalty = data.expected_penalty || 0;
  const upgCost = data.upgrade_cost || 0;
  const netBen = data.net_benefit_if_upgrade || 0;
  const recommend = data.recommend_upgrade;

  const card = document.getElementById('predictResultCard');
  if (card) card.classList.add('has-result');
  
  const placeholder = document.getElementById('predictPlaceholder');
  if (placeholder) placeholder.style.display = 'none';

  const content = document.getElementById('predictResultContent');
  if (content) content.style.display = 'flex';

  // 圓形儀表計數與動畫
  const circumference = 289.03;
  const offset = circumference * (1 - pLate);
  const gaugeFill = document.getElementById('gaugeFill');
  const colorMap = { High: '#c0392b', Medium: '#d68910', Low: '#27ae60' };
  const gaugeColor = colorMap[risk] || '#437096';

  if (gaugeFill) {
    gaugeFill.style.stroke = gaugeColor;
    gaugeFill.style.transition = 'none';
    gaugeFill.style.strokeDashoffset = circumference;
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        gaugeFill.style.transition = 'stroke-dashoffset 0.9s cubic-bezier(0.34,1.56,0.64,1), stroke 0.4s';
        gaugeFill.style.strokeDashoffset = offset;
      });
    });
  }

  const gaugePct = document.getElementById('gaugePct');
  if (gaugePct) {
    gaugePct.style.color = gaugeColor;
    animateCounter(gaugePct, 0, Math.round(pLate * 1000) / 10, 900, v => v.toFixed(1) + '%');
  }

  // 風險徽章
  const badgeEl = document.getElementById('predictRiskBadge');
  if (badgeEl) {
    badgeEl.className = 'predict-risk-badge';
    const badgeCls = { High: 'prb-high', Medium: 'prb-med', Low: 'prb-low' };
    const badgeIcon = { High: '🔴', Medium: '🟡', Low: '🟢' };
    badgeEl.classList.add(badgeCls[risk] || 'prb-low');
    badgeEl.textContent = `${badgeIcon[risk] || '○'} ${risk} 風險`;
  }

  // 明細數據
  document.getElementById('pdPenalty').textContent = `USD $${penalty.toFixed(2)}`;
  document.getElementById('pdUpgradeCost').textContent = `USD $${upgCost.toFixed(2)}`;
  const netEl = document.getElementById('pdNetBenefit');
  netEl.textContent = (netBen >= 0 ? '+' : '') + `USD $${netBen.toFixed(2)}`;
  netEl.style.color = netBen >= 0 ? '#27ae60' : '#c0392b';

  // 升級建議
  const hintEl = document.getElementById('predictUpgradeHint');
  if (hintEl) {
    hintEl.className = 'predict-upgrade-hint';
    if (recommend && risk === 'High') {
      hintEl.classList.add('hint-upgrade');
      hintEl.textContent = '⚠️ 建議升級運送！預估可避免罰金高於升級成本';
    } else if (recommend && risk === 'Medium') {
      hintEl.classList.add('hint-borderline');
      hintEl.textContent = '💡 可考慮升級，預估效益為正';
    } else if (!recommend && risk === 'Low') {
      hintEl.classList.add('hint-ok');
      hintEl.textContent = '✅ 低風險，無需升級';
    } else {
      hintEl.classList.add('hint-borderline');
      hintEl.textContent = '📋 升級效益為負，維持現有運送方式即可';
    }
  }
}

// 點擊列表中的訂單，一鍵載入單筆模擬器進行預測
function loadOrderIntoSimulator(shippingMode, orderRegion, days, price, qty, segment, market, orderDate) {
  // 自動滑動到模擬器區塊
  const simulator = document.getElementById('instantPredictPanel');
  if (simulator) {
    simulator.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  // 設定表單數值
  document.getElementById('pf-shipping-mode').value = shippingMode;
  document.getElementById('pf-order-region').value = orderRegion;
  document.getElementById('pf-days').value = days;
  document.getElementById('pf-price').value = price;
  document.getElementById('pf-qty').value = qty;
  document.getElementById('pf-segment').value = segment;
  document.getElementById('pf-market').value = market;
  if (orderDate) {
    document.getElementById('pf-date').value = orderDate.split(' ')[0]; // 提取 YYYY-MM-DD
  } else {
    document.getElementById('pf-date').value = '';
  }

  // 執行即時預測
  runInstantPredict();
}

// ── 8. What-if 全域參數模擬器 ───────────────────────────────────────────────
async function runGlobalSimulation(val) {
  const simLabel = document.getElementById('globalSimValue');
  const simNote = document.getElementById('globalSimResultNote');
  if (simLabel) simLabel.textContent = val;
  if (simNote) simNote.textContent = '計算模擬預估中...';

  try {
    // 呼叫 API 情境分析
    const res = await fetch(`${API_BASE}/api/scenario-analysis?budgets=1000,3000,5000,10000&upgrade_cost=${val}`);
    if (!res.ok) throw new Error('模擬失敗');
    const data = await res.json();
    if (simNote) {
      simNote.textContent = `全域模擬結果：當每筆訂單平均升級成本調整為 $${val} 時，${data.recommendation}`;
    }
  } catch (e) {
    if (simNote) simNote.textContent = `模擬分析出錯：${e.message}`;
  }
}

// ── 9. 模型診斷與重訓對比看板 (Engineer 整合版) ───────────────────────────────
async function loadModelPerformance() {
  const featList = document.getElementById('featureImportanceList');
  if (featList) featList.innerHTML = '載入中...';
  
  try {
    const d = await fetchMetrics();
    
    // 填寫基本指標
    document.getElementById('perfAuc').textContent = d.roc_auc.toFixed(4);
    document.getElementById('perfPrecision').textContent = (d.precision * 100).toFixed(2) + '%';
    document.getElementById('perfRecall').textContent = (d.recall * 100).toFixed(2) + '%';
    document.getElementById('perfF1').textContent = d.f1.toFixed(4);
    
    // 混淆矩陣連動
    if (d.confusion_matrix) {
      const tn = d.confusion_matrix[0][0];
      const fp = d.confusion_matrix[0][1];
      const fn = d.confusion_matrix[1][0];
      const tp = d.confusion_matrix[1][1];
      
      document.getElementById('cm-tn').innerHTML = `${tn.toLocaleString()}<br><span style="font-size:9px;color:var(--muted);font-weight:400;">True Negatives</span>`;
      document.getElementById('cm-fp').innerHTML = `${fp.toLocaleString()}<br><span style="font-size:9px;color:var(--muted);font-weight:400;">False Positives</span>`;
      document.getElementById('cm-fn').innerHTML = `${fn.toLocaleString()}<br><span style="font-size:9px;color:var(--muted);font-weight:400;">False Negatives</span>`;
      document.getElementById('cm-tp').innerHTML = `${tp.toLocaleString()}<br><span style="font-size:9px;color:var(--muted);font-weight:400;">True Positives</span>`;
    }
    
    // 繪製 XGBoost 特徵重要性
    if (d.feature_importance && featList) {
      const items = Object.entries(d.feature_importance).sort((a,b) => b[1] - a[1]);
      const maxVal = Math.max(...items.map(i => i[1])) || 1.0;
      
      featList.innerHTML = items.map(([feat, val]) => {
        const pct = (val * 100).toFixed(1);
        const barWidth = (val / maxVal * 100).toFixed(0);
        return `
          <div>
            <div style="display:flex; justify-content:space-between; font-size:11.5px; margin-bottom:4px; font-family:'DM Mono',monospace;">
              <span>${feat}</span>
              <span style="font-weight:600; color:var(--primary);">${pct}%</span>
            </div>
            <div style="height:12px; width:100%; background:var(--slate-lt); border-radius:6px; overflow:hidden;">
              <div style="height:100%; width:${barWidth}%; background:linear-gradient(90deg, var(--primary-lt), var(--primary)); border-radius:6px; transition: width 1s ease;"></div>
            </div>
          </div>
        `;
      }).join('');

      // 動態生成手動排除重訓的特徵複選框
      const manualFeatList = document.getElementById('manualRetrainFeatureList');
      if (manualFeatList) {
        manualFeatList.innerHTML = items.map(([feat, val]) => `
          <label style="display:flex; align-items:center; gap:8px; font-size:12.5px; cursor:pointer; padding:6px 8px; border:1px solid var(--border); border-radius:6px; background:var(--bg);">
            <input type="checkbox" name="manualRetrainFeature" value="${feat}" style="accent-color:var(--primary);">
            <span style="flex:1; text-align:left;">${feat}</span>
          </label>
        `).join('');
      }
    } else if (featList) {
      featList.innerHTML = '<div style="color:var(--muted); font-size:12px;">無特徵重要性數據</div>';
    }

    // 載入預測誤差清單 (供工程師進行模型診斷分析)
    const errorsRes = await fetch(`${API_BASE}/api/predict?limit=250&threshold=${window.edisState.threshold}&error_only=true`).then(r => r.json());
    const errors = errorsRes.data || [];
    document.getElementById('errorListCount').textContent = `共 ${errorsRes.count || errors.length} 筆誤差`;
    const errorBody = document.getElementById('errorListTableBody');
    if (errorBody) {
      if (errors.length === 0) {
        errorBody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:32px;color:var(--muted);font-size:13px">目前沒有預測判定錯誤的訂單</td></tr>`;
      } else {
        errorBody.innerHTML = errors.map(o => `
          <tr>
            <td><span class="order-id" title="${o.order_id_hash}" style="cursor:pointer; text-decoration:underline;" onclick="openExplainModal('${o.order_id_hash}')">${o.display_order_id || displayOrderId(o.order_id_hash)}</span></td>
            <td>${o.shipping_mode}</td>
            <td>${o.order_region}</td>
            <td>${(o.p_late*100).toFixed(0)}%</td>
            <td>${o.actual_late===1?'<span style="color:#b91c1c; font-weight:600;">延遲 (1)</span>':'<span style="color:#15803d; font-weight:600;">準時 (0)</span>'}</td>
            <td>${o.p_late>=window.edisState.threshold?'<span style="color:#b91c1c; font-weight:600;">延遲 (1)</span>':'<span style="color:#15803d; font-weight:600;">準時 (0)</span>'}</td>
            <td><button class="run-btn" onclick="openExplainModal('${o.order_id_hash}')" style="width:auto; padding:4px 10px; font-size:11px; border-radius:4px;">🔎 查看原因</button></td>
          </tr>
        `).join('');
      }
    }

  } catch(e) {
    if (featList) featList.innerHTML = `<div style="color:red; font-size:12px;">載入失敗: ${e.message}</div>`;
  }
}

// ── 10. CSV 上傳、門檻校準與其他原載入 JS 邏輯 ───────────────────────────────
async function populateRegionDropdown() {
  const dropdown = document.getElementById('filterRegion');
  if (!dropdown || dropdown.options.length > 1) return;

  try {
    const regionsData = await fetchRegions();
    regionsData.forEach(r => {
      if (r.order_region) {
        const opt = document.createElement('option');
        opt.value = r.order_region;
        opt.textContent = r.order_region;
        dropdown.appendChild(opt);
      }
    });
  } catch (e) {
    console.error('Failed to load regions filter', e);
  }
}

async function uploadTrainingCSV(input) {
  const file = input.files[0];
  if (!file) return;
  
  const uploadBtn = document.getElementById('uploadCsvBtn');
  const originalHtml = uploadBtn.innerHTML;
  uploadBtn.innerHTML = '<span class="spinner"></span>回填中...';
  uploadBtn.disabled = true;
  
  const formData = new FormData();
  formData.append('file', file);
  
  try {
    const res = await fetch(`${API_BASE}/api/upload-training`, {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.detail || '回填失敗');
    }
    const data = await res.json();
    showToast(data.message, 'success');
  } catch (e) {
    alert('訓練資料回填失敗: ' + e.message);
  } finally {
    uploadBtn.innerHTML = originalHtml;
    uploadBtn.disabled = false;
    input.value = '';
  }
}

async function resetCSV() {
  const resetBtn = document.getElementById('resetCsvBtn');
  resetBtn.disabled = true;
  try {
    const res = await fetch(`${API_BASE}/api/reset-orders`, {
      method: 'POST'
    });
    if (res.ok) {
      resetBtn.style.display = 'none';
      const aiResetBtn = document.getElementById('aiResetPredictBtn');
      if (aiResetBtn) aiResetBtn.style.display = 'none';
      const aiStatus = document.getElementById('aiUploadStatus');
      if (aiStatus) aiStatus.textContent = '已還原為預設驗證集。';
      appendAIMessage('system', '已還原為預設驗證集。');
      refreshDashboard();
      showToast('已成功還原為系統預設資料集！', 'success');
    } else {
      const err = await res.json();
      alert('重設失敗: ' + (err.detail || '未知錯誤'));
    }
  } catch (e) {
    alert('重設失敗: ' + e.message);
  } finally {
    resetBtn.disabled = false;
  }
}

function appendAIMessage(type, text) {
  const log = document.getElementById('aiChatLog');
  if (!log) return;
  const msg = document.createElement('div');
  msg.className = `ai-message ${type}`;
  msg.textContent = text;
  log.appendChild(msg);
  log.scrollTop = log.scrollHeight;
}

async function uploadPredictionCSV(input) {
  const file = input.files[0];
  if (!file) return;

  const btn = document.getElementById('aiUploadPredictBtn');
  const status = document.getElementById('aiUploadStatus');
  const originalText = btn.textContent;
  btn.textContent = '...';
  btn.disabled = true;
  status.textContent = '正在上傳並產生延遲預測...';
  appendAIMessage('user', `上傳待預測資料檔案：${file.name}`);
  appendAIMessage('system', '正在上傳待預測資料並運行 XGBoost 推論...');

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`${API_BASE}/api/upload`, {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || '預測上傳失敗');
    }
    const data = await res.json();
    status.textContent = `${data.message} 目前介面已顯示上傳檔案的延遲預測。`;
    appendAIMessage('assistant', `✅ ${data.message}\n目前系統已載入此批預測數據，您可以繼續向我詢問該批物流風險分析或調整預算執行最佳化！`);
    const aiResetBtn = document.getElementById('aiResetPredictBtn');
    if (aiResetBtn) aiResetBtn.style.display = 'inline-flex';
    document.getElementById('resetCsvBtn').style.display = 'inline-flex';
    await refreshDashboard();
  } catch (e) {
    status.textContent = '預測上傳失敗：' + e.message;
    appendAIMessage('system', '預測上傳失敗：' + e.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
    input.value = '';
  }
}

async function generateAIBrief() {
  const btn = document.getElementById('aiGenerateBriefBtn');
  const mode = document.getElementById('aiLlmMode');
  const questionInput = document.getElementById('aiQuestionInput');
  const question = questionInput.value.trim();
  const originalText = btn.textContent;
  btn.textContent = '...';
  btn.disabled = true;
  appendAIMessage('user', question || '請產生本批物流調度的主管摘要。');
  appendAIMessage('system', '正在整理去識別化預測結果與最佳化摘要...');

  try {
    const res = await fetch(`${API_BASE}/api/llm/manager-brief`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        budget: parseFloat(document.getElementById('budgetInput')?.value) || 5000,
        upgrade_cost: 80,
        delay_penalty: 250,
        risk_threshold: window.edisState.threshold,
        question
      })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail?.message || err.detail || 'AI 摘要產生失敗');
    }
    const data = await res.json();
    if (mode) {
      mode.textContent = data.llm?.used_external_llm
        ? `${data.llm.configured_provider || data.llm.provider}: ${data.llm.model || 'external'}`
        : 'local answer';
    }
    appendAIMessage('assistant', data.brief_text || '沒有產生摘要。');
    questionInput.value = '';
  } catch (e) {
    appendAIMessage('system', 'AI 摘要產生失敗：' + e.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

// ── 11. LLM 設定後台管理 ───────────────────────────────────────────────────────
const LLM_MODEL_OPTIONS = {
  local: [{ value: '', label: '不使用外部模型' }],
  openai: [
    { value: 'gpt-4o-mini', label: 'gpt-4o-mini' },
    { value: 'gpt-4o', label: 'gpt-4o' },
    { value: 'gpt-4', label: 'gpt-4' },
    { value: '__custom__', label: '自訂模型...' }
  ],
  openai_compatible: [
    { value: 'gpt-4o-mini', label: 'gpt-4o-mini' },
    { value: 'deepseek-chat', label: 'deepseek-chat' },
    { value: '__custom__', label: '自訂模型...' }
  ],
  gemini: [
    { value: 'gemini-1.5-flash', label: 'gemini-1.5-flash' },
    { value: 'gemini-2.0-flash', label: 'gemini-2.0-flash' },
    { value: '__custom__', label: '自訂模型...' }
  ],
  claude: [
    { value: 'claude-3-5-sonnet-20241022', label: 'claude-3-5-sonnet-20241022' },
    { value: 'claude-3-5-haiku-20241022', label: 'claude-3-5-haiku-20241022' },
    { value: '__custom__', label: '自訂模型...' }
  ],
  ollama: [
    { value: 'llama3.1', label: 'llama3.1' },
    { value: 'deepseek-r1', label: 'deepseek-r1' },
    { value: '__custom__', label: '自訂模型...' }
  ]
};

const LLM_PROVIDER_DEFAULT_URLS = {
  local: '',
  openai: 'https://api.openai.com/v1/chat/completions',
  openai_compatible: 'https://api.openai.com/v1/chat/completions',
  gemini: '',
  claude: 'https://api.anthropic.com/v1/messages',
  ollama: 'http://localhost:11434/api/chat'
};

let savedLLMProvider = null;

function providerNeedsApiKey(provider) {
  return !['local', 'ollama'].includes(provider);
}

function handleLLMProviderChange() {
  const providerInput = document.getElementById('llmProviderInput');
  const apiUrlInput = document.getElementById('llmApiUrlInput');
  const keep = document.getElementById('llmKeepKeyInput');
  const keyInput = document.getElementById('llmApiKeyInput');
  updateLLMModelOptions('', false);
  if (providerInput && apiUrlInput) {
    apiUrlInput.value = LLM_PROVIDER_DEFAULT_URLS[providerInput.value] || '';
  }
  if (keep) keep.checked = false;
  if (keyInput) keyInput.value = '';
  updateLLMKeyInputState();
}

function updateLLMModelOptions(selectedModel = '', allowCustomFallback = true) {
  const providerInput = document.getElementById('llmProviderInput');
  const modelInput = document.getElementById('llmModelInput');
  const customInput = document.getElementById('llmCustomModelInput');
  if (!providerInput || !modelInput) return;

  const provider = providerInput.value || 'local';
  const options = LLM_MODEL_OPTIONS[provider] || LLM_MODEL_OPTIONS.local;
  const previous = selectedModel || '';
  modelInput.innerHTML = '';

  options.forEach(item => {
    const opt = document.createElement('option');
    opt.value = item.value;
    opt.textContent = item.label;
    modelInput.appendChild(opt);
  });

  const matched = options.some(item => item.value === previous);
  if (matched) {
    modelInput.value = previous;
    if (customInput) customInput.value = '';
  } else if (allowCustomFallback && previous && options.some(item => item.value === '__custom__')) {
    modelInput.value = '__custom__';
    if (customInput) customInput.value = previous;
  } else {
    modelInput.value = options[0].value;
    if (customInput) customInput.value = '';
  }
  updateLLMCustomModelState();
}

function updateLLMCustomModelState() {
  const modelInput = document.getElementById('llmModelInput');
  const customInput = document.getElementById('llmCustomModelInput');
  if (!modelInput || !customInput) return;
  const isCustom = modelInput.value === '__custom__';
  customInput.style.display = isCustom ? 'block' : 'none';
  customInput.disabled = !isCustom;
}

function getSelectedLLMModel() {
  const modelInput = document.getElementById('llmModelInput');
  const customInput = document.getElementById('llmCustomModelInput');
  if (!modelInput) return '';
  if (modelInput.value === '__custom__') {
    return (customInput?.value || '').trim();
  }
  return modelInput.value.trim();
}

function updateLLMKeyInputState() {
  const keep = document.getElementById('llmKeepKeyInput');
  const keepRow = document.getElementById('llmKeepKeyRow');
  const input = document.getElementById('llmApiKeyInput');
  const hint = document.getElementById('llmKeyHint');
  const provider = document.getElementById('llmProviderInput')?.value || 'local';
  if (!keep || !input) return;

  if (!providerNeedsApiKey(provider)) {
    if (keepRow) keepRow.style.display = 'none';
    keep.checked = false;
    keep.disabled = true;
    input.value = '';
    input.disabled = true;
    input.placeholder = provider === 'ollama' ? 'Ollama 為本機服務，不需要 API Key' : 'Local 模式不需要 API Key';
  } else if (keep.checked) {
    if (keepRow) keepRow.style.display = 'flex';
    keep.disabled = false;
    input.value = '';
    input.disabled = true;
    input.placeholder = '已保留目前儲存的 API Key';
  } else {
    if (keepRow) keepRow.style.display = 'flex';
    keep.disabled = savedLLMProvider !== provider;
    input.disabled = false;
    input.placeholder = savedLLMProvider === provider ? '貼上新的 API Key；留空儲存會清除目前 Key' : '請貼上此 Provider 的 API Key';
  }
}

async function loadLLMSettings() {
  updateLLMSettingsAccess();
  if (window.edisState.currentRole !== 'manager') return;

  const status = document.getElementById('llmSettingsStatus');
  if (status) status.textContent = '讀取設定中...';
  try {
    const res = await fetch(`${API_BASE}/api/llm/settings`);
    if (!res.ok) throw new Error('讀取設定失敗');
    const data = await res.json();
    const s = data.settings || {};
    savedLLMProvider = s.api_key_set ? (s.provider || null) : null;
    document.getElementById('llmProviderInput').value = s.provider || 'local';
    updateLLMModelOptions(s.model || '');
    document.getElementById('llmApiUrlInput').value = s.api_url || '';
    document.getElementById('llmApiKeyInput').value = '';
    document.getElementById('llmKeepKeyInput').checked = !!s.api_key_set && providerNeedsApiKey(s.provider || 'local');
    updateLLMKeyInputState();
    if (status) {
      status.textContent = s.api_key_set
        ? `目前已設定：${s.provider} / ${s.model || '預設模型'} (API Key 已配置)`
        : `目前已設定：${s.provider} / ${s.model || '預設模型'} (未配置 API Key)`;
    }
  } catch (e) {
    if (status) status.textContent = '讀取設定失敗：' + e.message;
  }
}

async function saveLLMSettings() {
  if (window.edisState.currentRole !== 'manager') return;

  const btn = document.getElementById('llmSaveBtn');
  const status = document.getElementById('llmSettingsStatus');
  const originalText = btn.textContent;
  btn.textContent = '儲存中...';
  btn.disabled = true;

  const keepKey = document.getElementById('llmKeepKeyInput').checked;
  const apiKeyInput = document.getElementById('llmApiKeyInput').value.trim();
  const selectedModel = getSelectedLLMModel();
  const selectedProvider = document.getElementById('llmProviderInput').value;

  try {
    const res = await fetch(`${API_BASE}/api/llm/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: selectedProvider,
        model: selectedModel,
        api_url: document.getElementById('llmApiUrlInput').value.trim(),
        api_key: providerNeedsApiKey(selectedProvider)
          ? (keepKey && savedLLMProvider === selectedProvider && !apiKeyInput ? '__KEEP_EXISTING__' : apiKeyInput)
          : ''
      })
    });
    if (!res.ok) throw new Error('儲存失敗');
    showToast('LLM 設定已順利保存！', 'success');
    loadLLMSettings();
  } catch (e) {
    if (status) status.textContent = '儲存失敗：' + e.message;
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

function updateLLMSettingsAccess() {
  const isM = window.edisState.currentRole === 'manager';
  const badge = document.getElementById('llmSettingsRoleBadge');
  const locked = document.getElementById('llmSettingsLocked');
  const form = document.getElementById('llmSettingsForm');
  if (badge) {
    badge.className = isM ? 'role-badge badge-manager' : 'role-badge badge-viewer';
    badge.textContent = isM ? 'Manager' : 'Viewer';
  }
  if (locked) locked.style.display = isM ? 'none' : 'block';
  if (form) form.style.display = isM ? 'grid' : 'none';
}

// ── 12. Dashboard 渲染邏輯 ────────────────────────────────────────────────────
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
  document.getElementById('kpiPredictedDesc').textContent = `延遲機率 ≥ ${(window.edisState.threshold * 100).toFixed(0)}%`;
  
  document.getElementById('kpiExpectedPenaltyLoss').textContent = '$' + Math.round(d.expected_penalty_exposure || 0).toLocaleString();
  document.getElementById('kpiExpectedDesc').textContent = `建議升級預算: $${Math.round(d.recommended_budget || 0).toLocaleString()}`;

  // Actionable Insights 決策 Banner 顯示邏輯
  const banner = document.getElementById('actionableInsightsBanner');
  const bannerText = document.getElementById('actionableInsightsText');
  const savings = Math.max(0, (d.expected_penalty_exposure || 0) - (d.recommended_budget || 0));
  if (banner && bannerText) {
    if ((d.recommended_budget || 0) > 0 && savings > 0) {
      banner.style.display = 'flex';
      bannerText.innerHTML = `建議投入物流預算 <strong>$${Math.round(d.recommended_budget).toLocaleString()}</strong>，可挽回 <strong>${d.positive_roi_orders.toLocaleString()}</strong> 筆訂單的延遲罰金損失，預估為公司省下淨額 <strong>$${Math.round(savings).toLocaleString()}</strong>！`;
    } else {
      banner.style.display = 'none';
    }
  }

  // 簡報區數據 (防禦性檢查)
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

function fillClass(p) {
  return p >= 0.7 ? 'fill-high' : p >= 0.4 ? 'fill-med' : 'fill-low';
}
function pillClass(p) {
  return p >= 0.7 ? 'r-high' : p >= 0.4 ? 'r-med' : 'r-low';
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
    
    // 為了傳遞給一鍵模擬，將單引號防範處理
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

// ── 13. 最佳化計算 (Manager) ──────────────────────────────────────────────────
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


// ── 14. 門檻值調適統計資訊 (F1/Cost 建議) ───────────────────────────────────────
function formatTuneMetrics(row) {
  if (!row) return '無資料';
  return `預警命中 ${(row.precision * 100).toFixed(1)}% · 漏判率 ${( (1-row.recall) * 100).toFixed(1)}% · F1 ${row.f1.toFixed(4)} · 預期罰金損失 $${Math.round(row.expected_cost).toLocaleString()}`;
}

function renderThresholdTuning(data) {
  window.edisState.lastThresholdTuning = data;
  const panel = document.getElementById('thresholdTuningPanel');
  if (!panel || !data) return;
  panel.style.display = 'block';

  document.getElementById('thresholdTuningNote').textContent =
    `${data.row_count.toLocaleString()} 筆資料 · 升級成本 $${data.cost_model.upgrade_cost} · 漏判成本 $${data.cost_model.delay_penalty}`
    + (data.basis_note ? ` · ${data.basis_note}` : '');

  document.getElementById('tuneCurrentThreshold').textContent = data.current.threshold.toFixed(2);
  document.getElementById('tuneCurrentMetrics').textContent = formatTuneMetrics(data.current);

  document.getElementById('tuneBestF1Threshold').textContent = data.best_f1.threshold.toFixed(2);
  document.getElementById('tuneBestF1Metrics').textContent = formatTuneMetrics(data.best_f1);

  document.getElementById('tuneBestCostThreshold').textContent = data.best_expected_cost.threshold.toFixed(2);
  document.getElementById('tuneBestCostMetrics').textContent = formatTuneMetrics(data.best_expected_cost);
  
  if (document.getElementById('badgeF1Val')) {
    document.getElementById('badgeF1Val').textContent = data.best_f1.threshold.toFixed(2);
  }
  if (document.getElementById('badgeCostVal')) {
    document.getElementById('badgeCostVal').textContent = data.best_expected_cost.threshold.toFixed(2);
  }
  
  if (!window._sopDefaultThresholdInitialized) {
    window.edisState.sopDefaultThreshold = data.best_f1.threshold;
    window._sopDefaultThresholdInitialized = true;
    updateSopUI();
  }
}

function applyThresholdRecommendation(type) {
  if (!window.edisState.lastThresholdTuning) return;
  const selected = type === 'cost'
    ? window.edisState.lastThresholdTuning.best_expected_cost
    : window.edisState.lastThresholdTuning.best_f1;
    
  if (window.edisState.currentRole === 'manager' && !window.edisState.isSandboxMode) {
    window.edisState.isSandboxMode = true;
  }
  
  updateThreshold(selected.threshold);
  updateSopUI();
}

// ── 15. 風險訂單分頁過濾邏輯 ───────────────────────────────────────────────────
async function applyFilters() {
  window.edisState.currentRiskListPage = 1;
  loadFilteredRiskList();
}

async function loadFilteredRiskList() {
  const search = document.getElementById('riskSearchInput').value.trim();
  const risk = document.getElementById('filterRisk').value;
  const shipping = document.getElementById('filterShipping').value;
  const region = document.getElementById('filterRegion').value;
  
  const tbody = document.getElementById('riskListTableBody');
  if (!tbody) return;
  tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:32px;color:var(--muted);font-size:13px">載入中...</td></tr>`;

  try {
    const payload = await fetchPredictions(window.edisState.currentRiskListPage, search, risk, shipping, region);
    if (!payload) return;
    
    window.edisState.totalRiskListCount = payload.count || 0;
    const countLabel = document.getElementById('riskListCount');
    if (countLabel) countLabel.textContent = `共 ${window.edisState.totalRiskListCount} 筆`;
    
    const totalPages = Math.ceil(window.edisState.totalRiskListCount / window.edisState.limit) || 1;
    const pageIndicator = document.getElementById('riskListPageIndicator');
    if (pageIndicator) pageIndicator.textContent = `第 ${window.edisState.currentRiskListPage} / ${totalPages} 頁`;
    
    const prevBtn = document.getElementById('riskListPrevBtn');
    const nextBtn = document.getElementById('riskListNextBtn');
    
    if (prevBtn) {
      prevBtn.disabled = window.edisState.currentRiskListPage <= 1;
      prevBtn.style.opacity = window.edisState.currentRiskListPage <= 1 ? 0.5 : 1;
    }
    if (nextBtn) {
      nextBtn.disabled = window.edisState.currentRiskListPage >= totalPages;
      nextBtn.style.opacity = window.edisState.currentRiskListPage >= totalPages ? 0.5 : 1;
    }

    const data = payload.data || [];
    if (data.length === 0) {
      tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:32px;color:var(--muted);font-size:13px">無符合篩選條件的訂單</td></tr>`;
      return;
    }

    tbody.innerHTML = data.map(o => `
      <tr>
        <td><span class="order-id" title="${o.order_id_hash}">${o.display_order_id || displayOrderId(o.order_id_hash)}</span></td>
        <td>${o.shipping_mode || 'Unknown'}</td>
        <td style="color:var(--muted)">${o.order_region || 'Unknown'}</td>
        <td>
          <div class="prob-wrap">
            <div class="prob-bar"><div class="prob-fill ${fillClass(o.risk_bucket)}" style="width:${o.p_late*100}%"></div></div>
            <span class="prob-val">${(o.p_late*100).toFixed(0)}%</span>
          </div>
        </td>
        <td><span class="risk-pill ${pillClass(o.risk_bucket)}">${o.risk_bucket}</span></td>
        <td>${o.actual_late===1||o.actual_late===true?'<span style="padding:2px 8px;background:#fee2e2;color:#b91c1c;border-radius:12px;font-size:10px;font-weight:600;">延遲</span>':o.actual_late===0||o.actual_late===false?'<span style="padding:2px 8px;background:#dcfce7;color:#15803d;border-radius:12px;font-size:10px;font-weight:600;">準時</span>':'<span style="color:var(--muted);font-size:12px;">—</span>'}</td>
        <td style="white-space:nowrap;">
          ${o.is_correct===true?'<span style="padding:2px 8px;background:#dcfce7;color:#15803d;border-radius:12px;font-size:10px;font-weight:600;">✓ 正確</span>':o.is_correct===false?'<span style="padding:2px 8px;background:#fee2e2;color:#b91c1c;border-radius:12px;font-size:10px;font-weight:600;">✗ 錯誤</span>':'<span style="color:var(--muted);font-size:12px;">—</span>'}
          <button class="run-btn" style="width:auto; padding:2px 6px; font-size:10px; margin-left:6px; background:var(--steel);" onclick="loadOrderIntoSimulator('${o.shipping_mode}','${o.order_region}',${o.days_for_shipment||4},${o.product_price||59.99},${o.order_item_quantity||1},'${o.customer_segment||'Consumer'}','${o.market||'Europe'}','${o.order_date||''}')">🧪 模擬</button>
        </td>
      </tr>
    `).join('');

  } catch (e) {
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center;padding:32px;color:red;font-size:13px">資料載入失敗: ${e.message}</td></tr>`;
  }
}

async function changeRiskListPage(delta) {
  const totalPages = Math.ceil(window.edisState.totalRiskListCount / window.edisState.limit) || 1;
  const newPage = window.edisState.currentRiskListPage + delta;
  if (newPage >= 1 && newPage <= totalPages) {
    window.edisState.currentRiskListPage = newPage;
    loadFilteredRiskList();
  }
}

// ── 16. 月份 Flipper 及診斷重訓機制 ──────────────────────────────────────────
async function loadMonthlyChart() {
  const grid = document.getElementById('flipperGrid');
  const rangeEl = document.getElementById('flipPageRangeLabel');
  if (grid) grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;padding:24px;color:var(--muted);font-size:12px;">載入分析資料...</div>';
  try {
    const res = await fetch(`${API_BASE}/api/chart/monthly`);
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(error.detail || `HTTP ${res.status}`);
    }
    const json = await res.json();
    window.edisState.monthlyAllData = Array.isArray(json) ? json : (json.data || []);
    const note = document.getElementById('monthlyPeriodNote');
    if (note) note.textContent = json.period_note || '';
    if (!window.edisState.monthlyAllData.length) throw new Error('沒有可供分析的預測資料');

    const sel = document.getElementById('monthFlipSelect');
    if (sel) {
      const opts = [];
      for (let i = 0; i < window.edisState.monthlyAllData.length; i += window.edisState.FLIPPER_PAGE_SIZE) {
        opts.push(`<option value="${i}">${window.edisState.monthlyAllData[i].month}</option>`);
      }
      sel.innerHTML = opts.join('');
    }
    window.edisState.flipperPageStart = 0;
    renderFlipperPage(0);
  } catch(e) {
    window.edisState.monthlyAllData = [];
    if (rangeEl) rangeEl.textContent = '資料載入失敗';
    if (grid) grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:24px;color:#b91c1c;font-size:12px;">${e.message}</div>`;
  }
}

function renderFlipperPage(startIdx) {
  if (!window.edisState.monthlyAllData.length) return;
  startIdx = Math.max(0, Math.min(startIdx, window.edisState.monthlyAllData.length - 1));
  window.edisState.flipperPageStart = startIdx;

  const slice = window.edisState.monthlyAllData.slice(startIdx, startIdx + window.edisState.FLIPPER_PAGE_SIZE);
  const threshPct = (window.edisState.flipThreshold * 100).toFixed(0);

  const rangeEl = document.getElementById('flipPageRangeLabel');
  if (rangeEl) rangeEl.textContent = `${slice[0]?.month || '—'} ～ ${slice[slice.length-1]?.month || '—'}`;

  const sel = document.getElementById('monthFlipSelect');
  if (sel) {
    for (let i = 0; i < sel.options.length; i++) {
      if (parseInt(sel.options[i].value) <= startIdx) sel.selectedIndex = i;
    }
  }

  const prevBtn = document.getElementById('flipPrevBtn');
  const nextBtn = document.getElementById('flipNextBtn');
  if (prevBtn) prevBtn.style.opacity = startIdx === 0 ? '0.35' : '1';
  if (nextBtn) nextBtn.style.opacity = (startIdx + window.edisState.FLIPPER_PAGE_SIZE >= window.edisState.monthlyAllData.length) ? '0.35' : '1';

  const grid = document.getElementById('flipperGrid');
  if (!grid) return;

  grid.innerHTML = slice.map(d => {
    const yPct = d.actual_late_rate != null ? +(d.actual_late_rate * 100).toFixed(1) : null;
    const yhatPct = d.avg_p_late != null ? +(d.avg_p_late * 100).toFixed(1) : null;
    const errPct = (yPct != null && yhatPct != null) ? +(Math.abs(yhatPct - yPct)).toFixed(1) : null;
    const over = errPct != null && errPct > (window.edisState.flipThreshold * 100);
    const errColor = over ? '#e07b54' : '#16a34a';
    const cardBorder = over ? '2px solid #fed7aa' : '1px solid var(--border)';
    const cardBg = over ? '#fffbf7' : 'white';
    const errLabel = errPct != null ? (over ? `${errPct}% &gt; ${threshPct}%` : `${errPct}% ✓`) : '—';

    const diagBtn = over
      ? `<button onclick="openDiagnoseModal('${d.month}')" style="width:100%;margin-top:10px;padding:7px 0;background:var(--navy);color:#fff;border:none;border-radius:5px;font-size:11px;font-weight:600;cursor:pointer;">🔍 診斷</button>`
      : `<div style="margin-top:10px;text-align:center;font-size:10px;color:#16a34a;font-weight:500;">✓ 正常範圍</div>`;

    return `
      <div style="border:${cardBorder};background:${cardBg};border-radius:8px;padding:12px;display:flex;flex-direction:column;">
        <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:2px;">${d.month}</div>
        <div style="font-size:10px;color:var(--muted);margin-bottom:8px;font-family:'DM Mono',monospace;">${d.total_orders != null ? d.total_orders.toLocaleString() + ' 筆' : '—'}</div>
        <div style="font-size:10px;color:var(--muted);margin-bottom:3px;">Y 實際</div>
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:6px;">
          <div style="flex:1;height:8px;background:#f3f4f6;border-radius:4px;overflow:hidden;">
            <div style="height:100%;width:${yPct!=null?Math.min(yPct,100):0}%;background:#e07b54;border-radius:4px;"></div>
          </div>
          <span style="font-size:10px;font-weight:700;color:#e07b54;min-width:34px;text-align:right;">${yPct!=null?yPct+'%':'—'}</span>
        </div>
        <div style="font-size:10px;color:var(--muted);margin-bottom:3px;">Ŷ 預測</div>
        <div style="display:flex;align-items:center;gap:6px;margin-bottom:8px;">
          <div style="flex:1;height:8px;background:#f3f4f6;border-radius:4px;overflow:hidden;">
            <div style="height:100%;width:${yhatPct!=null?Math.min(yhatPct,100):0}%;background:#437096;border-radius:4px;"></div>
          </div>
          <span style="font-size:10px;font-weight:700;color:#437096;min-width:34px;text-align:right;">${yhatPct!=null?yhatPct+'%':'—'}</span>
        </div>
        <div style="font-size:10px;font-weight:600;color:${errColor};padding:4px 6px;background:${over?'#fff7ed':'#f0fdf4'};border-radius:4px;text-align:center;">△ ${errLabel}</div>
        ${diagBtn}
      </div>`;
  }).join('');
}

function updateFlipThreshold(val) {
  const v = parseFloat(val);
  if (isNaN(v) || v < 1 || v > 50) return;
  window.edisState.flipThreshold = v / 100;
  const lbl = document.getElementById('flipThresholdLabel');
  if (lbl) lbl.textContent = v + '%';
  renderFlipperPage(window.edisState.flipperPageStart);
}

function flipPage(delta) {
  renderFlipperPage(window.edisState.flipperPageStart + delta * window.edisState.FLIPPER_PAGE_SIZE);
}

function jumpToFlipPage(startIdx) {
  renderFlipperPage(startIdx);
}

function openDiagnoseModal(month) {
  if (!month) return;
  window.edisState.diagCurrentMonth = month;
  window.edisState.diagCurrentFactors = [];

  document.getElementById('diagMonthTitle').textContent = month;
  document.getElementById('diagMonthSummary').textContent = '載入中…';
  document.getElementById('diagFactors').innerHTML = '<div style="color:var(--muted);font-size:12px;">LIME 分析中…</div>';
  document.querySelectorAll('input[name="diagEventType"]').forEach(r => r.checked = false);
  document.getElementById('diagEventNote').value = '';
  document.getElementById('diagStep1').style.display = 'block';
  document.getElementById('diagStep2').style.display = 'none';

  const _retrainBtn = document.getElementById('diagStartRetrainBtn');
  const _retrainStatus = document.getElementById('diagRetrainStatus');
  if (_retrainBtn) { _retrainBtn.style.display = 'block'; _retrainBtn.disabled = false; }
  if (_retrainStatus) { _retrainStatus.style.display = 'none'; }

  const isManager = window.edisState.currentRole === 'manager';
  document.getElementById('diagManagerActions').style.display = isManager ? 'flex' : 'none';
  document.getElementById('diagViewerNote').style.display = isManager ? 'none' : 'block';

  const modal = document.getElementById('monthDiagnoseModal');
  if (modal) modal.style.display = 'flex';

  fetchDiagnoseData(month);
}

function closeDiagnoseModal() {
  const modal = document.getElementById('monthDiagnoseModal');
  if (modal) modal.style.display = 'none';
}

async function fetchDiagnoseData(month) {
  try {
    const res = await fetch(`${API_BASE}/api/diagnose/monthly?month=${encodeURIComponent(month)}`);
    if (!res.ok) throw new Error(res.status);
    const data = await res.json();

    const yPct = data.actual_late_rate != null ? (data.actual_late_rate * 100).toFixed(1) : '—';
    const yPhat = data.avg_p_late != null ? (data.avg_p_late * 100).toFixed(1) : '—';
    const errPct = data.error != null ? (data.error * 100).toFixed(1) : '—';
    document.getElementById('diagMonthSummary').textContent =
      `Y=${yPct}%  Ŷ=${yPhat}%  誤差=${errPct}%  錯誤訂單=${(data.error_orders_count||0).toLocaleString()} / ${(data.total_orders||0).toLocaleString()} 筆`;

    window.edisState.diagCurrentFactors = data.top_factors || [];
    const facEl = document.getElementById('diagFactors');
    if (!facEl) return;
    if (!window.edisState.diagCurrentFactors.length) {
      facEl.innerHTML = '<div style="font-size:12px;color:var(--muted);">無足夠誤差訂單可分析</div>';
    } else {
      const maxCnt = Math.max(...window.edisState.diagCurrentFactors.map(f => f.count || 1));
      facEl.innerHTML = window.edisState.diagCurrentFactors.map((f, i) => {
        const pct = maxCnt > 0 ? Math.round((f.count / maxCnt) * 100) : 0;
        const dirColor = f.direction === 'raises risk' ? '#e07b54' : '#437096';
        return `<div>
          <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px;">
            <span style="color:var(--text);font-weight:500;">${i+1}. ${f.feature}</span>
            <span style="color:${dirColor};font-size:11px;">${f.direction==='raises risk'?'↑ 增加風險':'↓ 降低風險'}</span>
          </div>
          <div style="height:8px;background:var(--bg);border-radius:4px;overflow:hidden;">
            <div style="height:100%;width:${pct}%;background:${dirColor};border-radius:4px;"></div>
          </div>
        </div>`;
      }).join('');
    }

    if (data.event_flag) {
      const match = document.querySelector(`input[name="diagEventType"][value="${data.event_flag.type}"]`);
      if (match) match.checked = true;
      if (data.event_flag.note) document.getElementById('diagEventNote').value = data.event_flag.note;
    }
  } catch(e) {
    document.getElementById('diagMonthSummary').textContent = '載入失敗：' + e.message;
  }
}

async function flagMonthEvent() {
  const selected = document.querySelector('input[name="diagEventType"]:checked');
  if (!selected) { alert('請先選擇事件類型'); return; }
  const note = document.getElementById('diagEventNote').value.trim();
  const btn = document.getElementById('diagFlagBtn');
  if (btn) { btn.disabled = true; btn.textContent = '標記中…'; }
  try {
    const res = await fetch(`${API_BASE}/api/diagnose/monthly/flag`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ month: window.edisState.diagCurrentMonth, event_type: selected.value, note })
    });
    if (!res.ok) { const e = await res.json().catch(()=>({})); throw new Error(e.detail || res.status); }
    closeDiagnoseModal();
    showToast(`已標記 ${window.edisState.diagCurrentMonth} 為「${selected.value}」`, 'success');
    await loadMonthlyChart();
  } catch(e) {
    showToast('標記失敗：' + e.message, 'error');
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = '標記為外部事件，排除重訓考量'; }
  }
}

function showRetrainStep() {
  document.getElementById('diagStep1').style.display = 'none';
  document.getElementById('diagStep2').style.display = 'block';

  const cbEl = document.getElementById('diagFeatureCheckboxes');
  if (!cbEl) return;
  if (!window.edisState.diagCurrentFactors.length) {
    cbEl.innerHTML = '<div style="font-size:12px;color:var(--muted);">無可選擇的問題特徵</div>';
    return;
  }
  cbEl.innerHTML = window.edisState.diagCurrentFactors.map((f, i) => `
    <label style="display:flex;align-items:center;gap:8px;font-size:13px;cursor:pointer;padding:6px 8px;border:1px solid var(--border);border-radius:6px;background:var(--bg);">
      <input type="checkbox" name="retrainFeature" value="${f.feature}" ${i < 2 ? 'checked' : ''} style="accent-color:var(--navy);">
      <span style="flex:1;">${f.feature}</span>
      <span style="font-size:11px;color:${f.direction==='raises risk'?'#e07b54':'#437096'};">${f.direction==='raises risk'?'↑ 高風險貢獻':'↓ 低風險貢獻'}</span>
    </label>`).join('');
}

function backToStep1() {
  document.getElementById('diagStep1').style.display = 'block';
  document.getElementById('diagStep2').style.display = 'none';
}

async function startRetrain() {
  const checked = [...document.querySelectorAll('input[name="retrainFeature"]:checked')];
  if (!checked.length) { alert('請至少選擇一個要排除的特徵'); return; }
  const excluded = checked.map(c => c.value);

  const btn = document.getElementById('diagStartRetrainBtn');
  const status = document.getElementById('diagRetrainStatus');
  if (btn) btn.style.display = 'none';
  if (status) { status.style.display = 'block'; status.innerHTML = '<span class="spinner"></span> 正在啟動背景重訓任務...'; }

  try {
    const res = await fetch(`${API_BASE}/api/retrain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ excluded_features: excluded })
    });
    if (!res.ok) { const e = await res.json().catch(()=>({})); throw new Error(e.detail || res.status); }
    const data = await res.json();
    
    sessionStorage.setItem('edis_active_task_id', data.task_id);
    sessionStorage.setItem('edis_active_task_month', window.edisState.diagCurrentMonth);
    
    pollRetrainTask(data.task_id);
  } catch(e) {
    if (status) { status.textContent = '重訓失敗：' + e.message; status.style.color = '#e07b54'; }
    if (btn) btn.style.display = 'block';
    showToast('重訓失敗：' + e.message, 'error');
  }
}

function pollRetrainTask(taskId) {
  const status = document.getElementById('diagRetrainStatus');
  const manualStatus = document.getElementById('manualRetrainStatus');
  const interval = setInterval(async () => {
    try {
      const res = await fetch(`${API_BASE}/api/tasks/${taskId}/status`);
      if (!res.ok) throw new Error('無法取得任務進度');
      const data = await res.json();
      
      const progressHtml = `<span class="spinner"></span> <strong>[${data.progress}%]</strong> ${data.log}`;
      if (status) status.innerHTML = progressHtml;
      if (manualStatus) manualStatus.innerHTML = progressHtml;
      
      if (data.status === 'success') {
        clearInterval(interval);
        sessionStorage.removeItem('edis_active_task_id');
        sessionStorage.removeItem('edis_active_task_month');
        if (status) status.style.display = 'none';
        if (manualStatus) manualStatus.style.display = 'none';
        
        window.edisState.pendingRetrainSession = data.result.session_id;
        renderDiagRetrainResult(data.result);
        renderRetrainResult(data.result);
        showToast('重訓完成，新舊模型指標比對就緒。', 'success');
        
        const manualBtn = document.getElementById('manualRetrainBtn');
        if (manualBtn) manualBtn.style.display = 'block';
      } else if (data.status === 'failed') {
        clearInterval(interval);
        sessionStorage.removeItem('edis_active_task_id');
        sessionStorage.removeItem('edis_active_task_month');
        const errText = '重訓失敗：' + (data.error || '未知錯誤');
        if (status) {
          status.textContent = errText;
          status.style.color = '#e07b54';
        }
        if (manualStatus) {
          manualStatus.textContent = errText;
          manualStatus.style.color = '#e07b54';
        }
        const btn = document.getElementById('diagStartRetrainBtn');
        if (btn) btn.style.display = 'block';
        const manualBtn = document.getElementById('manualRetrainBtn');
        if (manualBtn) manualBtn.style.display = 'block';
        showToast(errText, 'error');
      }
    } catch (e) {
      clearInterval(interval);
      const errText = '輪詢進度失敗：' + e.message;
      if (status) {
        status.textContent = errText;
        status.style.color = '#e07b54';
      }
      if (manualStatus) {
        manualStatus.textContent = errText;
        manualStatus.style.color = '#e07b54';
      }
      const btn = document.getElementById('diagStartRetrainBtn');
      if (btn) btn.style.display = 'block';
      const manualBtn = document.getElementById('manualRetrainBtn');
      if (manualBtn) manualBtn.style.display = 'block';
    }
  }, 2000);
}

function renderDiagRetrainResult(data) {
  document.getElementById('diagStep2').style.display = 'none';
  const step3 = document.getElementById('diagStep3');
  if (step3) step3.style.display = 'block';
  
  document.getElementById('diagDroppedColsNote').textContent =
    `排除特徵（${(data.dropped_columns||[]).length} 個）：${(data.dropped_columns||[]).join(' · ') || '無'}`;

  const metricKeys = ['roc_auc', 'f1', 'precision', 'recall'];
  const metricLabels = { roc_auc: 'ROC-AUC', f1: 'F1', precision: '精準率', recall: '召回率' };

  function renderMetricGrid(elId, metrics, compareMetrics) {
    const el = document.getElementById(elId);
    if (!el || !metrics) return;
    el.innerHTML = metricKeys.map(k => {
      const v = metrics[k] != null ? (+metrics[k]).toFixed(4) : '—';
      const vCmp = compareMetrics && compareMetrics[k] != null ? +compareMetrics[k] : null;
      const vNum = metrics[k] != null ? +metrics[k] : null;
      let delta = '';
      if (vNum != null && vCmp != null) {
        const diff = ((vNum - vCmp) * 100).toFixed(2);
        const isUp = vNum >= vCmp;
        delta = `<span style="font-size:10px; margin-left:2px; color:${isUp?'#16a34a':'#e07b54'};">${isUp?'▲':'▼'} ${Math.abs(diff)}%</span>`;
      }
      return `<div class="stat-box" style="padding:6px 8px;"><div class="stat-label" style="font-size:9px;">${metricLabels[k]}</div><div class="stat-value" style="font-size:13px; font-weight:700;">${v}${delta}</div></div>`;
    }).join('');
  }

  renderMetricGrid('diagOldMetricsGrid', data.old_metrics, data.new_metrics);
  renderMetricGrid('diagNewMetricsGrid', data.new_metrics, data.old_metrics);
}

async function diagAdoptNewModel() {
  if (!window.edisState.pendingRetrainSession) return;
  const btn = document.getElementById('diagAdoptBtn');
  if (btn) { btn.disabled = true; btn.textContent = '採用中...'; }
  try {
    const res = await fetch(`${API_BASE}/api/retrain/adopt`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: window.edisState.pendingRetrainSession })
    });
    if (!res.ok) {
      const e = await res.json().catch(()=>({}));
      throw new Error(e.detail || res.status);
    }
    window.edisState.pendingRetrainSession = null;
    const step3 = document.getElementById('diagStep3');
    if (step3) step3.style.display = 'none';
    closeDiagnoseModal();
    showToast('新模型已採用並就地更新。', 'success');
    await loadMonthlyChart();
    await refreshDashboard();
  } catch(e) {
    showToast('採用失敗：' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = '✓ 採用新模型'; }
  }
}

async function diagDiscardNewModel() {
  if (!window.edisState.pendingRetrainSession) return;
  const btn = document.getElementById('diagDiscardBtn');
  if (btn) { btn.disabled = true; btn.textContent = '捨棄中...'; }
  try {
    await fetch(`${API_BASE}/api/retrain/discard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: window.edisState.pendingRetrainSession })
    });
  } catch(e) {}
  
  window.edisState.pendingRetrainSession = null;
  const step3 = document.getElementById('diagStep3');
  if (step3) step3.style.display = 'none';
  closeDiagnoseModal();
  showToast('已捨棄新模型，保留現有模型。', 'info');
  if (btn) { btn.disabled = false; btn.textContent = '✗ 捨棄，保留舊模型'; }
}

// ── 17. 其它彈窗與輔助函數 ──────────────────────────────────────────────────────
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
    const res = await fetch(`${API_BASE}/api/explain/${orderId}`);
    if (!res.ok) throw new Error('分析資料讀取失敗');
    const data = await res.json();
    
    document.getElementById('modalProb').textContent = (data.p_late * 100).toFixed(0) + '%';
    document.getElementById('modalPenalty').textContent = '$' + Math.round(data.expected_penalty).toLocaleString();
    document.getElementById('modalSummaryText').textContent = data.manager_summary || '無摘要。';
    
    const factors = data.top_x_factors || [];
    document.getElementById('modalFactorsList').innerHTML = factors.map(f => `
      <div style="padding:10px 14px; border:1px solid var(--border); border-radius:8px; background:#fcfcfc; display:flex; justify-content:space-between; align-items:center; gap:12px;">
        <div>
          <div style="font-size:12px; font-weight:600; color:var(--text);">${f.label || f.feature}</div>
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

function closeExplainModal() {
  const modal = document.getElementById('explainModal');
  if (modal) modal.style.display = 'none';
}

function showToast(msg, type = 'info') {
  const colors = { success: '#22c55e', error: '#e07b54', info: 'var(--navy)' };
  const toast = document.createElement('div');
  toast.textContent = msg;
  toast.style.cssText = `position:fixed;bottom:24px;right:24px;z-index:2000;padding:10px 16px;border-radius:8px;font-size:13px;font-weight:500;color:#fff;background:${colors[type]||colors.info};box-shadow:0 4px 12px rgba(0,0,0,0.15);opacity:0;transition:opacity 0.2s;`;
  document.body.appendChild(toast);
  requestAnimationFrame(() => { toast.style.opacity = '1'; });
  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3500);
}

function closeLoginModal() {
  document.getElementById('loginModal').classList.remove('show');
  const activeRole = window.edisState.currentRole || 'viewer';
  document.querySelectorAll('.role-btn').forEach(b =>
    b.classList.toggle('active', b.textContent.toLowerCase() === activeRole));
}

async function submitLogin() {
  const username = document.getElementById('loginUsername').value.trim();
  const password = document.getElementById('loginPassword').value;
  const errEl = document.getElementById('loginError');
  if (errEl) errEl.classList.remove('show');
  try {
    const res = await fetch(API_BASE + '/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password })
    });
    if (res.ok) {
      const data = await res.json();
      sessionStorage.setItem('edis_token', data.token);
      sessionStorage.setItem('edis_session_id', data.session_id);
      document.getElementById('loginModal').classList.remove('show');
      
      const serverRole = data.role; // "Logistics_Manager", "Engineer", or "Viewer"
      const clientRole = serverRole === 'Logistics_Manager' ? 'manager' : (serverRole === 'Engineer' ? 'engineer' : 'viewer');
      
      window[`_${clientRole}Authenticated`] = true;
      await setRole(clientRole);
      
      const roleText = clientRole === 'manager' ? 'Manager' : (clientRole === 'engineer' ? 'Engineer' : 'Viewer');
      showToast(`🔑 登入成功，已切換至 ${roleText} 權限。`, 'success');
    } else {
      if (errEl) errEl.classList.add('show');
    }
  } catch(e) {
    if (errEl) errEl.classList.add('show');
  }
}

async function setRole(role) {
  // If role is manager or engineer and we are not yet authenticated, open login modal
  const isAuthenticated = window[`_${role}Authenticated`];
  if ((role === 'manager' || role === 'engineer') && window.edisState.currentRole !== role && !isAuthenticated) {
    document.getElementById('loginUsername').value = '';
    document.getElementById('loginPassword').value = '';
    const err = document.getElementById('loginError');
    if (err) err.classList.remove('show');
    window._pendingRole = role;
    document.getElementById('loginModal').classList.add('show');
    setTimeout(() => document.getElementById('loginUsername').focus(), 100);
    return;
  }
  
  if (role === 'viewer') {
    sessionStorage.removeItem('edis_token');
    sessionStorage.removeItem('edis_session_id');
    window._managerAuthenticated = false;
    window._engineerAuthenticated = false;
  }
  
  window._pendingRole = null;
  window.edisState.currentRole = role;
  
  // Update role buttons active state in topbar
  document.querySelectorAll('.role-btn').forEach(b => {
    b.classList.toggle('active', b.textContent.toLowerCase() === role);
  });

  const isM = role === 'manager';
  const isEng = role === 'engineer';
  const isMOrEng = isM || isEng;
  
  // Update Role Badges (defensively)
  const roleBadge = document.getElementById('roleBadge');
  if (roleBadge) {
    if (isEng) {
      roleBadge.className = 'role-badge badge-engineer';
      roleBadge.textContent = '● Engineer';
    } else if (isM) {
      roleBadge.className = 'role-badge badge-manager';
      roleBadge.textContent = '● Manager';
    } else {
      roleBadge.className = 'role-badge badge-viewer';
      roleBadge.textContent = '● Viewer';
    }
  }

  const optRoleBadge = document.getElementById('optRoleBadge');
  if (optRoleBadge) {
    optRoleBadge.className = isMOrEng ? 'role-badge badge-manager' : 'role-badge badge-viewer';
    optRoleBadge.textContent = isEng ? 'Engineer' : (isM ? 'Manager' : 'Viewer');
  }

  const optPageRoleBadge = document.getElementById('optPageRoleBadge');
  if (optPageRoleBadge) {
    optPageRoleBadge.className = isMOrEng ? 'role-badge badge-manager' : 'role-badge badge-viewer';
    optPageRoleBadge.textContent = isEng ? 'Engineer' : (isM ? 'Manager' : 'Viewer');
  }

  // Sidebar sections and items visibility control
  const secViewer = document.getElementById('section-viewer');
  const secManager = document.getElementById('section-manager');
  const secEngineer = document.getElementById('section-engineer');
  if (secViewer) secViewer.style.display = 'block';
  if (secManager) secManager.style.display = isMOrEng ? 'block' : 'none';
  if (secEngineer) secEngineer.style.display = isEng ? 'block' : 'none';

  const navItems = {
    'nav-dashboard': true,
    'nav-optimization': true,
    'nav-risk-list': isMOrEng,
    'nav-ai-assistant': isMOrEng,
    'nav-model-perf': isEng,
    'nav-region-map': isEng,
    'nav-rbac': isEng,
    'nav-llm-settings': isEng
  };

  for (const [id, visible] of Object.entries(navItems)) {
    const el = document.getElementById(id);
    if (el) el.style.display = visible ? 'flex' : 'none';
  }

  // If current page is not allowed for the new role, switch to dashboard
  const allowedPages = {
    viewer: ['dashboard', 'optimization'],
    manager: ['dashboard', 'optimization', 'risk-list', 'ai-assistant'],
    engineer: ['dashboard', 'optimization', 'risk-list', 'ai-assistant', 'model-perf', 'region-map', 'rbac', 'llm-settings']
  };

  let activePageId = 'dashboard';
  document.querySelectorAll('.page-section').forEach(el => {
    if (!el.classList.contains('hidden')) {
      activePageId = el.id.replace('page-', '');
    }
  });

  if (!allowedPages[role].includes(activePageId)) {
    showPage('dashboard');
  }

  // CSV Upload button and locked box control
  const uploadCsvBtn = document.getElementById('uploadCsvBtn');
  if (uploadCsvBtn) uploadCsvBtn.style.display = isMOrEng ? 'inline-flex' : 'none';
  const lockedUploadBox = document.getElementById('lockedUploadBox');
  if (lockedUploadBox) lockedUploadBox.style.display = isMOrEng ? 'none' : 'inline-flex';
  
  const aiUploadBtn = document.getElementById('aiUploadPredictBtn');
  const aiBriefBtn = document.getElementById('aiGenerateBriefBtn');
  const aiLockedBox = document.getElementById('aiLockedBox');
  const aiRoleBadge = document.getElementById('aiRoleBadge');
  if (aiUploadBtn) aiUploadBtn.style.display = isMOrEng ? 'inline-flex' : 'none';
  if (aiBriefBtn) aiBriefBtn.disabled = !isMOrEng;
  if (aiLockedBox) aiLockedBox.style.display = isMOrEng ? 'none' : 'inline-flex';
  if (aiRoleBadge) {
    aiRoleBadge.className = isMOrEng ? 'role-badge badge-manager' : 'role-badge badge-viewer';
    aiRoleBadge.textContent = isEng ? 'Engineer' : (isM ? 'Manager' : 'Viewer');
  }
  
  updateLLMSettingsAccess();
  if (isMOrEng && !document.getElementById('page-llm-settings').classList.contains('hidden')) {
    loadLLMSettings();
  }
  
  const resetCsvBtn = document.getElementById('resetCsvBtn');
  if (resetCsvBtn) {
    if (!isMOrEng) {
      resetCsvBtn.style.display = 'none';
      const aiResetBtn = document.getElementById('aiResetPredictBtn');
      if (aiResetBtn) aiResetBtn.style.display = 'none';
    } else {
      const m = await fetchMetrics();
      if (m && m.is_active) {
        resetCsvBtn.style.display = 'inline-flex';
        const aiResetBtn = document.getElementById('aiResetPredictBtn');
        if (aiResetBtn) aiResetBtn.style.display = 'inline-flex';
      } else {
        resetCsvBtn.style.display = 'none';
        const aiResetBtn = document.getElementById('aiResetPredictBtn');
        if (aiResetBtn) aiResetBtn.style.display = 'none';
      }
    }
  }

  // Defensive updates of old panels (in case they still exist somewhere)
  const runBtnOld = document.getElementById('runBtn');
  if (runBtnOld) runBtnOld.classList.toggle('hidden', !isMOrEng);
  const lockedBoxOld = document.getElementById('lockedBox');
  if (lockedBoxOld) lockedBoxOld.classList.toggle('hidden', isMOrEng);
  const optResultOld = document.getElementById('optResult');
  if (optResultOld) optResultOld.classList.add('hidden');
  
  // Optimization page controls
  const optPageRunBtn = document.getElementById('optPageRunBtn');
  if (optPageRunBtn) optPageRunBtn.classList.toggle('hidden', !isMOrEng);
  const optPageLockedBox = document.getElementById('optPageLockedBox');
  if (optPageLockedBox) optPageLockedBox.classList.toggle('hidden', isMOrEng);
  const optPageResult = document.getElementById('optPageResult');
  if (optPageResult) optPageResult.classList.add('hidden');
  const optPageResultPlaceholder = document.getElementById('optPageResultPlaceholder');
  if (optPageResultPlaceholder) optPageResultPlaceholder.classList.remove('hidden');

  // Re-render analysis
  renderManagerAnalysis('optPageManagerAnalysisBox', 'optPageManagerAnalysisText', 'optPageManagerAnalysisFactors', null);
  renderManagerAnalysis('managerAnalysisBox', 'managerAnalysisText', 'managerAnalysisFactors', null);

  updateSopUI();
  refreshDashboard();
  
  if (!document.getElementById('page-risk-list').classList.contains('hidden')) {
    applyFilters();
  }
}

function displayOrderId(orderId) {
  const raw = String(orderId || '').replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
  return raw ? `ORD-${raw.slice(0, 8)}` : 'ORD-UNKNOWN';
}

function displayOrderId(orderId) {
  const raw = String(orderId || '').replace(/[^a-zA-Z0-9]/g, '').toUpperCase();
  return raw ? `ORD-${raw.slice(0, 8)}` : 'ORD-UNKNOWN';
}

function animateCounter(el, from, to, duration, formatter) {
  const start = performance.now();
  function step(now) {
    const t = Math.min((now - start) / duration, 1);
    const ease = t < 0.5 ? 2 * t * t : -1 + (4 - 2 * t) * t;
    el.textContent = formatter(from + (to - from) * ease);
    if (t < 1) requestAnimationFrame(step);
  }
  requestAnimationFrame(step);
}

// ── 18. 初始化與 Refresh 機制 ───────────────────────────────────────────────
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

function getRoleFromToken() {
  const token = sessionStorage.getItem('edis_token');
  if (!token) return null;
  try {
    const payloadB64 = token.split('.')[0];
    const payloadStr = atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/'));
    const payload = JSON.parse(payloadStr);
    if (payload.exp && Date.now() / 1000 > payload.exp) {
      sessionStorage.removeItem('edis_token');
      sessionStorage.removeItem('edis_session_id');
      return null;
    }
    return payload.role;
  } catch (e) {
    return null;
  }
}

async function init() {
  try {
    // 初始載入時回復已登入之角色身分
    const savedRole = getRoleFromToken();
    if (savedRole) {
      const clientRole = savedRole === 'Logistics_Manager' ? 'manager' : (savedRole === 'Engineer' ? 'engineer' : 'viewer');
      window[`_${clientRole}Authenticated`] = true;
      window.edisState.currentRole = clientRole;
    }

    // 呼叫 setRole 以同步 UI 權限限制與顯示
    await setRole(window.edisState.currentRole);
    await loadMonthlyChart();

    const status = document.getElementById('statusText');
    if (status) status.textContent = 'Live API Connection';

    // 重載背景重訓任務狀態
    const activeTaskId = sessionStorage.getItem('edis_active_task_id');
    const activeMonth = sessionStorage.getItem('edis_active_task_month');
    if (activeTaskId && activeMonth) {
      openDiagnoseModal(activeMonth);
      document.getElementById('diagStep1').style.display = 'none';
      document.getElementById('diagStep2').style.display = 'block';
      document.getElementById('diagStartRetrainBtn').style.display = 'none';
      document.getElementById('diagRetrainStatus').style.display = 'block';
      pollRetrainTask(activeTaskId);
    }
  } catch (e) {
    console.error('Initialization failed', e);
    const status = document.getElementById('statusText');
    if (status) status.textContent = 'API Connection Error';
  }
}

// 註冊頁面按鍵監聽器
document.addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && document.getElementById('loginModal').classList.contains('show')) {
    submitLogin();
  }
});

document.addEventListener('keydown', function(e) {
  const input = document.getElementById('aiQuestionInput');
  if (e.key === 'Enter' && !e.shiftKey && document.activeElement === input) {
    e.preventDefault();
    generateAIBrief();
  }
});

// 當網頁載入完成後啟動初始化
window.addEventListener('DOMContentLoaded', () => {
  init();
});

// ── 19. 全域掛載以相容舊有的 Inline Onclick 屬性 ──────────────────────────────────
window.showPage = showPage;
window.setRole = setRole;
window.updateThreshold = updateThreshold;
window.uploadTrainingCSV = uploadTrainingCSV;
window.resetCSV = resetCSV;
window.uploadPredictionCSV = uploadPredictionCSV;
window.generateAIBrief = generateAIBrief;
window.saveLLMSettings = saveLLMSettings;
window.handleLLMProviderChange = handleLLMProviderChange;
window.updateLLMCustomModelState = updateLLMCustomModelState;
window.updateLLMKeyInputState = updateLLMKeyInputState;
window.applyThresholdRecommendation = applyThresholdRecommendation;
window.toggleSandboxMode = toggleSandboxMode;
window.publishSopThreshold = publishSopThreshold;
window.runInstantPredict = runInstantPredict;
window.runOptimize = runOptimize;
window.runPageOptimize = runPageOptimize;
window.changePage = changePage;
window.applyFilters = applyFilters;
window.changeRiskListPage = changeRiskListPage;
window.toggleRowExplanation = toggleRowExplanation;
window.openExplainModal = openExplainModal;
window.closeExplainModal = closeExplainModal;
window.openDiagnoseModal = openDiagnoseModal;
window.closeDiagnoseModal = closeDiagnoseModal;
window.flagMonthEvent = flagMonthEvent;
window.showRetrainStep = showRetrainStep;
window.backToStep1 = backToStep1;
window.startRetrain = startRetrain;
window.diagAdoptNewModel = diagAdoptNewModel;
window.diagDiscardNewModel = diagDiscardNewModel;
window.adoptNewModel = adoptNewModel;
window.discardNewModel = discardNewModel;
window.flipPage = flipPage;
window.jumpToFlipPage = jumpToFlipPage;
window.updateFlipThreshold = updateFlipThreshold;
window.loadOrderIntoSimulator = loadOrderIntoSimulator;
window.runGlobalSimulation = runGlobalSimulation;

async function startManualRetrain() {
  const checked = [...document.querySelectorAll('input[name="manualRetrainFeature"]:checked')];
  if (!checked.length) { alert('請至少選擇一個要排除的特徵'); return; }
  const excluded = checked.map(c => c.value);
  const xRole = window.edisState.currentRole === 'manager' ? 'Logistics_Manager' : (window.edisState.currentRole === 'engineer' ? 'Engineer' : 'Viewer');

  const btn    = document.getElementById('manualRetrainBtn');
  const status = document.getElementById('manualRetrainStatus');
  if (btn) btn.style.display = 'none';
  if (status) {
    status.style.display = 'block';
    status.innerHTML = '<span class="spinner"></span> 正在啟動重訓任務...';
  }

  try {
    const res = await fetch(`${API_BASE}/api/retrain`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Role': xRole },
      body: JSON.stringify({ excluded_features: excluded })
    });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.detail?.message || e.detail || res.status);
    }
    const data = await res.json();
    
    sessionStorage.setItem('edis_active_task_id', data.task_id);
    
    if (status) {
      status.innerHTML = '<span class="spinner"></span> <strong>[任務已啟動]</strong> 正在進行特徵排除重構訓練...';
    }
    
    pollRetrainTask(data.task_id);
  } catch(e) {
    if (status) {
      status.textContent = '重訓失敗：' + e.message;
      status.style.color = 'var(--danger)';
    }
    if (btn) btn.style.display = 'block';
    showToast('重訓失敗：' + e.message, 'error');
  }
}

window.startManualRetrain = startManualRetrain;

