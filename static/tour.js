const _TOUR = [
  { center:true,  icon:'🚀', title:'歡迎使用 EDIS',     desc:'這是一套物流延遲預測與最佳化調度系統。\n只需 1 分鐘，帶你快速認識各功能。' },
  { target:'nav-dashboard',    icon:'📊', title:'Dashboard 總覽',  desc:'查看模型 KPI、延遲風險指標與趨勢，\n快速掌握整體物流狀況。' },
  { target:'nav-optimization', icon:'⚡', title:'最佳化調度',      desc:'設定預算，系統自動找出 ROI 最佳的升級方案，\n降低延遲罰款。' },
  { target:'nav-risk-list',    icon:'⚠️', title:'風險訂單列表',    desc:'瀏覽高風險訂單，支援搜尋與篩選，\n點擊訂單可查看延遲原因分析。（需 Manager/Engineer 權限）' },
  { target:'nav-ai-assistant', icon:'✦',  title:'AI 助理',         desc:'用中文詢問物流決策建議，\nAI 根據去識別化資料回答。（需 Manager/Engineer 權限）' },
  { target:'nav-model-perf',   icon:'⚙',  title:'模型診斷與重訓',   desc:'監控 AUC、F1、Precision、Recall，並可進行手動/排除特徵重訓。（需 Engineer 權限）' },
  { target:'nav-region-map',   icon:'🗺️', title:'區域風險地圖',    desc:'全球熱力圖顯示各地區延遲風險，\n快速識別高風險配送區域。（需 Engineer 權限）' },
  { target:'nav-rbac',         icon:'🔐', title:'角色與權限',      desc:'展示系統基於角色的 API 安全防禦架獲。（需 Engineer 權限）' },
  { target:'nav-llm-settings', icon:'⚙',  title:'LLM 設定',        desc:'加密儲存底層 LLM 模組之連線參數與金鑰。（需 Engineer 權限）' }
];

let _tourStep = 0;

function startTour() {
  _tourStep = 0;
  const overlay = document.getElementById('tourOverlay');
  if (overlay) overlay.classList.add('active');
  _renderTour();
}

function _dots(current) {
  return _TOUR.map((_,i) => `<div class="t-dot${i===current?' on':''}"></div>`).join('');
}

function _renderTour() {
  const s = _TOUR[_tourStep];
  const card   = document.getElementById('tourCard');
  const cardC  = document.getElementById('tourCardCenter');
  const spot   = document.getElementById('tourSpotlight');

  if (!card || !cardC || !spot) return;

  if (s.center) {
    card.style.display = 'none'; spot.style.display = 'none';
    cardC.style.display = 'block';
    document.getElementById('tIconC').textContent  = s.icon;
    document.getElementById('tTitleC').textContent = s.title;
    document.getElementById('tDescC').textContent  = s.desc;
    document.getElementById('tDotsC').innerHTML    = _dots(_tourStep);
  } else {
    cardC.style.display = 'none';
    card.style.display = 'block'; spot.style.display = 'block';

    const total = _TOUR.length - 1;
    document.getElementById('tStepLabel').textContent = `步驟 ${_tourStep} / ${total}`;
    document.getElementById('tIcon').textContent  = s.icon;
    document.getElementById('tTitle').textContent = s.title;
    document.getElementById('tDesc').textContent  = s.desc;
    document.getElementById('tDots').innerHTML    = _dots(_tourStep);
    document.getElementById('tPrev').style.visibility = _tourStep <= 1 ? 'hidden' : 'visible';
    document.getElementById('tNext').textContent  = _tourStep === _TOUR.length-1 ? '完成 ✓' : '下一步 →';

    const el = document.getElementById(s.target);
    if (el) {
      const r = el.getBoundingClientRect(), p = 7;
      spot.style.cssText += `left:${r.left-p}px;top:${r.top-p}px;width:${r.width+p*2}px;height:${r.height+p*2}px;`;
      const cardTop = Math.min(Math.max(r.top - 10, 80), window.innerHeight - 260);
      card.style.left = '248px';
      card.style.top  = cardTop + 'px';
    }
  }
}

function tourNext() {
  _tourStep >= _TOUR.length - 1 ? _tourEnd() : (++_tourStep, _renderTour());
}
function tourPrev() {
  _tourStep > 1 && (--_tourStep, _renderTour());
}
function tourSkip() { _tourEnd(); }
function _tourEnd() {
  const overlay = document.getElementById('tourOverlay');
  if (overlay) overlay.classList.remove('active');
  localStorage.setItem('edis_tour','1');
}

window.addEventListener('load', function() {
  if (!localStorage.getItem('edis_tour')) setTimeout(startTour, 900);
});

// Export functions to global scope
window.startTour = startTour;
window.tourNext = tourNext;
window.tourPrev = tourPrev;
window.tourSkip = tourSkip;
