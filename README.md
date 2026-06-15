# EDIS — Enterprise Decision Intelligence System

> DataCo 供應鏈物流延遲預測與最佳化調度系統

![Python](https://img.shields.io/badge/Python-3.14-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-0.136-green)
![XGBoost](https://img.shields.io/badge/XGBoost-ROC--AUC%200.80-orange)
![License](https://img.shields.io/badge/License-Academic-lightgrey)

---

## 專案簡介

EDIS 是一套針對 **DataCo 供應鏈資料集**（180,519 筆訂單）建立的 AI 決策支援系統，整合：

- 🧠 **XGBoost 延遲預測模型**（ROC-AUC 0.80、Precision 0.85）
- ⚙️ **PuLP 整數規劃最佳化引擎**（預算限制下最大化節省金額）
- 🔐 **RBAC 角色權限控制**（Viewer / Logistics_Manager）
- 📊 **互動式 Dashboard**（即時串接 FastAPI）

---

## 五人分工

| 組員 | 負責範圍 |
|---|---|
| Bright | FastAPI 後端、RBAC 權限、API 設計 |
| Lisa | 資料處理、去識別化、特徵工程 |
| Danny | PuLP 最佳化引擎、LIME 解釋模組 |
| 子堯 | XGBoost 模型訓練、模型評估 |
| 紹光 | Dashboard UI/UX、前端串接、簡報 |

---

## 系統架構
---

## 模型效能

| 指標 | 數值 |
|---|---|
| ROC-AUC | 0.80 |
| F1-Score | 0.71 |
| Precision | 0.85 |
| Recall | 0.61 |
| 整體延遲率 | 54.8% |
| 高風險訂單數 | 10,659 筆 |

**Top 特徵重要性：**
1. Shipping Mode_Standard Class — 33.2%
2. Shipping Mode_Same Day — 19.3%
3. Days for shipment (scheduled) — 17.4%
4. Shipping Mode_First Class — 16.7%

---

## API 端點

| 方法 | 路徑 | 權限 | 說明 |
|---|---|---|---|
| GET | `/api/metrics` | 公開 | 模型 KPI 指標 |
| GET | `/api/predict` | Viewer / Manager | 風險預測列表 |
| POST | `/api/optimize` | Manager only | 最佳化調度 |
| POST | `/api/login` | 公開 | 使用者登入驗證 |
| GET | `/api/chart/monthly` | 公開 | 月份延遲趨勢 |
| GET | `/api/geojson/countries` | 公開 | 區域地圖資料 |

---

## 快速開始

### 環境需求
- Python 3.10+
- Anaconda / Miniconda（建議）或 venv

### 1. Clone 專案
```bash
git clone https://github.com/brightkhlin325-max/edis_logistics_optimization.git
cd edis_logistics_optimization
```

### 2. 下載資料集
從 Kaggle 下載 [DataCo Smart Supply Chain Dataset](https://www.kaggle.com/datasets/shashwatwork/dataco-smart-supply-chain-for-big-data-analysis)，將 `DataCoSupplyChainDataset.csv` 放入 `data/raw/`。

### 3. 一鍵啟動（Windows）
```bash
# 雙擊執行
setup_and_run.bat
```

### 4. 手動啟動（venv）
```bash
python -m venv .venv
source .venv/Scripts/activate    # Windows Git Bash
pip install -r requirements.txt
python core/auth.py              # 初始化資料庫
python core/data_pipeline.py    # 資料處理
python core/model_pipeline.py   # 模型訓練
python -m uvicorn app:app --port 8000
```

### 5. 開啟 Dashboard
http://localhost:8000/static/index.html
---

## 登入帳號

| 角色 | 帳號 | 密碼 |
|---|---|---|
| Manager | `admin` | `edis1234` |

> Viewer 模式不需要登入，直接使用即可。

---

## 專案結構
edis_logistics_optimization/

├── app.py                    # FastAPI 後端

├── core/

│   ├── auth.py               # SQLite 登入驗證

│   ├── data_pipeline.py      # 資料處理

│   ├── model_pipeline.py     # XGBoost 訓練

│   ├── optimizer.py          # PuLP 最佳化

│   ├── explainer.py          # LIME 解釋模組

│   └── preprocessor.py       # 預處理工具

├── data/

│   ├── raw/                  # 原始資料集

│   └── processed/            # 處理後資料

├── models/                   # 訓練好的模型

├── static/                   # 前端 Dashboard

├── reports/                  # 分析報告

├── scripts/                  # 工具腳本

└── setup_and_run.bat         # 一鍵啟動
---

## Dashboard 功能

- 📊 **KPI 總覽** — 延遲率、ROC-AUC、高風險訂單數
- 📋 **風險訂單列表** — 分頁、篩選、搜尋
- ⚙️ **最佳化調度** — 預算輸入、一鍵計算最佳升級方案
- 📈 **模型效能** — 混淆矩陣、特徵重要性
- 🗺️ **區域風險地圖** — 互動式世界地圖
- 🔐 **RBAC 權限** — Manager 登入驗證

---

*DataCo EDIS v1.0 · 2026 · 五人組專案*
