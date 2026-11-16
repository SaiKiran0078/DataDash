"""Reusable sample datasets for tests."""
import io
import random

import openpyxl

REGIONS = ["North", "South", "East", "West"]
PRODUCTS = ["Laptop", "Phone", "Tablet"]


def sales_csv(rows: int = 120, seed: int = 7, outlier: bool = True) -> bytes:
    """Messy-but-realistic sales export: currency symbols, mixed missing tokens, a Yes/No column."""
    rng = random.Random(seed)
    lines = ["order_id,order_date,region,product,units,revenue,returned,customer_note"]
    for i in range(1, rows + 1):
        month = (i - 1) % 12 + 1
        day = (i - 1) % 27 + 1
        units = rng.randint(1, 9)
        revenue = units * rng.choice([800, 900, 1000]) + rng.randint(0, 50)
        if outlier and i == 5:
            revenue = 900000
        rev_txt = f"₹{revenue:,}" if i % 2 else str(revenue)
        region = REGIONS[i % 4] if i != 9 else "N/A"
        returned = "Yes" if i % 10 == 0 else "No"
        note = f"Customer remark number {i} about delivery"
        lines.append(f'{i},2025-{month:02d}-{day:02d},{region},{PRODUCTS[i % 3]},{units},"{rev_txt}",{returned},{note}')
    return ("\n".join(lines) + "\n").encode("utf-8")


def xlsx_bytes() -> bytes:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Name", "Score", "Joined"])
    from datetime import datetime
    for i in range(12):
        ws.append([f"Person {i}", 50 + i * 3, datetime(2024, 1 + i % 12, 5)])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def multi_sheet_xlsx_bytes() -> bytes:
    """Workbook with separate fact/dimension sheets for worksheet-import tests."""
    wb = openpyxl.Workbook()
    sales = wb.active
    sales.title = "Sales"
    sales.append(["Order", "Revenue"])
    sales.append(["A-1", 125.5])
    sales.append(["A-2", 240.0])
    customers = wb.create_sheet("Customers")
    customers.append(["Customer", "Region"])
    customers.append(["Asha", "North"])
    customers.append(["Ravi", "South"])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
