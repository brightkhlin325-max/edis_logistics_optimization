// ==========================================
// simulator.js — EDIS What-if 模擬器控制與結果渲染邏輯
// ==========================================

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
    badgeEl.textContent = `${badgeIcon[risk] || '○'} ${risk} 風險`;
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

function loadOrderIntoSimulator(shippingMode, orderRegion, days, price, qty, segment, market, orderDate) {
  const simulator = document.getElementById('instantPredictPanel');
  if (simulator) {
    simulator.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  document.getElementById('pf-shipping-mode').value = shippingMode;
  document.getElementById('pf-order-region').value = orderRegion;
  document.getElementById('pf-days').value = days;
  document.getElementById('pf-price').value = price;
  document.getElementById('pf-qty').value = qty;
  document.getElementById('pf-segment').value = segment;
  document.getElementById('pf-market').value = market;
  if (orderDate) {
    document.getElementById('pf-date').value = orderDate.split(' ')[0];
  } else {
    document.getElementById('pf-date').value = '';
  }

  runInstantPredict();
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
window.loadOrderIntoSimulator = loadOrderIntoSimulator;
window.runGlobalSimulation = runGlobalSimulation;
