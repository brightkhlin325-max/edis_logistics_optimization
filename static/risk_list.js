// ==========================================
// risk_list.js — EDIS 風險名單過濾與分頁控制邏輯
// ==========================================

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

// Bind to window
window.applyFilters = applyFilters;
window.loadFilteredRiskList = loadFilteredRiskList;
window.changeRiskListPage = changeRiskListPage;
