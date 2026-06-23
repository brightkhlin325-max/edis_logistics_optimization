# 收益預測 Ready CSV 交付規格

本文給資料前處理負責人使用。請依照此規格產出收益預測模型可直接使用的 ready CSV，模型端會讀取這些檔案後直接訓練，不再做清理、編碼或特徵工程。

## 1. 檔案位置與名稱

請產出以下三個檔案：

```text
data/processed/profit_train_ready.csv
data/processed/profit_val_ready.csv
data/processed/profit_test_ready.csv
```

模型預設會用這三個檔名。若檔名不同，訓練時要額外指定參數，會增加整合成本。

## 2. 目標欄位

三個 CSV 都必須包含目標欄位：

```text
Order Profit Per Order
```

這是每筆訂單的實際利潤金額，也是收益預測模型要學習的 y。

## 3. 特徵欄位規則

除了 `Order Profit Per Order` 以外，其餘欄位都會被模型視為 X 特徵。

請確保所有特徵欄位都已經前處理完成：

- 欄位型態必須是數值或布林值
- 不可有原始字串類別欄位
- 不可有日期字串欄位
- 不可有缺值 `NaN`
- train、val、test 三個檔案的特徵欄位必須完全一致
- 欄位順序建議完全一致，避免人工檢查混淆

可接受範例：

```csv
Product Price,Order Item Quantity,Order Item Discount Rate,Days for shipment (scheduled),Shipping Mode_Standard Class,Shipping Mode_First Class,Market_Europe,Market_USCA,order_month,order_dayofweek,Order Profit Per Order
59.99,2,0.10,4,1,0,1,0,6,2,18.45
120.00,1,0.00,2,0,1,0,1,6,3,31.20
```

不可接受範例：

```csv
Product Price,Shipping Mode,order date (DateOrders),Order Item Profit Ratio,Order Profit Per Order
59.99,Standard Class,2017-06-12 14:30:00,0.31,18.45
```

原因：
- `Shipping Mode` 尚未編碼
- `order date (DateOrders)` 尚未轉成數值特徵
- `Order Item Profit Ratio` 是利潤洩漏欄位

## 4. 必須移除的洩漏欄位

以下欄位不可出現在 ready CSV：

```text
Benefit per order
Order Item Profit Ratio
```

原因是這些欄位會直接或間接透露 `Order Profit Per Order`，模型會變成抄答案，評估分數會虛高。

模型端預設會檢查這些欄位；若出現，訓練會直接失敗。

## 5. 必須移除的個資、識別碼、非模型欄位

以下欄位不可出現在 ready CSV：

```text
Customer Email
Customer Password
Customer Fname
Customer Lname
Customer Street
Customer Zipcode
Customer Id
Order Id
Order Item Id
Order Customer Id
Category Id
Department Id
Product Card Id
Product Category Id
Order Item Cardprod Id
Product Image
Product Description
Order Zipcode
```

原因：
- 個資不可進模型
- ID 類欄位容易造成記憶化，泛化能力差
- 圖片、描述、zipcode 等原始欄位未處理前不適合直接給目前模型

若需要保留 `Order Id` 供結果對照，請另外產出 metadata 檔，不要放進 ready CSV。

建議 metadata 檔名：

```text
data/processed/profit_test_metadata.csv
```

## 6. 建議特徵

以下是建議保留或轉換後保留的特徵方向，實際欄位可依前處理策略調整。

數值特徵：

```text
Sales
Sales per customer
Order Item Total
Order Item Discount
Order Item Discount Rate
Order Item Product Price
Product Price
Order Item Quantity
Days for shipping (real)
Days for shipment (scheduled)
Late_delivery_risk
Latitude
Longitude
```

類別特徵需先編碼成數值：

```text
Type
Customer Segment
Shipping Mode
Delivery Status
Market
Order Status
Category Name
Department Name
Order Region
Customer City
Order City
Order Country
Customer State
Order State
```

日期特徵需由 `order date (DateOrders)` 轉換成數值欄位，例如：

```text
order_year
order_month
order_day
order_dayofweek
order_hour
order_is_weekend
```

## 7. 切分方式

建議使用 time-based split：

- 依 `order date (DateOrders)` 由舊到新排序
- 前 70% 作為 train
- 中間 15% 作為 validation
- 最後 15% 作為 test

若團隊已決定使用 80/20，也可以：

- 前 80% 作為 train
- 後 20% 作為 test
- 從 train 的最後一段切出 validation，或另外產出 `profit_val_ready.csv`

重點是 test 必須代表未來資料，不建議 random split 當主評估。

## 8. 缺值處理

ready CSV 不應包含缺值。

建議：

- 數值欄位用 train set median 補值
- 類別欄位先補 `"Unknown"` 再編碼
- validation/test 必須使用 train set 學到的補值與編碼規則
- 不可用 validation/test 的統計值回填 train，避免資料洩漏

## 9. 類別編碼要求

可使用 One-Hot Encoding、Target Encoding、Label Encoding，或其他已約定方式。

但請確保：

- train、val、test 欄位集合完全一致
- test 出現未知類別時要有固定 fallback
- 若使用 Target Encoding，encoding map 必須只從 train set 學習
- 不可用完整資料集先算 target encoding，再切 train/test

## 10. 模型端執行方式

前處理檔案完成後，模型端會用以下指令訓練：

```powershell
D:\anaconda_envs\AI\python.exe core\profit_model_pipeline.py `
  --train data\processed\profit_train_ready.csv `
  --val data\processed\profit_val_ready.csv `
  --test data\processed\profit_test_ready.csv `
  --output data\processed `
  --model-dir models
```

成功後會輸出：

```text
models/profit_lightgbm_model.txt
models/profit_feature_manifest.json
data/processed/profit_model_metrics.json
data/processed/profit_predictions.csv
```

## 11. 交付前驗收清單

交付前請確認：

- 三個檔案都存在於 `data/processed/`
- 三個檔案都包含 `Order Profit Per Order`
- 除 target 外，所有欄位都是數值或布林值
- 沒有缺值
- train、val、test 的特徵欄位完全一致
- 沒有 `Benefit per order`
- 沒有 `Order Item Profit Ratio`
- 沒有個資、ID、圖片、描述等非模型欄位
- 類別欄位已編碼
- 日期欄位已轉成數值特徵
- validation/test 的補值與編碼規則只來自 train

## 12. 最小檢查程式

可用以下 Python 片段先自檢：

```python
import pandas as pd

paths = [
    "data/processed/profit_train_ready.csv",
    "data/processed/profit_val_ready.csv",
    "data/processed/profit_test_ready.csv",
]

target = "Order Profit Per Order"
forbidden = {
    "Benefit per order",
    "Order Item Profit Ratio",
    "Customer Email",
    "Customer Password",
    "Customer Fname",
    "Customer Lname",
    "Customer Street",
    "Customer Zipcode",
    "Customer Id",
    "Order Id",
    "Order Item Id",
    "Order Customer Id",
    "Category Id",
    "Department Id",
    "Product Card Id",
    "Product Category Id",
    "Order Item Cardprod Id",
    "Product Image",
    "Product Description",
    "Order Zipcode",
}

frames = [pd.read_csv(path) for path in paths]
feature_columns = None

for path, df in zip(paths, frames):
    assert target in df.columns, f"{path} missing target"
    bad = forbidden.intersection(df.columns)
    assert not bad, f"{path} contains forbidden columns: {bad}"
    assert not df.isna().any().any(), f"{path} contains NaN"

    X = df.drop(columns=[target])
    non_numeric = X.select_dtypes(exclude=["number", "bool"]).columns.tolist()
    assert not non_numeric, f"{path} has non-numeric columns: {non_numeric}"

    if feature_columns is None:
        feature_columns = X.columns.tolist()
    else:
        assert X.columns.tolist() == feature_columns, f"{path} feature columns mismatch"

print("profit ready CSV check passed")
```
