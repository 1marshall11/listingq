"""Create the demo job inputs for a fictional brand (Northwind Home).

Run:  python3 scripts/make_demo_inputs.py
Makes jobs/demo-001/input/ with three files, the way a real job arrives:
  supplier_specs.xlsx         messy supplier spreadsheet (abbreviations, mixed units, a missing MRP)
  supplier_catalogue.pdf      supplier PDF catalogue (company details, range claims, product pages)
  marketplace_template.xlsx   Amazon.in-style upload template (simplified) with 6 SKU rows to fill

The data is invented on purpose and includes traps a good intern must catch:
  - NW-BTL-500-PNK: the sheet says 500 ml, the catalogue says 550 ml (conflict)
  - NW-CUT-BMB-01:  MRP is "TBC" (must not be guessed); "eco friendly, antibacterial" has no proof
  - NW-JAR-SET4-GLS: made in China, so importer details become mandatory
"""
from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "jobs" / "demo-001" / "input"

SKUS = ["NW-BTL-750-BLK", "NW-BTL-1000-BLU", "NW-BTL-500-PNK", "NW-LBX-3C-SS", "NW-JAR-SET4-GLS", "NW-CUT-BMB-01"]


def supplier_sheet(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Specs"
    ws["A1"] = "Northwind Home - Spring range - spec sheet from Demo Metalworks (fictional)"
    ws["A1"].font = Font(bold=True)
    header = ["Item Code", "Description", "Brand", "Matl", "Cap", "Dim (cm)", "Wt", "Colour", "Pack",
              "MRP (Rs)", "Origin", "HSN", "Notes"]
    ws.append([])
    ws.append(header)
    for c in ws[3]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
    rows = [
        ["NW-BTL-750-BLK", "Insulated bottle 750ml blk", "Northwind Home", "SS 304", "750 ml", "7.5 x 7.5 x 26.5",
         "340 g", "Blk", "1 N", 899, "Made in India", 7323, "leakproof lid, tested 24h inverted (QC-221)"],
        ["NW-BTL-1000-BLU", "Insulated bottle 1L blue", "Northwind Home", "SS 304", "1 ltr", "8.5 x 8.5 x 29",
         "0.41 kg", "Blu", "1 N", "1,099", "Made in India", 7323, "same lid as 750"],
        ["NW-BTL-500-PNK", "Insulated bottle 500ml pink", "Northwind Home", "SS 304", "500 ml", "7 x 7 x 22.5",
         "260 g", "Pink", "1 N", 749, "Made in India", None, "new colour for spring"],
        ["NW-LBX-3C-SS", "Lunch box 3 compartment steel", "Northwind Home", "SS 304", "1200 ml total",
         "21 x 15 x 7", "520 g", "Silver", "1 N", "1,299", "Made in India", 7323, "BPA free gasket (SD-118)"],
        ["NW-JAR-SET4-GLS", "Glass jar set of 4 bamboo lid", "Northwind Home", "Borosilicate glass",
         "1000 ml each", "10 x 10 x 18 (each jar)", "2.4 kg (set)", "Clear", "4 N", "1,499", "China", 7013,
         "imported"],
        ["NW-CUT-BMB-01", "Bamboo chopping board large", "Northwind Home", "Bamboo", None, "38 x 28 x 1.8",
         "900 g", "Natural", "1 N", "TBC", "Made in India", None, "eco friendly, antibacterial surface"],
    ]
    for r in rows:
        ws.append(r)
    for col, width in zip("ABCDEFGHIJKLM", [18, 30, 16, 18, 14, 22, 14, 10, 8, 10, 14, 8, 42]):
        ws.column_dimensions[col].width = width
    wb.save(path)


def catalogue_pdf(path: Path) -> None:
    styles = getSampleStyleSheet()
    body = styles["BodyText"]
    h1, h2 = styles["Title"], styles["Heading2"]
    doc = SimpleDocTemplate(str(path), pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            title="Northwind Home Spring Range Catalogue (fictional)")
    s = []

    def p(text, style=body):
        s.append(Paragraph(text, style))

    p("Northwind Home Spring Range Product Catalogue", h1)
    p("Prepared by Demo Metalworks Pvt. Ltd. for Northwind Home. Fictional demo data.")
    s.append(Spacer(1, 6))
    p("Company information", h2)
    p("Brand: Northwind Home")
    p("Manufactured by: Demo Metalworks Pvt. Ltd., Plot 12, Example Industrial Estate, Rajkot, Gujarat 360001, India")
    p("Marketed by: Northwind Home Trading LLP, Unit 4, Example Business Park, Ahmedabad, Gujarat 380015, India")
    p("Consumer care: Northwind Home Trading LLP, Unit 4, Example Business Park, Ahmedabad, Gujarat 380015, "
      "care@northwind-home.example, +91 00000 00000")
    p("General: net quantity, weight and MRP for each item are given in the supplier spec sheet.")
    p("Steel range (NW-BTL-*, NW-LBX-*)", h2)
    p("Material: food-grade 18/8 (SS 304) stainless steel, as per supplier material declaration MD-304-2026.")
    p("Bottle range (NW-BTL-*)", h2)
    p("Double-wall vacuum insulation. Lab test LT-2291: keeps drinks cold for up to 24 hours and hot for up to 12 hours.")
    p("Leak-proof screw lid: passed a 24-hour inverted leak test (QC-221).")
    p("Care: hand wash only with warm soapy water. Not dishwasher safe. Do not freeze.")
    s.append(PageBreak())
    p("NW-BTL-750-BLK - Insulated Water Bottle, 750 ml", h2)
    p("Capacity 750 ml. Matte black powder-coated finish. Fits most car cup holders.")
    p("NW-BTL-1000-BLU - Insulated Water Bottle, 1000 ml", h2)
    p("Capacity 1000 ml. Ocean blue powder-coated finish. Carry loop on the lid.")
    p("NW-BTL-500-PNK - Insulated Water Bottle, 550 ml", h2)
    p("Capacity 550 ml. Blush pink powder-coated finish. Slim body for school bags.")
    p("NW-LBX-3C-SS - Three-Compartment Lunch Box", h2)
    p("Three compartments of 400 ml each (1200 ml total). The silicone gasket is BPA-free (supplier declaration SD-118).")
    p("Not suitable for microwave use. The container is dishwasher safe; remove the gasket and wash it by hand.")
    p("NW-JAR-SET4-GLS - Glass Storage Jars, Set of 4", h2)
    p("Four borosilicate glass jars, 1000 ml each, with bamboo lids and a silicone seal for an airtight fit.")
    p("Glass jars are dishwasher safe; wipe the bamboo lids clean with a damp cloth.")
    p("Country of origin: China.")
    p("Imported by: Northwind Home Trading LLP, Unit 4, Example Business Park, Ahmedabad, Gujarat 380015, India")
    p("NW-CUT-BMB-01 - Bamboo Chopping Board, Large", h2)
    p("Made from moso bamboo with a food-safe mineral oil finish. Juice groove on one side.")
    p("Care: hand wash and dry upright. Re-oil once a month. Not dishwasher safe.")
    doc.build(s)


TEMPLATE_COLUMNS = [
    ("item_sku", "Seller SKU"), ("item_name", "Product Name"), ("brand_name", "Brand Name"),
    ("generic_name", "Generic Name"), ("bullet_point1", "Key Product Features 1"),
    ("bullet_point2", "Key Product Features 2"), ("bullet_point3", "Key Product Features 3"),
    ("bullet_point4", "Key Product Features 4"), ("bullet_point5", "Key Product Features 5"),
    ("product_description", "Product Description"), ("generic_keywords", "Search Terms"),
    ("material", "Material"), ("colour", "Colour"), ("capacity_ml", "Capacity (ml)"),
    ("item_dimensions_cm", "Item Dimensions L x W x H (cm)"), ("item_weight_g", "Item Weight (g)"),
    ("net_quantity", "Net Quantity"), ("country_of_origin", "Country of Origin"),
    ("manufacturer_details", "Manufacturer"), ("importer_details", "Importer"),
    ("mrp_inr", "Maximum Retail Price"), ("consumer_care", "Consumer Care"),
    ("care_instructions", "Care Instructions"), ("dishwasher_safe", "Dishwasher Safe"),
    ("hsn_code", "HSN Code"), ("main_image_url", "Main Image URL"),
]
VALID = {
    "material": ["Stainless Steel", "Glass", "Bamboo", "Ceramic", "Plastic", "Silicone"],
    "colour": ["Black", "Blue", "Pink", "Green", "Silver", "White", "Clear", "Natural", "Multicolour"],
    "country_of_origin": ["India", "China", "Vietnam", "Thailand", "Bangladesh", "Indonesia", "Turkey",
                          "Germany", "Italy", "United States"],
    "dishwasher_safe": ["Yes", "No"],
}


def template_xlsx(path: Path) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Template"
    ws.append([label for _, label in TEMPLATE_COLUMNS])
    ws.append([key for key, _ in TEMPLATE_COLUMNS])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="FCE4D6")
    for c in ws[2]:
        c.font = Font(italic=True, color="7F7F7F")
    for sku in SKUS:
        ws.append([sku] + [None] * (len(TEMPLATE_COLUMNS) - 1))
    for i, (key, _) in enumerate(TEMPLATE_COLUMNS, start=1):
        letter = ws.cell(row=1, column=i).column_letter
        ws.column_dimensions[letter].width = 40 if key in ("item_name", "product_description") else 22
    vv = wb.create_sheet("Valid Values")
    for col, (key, values) in enumerate(VALID.items(), start=1):
        vv.cell(row=1, column=col, value=key).font = Font(bold=True)
        for r, v in enumerate(values, start=2):
            vv.cell(row=r, column=col, value=v)
        letter = vv.cell(row=1, column=col).column_letter
        target_col = next(i for i, (k, _) in enumerate(TEMPLATE_COLUMNS, start=1) if k == key)
        target_letter = ws.cell(row=1, column=target_col).column_letter
        dv = DataValidation(type="list", formula1=f"='Valid Values'!${letter}$2:${letter}${len(values) + 1}",
                            allow_blank=True)
        ws.add_data_validation(dv)
        dv.add(f"{target_letter}3:{target_letter}{2 + len(SKUS)}")
    info = wb.create_sheet("Instructions")
    for line in [
        "Simplified Amazon.in-style Home & Kitchen upload template (demo).",
        "Row 1 = column names shown to people. Row 2 = attribute keys used by the upload. Data starts on row 3.",
        "Fill one row per Seller SKU. Use only values from 'Valid Values' where a list exists.",
    ]:
        info.append([line])
    wb.save(path)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    supplier_sheet(OUT / "supplier_specs.xlsx")
    catalogue_pdf(OUT / "supplier_catalogue.pdf")
    template_xlsx(OUT / "marketplace_template.xlsx")
    print(f"Demo inputs written to {OUT}")


if __name__ == "__main__":
    main()
