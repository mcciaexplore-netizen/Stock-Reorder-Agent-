"""
setup_sample.py
Creates sample inventory.xlsx with 3 suppliers and 8 items.
Run once before running the agent.

  python setup_sample.py
  python agent.py --file inventory.xlsx
"""

import argparse
from pathlib import Path
import pandas as pd

DATA = {
    "Item Name": [
        "A4 Paper Reams",
        "Printer Cartridge Black",
        "Packaging Box Large",
        "Packaging Tape",
        "Bubble Wrap Roll",
        "Hand Sanitiser",
        "Surgical Gloves Box",
        "Office Chair Cushion",
    ],
    "Item Code": [
        "SKU-ST-001", "SKU-ST-002",
        "SKU-PK-001", "SKU-PK-002", "SKU-PK-003",
        "SKU-SF-001", "SKU-SF-002",
        "SKU-OF-001",
    ],
    "Current Stock": [5,  2,  50, 8,  120, 3,  200, 4],
    "Reorder Level": [20, 5,  100, 15, 50, 10,  50, 2],
    "Reorder Qty":   [50, 10, 200, 30, 0,  20,  0,  5],
    "Unit": [
        "Reams", "Pcs",
        "Pcs",   "Rolls", "Metres",
        "Litres","Pcs",
        "Pcs",
    ],
    "Supplier Name": [
        "Sharma Stationery",   "Sharma Stationery",
        "Rathi Packaging Co",  "Rathi Packaging Co", "Rathi Packaging Co",
        "City Safety Supplies","City Safety Supplies",
        "Sharma Stationery",
    ],
    "Supplier Email": [
        "orders@sharmastationary.com", "orders@sharmastationary.com",
        "purchase@rathipackaging.in",  "purchase@rathipackaging.in",  "purchase@rathipackaging.in",
        "sales@citysafety.co.in",      "sales@citysafety.co.in",
        "orders@sharmastationary.com",
    ],
    "Unit Price": [350, 850, 45, 120, 8, 250, 15, 1200],
    "Category": [
        "Stationery", "Stationery",
        "Packaging",  "Packaging",  "Packaging",
        "Safety",     "Safety",
        "Office",
    ],
}

def main():
    parser = argparse.ArgumentParser(description='Generate the eight-product sample inventory.')
    parser.add_argument('--output', default='inventory.xlsx')
    parser.add_argument('--force', action='store_true', help='Replace an existing output file.')
    args = parser.parse_args()
    out = Path(args.output)
    if out.exists() and not args.force:
        parser.error('The output already exists. Choose --output with a new filename or use --force.')
    pd.DataFrame(DATA).to_excel(out, index=False)
    print(f'Created {out}: 8 products, 3 suppliers, 5 low-stock products, ₹43,600 suggested purchases.')


if __name__ == '__main__':
    main()
