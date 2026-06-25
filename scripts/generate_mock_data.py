#!/usr/bin/env python
"""
generate_mock_data.py
產生預估訂單與上一季實績 CSV 以進行功能驗證
"""
import csv
import random
import argparse
from datetime import datetime, timedelta

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--rows', type=int, default=100)
    parser.add_argument('--output-predict', type=str, default='static/mock/predict_orders.csv')
    parser.add_argument('--output-perf', type=str, default='static/mock/historical_perf.csv')
    args = parser.parse_args()

    shipping_modes = ['Standard Class', 'Second Class', 'First Class', 'Same Day']
    regions = ['Western Europe', 'Central America', 'East of USA', 'South America', 'East Asia']
    categories = ['Cardo', 'Water Sports', 'Apparel', 'Cleats']
    segments = ['Consumer', 'Corporate', 'Home Office']
    types = ['DEBIT', 'PAYMENT', 'TRANSFER', 'CASH']
    markets = ['EU', 'LATAM', 'USCA', 'Pacific Asia', 'Africa']

    headers = [
        "Order Id", "order date (DateOrders)", "Shipping Mode", "Order Region",
        "Days for shipment (scheduled)", "Product Price", "Order Item Quantity",
        "Order Item Discount Rate", "Order Item Profit Ratio", "Order Profit Per Order",
        "Category Name", "Order Country", "Customer Segment", "Type",
        "Department Name", "Market", "Late_delivery_risk"
    ]

    base_id = 190000
    start_date = datetime(2026, 6, 10, 12, 0)

    # 產出 predict
    with open(args.output_predict, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for i in range(args.rows):
            order_id = base_id + i
            dt = start_date + timedelta(minutes=15 * i)
            shipping = random.choice(shipping_modes)
            region = random.choice(regions)
            sched = random.choice([1, 2, 4])
            price = round(random.uniform(20.0, 300.0), 2)
            qty = random.randint(1, 5)
            discount = random.choice([0.0, 0.05, 0.1, 0.2, 0.25])
            profit_ratio = round(random.uniform(0.05, 0.40), 2)
            profit = round(price * qty * profit_ratio, 2)
            cat = random.choice(categories)
            country = "United States" if "USA" in region else "GlobalRegion"
            segment = random.choice(segments)
            t = random.choice(types)
            dept = "Apparel" if cat == "Apparel" else "Fan Shop"
            market = random.choice(markets)
            late = random.choice([0, 1])

            writer.writerow([
                order_id, dt.strftime("%m/%d/%Y %H:%M"), shipping, region,
                sched, price, qty, discount, profit_ratio, profit,
                cat, country, segment, t, dept, market, late
            ])

    # 產出 historical
    with open(args.output_perf, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        for i in range(args.rows):
            order_id = base_id + 10000 + i
            dt = start_date - timedelta(days=90) + timedelta(minutes=15 * i)
            shipping = random.choice(shipping_modes)
            region = random.choice(regions)
            sched = random.choice([1, 2, 4])
            price = round(random.uniform(20.0, 300.0), 2)
            qty = random.randint(1, 5)
            discount = random.choice([0.0, 0.05, 0.1, 0.2, 0.25])
            profit_ratio = round(random.uniform(0.05, 0.40), 2)
            profit = round(price * qty * profit_ratio, 2)
            cat = random.choice(categories)
            country = "United States" if "USA" in region else "GlobalRegion"
            segment = random.choice(segments)
            t = random.choice(types)
            dept = "Apparel" if cat == "Apparel" else "Fan Shop"
            market = random.choice(markets)
            late = random.choice([0, 1])

            writer.writerow([
                order_id, dt.strftime("%m/%d/%Y %H:%M"), shipping, region,
                sched, price, qty, discount, profit_ratio, profit,
                cat, country, segment, t, dept, market, late
            ])

    print(f"Successfully generated mock datasets!")

if __name__ == '__main__':
    main()
