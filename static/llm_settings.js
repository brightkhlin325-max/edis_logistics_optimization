// ==========================================
// llm_settings.js — EDIS AI 助理與大語言模型設定邏輯
// ==========================================

const LLM_MODEL_OPTIONS = {
  local: [{ value: '', label: '不使用外部模型' }],
  openai: [
    { value: 'gpt-4o-mini', label: 'gpt-4o-mini' },
    { value: 'gpt-4o', label: 'gpt-4o' },
    { value: 'gpt-4', label: 'gpt-4' },
    { value: '__custom__', label: '自訂模型...' }
  ],
  openai_compatible: [
    { value: 'gpt-4o-mini', label: 'gpt-4o-mini' },
    { value: 'deepseek-chat', label: 'deepseek-chat' },
    { value: '__custom__', label: '自訂模型...' }
  ],
  gemini: [
    { value: 'gemini-1.5-flash', label: 'gemini-1.5-flash' },
    { value: 'gemini-2.0-flash', label: 'gemini-2.0-flash' },
    { value: '__custom__', label: '自訂模型...' }
  ],
  claude: [
    { value: 'claude-3-5-sonnet-20241022', label: 'claude-3-5-sonnet-20241022' },
    { value: 'claude-3-5-haiku-20241022', label: 'claude-3-5-haiku-20241022' },
    { value: '__custom__', label: '自訂模型...' }
  ],
  ollama: [
    { value: 'llama3.1', label: 'llama3.1' },
    { value: 'deepseek-r1', label: 'deepseek-r1' },
    { value: '__custom__', label: '自訂模型...' }
  ]
};

const LLM_PROVIDER_DEFAULT_URLS = {
  local: '',
  openai: 'https://api.openai.com/v1/chat/completions',
  openai_compatible: 'https://api.openai.com/v1/chat/completions',
  gemini: '',
  claude: 'https://api.anthropic.com/v1/messages',
  ollama: 'http://localhost:11434/api/chat'
};

let savedLLMProvider = null;

function providerNeedsApiKey(provider) {
  return !['local', 'ollama'].includes(provider);
}

function handleLLMProviderChange() {
  const providerInput = document.getElementById('llmProviderInput');
  const apiUrlInput = document.getElementById('llmApiUrlInput');
  const keep = document.getElementById('llmKeepKeyInput');
  const keyInput = document.getElementById('llmApiKeyInput');
  updateLLMModelOptions('', false);
  if (providerInput && apiUrlInput) {
    apiUrlInput.value = LLM_PROVIDER_DEFAULT_URLS[providerInput.value] || '';
  }
  if (keep) keep.checked = false;
  if (keyInput) keyInput.value = '';
  updateLLMKeyInputState();
}

function updateLLMModelOptions(selectedModel = '', allowCustomFallback = true) {
  const providerInput = document.getElementById('llmProviderInput');
  const modelInput = document.getElementById('llmModelInput');
  const customInput = document.getElementById('llmCustomModelInput');
  if (!providerInput || !modelInput) return;

  const provider = providerInput.value || 'local';
  const options = LLM_MODEL_OPTIONS[provider] || LLM_MODEL_OPTIONS.local;
  const previous = selectedModel || '';
  modelInput.innerHTML = '';

  options.forEach(item => {
    const opt = document.createElement('option');
    opt.value = item.value;
    opt.textContent = item.label;
    modelInput.appendChild(opt);
  });

  const matched = options.some(item => item.value === previous);
  if (matched) {
    modelInput.value = previous;
    if (customInput) customInput.value = '';
  } else if (allowCustomFallback && previous && options.some(item => item.value === '__custom__')) {
    modelInput.value = '__custom__';
    if (customInput) customInput.value = previous;
  } else {
    modelInput.value = options[0].value;
    if (customInput) customInput.value = '';
  }
  updateLLMCustomModelState();
}

function updateLLMCustomModelState() {
  const modelInput = document.getElementById('llmModelInput');
  const customInput = document.getElementById('llmCustomModelInput');
  if (!modelInput || !customInput) return;
  const isCustom = modelInput.value === '__custom__';
  customInput.style.display = isCustom ? 'block' : 'none';
  customInput.disabled = !isCustom;
}

function getSelectedLLMModel() {
  const modelInput = document.getElementById('llmModelInput');
  const customInput = document.getElementById('llmCustomModelInput');
  if (!modelInput) return '';
  if (modelInput.value === '__custom__') {
    return (customInput?.value || '').trim();
  }
  return modelInput.value.trim();
}

function updateLLMKeyInputState() {
  const keep = document.getElementById('llmKeepKeyInput');
  const keepRow = document.getElementById('llmKeepKeyRow');
  const input = document.getElementById('llmApiKeyInput');
  const provider = document.getElementById('llmProviderInput')?.value || 'local';
  if (!keep || !input) return;

  if (!providerNeedsApiKey(provider)) {
    if (keepRow) keepRow.style.display = 'none';
    keep.checked = false;
    keep.disabled = true;
    input.value = '';
    input.disabled = true;
    input.placeholder = provider === 'ollama' ? 'Ollama 為本機服務，不需要 API Key' : 'Local 模式不需要 API Key';
  } else if (keep.checked) {
    if (keepRow) keepRow.style.display = 'flex';
    keep.disabled = false;
    input.value = '';
    input.disabled = true;
    input.placeholder = '已保留目前儲存的 API Key';
  } else {
    if (keepRow) keepRow.style.display = 'flex';
    keep.disabled = savedLLMProvider !== provider;
    input.disabled = false;
    input.placeholder = savedLLMProvider === provider ? '貼上新的 API Key；留空儲存會清除目前 Key' : '請貼上此 Provider 的 API Key';
  }
}

async function loadLLMSettings() {
  updateLLMSettingsAccess();
  const isMOrEng = window.edisState.currentRole === 'manager' || window.edisState.currentRole === 'engineer';
  if (!isMOrEng) return;

  const status = document.getElementById('llmSettingsStatus');
  if (status) status.textContent = '讀取設定中...';
  try {
    const res = await fetch(`${API_BASE}/api/llm/settings`);
    if (!res.ok) throw new Error('讀取設定失敗');
    const data = await res.json();
    const s = data.settings || {};
    savedLLMProvider = s.api_key_set ? (s.provider || null) : null;
    document.getElementById('llmProviderInput').value = s.provider || 'local';
    updateLLMModelOptions(s.model || '');
    document.getElementById('llmApiUrlInput').value = s.api_url || '';
    document.getElementById('llmApiKeyInput').value = '';
    document.getElementById('llmKeepKeyInput').checked = !!s.api_key_set && providerNeedsApiKey(s.provider || 'local');
    updateLLMKeyInputState();
    if (status) {
      status.textContent = s.api_key_set
        ? `目前已設定：${s.provider} / ${s.model || '預設模型'} (API Key 已配置)`
        : `目前已設定：${s.provider} / ${s.model || '預設模型'} (未配置 API Key)`;
    }
  } catch (e) {
    if (status) status.textContent = '讀取設定失敗：' + e.message;
  }
}

async function saveLLMSettings() {
  const isMOrEng = window.edisState.currentRole === 'manager' || window.edisState.currentRole === 'engineer';
  if (!isMOrEng) return;

  const btn = document.getElementById('llmSaveBtn');
  const status = document.getElementById('llmSettingsStatus');
  const originalText = btn.textContent;
  btn.textContent = '儲存中...';
  btn.disabled = true;

  const keepKey = document.getElementById('llmKeepKeyInput').checked;
  const apiKeyInput = document.getElementById('llmApiKeyInput').value.trim();
  const selectedModel = getSelectedLLMModel();
  const selectedProvider = document.getElementById('llmProviderInput').value;

  try {
    const res = await fetch(`${API_BASE}/api/llm/settings`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider: selectedProvider,
        model: selectedModel,
        api_url: document.getElementById('llmApiUrlInput').value.trim(),
        api_key: providerNeedsApiKey(selectedProvider)
          ? (keepKey && savedLLMProvider === selectedProvider && !apiKeyInput ? '__KEEP_EXISTING__' : apiKeyInput)
          : ''
      })
    });
    if (!res.ok) throw new Error('儲存失敗');
    showToast('LLM 設定已順利保存！', 'success');
    loadLLMSettings();
  } catch (e) {
    if (status) status.textContent = '儲存失敗：' + e.message;
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

function updateLLMSettingsAccess() {
  const role = window.edisState.currentRole;
  const isM = role === 'manager';
  const isEng = role === 'engineer';
  const isMOrEng = isM || isEng;
  const badge = document.getElementById('llmSettingsRoleBadge');
  const locked = document.getElementById('llmSettingsLocked');
  const form = document.getElementById('llmSettingsForm');
  if (badge) {
    if (isEng) {
      badge.className = 'role-badge badge-engineer';
      badge.textContent = 'Engineer';
    } else if (isM) {
      badge.className = 'role-badge badge-manager';
      badge.textContent = 'Manager';
    } else {
      badge.className = 'role-badge badge-viewer';
      badge.textContent = 'Viewer';
    }
  }
  if (locked) locked.style.display = isMOrEng ? 'none' : 'block';
  if (form) form.style.display = isMOrEng ? 'grid' : 'none';
}

function appendAIMessage(type, text) {
  const log = document.getElementById('aiChatLog');
  if (!log) return;
  const msg = document.createElement('div');
  msg.className = `ai-message ${type}`;
  msg.textContent = text;
  log.appendChild(msg);
  log.scrollTop = log.scrollHeight;
}

async function uploadPredictionCSV(input) {
  const file = input.files[0];
  if (!file) return;

  const parent = input.parentElement;
  const currentUploadBtn = parent.querySelector('.uploadPredictBtn') || parent.querySelector('.uploadCsvBtn');
  let originalHtml = '';
  
  const isLlmUpload = input.id === 'aiPredictCsvInput';
  
  if (isLlmUpload) {
    const btn = document.getElementById('aiUploadPredictBtn');
    const status = document.getElementById('aiUploadStatus');
    if (btn) {
      btn.textContent = '...';
      btn.disabled = true;
    }
    if (status) status.textContent = '正在上傳並產生延遲預測...';
    appendAIMessage('user', `上傳待預測資料檔案：${file.name}`);
    appendAIMessage('system', '正在上傳待預測資料並運行 XGBoost 推論...');
  } else {
    const uploadBtns = document.querySelectorAll('.uploadPredictBtn');
    uploadBtns.forEach(btn => btn.disabled = true);
    if (currentUploadBtn) {
      originalHtml = currentUploadBtn.innerHTML;
      currentUploadBtn.innerHTML = '<span class="spinner"></span>上傳中...';
    }
  }

  const formData = new FormData();
  formData.append('file', file);

  try {
    const res = await fetch(`${API_BASE}/api/upload`, {
      method: 'POST',
      body: formData
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || '預測上傳失敗');
    }
    const data = await res.json();
    
    if (isLlmUpload) {
      const status = document.getElementById('aiUploadStatus');
      if (status) status.textContent = `${data.message} 目前介面已顯示上傳檔案的延遲預測。`;
      appendAIMessage('assistant', `✅ ${data.message}\n目前系統已載入此批預測數據，您可以繼續向我詢問該批物流風險分析或調整預算執行最佳化！`);
      const aiResetBtn = document.getElementById('aiResetPredictBtn');
      if (aiResetBtn) aiResetBtn.style.display = 'inline-flex';
    } else {
      showToast(data.message, 'success');
    }
    
    const resetBtns = document.querySelectorAll('.resetCsvBtn');
    resetBtns.forEach(btn => btn.style.display = 'inline-flex');
    
    await refreshDashboard();
  } catch (e) {
    if (isLlmUpload) {
      const status = document.getElementById('aiUploadStatus');
      if (status) status.textContent = '預測上傳失敗：' + e.message;
      appendAIMessage('system', '預測上傳失敗：' + e.message);
    } else {
      alert('預測資料上傳失敗: ' + e.message);
    }
  } finally {
    if (isLlmUpload) {
      const btn = document.getElementById('aiUploadPredictBtn');
      if (btn) {
        btn.textContent = '➕';
        btn.disabled = false;
      }
    } else {
      const uploadBtns = document.querySelectorAll('.uploadPredictBtn');
      uploadBtns.forEach(btn => btn.disabled = false);
      if (currentUploadBtn) {
        currentUploadBtn.innerHTML = originalHtml;
      }
    }
    input.value = '';
  }
}

async function generateAIBrief() {
  const btn = document.getElementById('aiGenerateBriefBtn');
  const mode = document.getElementById('aiLlmMode');
  const questionInput = document.getElementById('aiQuestionInput');
  const question = questionInput.value.trim();
  const originalText = btn.textContent;
  btn.textContent = '...';
  btn.disabled = true;
  appendAIMessage('user', question || '請產生本批物流調度的主管摘要。');
  appendAIMessage('system', '正在整理去識別化預測結果與最佳化摘要...');

  try {
    const res = await fetch(`${API_BASE}/api/llm/manager-brief`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        budget: parseFloat(document.getElementById('budgetInput')?.value) || 5000,
        upgrade_cost: 80,
        delay_penalty: 250,
        risk_threshold: window.edisState.threshold,
        question
      })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail?.message || err.detail || 'AI 摘要產生失敗');
    }
    const data = await res.json();
    if (mode) {
      mode.textContent = data.llm?.used_external_llm
        ? `${data.llm.configured_provider || data.llm.provider}: ${data.llm.model || 'external'}`
        : 'local answer';
    }
    appendAIMessage('assistant', data.brief_text || '沒有產生摘要。');
    questionInput.value = '';
  } catch (e) {
    appendAIMessage('system', 'AI 摘要產生失敗：' + e.message);
  } finally {
    btn.textContent = originalText;
    btn.disabled = false;
  }
}

// Bind to window
window.handleLLMProviderChange = handleLLMProviderChange;
window.updateLLMModelOptions = updateLLMModelOptions;
window.updateLLMCustomModelState = updateLLMCustomModelState;
window.getSelectedLLMModel = getSelectedLLMModel;
window.updateLLMKeyInputState = updateLLMKeyInputState;
window.loadLLMSettings = loadLLMSettings;
window.saveLLMSettings = saveLLMSettings;
window.updateLLMSettingsAccess = updateLLMSettingsAccess;
window.appendAIMessage = appendAIMessage;
window.uploadPredictionCSV = uploadPredictionCSV;
window.generateAIBrief = generateAIBrief;
