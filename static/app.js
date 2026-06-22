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

// ── 3. 頁面組件動態載入器 ───────────────────────────────────────────────────────
async function loadComponents() {
  const sections = document.querySelectorAll('.page-section[data-src]');
  const promises = Array.from(sections).map(async (el) => {
    try {
      const resp = await fetch(el.getAttribute('data-src'));
      if (resp.ok) {
        el.innerHTML = await resp.text();
      } else {
        el.innerHTML = `<div style="color:red; padding:20px;">載入組件失敗: ${el.getAttribute('data-src')}</div>`;
      }
    } catch (e) {
      el.innerHTML = `<div style="color:red; padding:20px;">載入組件錯誤: ${e.message}</div>`;
    }
  });
  await Promise.all(promises);
}

// ── 4. 頁面切換機制 (SPA Routing) ──────────────────────────────────────────
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
    if (window.refreshDashboard) refreshDashboard();
  } else if (pageId === 'risk-list') {
    if (window.populateRegionDropdown) populateRegionDropdown();
    if (window.applyFilters) applyFilters();
    if (window.loadRegionalRisk) loadRegionalRisk();
  } else if (pageId === 'optimization') {
    if (window.loadMonthlyChart) loadMonthlyChart();
  } else if (pageId === 'model-perf') {
    if (window.loadModelPerformance) loadModelPerformance();
  } else if (pageId === 'region-map') {
    if (window.loadRegionalRisk) loadRegionalRisk();
  } else if (pageId === 'llm-settings') {
    if (window.loadLLMSettings) loadLLMSettings();
  }
}

// ── 5. API 通訊端點 ─────────────────────────────────────────────────────────
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

async function fetchPredictions(page = 1, search = '', risk = '', shipping = '', region = '', month = '') {
  let url = `${API_BASE}/api/predict?page=${page}&limit=${window.edisState.limit}&threshold=${window.edisState.threshold}`;
  if (search) url += `&search=${encodeURIComponent(search)}`;
  if (risk) url += `&risk=${encodeURIComponent(risk)}`;
  if (shipping) url += `&shipping=${encodeURIComponent(shipping)}`;
  if (region) url += `&region=${encodeURIComponent(region)}`;
  if (month) url += `&month=${encodeURIComponent(month)}`;
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

// ── 6. 全域 Threshold 狀態同步 ───────────────────────────────────────────────
function updateThreshold(val) {
  const num = parseFloat(val);
  window.edisState.threshold = num;
  
  // 同步所有存在於頁面中的 Slider 與數值顯示
  const sliders = document.querySelectorAll('.thresholdSlider');
  sliders.forEach(s => s.value = num.toFixed(2));
  const displays = document.querySelectorAll('.thresholdValDisplay');
  displays.forEach(d => d.textContent = num.toFixed(2));

  const slider2 = document.getElementById('perfThresholdSlider');
  const display2 = document.getElementById('perfThresholdDisplay');
  if (slider2) slider2.value = num.toFixed(2);
  if (display2) display2.textContent = num.toFixed(2);

  if (window.refreshDashboard) refreshDashboard();
  const perfPage = document.getElementById('page-model-perf');
  if (perfPage && !perfPage.classList.contains('hidden') && window.loadModelPerformance) {
    loadModelPerformance();
  }
}

// ── 7. SOP 與沙盒模擬控制 (Viewer & Manager 權限防禦) ──────────────────────────
function updateSopUI() {
  const sliders = document.querySelectorAll('.thresholdSlider');
  const lockWraps = document.querySelectorAll('.sopStatusLockWrap');
  const badge = document.getElementById('sopRoleBadge');
  if (sliders.length === 0) return;

  const badgeSpan = (bg, color, border, text) =>
    `<span style="background:${bg}; color:${color}; border:1px solid ${border}; border-radius:20px; padding:3px 12px; font-size:11px; font-weight:700; display:inline-block;">${text}</span>`;

  if (window.edisState.currentRole === 'manager' || window.edisState.currentRole === 'engineer') {
    window.edisState.isSandboxMode = false;
    sliders.forEach(s => s.disabled = false);
    if (badge) {
      if (window.edisState.currentRole === 'engineer') {
        badge.innerHTML = badgeSpan('rgba(67,112,150,0.1)', '#437096', 'rgba(67,112,150,0.3)', '● 工程師模式');
      } else {
        badge.innerHTML = badgeSpan('rgba(5,150,105,0.1)', '#059669', 'rgba(5,150,105,0.3)', '● 管理者模式');
      }
    }
    lockWraps.forEach(lw => {
      lw.innerHTML = `
        <button onclick="publishSopThreshold()" class="run-btn" style="width:auto; padding:2px 8px; font-size:10px; font-weight:bold; background:var(--navy);">發佈為公司 SOP 基準</button>
      `;
    });
  } else {
    // Viewer 唯讀，除非啟動沙盒模擬
    if (window.edisState.isSandboxMode) {
      sliders.forEach(s => s.disabled = false);
      if (badge) badge.innerHTML = badgeSpan('rgba(217,119,6,0.1)', '#d97706', 'rgba(217,119,6,0.3)', '🔓 沙盒模擬中（不影響正式 SOP）');
      lockWraps.forEach(lw => {
        lw.innerHTML = `
          <button onclick="toggleSandboxMode()" style="background:#dc2626; color:white; border:none; border-radius:4px; padding:2px 8px; cursor:pointer; font-size:10px; font-weight:bold;">恢復 SOP</button>
        `;
      });
    } else {
      sliders.forEach(s => {
        s.disabled = true;
        s.value = window.edisState.sopDefaultThreshold.toFixed(2);
      });
      const displays = document.querySelectorAll('.thresholdValDisplay');
      displays.forEach(d => d.textContent = window.edisState.sopDefaultThreshold.toFixed(2));
      window.edisState.threshold = window.edisState.sopDefaultThreshold;
      if (badge) badge.innerHTML = badgeSpan('rgba(220,38,38,0.08)', '#dc2626', 'rgba(220,38,38,0.2)', '🔒 SOP 已鎖定');
      lockWraps.forEach(lw => {
        lw.innerHTML = `
          <button onclick="toggleSandboxMode()" style="background:var(--steel); color:white; border:none; border-radius:4px; padding:2px 8px; cursor:pointer; font-size:10px; font-weight:bold;">啟動沙盒模擬</button>
        `;
      });
    }
  }
}

function toggleSandboxMode() {
  window.edisState.isSandboxMode = !window.edisState.isSandboxMode;
  updateSopUI();
  if (window.refreshDashboard) refreshDashboard();
}

function publishSopThreshold() {
  const slider = document.querySelector('.thresholdSlider');
  if (!slider) return;
  const newSop = parseFloat(slider.value);
  window.edisState.sopDefaultThreshold = newSop;
  showToast(`已將門檻值 ${newSop.toFixed(2)} 發佈為公司新季度 SOP 基準門檻！`, 'success');
  updateSopUI();
  if (window.refreshDashboard) refreshDashboard();
}

// ── 8. 輔助與公共 Utility 函數 ───────────────────────────────────────────────
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

function showToast(msg, type = 'info') {
  const colors = { success: '#22c55e', error: '#e07b54', info: 'var(--navy)' };
  const toast = document.createElement('div');
  toast.textContent = msg;
  toast.style.cssText = `position:fixed;bottom:24px;right:24px;z-index:2000;padding:10px 16px;border-radius:8px;font-size:13px;font-weight:500;color:#fff;background:${colors[type]||colors.info};box-shadow:0 4px 12px rgba(0,0,0,0.15);opacity:0;transition:opacity 0.2s;`;
  document.body.appendChild(toast);
  requestAnimationFrame(() => { toast.style.opacity = '1'; });
  setTimeout(() => { toast.style.opacity = '0'; setTimeout(() => toast.remove(), 300); }, 3500);
}

// ── 9. CSV 管理與操作 ────────────────────────────────────────────────────────
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
  
  const uploadBtns = document.querySelectorAll('.uploadCsvBtn');
  uploadBtns.forEach(btn => {
    btn.disabled = true;
  });
  
  const parent = input.parentElement;
  const currentUploadBtn = parent.querySelector('.uploadCsvBtn');
  let originalHtml = '';
  if (currentUploadBtn) {
    originalHtml = currentUploadBtn.innerHTML;
    currentUploadBtn.innerHTML = '<span class="spinner"></span>回填中...';
  }
  
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
    uploadBtns.forEach(btn => {
      btn.disabled = false;
    });
    if (currentUploadBtn) {
      currentUploadBtn.innerHTML = originalHtml;
    }
    input.value = '';
  }
}

async function resetCSV() {
  const resetBtns = document.querySelectorAll('.resetCsvBtn');
  resetBtns.forEach(btn => btn.disabled = true);
  try {
    const res = await fetch(`${API_BASE}/api/reset-orders`, {
      method: 'POST'
    });
    if (res.ok) {
      resetBtns.forEach(btn => btn.style.display = 'none');
      const aiResetBtn = document.getElementById('aiResetPredictBtn');
      if (aiResetBtn) aiResetBtn.style.display = 'none';
      const aiStatus = document.getElementById('aiUploadStatus');
      if (aiStatus) aiStatus.textContent = '已還原為預設驗證集。';
      if (window.appendAIMessage) appendAIMessage('system', '已還原為預設驗證集。');
      if (window.refreshDashboard) refreshDashboard();
      showToast('已成功還原為系統預設資料集！', 'success');
    } else {
      const err = await res.json();
      alert('重設失敗: ' + (err.detail || '未知錯誤'));
    }
  } catch (e) {
    alert('重設失敗: ' + e.message);
  } finally {
    resetBtns.forEach(btn => btn.disabled = false);
  }
}

// ── 10. Authentication 與權限管理 ───────────────────────────────────────────
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
  
  document.querySelectorAll('.role-btn').forEach(b => {
    b.classList.toggle('active', b.textContent.toLowerCase() === role);
  });

  const isM = role === 'manager';
  const isEng = role === 'engineer';
  const isMOrEng = isM || isEng;
  
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
    'nav-llm-settings': isMOrEng
  };

  for (const [id, visible] of Object.entries(navItems)) {
    const el = document.getElementById(id);
    if (el) el.style.display = visible ? 'flex' : 'none';
  }

  const allowedPages = {
    viewer: ['dashboard', 'optimization'],
    manager: ['dashboard', 'optimization', 'risk-list', 'ai-assistant', 'llm-settings'],
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

  const uploadCsvBtns = document.querySelectorAll('.uploadCsvBtn, .uploadPredictBtn');
  uploadCsvBtns.forEach(btn => btn.style.display = isMOrEng ? 'inline-flex' : 'none');
  const lockedUploadBoxes = document.querySelectorAll('.lockedUploadBox, .lockedPredictBox');
  lockedUploadBoxes.forEach(box => box.style.display = isMOrEng ? 'none' : 'inline-flex');
  
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
  
  if (window.updateLLMSettingsAccess) updateLLMSettingsAccess();
  const llmPage = document.getElementById('page-llm-settings');
  if (isMOrEng && llmPage && !llmPage.classList.contains('hidden') && window.loadLLMSettings) {
    loadLLMSettings();
  }
  
  const resetCsvBtns = document.querySelectorAll('.resetCsvBtn');
  if (resetCsvBtns.length > 0) {
    if (!isMOrEng) {
      resetCsvBtns.forEach(btn => btn.style.display = 'none');
      const aiResetBtn = document.getElementById('aiResetPredictBtn');
      if (aiResetBtn) aiResetBtn.style.display = 'none';
    } else {
      const m = await fetchMetrics();
      if (m && m.is_active) {
        resetCsvBtns.forEach(btn => btn.style.display = 'inline-flex');
        const aiResetBtn = document.getElementById('aiResetPredictBtn');
        if (aiResetBtn) aiResetBtn.style.display = 'inline-flex';
      } else {
        resetCsvBtns.forEach(btn => btn.style.display = 'none');
        const aiResetBtn = document.getElementById('aiResetPredictBtn');
        if (aiResetBtn) aiResetBtn.style.display = 'none';
      }
    }
  }

  const runBtnOld = document.getElementById('runBtn');
  if (runBtnOld) runBtnOld.classList.toggle('hidden', !isMOrEng);
  const lockedBoxOld = document.getElementById('lockedBox');
  if (lockedBoxOld) lockedBoxOld.classList.toggle('hidden', isMOrEng);
  const optResultOld = document.getElementById('optResult');
  if (optResultOld) optResultOld.classList.add('hidden');
  
  const optPageRunBtn = document.getElementById('optPageRunBtn');
  if (optPageRunBtn) optPageRunBtn.classList.toggle('hidden', !isMOrEng);
  const optPageLockedBox = document.getElementById('optPageLockedBox');
  if (optPageLockedBox) optPageLockedBox.classList.toggle('hidden', isMOrEng);
  const optPageResult = document.getElementById('optPageResult');
  if (optPageResult) optPageResult.classList.add('hidden');
  const optPageResultPlaceholder = document.getElementById('optPageResultPlaceholder');
  if (optPageResultPlaceholder) optPageResultPlaceholder.classList.remove('hidden');

  if (window.renderManagerAnalysis) {
    renderManagerAnalysis('optPageManagerAnalysisBox', 'optPageManagerAnalysisText', 'optPageManagerAnalysisFactors', null);
    renderManagerAnalysis('managerAnalysisBox', 'managerAnalysisText', 'managerAnalysisFactors', null);
  }

  updateSopUI();
  if (window.refreshDashboard) refreshDashboard();
  
  const riskPage = document.getElementById('page-risk-list');
  if (riskPage && !riskPage.classList.contains('hidden') && window.applyFilters) {
    applyFilters();
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

// ── 11. 初始化與 Refresh 機制 ───────────────────────────────────────────────
async function init() {
  try {
    // 1. 載入組件 HTML
    await loadComponents();

    // 2. 初始載入時回復已登入之角色身分
    const savedRole = getRoleFromToken();
    if (savedRole) {
      const clientRole = savedRole === 'Logistics_Manager' ? 'manager' : (savedRole === 'Engineer' ? 'engineer' : 'viewer');
      window[`_${clientRole}Authenticated`] = true;
      window.edisState.currentRole = clientRole;
    }

    // 3. 呼叫 setRole 以同步 UI 權限限制與顯示
    await setRole(window.edisState.currentRole);
    if (window.loadMonthlyChart) await loadMonthlyChart();

    const status = document.getElementById('statusText');
    if (status) status.textContent = 'Live API Connection';

    // 4. 重載背景重訓任務狀態
    const activeTaskId = sessionStorage.getItem('edis_active_task_id');
    const activeMonth = sessionStorage.getItem('edis_active_task_month');
    if (activeTaskId && activeMonth) {
      if (window.openDiagnoseModal) {
        openDiagnoseModal(activeMonth);
        document.getElementById('diagStep1').style.display = 'none';
        document.getElementById('diagStep2').style.display = 'block';
        document.getElementById('diagStartRetrainBtn').style.display = 'none';
        document.getElementById('diagRetrainStatus').style.display = 'block';
      }
      if (window.pollRetrainTask) pollRetrainTask(activeTaskId);
    }
  } catch (e) {
    console.error('Initialization failed', e);
    const status = document.getElementById('statusText');
    if (status) status.textContent = 'API Connection Error';
  }
}

// 註冊頁面按鍵監聽器
document.addEventListener('keydown', function(e) {
  const loginModal = document.getElementById('loginModal');
  if (e.key === 'Enter' && loginModal && loginModal.classList.contains('show')) {
    submitLogin();
  }
});

document.addEventListener('keydown', function(e) {
  const input = document.getElementById('aiQuestionInput');
  if (e.key === 'Enter' && !e.shiftKey && document.activeElement === input) {
    e.preventDefault();
    if (window.generateAIBrief) generateAIBrief();
  }
});

// 當網頁載入完成後啟動初始化
window.addEventListener('DOMContentLoaded', () => {
  init();
});

// ── 12. 全域掛載以相容舊有的 Inline Onclick 屬性 ──────────────────────────────────
window.showPage = showPage;
window.setRole = setRole;
window.updateThreshold = updateThreshold;
window.uploadTrainingCSV = uploadTrainingCSV;
window.resetCSV = resetCSV;
window.animateCounter = animateCounter;
window.showToast = showToast;
window.closeLoginModal = closeLoginModal;
window.submitLogin = submitLogin;
window.displayOrderId = displayOrderId;
window.populateRegionDropdown = populateRegionDropdown;
window.toggleSandboxMode = toggleSandboxMode;
window.publishSopThreshold = publishSopThreshold;
