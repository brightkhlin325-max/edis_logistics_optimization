# retrainer.py 逐句程式碼說明

> 檔案位置：`core/retrainer.py`
> 用途：EDIS 模型重訓模組，讓 Manager 可以針對 LIME 診斷出的問題特徵，排除後重新訓練 XGBoost，然後決定要不要採用新模型。

---

## 一、整體設計思路

整個重訓流程分成三個動作，彼此獨立：

| 方法 | 做什麼 | 時機 |
|------|--------|------|
| `run(excluded_features)` | 重訓，把新模型存到 temp，回傳新舊指標對比 | 使用者點「開始重訓」 |
| `adopt(session_id)` | 把 temp 新模型複製到正式路徑 | 使用者看完指標確認要採用 |
| `discard(session_id)` | 刪除 temp，現有模型不動 | 使用者看完指標決定不要 |

**重要設計決策**：重訓不會立刻蓋掉現有模型。新模型先放在 `data/processed/retrain_temp/<session_id>/`，等 Manager 確認指標改善了，才呼叫 `adopt()` 正式替換。這樣就算重訓結果更差，也不會影響線上預測。

---

## 二、匯入區（第 16–24 行）

```python
import json
import shutil
import uuid
from pathlib import Path
import pandas as pd
import sys
sys.path.insert(0, str(Path(__file__).parent))
```

- `json`：用來讀寫 `model_metrics.json`、`feature_columns.json`
- `shutil`：用 `shutil.copy2()` 複製模型檔；`shutil.rmtree()` 刪除 temp 目錄
- `uuid`：產生每次重訓的唯一 session ID（12 位 hex 字串）
- `pathlib.Path`：跨平台的路徑操作，不用手動拼 `/` 或 `\`
- `pandas`：type hint 用（`pd.DataFrame`, `pd.Series`）
- `sys.path.insert`：把 `core/` 目錄加入 Python 搜索路徑，這樣 `from data_pipeline import ...` 才找得到

**為什麼 xgboost、data_pipeline、model_pipeline 不在這裡 import？**

因為 xgboost 不一定安裝（`discard`/`adopt` 根本不需要它），如果在模組頂層就 import，一旦 xgboost 沒裝，整個 retrainer 模組就無法載入，連 `discard` 也不能用。所以改成只在 `run()` 裡面才 import，讓 `discard`/`adopt` 可以正常運作。

---

## 三、FEATURE_GROUP_MAP（第 31–60 行）

```python
FEATURE_GROUP_MAP: dict[str, list[str]] = {
    "運送模式": ["Shipping Mode_"],
    "Shipping Mode": ["Shipping Mode_"],
    ...
}
```

這個字典解決「顯示名稱 vs 實際欄位名稱」的落差。

**背景**：LIME 回傳的特徵名稱是像 `Shipping Mode_Standard Class`（one-hot 後的欄位名），但使用者在畫面上看到、勾選的是 `"運送模式"` 或 `"Shipping Mode"` 這種顯示名稱。如果直接用顯示名稱去刪欄位，會找不到任何欄位。

**字典格式**：key = 使用者可能輸入的顯示名稱（中文或英文都有），value = 要刪除的欄位前綴 list。

**例子**：使用者勾選「運送模式」→ 查到前綴 `"Shipping Mode_"` → 找出所有以這個前綴開頭的欄位（`Shipping Mode_Standard Class`, `Shipping Mode_First Class` 等）→ 一起刪掉。

---

## 四、ModelRetrainer 類別初始化（第 74–81 行）

```python
def __init__(self, base_dir: Path):
    self.base_dir     = base_dir
    self.raw_path     = base_dir / "data" / "raw" / "DataCoSupplyChainDataset.csv"
    self.model_path   = base_dir / "models" / "xgboost_model.json"
    self.metrics_path = base_dir / "data" / "processed" / "model_metrics.json"
    self.pred_path    = base_dir / "data" / "processed" / "predictions.csv"
    self.mapping_path = base_dir / "models" / "feature_mapping.json"
    self.temp_dir     = base_dir / "data" / "processed" / "retrain_temp"
```

初始化時只設定所有路徑，不做任何 I/O。

- `raw_path`：93 MB 的原始 DataCo 資料集，每次重訓都要重新讀它（因為 `train_ready.csv`/`test_ready.csv` 不存在）
- `model_path`：目前正在線上使用的 XGBoost 模型
- `metrics_path`：目前模型的評估指標（AUC、F1 等），JSON 格式
- `temp_dir`：所有重訓 session 的暫存根目錄，每個 session 各自一個子目錄

---

## 五、run() 方法（第 85–161 行）

### Step 0：檢查 xgboost 可不可用

```python
try:
    import xgboost as _xgb
except ImportError:
    raise RuntimeError("XGBoost 未安裝，無法重訓。請先執行：conda install -n Fastapp -c conda-forge xgboost")
from data_pipeline import DataPipeline
from model_pipeline import ModelPipeline
```

先確認 xgboost 有裝再繼續，否則丟出清楚的錯誤訊息告訴使用者怎麼安裝。`data_pipeline` 和 `model_pipeline` 也在這裡 lazy import（原因見第二節）。

### Step 1：資料前處理

```python
pipeline = DataPipeline()
splits = pipeline.run(
    filepath=str(self.raw_path),
    output_dir=str(self.base_dir / "data" / "processed"),
)
X_train = splits["X_train"]
X_test  = splits["X_test"]
y_train = splits["y_train"]
y_test  = splits["y_test"]
```

呼叫現有的 `DataPipeline.run()`，從原始 CSV 重新跑一遍特徵工程（去識別化 + 類別編碼 + one-hot），得到訓練/測試分割。這步驟大概要 1-3 分鐘（93 MB 原始檔）。

### Step 2：刪除問題特徵

```python
cols_to_drop = self._resolve_columns(excluded_features, X_train.columns.tolist())
X_train_new = X_train.drop(columns=cols_to_drop, errors="ignore")
X_test_new  = X_test.drop(columns=cols_to_drop,  errors="ignore")
```

把使用者勾選的顯示名稱展開成實際欄位名（透過 `_resolve_columns`），然後從訓練集和測試集都刪掉這些欄位。`errors="ignore"` 是防止欄位名稱打錯時程式崩潰。

### Step 3：訓練新模型

```python
mp = ModelPipeline()
mp.train(X_train_new, y_train, X_test_new, y_test)
```

用刪除特徵後的資料訓練新 XGBoost。`ModelPipeline` 內部使用預設的 `XGBOOST_PARAMS`（max_depth、learning_rate 等超參數，和原始模型相同），保持公平對比。

### Step 4：評估新模型

```python
new_metrics = mp.evaluate(X_test_new, y_test)
new_metrics["feature_count"] = X_train_new.shape[1]
new_metrics["dropped_columns"] = cols_to_drop
```

對測試集算出 ROC-AUC、F1、精準率、召回率。然後在 metrics dict 裡額外記錄「用了幾個特徵」和「刪了哪些欄位」，這樣前端顯示比對結果時可以標注排除了什麼。

### Step 5：讀舊模型指標

```python
old_metrics = self._load_old_metrics()
```

讀取現有模型的 `model_metrics.json`，用來和新模型對比。

### Step 6：存到 temp 目錄

```python
session_id = uuid.uuid4().hex[:12]
session_dir = self.temp_dir / session_id
session_dir.mkdir(parents=True, exist_ok=True)

mp.save(str(session_dir / "xgboost_model.json"))

with open(session_dir / "new_metrics.json", "w", encoding="utf-8") as f:
    json.dump(new_metrics, f, ensure_ascii=False, indent=2)
with open(session_dir / "new_feature_columns.json", "w", encoding="utf-8") as f:
    json.dump({"feature_columns": new_feature_cols}, f, ensure_ascii=False, indent=2)
```

產生 12 位 hex session ID（`uuid4().hex[:12]` 確保不同重訓不衝突），在 temp 目錄下建一個子目錄，存三個檔：
- `xgboost_model.json`：新訓練好的模型（XGBoost JSON 格式）
- `new_metrics.json`：新模型的指標（AUC/F1/精準率/召回率）
- `new_feature_columns.json`：新模型用的特徵清單（比原始少了被排除的欄位）

存好後回傳結果 dict 給前端顯示比對。

---

## 六、adopt() 方法（第 163–195 行）

```python
def adopt(self, session_id: str) -> None:
    session_dir = self.temp_dir / session_id
    if not session_dir.exists():
        raise FileNotFoundError(f"找不到 session：{session_id}")
```

先確認 session 目錄存在，不存在就拋 404 讓 API 回傳給前端。

```python
    shutil.copy2(session_dir / "xgboost_model.json", self.model_path)
```

`shutil.copy2` 把新模型複製到 `models/xgboost_model.json`（原本的位置），**覆蓋**現有模型。`copy2` 比 `copy` 好，因為它會保留 metadata（修改時間等）。

```python
    with open(self.metrics_path, "w", encoding="utf-8") as f:
        json.dump(new_metrics, f, ...)
```

更新 `model_metrics.json`，這樣模型效能頁面下次載入就會顯示新模型的指標。

```python
    if self.mapping_path.exists():
        mapping["feature_columns"] = fc_data["feature_columns"]
        ...
```

更新 `feature_mapping.json` 的 `feature_columns` 欄位清單。這很重要—如果不更新，下次上傳 CSV 預測時，preprocessor 還是會嘗試尋找被排除掉的特徵欄位，導致預測失敗。

```python
    shutil.rmtree(session_dir, ignore_errors=True)
```

採用後清理 temp，節省磁碟空間。

---

## 七、discard() 方法（第 197–200 行）

```python
def discard(self, session_id: str) -> None:
    session_dir = self.temp_dir / session_id
    shutil.rmtree(session_dir, ignore_errors=True)
```

只刪 temp 目錄，現有模型完全不動。`ignore_errors=True` 讓這個方法即使目錄不存在也不會噴錯（冪等操作，前端可以重複呼叫）。

---

## 八、_resolve_columns() 方法（第 204–231 行）

```python
to_drop = set()
for name in excluded:
    resolved = False
    for key, prefixes in FEATURE_GROUP_MAP.items():
        if key.lower() in name.lower() or name.lower() in key.lower():
            for prefix in prefixes:
                for col in all_cols:
                    if col.startswith(prefix) or col == prefix.rstrip():
                        to_drop.add(col)
            resolved = True
    if not resolved:
        for col in all_cols:
            if col == name or col.startswith(name):
                to_drop.add(col)
```

**雙重查找邏輯**：

1. **FEATURE_GROUP_MAP 查找**：用「部分字串包含」判斷是否匹配（`key.lower() in name.lower()`），這樣使用者輸入 `"Shipping Mode_Standard Class"`（LIME 回傳的完整欄位名）也能匹配到 key `"Shipping Mode"`，然後展開成前綴。

2. **直接比對**：如果 FEATURE_GROUP_MAP 找不到，就直接用 `col.startswith(name)` 找精確/前綴比對。這是保底邏輯，應付 FEATURE_GROUP_MAP 沒有收錄的特徵名稱。

用 `set` 避免重複欄位，最後 `sorted()` 讓輸出順序固定（方便測試與除錯）。

---

## 九、_load_old_metrics() 方法（第 233–238 行）

```python
if self.metrics_path.exists():
    with open(self.metrics_path, "r", encoding="utf-8") as f:
        return json.load(f)
return {}
```

如果 `model_metrics.json` 存在就讀取，不存在就回傳空字典。前端比對面板收到空字典時，不會顯示舊模型的數字，但新模型的指標還是會正常顯示。

---

## 十、重點注意事項

| 項目 | 說明 |
|------|------|
| 重訓速度 | 每次重訓都要重跑 DataPipeline 處理 93 MB 原始 CSV，大概 1-3 分鐘 |
| XGBoost 必要條件 | `run()` 需要 xgboost；`adopt()`/`discard()` 不需要 |
| Session 唯一性 | uuid4 hex 12 位，衝突機率可忽略（2^48 種組合） |
| 採用後的影響 | 覆蓋模型 + 更新 metrics + 更新 feature_mapping，三個檔案都會變 |
| 捨棄的安全性 | `discard` 只刪 temp，不動任何生產用檔案 |
