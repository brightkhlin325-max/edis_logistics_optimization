// ==========================================
// monthly_diagnose.js — EDIS 月份 SLAs 診斷與重訓對比彈窗
// ==========================================

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
  const actions = document.getElementById('diagManagerActions');
  const note = document.getElementById('diagViewerNote');
  if (actions) actions.style.display = isManager ? 'flex' : 'none';
  if (note) note.style.display = isManager ? 'none' : 'block';

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

// Bind to window
window.loadMonthlyChart = loadMonthlyChart;
window.renderFlipperPage = renderFlipperPage;
window.updateFlipThreshold = updateFlipThreshold;
window.flipPage = flipPage;
window.jumpToFlipPage = jumpToFlipPage;
window.openDiagnoseModal = openDiagnoseModal;
window.closeDiagnoseModal = closeDiagnoseModal;
window.flagMonthEvent = flagMonthEvent;
window.showRetrainStep = showRetrainStep;
window.backToStep1 = backToStep1;
window.startRetrain = startRetrain;
window.diagAdoptNewModel = diagAdoptNewModel;
window.diagDiscardNewModel = diagDiscardNewModel;
