const TOUR_STEPS = [
  {
    center: true,
    icon: '🚀',
    title: '歡迎使用 SLIDE',
    desc: '這是一套供應鏈物流智慧調度引擎，依你的權限顯示可使用的功能。\n只需 1 分鐘，帶你快速認識目前角色能做什麼。'
  },
  {
    target: 'nav-dashboard',
    icon: '📊',
    title: 'Dashboard 總覽',
    desc: '查看延遲預估、風險集中組合與主管建議，快速掌握整體物流狀況。'
  },
  {
    target: 'nav-optimization',
    icon: '⚡',
    title: '最佳化調度',
    desc: '比較不同預算、升級成本與罰金假設。主管與工程師可送出最佳化試算，Viewer 可查看結果與假設。'
  },
  {
    target: 'nav-risk-list',
    icon: '⚠️',
    title: '風險訂單管理',
    desc: '瀏覽高風險訂單、篩選區域與配送方式，並可把訂單帶入 What-if 模擬。',
    roles: ['manager', 'engineer']
  },
  {
    target: 'nav-ai-assistant',
    icon: '✦',
    title: 'AI 決策助理',
    desc: '用目前資料回答延遲診斷、預算配置、ROI 罰金檢查與回填資料流程。',
    roles: ['manager', 'engineer']
  },
  {
    target: 'nav-model-perf',
    icon: '⚙',
    title: '模型診斷與重訓',
    desc: '檢查延遲模型與收益模型的測試表現、資料洩漏守門與重訓資料匯入。',
    roles: ['engineer']
  },
  {
    target: 'nav-rbac',
    icon: '🔐',
    title: '權限管理',
    desc: '檢查 Viewer、Manager、Engineer 對應的後端 API 權限與頁面功能。',
    roles: ['engineer']
  },
  {
    target: 'nav-llm-settings',
    icon: '🤖',
    title: '模型設定',
    desc: '設定本機或外部模型連線參數，僅工程師可使用。',
    roles: ['engineer']
  }
];

let _tourStep = 0;

function _currentRole() {
  return String(window.edisState?.currentRole || 'viewer').toLowerCase();
}

function _roleAllowed(step) {
  if (!step.roles) return true;
  return step.roles.includes(_currentRole());
}

function _targetVisible(step) {
  if (step.center) return true;
  const el = document.getElementById(step.target);
  if (!el) return false;
  const style = window.getComputedStyle(el);
  return style.display !== 'none' && style.visibility !== 'hidden' && el.offsetParent !== null;
}

function _currentTour() {
  const steps = TOUR_STEPS.filter(step => _roleAllowed(step) && _targetVisible(step));
  return steps.length ? steps : TOUR_STEPS.filter(step => step.center);
}

function startTour() {
  _tourStep = 0;
  const overlay = document.getElementById('tourOverlay');
  if (overlay) overlay.classList.add('active');
  _renderTour();
}

function _dots(current) {
  return _currentTour().map((_, i) => `<div class="t-dot${i === current ? ' on' : ''}"></div>`).join('');
}

function _setText(id, text) {
  const el = document.getElementById(id);
  if (el) el.textContent = text;
}

function _setHtml(id, html) {
  const el = document.getElementById(id);
  if (el) el.innerHTML = html;
}

function _renderTour() {
  const tour = _currentTour();
  if (!tour.length) return;
  if (_tourStep >= tour.length) _tourStep = tour.length - 1;

  const s = tour[_tourStep];
  const card = document.getElementById('tourCard');
  const cardC = document.getElementById('tourCardCenter');
  const spot = document.getElementById('tourSpotlight');
  if (!card || !cardC || !spot) return;

  if (s.center) {
    card.style.display = 'none';
    spot.style.display = 'none';
    cardC.style.display = 'block';
    _setText('tIconC', s.icon);
    _setText('tTitleC', s.title);
    _setText('tDescC', s.desc);
    _setHtml('tDotsC', _dots(_tourStep));
    return;
  }

  cardC.style.display = 'none';
  card.style.display = 'block';
  spot.style.display = 'block';

  const total = tour.length - 1;
  _setText('tStepLabel', `步驟 ${_tourStep} / ${total}`);
  _setText('tIcon', s.icon);
  _setText('tTitle', s.title);
  _setText('tDesc', s.desc);
  _setHtml('tDots', _dots(_tourStep));

  const prev = document.getElementById('tPrev');
  const next = document.getElementById('tNext');
  if (prev) prev.style.visibility = _tourStep <= 1 ? 'hidden' : 'visible';
  if (next) next.textContent = _tourStep === tour.length - 1 ? '完成 ✓' : '下一步 →';

  const el = document.getElementById(s.target);
  if (el) {
    const r = el.getBoundingClientRect();
    const p = 7;
    spot.style.cssText += `left:${r.left - p}px;top:${r.top - p}px;width:${r.width + p * 2}px;height:${r.height + p * 2}px;`;
    const cardTop = Math.min(Math.max(r.top - 10, 80), window.innerHeight - 260);
    card.style.left = '248px';
    card.style.top = `${cardTop}px`;
  }
}

function tourNext() {
  const tour = _currentTour();
  _tourStep >= tour.length - 1 ? _tourEnd() : (++_tourStep, _renderTour());
}

function tourPrev() {
  if (_tourStep > 1) {
    _tourStep -= 1;
    _renderTour();
  }
}

function tourSkip() {
  _tourEnd();
}

function _tourEnd() {
  const overlay = document.getElementById('tourOverlay');
  if (overlay) overlay.classList.remove('active');
  localStorage.setItem('edis_tour', '1');
}

window.addEventListener('load', function() {
  if (!localStorage.getItem('edis_tour')) setTimeout(startTour, 900);
});

window.startTour = startTour;
window.tourNext = tourNext;
window.tourPrev = tourPrev;
window.tourSkip = tourSkip;
