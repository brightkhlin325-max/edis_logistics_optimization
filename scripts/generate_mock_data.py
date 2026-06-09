import os
import pandas as pd
import numpy as np

def generate_mock_dataset():
    np.random.seed(42)
    num_rows = 500
    
    order_ids = np.arange(10000, 10000 + num_rows)
    shipping_modes = np.random.choice(["Standard Class", "First Class", "Second Class", "Same Day"], size=num_rows, p=[0.6, 0.2, 0.15, 0.05])
    customer_segments = np.random.choice(["Consumer", "Corporate", "Home Office"], size=num_rows)
    order_regions = np.random.choice(["Western Europe", "Central America", "South America", "Northern Europe", "Southern Europe", "Southeast Asia", "Eastern Asia"], size=num_rows)
    
    scheduled_days = np.random.choice([0, 1, 2, 4], size=num_rows)
    product_prices = np.round(np.random.uniform(10.0, 350.0, size=num_rows), 2)
    quantities = np.random.randint(1, 6, size=num_rows)
    
    # Simple logic for late delivery risk to make the model learn something
    # Standard class and higher product price -> higher risk
    p_late = 0.2 + 0.3 * (shipping_modes == "Standard Class") + 0.2 * (scheduled_days <= 1)
    p_late = np.clip(p_late, 0.0, 1.0)
    late_delivery_risk = np.random.binomial(1, p_late)
    
    # Dates
    start_date = pd.to_datetime("2026-01-01")
    date_offsets = np.random.randint(0, 150, size=num_rows)
    order_dates = (start_date + pd.to_timedelta(date_offsets, unit='D') + pd.to_timedelta(np.random.randint(0, 24, size=num_rows), unit='h')).strftime("%m/%d/%Y %H:%M")

    df = pd.DataFrame({
        "Order Id": order_ids,
        "Customer Fname": [f"FirstName_{i}" for i in range(num_rows)],
        "Customer Lname": [f"LastName_{i}" for i in range(num_rows)],
        "Customer Street": [f"Street Address {i}" for i in range(num_rows)],
        "Customer Zipcode": [f"{np.random.randint(10000, 99999)}" for _ in range(num_rows)],
        "Customer Email": [f"user_{i}@example.com" for i in range(num_rows)],
        "Customer Password": ["password_hash_here"] * num_rows,
        "Days for shipment (scheduled)": scheduled_days,
        "Product Price": product_prices,
        "Order Item Quantity": quantities,
        "Shipping Mode": shipping_modes,
        "Customer Segment": customer_segments,
        "Order Region": order_regions,
        "order date (DateOrders)": order_dates,
        "Late_delivery_risk": late_delivery_risk,
        "Delivery Status": ["Shipping on time" if r == 0 else "Late delivery" for r in late_delivery_risk],
        "Days for shipping (real)": scheduled_days + np.random.randint(0, 3, size=num_rows) * late_delivery_risk,
        "Order Status": ["COMPLETE"] * num_rows
    })
    
    os.makedirs("data/raw", exist_ok=True)
    df.to_csv("data/raw/DataCoSupplyChainDataset.csv", index=False)
    print(f"Mock dataset generated successfully with {num_rows} rows.")

if __name__ == "__main__":
    generate_mock_dataset()
