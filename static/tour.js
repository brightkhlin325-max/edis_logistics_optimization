const _TOUR = [
  { center:true,  icon:'🚀', title:'歡迎使用 SLIDE',     desc:'這是一套供應鏈物流智慧調度引擎，提供延遲預估與優化調度。\n只需 1 分鐘，帶你快速認識各功能。' },
  { target:'nav-dashboard',    icon:'📊', title:'Dashboard 總覽',  desc:'查看關鍵預估指標與延遲趨勢，\n快速掌握整體物流狀況。' },
  { target:'nav-optimization', icon:'⚡', title:'最佳化調度',      desc:'設定預算，系統自動找出效益最佳的升級方案，\n降低延遲損失。' },
  { target:'nav-roi-simulator', icon:'◎', title:'最佳化ROI模擬器',  desc:'結合真實價值、風險散點、四象限決策矩陣與 What-if 模擬，\n幫助你快速制定最佳物流策略。' },
  { target:'nav-risk-list',    icon:'⚠️', title:'風險訂單管理',    desc:'瀏覽高風險訂單，支援搜尋與篩選，\n點擊訂單可查看延遲原因分析。（需主管與工程師權限）' },
  { target:'nav-ai-assistant', icon:'✦',  title:'AI 決策助理',      desc:'輸入查詢尋求物流對策，可點選新增的「引導問題卡片」快速對話。\n系統根據去識別化資料生成分析。（需主管與工程師權限）' },
  { target:'nav-model-perf',   icon:'⚙',  title:'模型診斷與重訓',   desc:'監控各項預估指標，並可啟動模型重訓校準。（需工程師權限）' },
  { target:'nav-region-map',   icon:'🗺️', title:'區域風險地圖',    desc:'全球熱力圖顯示各地區延遲風險，\n快速識別高風險配送區域。（需工程師權限）' },
  { target:'nav-rbac',         icon:'🔐', title:'權限管理',        desc:'展示系統不同角色的功能操作與存取限制。（需工程師權限）' },
  { target:'nav-llm-settings', icon:'⚙',  title:'模型設定',        desc:'安全儲存模型連線參數與金鑰。（需工程師權限）' }
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
