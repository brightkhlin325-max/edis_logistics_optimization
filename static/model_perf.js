// ==========================================
// model_perf.js — EDIS 模型診斷與排除特徵重訓頁面邏輯
// ==========================================

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
