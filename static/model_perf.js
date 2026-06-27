// ==========================================
// model_perf.js — SLIDE 模型診斷與排除特徵重訓頁面邏輯
// ==========================================

async function loadModelPerformance() {
  const featList = document.getElementById('featureImportanceList');
  if (featList) featList.innerHTML = '載入中...';

  if (window.loadDeterioration) loadDeterioration();
  if (window.loadLeakageAudit) loadLeakageAudit();

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

async function uploadNewTrainingData(input) {
  if (!input.files || input.files.length === 0) return;
  const file = input.files[0];
  const formData = new FormData();
  formData.append('file', file);
  
  const status = document.getElementById('newTrainingStatus');
  status.style.display = 'block';
  status.style.color = 'var(--text)';
  status.innerHTML = '<span class="spinner"></span> 正在上傳資料...';
  
  try {
    const res = await fetch(`${API_BASE}/api/upload-training`, {
      method: 'POST',
      body: formData
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || '上傳失敗');
    
    status.style.color = 'var(--success)';
    status.textContent = `已匯入 ${data.added ?? 0} 筆已知結果，累積 ${data.total ?? 0} 筆；請啟動重訓並採用新版模型後，系統頁面才會改用新結果。`;
    showToast('已知結果已累積，尚未取代現行模型', 'success');
  } catch(e) {
    status.style.color = 'var(--danger)';
    status.textContent = '上傳失敗：' + e.message;
    showToast('上傳失敗：' + e.message, 'error');
  }
  input.value = ''; // Reset input
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
  const step2 = document.getElementById('diagStep2');
  if (step2) step2.style.display = 'none';
  const step3 = document.getElementById('diagStep3');
  if (step3) step3.style.display = 'block';
  
  const note = document.getElementById('diagDroppedColsNote');
  if (note) {
    note.textContent = `排除特徵（${(data.dropped_columns||[]).length} 個）：${(data.dropped_columns||[]).join(' · ') || '無'}`;
  }

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

function renderRetrainResult(data) {
  const panel = document.getElementById('retrainResultPanel');
  if (panel) panel.style.display = 'block';
  const subtitle = document.getElementById('retrainResultSubtitle');
  if (subtitle) {
    subtitle.textContent = `Session ID: ${data.session_id}`;
  }
  
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
      return `<div style="display:flex; justify-content:space-between; font-size:11.5px; border-bottom:1px dashed var(--border); padding:4px 0;"><span>${metricLabels[k]}</span><span style="font-weight:600;">${v}${delta}</span></div>`;
    }).join('');
  }
  
  renderMetricGrid('oldMetricsGrid', data.old_metrics, data.new_metrics);
  renderMetricGrid('newMetricsGrid', data.new_metrics, data.old_metrics);
  
  const droppedNote = document.getElementById('droppedColsNote');
  if (droppedNote) {
    droppedNote.textContent = `排除特徵: ${(data.dropped_columns||[]).join(', ') || '無'}`;
  }
}

async function adoptNewModel() {
  if (!window.edisState.pendingRetrainSession) return;
  const btn = document.getElementById('adoptBtn');
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
    const panel = document.getElementById('retrainResultPanel');
    if (panel) panel.style.display = 'none';
    showToast('新模型已採用並就地更新。', 'success');
    await refreshDashboard();
    await loadModelPerformance();
  } catch(e) {
    showToast('採用失敗：' + e.message, 'error');
    if (btn) { btn.disabled = false; btn.textContent = '✓ 採用新模型'; }
  }
}

async function discardNewModel() {
  if (!window.edisState.pendingRetrainSession) return;
  const btn = document.getElementById('discardBtn');
  if (btn) { btn.disabled = true; btn.textContent = '捨棄中...'; }
  try {
    await fetch(`${API_BASE}/api/retrain/discard`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: window.edisState.pendingRetrainSession })
    });
  } catch(e) {}
  
  window.edisState.pendingRetrainSession = null;
  const panel = document.getElementById('retrainResultPanel');
  if (panel) panel.style.display = 'none';
  showToast('已捨棄新模型，保留現有模型。', 'info');
  if (btn) { btn.disabled = false; btn.textContent = '✗ 捨棄新模型'; }
}

// Bind to window
window.loadModelPerformance = loadModelPerformance;
window.startManualRetrain = startManualRetrain;
window.pollRetrainTask = pollRetrainTask;
window.renderDiagRetrainResult = renderDiagRetrainResult;
window.renderRetrainResult = renderRetrainResult;
window.adoptNewModel = adoptNewModel;
window.discardNewModel = discardNewModel;

// ==========================================
// 診斷落地：帳戶劣化趨勢 + forecast（點3）、洩漏守門狀態（點4）
// 防 overflow：圖表先 destroy 再建；切換 unit 只重抓本面板。
// ==========================================
let _deterChart = null;
const _mpMoney = (v) => (v < 0 ? '-$' : '$') + Math.abs(Math.round(v)).toLocaleString();

async function loadDeterioration() {
  const unit = document.getElementById('deterUnit')?.value || 'segment';
  try {
    const d = await fetch(`${API_BASE}/api/diagnose/deterioration?unit=${unit}&penalty=250`).then(r => r.json());
    renderDeterChart(d.series || []);
    const body = document.getElementById('deterBody');
    if (body) body.innerHTML = (d.deteriorating || []).map(g => `
      <tr><td>${g.group}</td>
      <td style="font-weight:700;color:${g.trend_slope < 0 ? '#b91c1c' : '#15803d'};">${g.trend_slope}</td>
      <td>${_mpMoney(g.last_net_of_service)}</td>
      <td>${_mpMoney(g.forecast_next)}</td></tr>`).join('')
      || `<tr><td colspan="4" style="text-align:center;padding:20px;color:var(--muted)">資料不足</td></tr>`;
  } catch (e) { console.error('deterioration', e); }
}

function renderDeterChart(series) {
  const canvas = document.getElementById('deterChart');
  const fb = document.getElementById('deterFallback');
  if (!window.Chart || !canvas) { if (fb) { fb.style.display = 'block'; } if (canvas) canvas.style.display = 'none'; return; }
  if (fb) fb.style.display = 'none';
  canvas.style.display = 'block';
  // 月份取聯集排序，避免群組月份不一致時錯位
  const monthSet = new Set();
  series.forEach(s => s.months.forEach(m => monthSet.add(m)));
  const labels = Array.from(monthSet).sort();
  labels.push('下月(預測)');
  const palette = ['#437096', '#e07b54', '#15803d', '#9b59b6', '#d68910', '#16a085', '#c0392b'];
  const datasets = series.map((s, i) => {
    const map = {};
    s.months.forEach((m, j) => { map[m] = s.net_of_service[j]; });
    const data = labels.slice(0, -1).map(m => (m in map ? map[m] : null));
    data.push(s.forecast_next);   // 最後一格＝外推預測
    return { label: s.group, data, borderColor: palette[i % palette.length], backgroundColor: 'transparent', tension: 0.25, spanGaps: true, pointRadius: 2, borderWidth: 2 };
  });
  if (_deterChart) { _deterChart.destroy(); _deterChart = null; }
  _deterChart = new Chart(canvas.getContext('2d'), {
    type: 'line',
    data: { labels, datasets },
    options: {
      responsive: true, maintainAspectRatio: false,
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
        tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${_mpMoney(c.parsed.y)}` } } },
      scales: { y: { title: { display: true, text: '真價值 Net-of-Service $' } } },
    },
  });
}

async function loadLeakageAudit() {
  try {
    const d = await fetch(`${API_BASE}/api/profit/leakage-audit`).then(r => r.json());
    const tag = document.getElementById('leakGateTag');
    if (tag) { tag.textContent = d.gate_status === 'PASS' ? '✓ PASS' : '✗ FAIL';
      tag.style.background = d.gate_status === 'PASS' ? 'var(--success)' : 'var(--danger)'; tag.style.color = 'white'; }
    const lbl = d.column_labeling || {};
    const contract = d.serving_contract || {};
    const legacyText = contract.legacy_schema_ignored
      ? `舊 schema ${contract.legacy_schema_feature_count || 0} 欄已忽略`
      : `舊 schema：${contract.legacy_schema_status || '—'}`;
    const body = document.getElementById('leakAuditBody');
    if (body) body.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
        <div>
          <div style="font-size:12px;font-weight:700;margin-bottom:6px;">被擋欄位 (Blocked)</div>
          <div style="font-size:11px;color:var(--muted);line-height:1.8;">
            洩漏：${(d.blocked?.leakage || []).join('、') || '—'}<br>
            個資：${(d.blocked?.pii || []).length} 欄、ID：${(d.blocked?.id || []).length} 欄、雜訊：${(d.blocked?.noise || []).length} 欄</div>
          <div style="font-size:12px;font-weight:700;margin:12px 0 6px;">白名單 (Whitelist)</div>
          ${(d.whitelist || []).map(w => `<div style="font-size:11px;color:var(--muted);line-height:1.6;">• <b>${w.column}</b>：${w.reason}</div>`).join('')}
          <div style="font-size:11px;color:var(--muted);margin-top:10px;">守門規則：${d.identity_corr_guard?.rule || ''}<br>位置：<code>${d.identity_corr_guard?.enforced_in || ''}</code></div>
        </div>
        <div>
          <div style="font-size:12px;font-weight:700;margin-bottom:6px;">欄位標示 (actual / pred)</div>
          ${Object.entries(lbl).map(([k, v]) => `<div style="font-size:11px;line-height:1.7;padding:6px 8px;background:var(--slate-lt);border-radius:6px;margin-bottom:5px;"><b>${k}</b><br><span style="color:var(--muted);">${v}</span></div>`).join('')}
          <div style="font-size:11px;color:var(--muted);margin-top:8px;">特徵數：${d.feature_count}；洩漏入侵：${(d.leaked_in_features || []).length === 0 ? '無' : d.leaked_in_features.join('、')}</div>
          <div style="font-size:11px;color:var(--muted);margin-top:4px;">部署契約：${contract.source || '—'}；部署特徵 ${contract.active_feature_count || d.feature_count || 0} 欄；模型檔 ${contract.model_feature_count || '—'} 欄</div>
          <div style="font-size:11px;color:var(--muted);margin-top:4px;">${legacyText}</div>
          <div style="font-size:11px;color:var(--muted);margin-top:4px;">${contract.legacy_schema_note || ''}</div>
        </div>
      </div>`;
  } catch (e) { console.error('leakage audit', e); }
}

window.loadDeterioration = loadDeterioration;
window.loadLeakageAudit = loadLeakageAudit;

// 項目8：模型診斷子頁切換（延遲 / 收益）
let _mpProfitLoaded = false;
async function switchModelSubpage(which) {
  const delayPane = document.getElementById('mpDelayPane');
  const profitPane = document.getElementById('mpProfitPane');
  const tabDelay = document.getElementById('mpTabDelay');
  const tabProfit = document.getElementById('mpTabProfit');
  if (!delayPane || !profitPane) return;

  const setActive = (btn, active) => {
    if (!btn) return;
    btn.style.color = active ? 'var(--primary)' : 'var(--muted)';
    btn.style.borderBottom = active ? '2px solid var(--primary)' : '2px solid transparent';
  };

  if (which === 'profit') {
    delayPane.style.display = 'none';
    profitPane.style.display = 'block';
    setActive(tabProfit, true); setActive(tabDelay, false);
    if (!_mpProfitLoaded) {
      try {
        const resp = await fetch('/static/components/profit_prediction.html');
        profitPane.innerHTML = await resp.text();
        _mpProfitLoaded = true;
      } catch (e) {
        profitPane.innerHTML = `<div style="color:red;padding:20px;">收益模型子頁載入失敗：${e.message}</div>`;
        return;
      }
    }
    if (window.loadProfitPrediction) loadProfitPrediction();
    if (window.loadDeterioration) loadDeterioration();
    if (window.loadLeakageAudit) loadLeakageAudit();
  } else {
    profitPane.style.display = 'none';
    delayPane.style.display = 'block';
    setActive(tabDelay, true); setActive(tabProfit, false);
  }
}
window.switchModelSubpage = switchModelSubpage;
