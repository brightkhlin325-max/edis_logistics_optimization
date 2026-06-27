// Profit prediction page.

window.edisState.profitPredictionPage = 1;
window.edisState.profitPredictionLimit = 25;

function formatProfitMoney(value) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  return num.toLocaleString('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function formatProfitMetric(value, digits = 3) {
  const num = Number(value);
  if (!Number.isFinite(num)) return '--';
  return num.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function setProfitEmptyState(isEmpty, message) {
  const emptyState = document.getElementById('profitEmptyState');
  const content = document.getElementById('profitContent');
  if (emptyState) {
    emptyState.style.display = isEmpty ? 'block' : 'none';
    if (message) {
      const subtitle = emptyState.querySelector('.panel-subtitle');
      if (subtitle) subtitle.textContent = message;
    }
  }
  if (content) content.style.display = isEmpty ? 'none' : 'block';
}

async function fetchProfitMetrics() {
  const res = await fetch(`${API_BASE}/api/profit/metrics`);
  if (!res.ok) throw new Error('收益模型指標載入失敗');
  return res.json();
}

async function fetchProfitFeatureImportance() {
  const res = await fetch(`${API_BASE}/api/profit/feature-importance?limit=20`);
  if (!res.ok) throw new Error('收益影響因子載入失敗');
  return res.json();
}

async function fetchProfitPredictions(page = 1) {
  const limit = window.edisState.profitPredictionLimit || 25;
  const url = `${API_BASE}/api/profit/predictions?page=${page}&limit=${limit}&sort=abs_residual`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('收益預測結果載入失敗');
  return res.json();
}

function renderProfitMetrics(payload) {
  const metrics = payload.metrics || {};
  const manifest = payload.manifest || {};

  const rmse = document.getElementById('profitRmse');
  const mae = document.getElementById('profitMae');
  const r2 = document.getElementById('profitR2');
  const shape = document.getElementById('profitShape');
  const target = document.getElementById('profitTarget');

  if (rmse) rmse.textContent = formatProfitMoney(metrics.rmse);
  if (mae) mae.textContent = formatProfitMoney(metrics.mae);
  if (r2) r2.textContent = formatProfitMetric(metrics.r2, 3);
  if (shape) shape.textContent = `${metrics.row_count || 0} / ${manifest.feature_count || metrics.feature_count || 0}`;
  if (target) target.textContent = `Target: ${manifest.target_column || metrics.target_column || 'Order Profit Per Order'}`;
}

function renderProfitFeatureImportance(payload) {
  const container = document.getElementById('profitFeatureImportance');
  if (!container) return;

  const rows = payload.data || [];
  if (!rows.length) {
    container.innerHTML = `<div style="color:var(--muted); font-size:13px;">尚無 feature importance。</div>`;
    return;
  }

  const maxValue = Math.max(...rows.map(row => Number(row.importance) || 0), 0.000001);
  container.innerHTML = rows.map(row => {
    const width = Math.max(4, ((Number(row.importance) || 0) / maxValue) * 100);
    return `
      <div>
        <div style="display:flex; justify-content:space-between; gap:12px; font-size:12px; margin-bottom:4px;">
          <span style="font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${row.feature}">${row.feature}</span>
          <span style="font-family:monospace; color:var(--muted);">${formatProfitMetric(row.importance, 4)}</span>
        </div>
        <div style="height:8px; background:var(--slate-lt); border-radius:999px; overflow:hidden;">
          <div style="height:100%; width:${width}%; background:var(--primary); border-radius:999px;"></div>
        </div>
      </div>
    `;
  }).join('');
}

function renderProfitPredictions(payload) {
  const tbody = document.getElementById('profitPredictionTableBody');
  if (!tbody) return;

  const countLabel = document.getElementById('profitPredictionCount');
  if (countLabel) countLabel.textContent = `${payload.count || 0} rows`;

  const totalPages = payload.total_pages || 1;
  const pageIndicator = document.getElementById('profitPageIndicator');
  if (pageIndicator) pageIndicator.textContent = `Page ${payload.page || 1} / ${totalPages}`;

  const prevBtn = document.getElementById('profitPrevBtn');
  const nextBtn = document.getElementById('profitNextBtn');
  if (prevBtn) {
    prevBtn.disabled = (payload.page || 1) <= 1;
    prevBtn.style.opacity = prevBtn.disabled ? 0.5 : 1;
  }
  if (nextBtn) {
    nextBtn.disabled = (payload.page || 1) >= totalPages;
    nextBtn.style.opacity = nextBtn.disabled ? 0.5 : 1;
  }

  const rows = payload.data || [];
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:24px;color:var(--muted)">尚無收益預測結果。</td></tr>`;
    return;
  }

  tbody.innerHTML = rows.map(row => {
    const residual = Number(row.residual) || 0;
    const color = residual >= 0 ? 'var(--success)' : 'var(--danger)';
    return `
      <tr>
        <td><span class="order-id">${row.row_id}</span></td>
        <td>${formatProfitMoney(row.actual_profit)}</td>
        <td>${formatProfitMoney(row.predicted_profit)}</td>
        <td style="color:${color}; font-weight:600;">${formatProfitMoney(row.residual)}</td>
        <td>${formatProfitMoney(row.abs_residual)}</td>
      </tr>
    `;
  }).join('');
}

async function loadProfitPrediction() {
  const content = document.getElementById('profitContent');
  if (!content) return;

  try {
    const metrics = await fetchProfitMetrics();
    if (!metrics.is_trained) {
      setProfitEmptyState(true, metrics.message);
      return;
    }

    setProfitEmptyState(false);
    renderProfitMetrics(metrics);

    const [importance, predictions] = await Promise.all([
      fetchProfitFeatureImportance(),
      fetchProfitPredictions(window.edisState.profitPredictionPage || 1),
    ]);
    renderProfitFeatureImportance(importance);
    renderProfitPredictions(predictions);
  } catch (e) {
    setProfitEmptyState(true, e.message);
    if (window.showToast) showToast(e.message, 'error');
  }
}

function changeProfitPage(delta) {
  const nextPage = Math.max(1, (window.edisState.profitPredictionPage || 1) + delta);
  window.edisState.profitPredictionPage = nextPage;
  loadProfitPrediction();
}

window.loadProfitPrediction = loadProfitPrediction;
window.changeProfitPage = changeProfitPage;
