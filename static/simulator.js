// ==========================================
// simulator.js — SLIDE What-if 模擬器控制與結果渲染邏輯
// ==========================================

const SIM_FEATURE_FALLBACK_ORDER = [
  'shipping_mode',
  'days_for_shipment',
  'order_type',
  'order_region',
  'product_price',
  'order_item_quantity'
];

const SIM_FEATURE_IMPORTANCE_MAP = {
  'Shipping Mode': 'shipping_mode',
  'Days for shipment (scheduled)': 'days_for_shipment',
  'Type': 'order_type',
  'order_hour': 'order_hour',
  'Order Region': 'order_region',
  'Product Price': 'product_price',
  'Order Item Quantity': 'order_item_quantity',
  'Customer Segment': 'customer_segment',
  'Market': 'market',
};

const SIM_FULL_WIDTH_FEATURES = new Set(['shipping_mode', 'order_region']);
const SIM_HIDDEN_UI_FEATURES = new Set(['order_hour']);

let simulatorFeatureOrderLoaded = false;

function groupedSimulatorFeatureKey(feature) {
  const name = String(feature || '');
  if (name.startsWith('Shipping Mode_')) return 'shipping_mode';
  if (name.startsWith('Type_')) return 'order_type';
  if (name.startsWith('Customer Segment_')) return 'customer_segment';
  if (name.startsWith('Market_')) return 'market';
  if (name.includes('Order Region')) return 'order_region';
  const key = SIM_FEATURE_IMPORTANCE_MAP[name] || null;
  return key && !SIM_HIDDEN_UI_FEATURES.has(key) ? key : null;
}

function applySimulatorFeatureOrder(order) {
  const fields = Array.from(document.querySelectorAll('#instantPredictFields .sim-feature-field'));
  if (!fields.length) return;
  const ranked = Array.isArray(order) && order.length ? order : SIM_FEATURE_FALLBACK_ORDER;
  const visualOrder = [
    ...ranked.filter((key) => SIM_FULL_WIDTH_FEATURES.has(key)),
    ...ranked.filter((key) => !SIM_FULL_WIDTH_FEATURES.has(key)),
  ];
  fields.forEach((field) => {
    const key = field.dataset.featureKey;
    const idx = visualOrder.indexOf(key);
    field.style.order = String(idx >= 0 ? idx : visualOrder.length + 10);
  });
}

async function loadSimulatorFeatureOrder() {
  if (simulatorFeatureOrderLoaded) {
    applySimulatorFeatureOrder(window.edisState?.simulatorFeatureOrder);
    return;
  }
  simulatorFeatureOrderLoaded = true;
  try {
    const metrics = await fetchMetrics();
    const importance = metrics.feature_importance || {};
    const grouped = {};
    Object.entries(importance).forEach(([feature, weight]) => {
      const key = groupedSimulatorFeatureKey(feature);
      if (!key) return;
      grouped[key] = (grouped[key] || 0) + Number(weight || 0);
    });
    const ranked = Object.entries(grouped)
      .sort((a, b) => b[1] - a[1])
      .map(([key]) => key);
    SIM_FEATURE_FALLBACK_ORDER.forEach((key) => {
      if (!ranked.includes(key)) ranked.push(key);
    });
    window.edisState.simulatorFeatureOrder = ranked;
    applySimulatorFeatureOrder(ranked);
  } catch (error) {
    applySimulatorFeatureOrder(SIM_FEATURE_FALLBACK_ORDER);
  }
}

function orderDateWithHour(dateValue, hourValue) {
  const hour = Math.max(0, Math.min(23, parseInt(hourValue, 10) || 0));
  const hh = String(hour).padStart(2, '0');
  const baseDate = dateValue || '2020-01-01';
  return `${String(baseDate).split(' ')[0]} ${hh}:00:00`;
}

async function runInstantPredict() {
  const btn = document.getElementById('predictRunBtn');
  const btnIcon = document.getElementById('predictBtnIcon');
  const btnText = document.getElementById('predictBtnText');
  if (!btn) return;

  const dateValue = document.getElementById('pf-date').value || '';
  const hourValue = document.getElementById('pf-hour').value || 0;
  const payload = {
    shipping_mode:       document.getElementById('pf-shipping-mode').value,
    order_region:        document.getElementById('pf-order-region').value,
    order_type:          document.getElementById('pf-order-type').value,
    days_for_shipment:   parseFloat(document.getElementById('pf-days').value)   || 4,
    product_price:       parseFloat(document.getElementById('pf-price').value)  || 59.99,
    order_item_quantity: parseInt(document.getElementById('pf-qty').value)       || 1,
    customer_segment:    document.getElementById('pf-segment').value,
    market:              document.getElementById('pf-market').value,
    order_date:          orderDateWithHour(dateValue, hourValue),
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
    if (card) card.classList.add('has-result');
    const placeholder = document.getElementById('predictPlaceholder');
    if (placeholder) placeholder.style.display = 'none';
    const content = document.getElementById('predictResultContent');
    if (content) {
      content.style.display = 'flex';
      content.innerHTML = `
        <div style="text-align:center;color:#c0392b;padding:20px 0;">
          <div style="font-size:32px;margin-bottom:8px;">⚠️</div>
          <div style="font-size:13px;font-weight:600;">預測失敗</div>
          <div style="font-size:12px;color:var(--muted);margin-top:6px;line-height:1.6;">${e.message}</div>
        </div>`;
    }
  } finally {
    btn.disabled = false;
    if (btnIcon) { btnIcon.innerHTML = ''; btnIcon.textContent = '🔮'; }
    if (btnText) btnText.textContent = '分析單筆訂單調度風險';
  }
}

function renderPredictResult(data) {
  const pLate = data.p_late || 0;
  const risk = data.risk_bucket || 'Low';
  const riskUpper = String(risk).toUpperCase();
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

  const gaugeFill = document.getElementById('gaugeFill');
  const colorMap = { High: '#c0392b', Medium: '#d68910', Low: '#27ae60' };
  const gaugeColor = colorMap[risk] || '#437096';

  if (gaugeFill) {
    gaugeFill.style.background = gaugeColor;
    gaugeFill.style.width = (pLate * 100).toFixed(1) + '%';
  }

  const gaugePct = document.getElementById('gaugePct');
  if (gaugePct) {
    gaugePct.style.color = gaugeColor;
    animateCounter(gaugePct, 0, Math.round(pLate * 1000) / 10, 900, v => v.toFixed(1) + '%');
  }

  const badgeEl = document.getElementById('predictRiskBadge');
  if (badgeEl) {
    badgeEl.className = 'predict-risk-badge';
    const badgeCls = { High: 'prb-high', Medium: 'prb-med', Low: 'prb-low' };
    const badgeIcon = { High: '🔴', Medium: '🟡', Low: '🟢' };
    badgeEl.classList.add(badgeCls[risk] || 'prb-low');
    badgeEl.textContent = `${badgeIcon[risk] || '○'} ${riskUpper}`;
  }

  document.getElementById('pdPenalty').textContent = `USD $${penalty.toFixed(2)}`;
  document.getElementById('pdUpgradeCost').textContent = `USD $${upgCost.toFixed(2)}`;
  const netEl = document.getElementById('pdNetBenefit');
  netEl.textContent = (netBen >= 0 ? '+' : '') + `USD $${netBen.toFixed(2)}`;
  netEl.style.color = netBen >= 0 ? '#27ae60' : '#c0392b';

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

function setSimulatorSelectValue(id, value) {
  const select = document.getElementById(id);
  if (!select) return false;

  const normalized = String(value || '');
  if (normalized && !Array.from(select.options).some(option => option.value === normalized)) {
    const option = new Option(normalized, normalized, true, true);
    select.add(option);
  }
  if (normalized) select.value = normalized;
  return true;
}

function normalizeSimulationOrder(orderOrShippingMode, orderRegion, days, price, qty, segment, market, orderDate) {
  if (orderOrShippingMode && typeof orderOrShippingMode === 'object' && !Array.isArray(orderOrShippingMode)) {
    return orderOrShippingMode;
  }
  return {
    shipping_mode: orderOrShippingMode,
    order_region: orderRegion,
    days_for_shipment: days,
    product_price: price,
    order_item_quantity: qty,
    customer_segment: segment,
    market,
    order_date: orderDate,
  };
}

function loadOrderIntoSimulator(orderOrShippingMode, orderRegion, days, price, qty, segment, market, orderDate) {
  const order = normalizeSimulationOrder(orderOrShippingMode, orderRegion, days, price, qty, segment, market, orderDate);
  const simulator = document.getElementById('instantPredictPanel');
  const requiredIds = [
    'pf-shipping-mode', 'pf-order-region', 'pf-days', 'pf-price', 'pf-qty',
    'pf-segment', 'pf-market', 'pf-date', 'pf-order-type', 'pf-hour', 'predictRunBtn'
  ];
  if (!simulator || requiredIds.some(id => !document.getElementById(id))) return false;

  loadSimulatorFeatureOrder();
  simulator.scrollIntoView({ behavior: 'smooth', block: 'center' });

  setSimulatorSelectValue('pf-shipping-mode', order.shipping_mode || order.shippingMode || 'Standard Class');
  setSimulatorSelectValue('pf-order-region', order.order_region || order.orderRegion || 'Western Europe');
  setSimulatorSelectValue('pf-order-type', order.order_type || order.orderType || 'PAYMENT');
  document.getElementById('pf-days').value = order.days_for_shipment ?? order.days ?? 4;
  document.getElementById('pf-price').value = order.product_price ?? order.price ?? 59.99;
  document.getElementById('pf-qty').value = order.order_item_quantity ?? order.quantity ?? 1;
  document.getElementById('pf-segment').value = order.customer_segment || order.segment || 'Consumer';
  document.getElementById('pf-market').value = order.market || 'Europe';
  const sourceDate = order.order_date || order.orderDate || '';
  if (sourceDate) {
    document.getElementById('pf-date').value = String(sourceDate).split(' ')[0];
  } else {
    document.getElementById('pf-date').value = '';
  }
  document.getElementById('pf-hour').value = order.order_hour ?? order.orderHour ?? 11;

  runInstantPredict();
  return true;
}

function openOrderSimulation(orderOrShippingMode, orderRegion, days, price, qty, segment, market, orderDate) {
  const order = normalizeSimulationOrder(orderOrShippingMode, orderRegion, days, price, qty, segment, market, orderDate);
  let attempts = 0;

  const applyWhenReady = () => {
    if (loadOrderIntoSimulator(order)) return;
    attempts += 1;
    if (attempts < 20) {
      window.setTimeout(applyWhenReady, 50);
    } else if (window.showToast) {
      window.showToast('What-if 模擬器尚未載入完成，請重新點選模擬。', 'error');
    }
  };

  if (window.showPage) window.showPage('risk-list');
  window.requestAnimationFrame(applyWhenReady);
}

async function runGlobalSimulation(val) {
  const simLabel = document.getElementById('globalSimValue');
  const simNote = document.getElementById('globalSimResultNote');
  if (simLabel) simLabel.textContent = val;
  if (simNote) simNote.textContent = '計算模擬預估中...';

  try {
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

// Bind to window
window.runInstantPredict = runInstantPredict;
window.renderPredictResult = renderPredictResult;
window.loadSimulatorFeatureOrder = loadSimulatorFeatureOrder;
window.loadOrderIntoSimulator = loadOrderIntoSimulator;
window.openOrderSimulation = openOrderSimulation;
window.runGlobalSimulation = runGlobalSimulation;
