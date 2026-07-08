"""
setup_sample.py
Creates sample inventory.xlsx with 3 suppliers and 8 items.
Run once before running the agent.

  python setup_sample.py
  python agent.py
"""

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

out = Path("inventory.xlsx")
pd.DataFrame(DATA).to_excel(out, index=False)
print(f"Created {out} — {len(DATA['Item Name'])} items across 3 suppliers.\n")

print("Expected behaviour when agent runs:")
print("─" * 60)
print("Items BELOW reorder level (will trigger POs):")
print("  SKU-ST-001  A4 Paper          5  < 20  → order 50 Reams  @ ₹350  = ₹17,500")
print("  SKU-ST-002  Printer Cartridge  2  <  5  → order 10 Pcs   @ ₹850  = ₹8,500")
print("  SKU-PK-001  Packaging Box     50 < 100 → order 200 Pcs  @ ₹45   = ₹9,000")
print("  SKU-PK-002  Packaging Tape     8  < 15  → order 30 Rolls @ ₹120  = ₹3,600")
print("  SKU-SF-001  Hand Sanitiser     3  < 10  → order 20 Ltrs  @ ₹250  = ₹5,000")
print("  SKU-OF-001  Chair Cushion      4  >  2  → OK, no order")
print()
print("POs that will be drafted:")
print("  PO-XXXXXX-001 → Sharma Stationery      ₹26,000  (2 items + chair cushion OK)")
print("  PO-XXXXXX-002 → Rathi Packaging Co     ₹12,600  (2 items)")
print("  PO-XXXXXX-003 → City Safety Supplies   ₹5,000   (1 item)")
print()
print("Items ABOVE reorder level (no PO needed):")
print("  SKU-PK-003  Bubble Wrap       120 >= 50  → OK")
print("  SKU-SF-002  Surgical Gloves   200 >= 50  → OK")
print("  SKU-OF-001  Chair Cushion       4 >=  2  → OK")
