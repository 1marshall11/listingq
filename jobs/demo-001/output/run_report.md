# ListingQ run report - demo-001

Generated 2026-11-23T18:55:07+00:00 | profile `amazon_in_home_kitchen` | check run 2

**4 of 6 products are ready to upload.** 133 of 138 applicable cells (96%) passed every check automatically, and 0 more were approved or edited by a reviewer.

## Products

| SKU | Ready | Auto-approved | Reviewer-approved | Reviewer-rejected | Pending review | Not found | Not applicable | Missing required fields |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| NW-BTL-750-BLK | yes | 23 | 0 | 0 | 0 | 0 | 1 | - |
| NW-BTL-1000-BLU | yes | 23 | 0 | 0 | 0 | 0 | 1 | - |
| NW-BTL-500-PNK | yes | 21 | 0 | 1 | 0 | 1 | 1 | - |
| NW-LBX-3C-SS | yes | 23 | 0 | 0 | 0 | 0 | 1 | - |
| NW-JAR-SET4-GLS | NO | 23 | 0 | 0 | 0 | 1 | 0 | manufacturer_details |
| NW-CUT-BMB-01 | NO | 20 | 0 | 0 | 0 | 2 | 2 | mrp_inr |

## What still needs a person

- **NW-JAR-SET4-GLS / Manufacturer Name and Address** (NOT_FOUND, required): The only 'Manufactured by' line (E073) names an Indian steel maker. These jars are made in China and the foreign manufacturer is not stated. Ask the supplier.; required field has no supported value
- **NW-CUT-BMB-01 / Maximum Retail Price (INR)** (NOT_FOUND, required): the spec sheet says MRP 'TBC' (E067). The MRP must come from the brand.; required field has no supported value
- **NW-BTL-500-PNK / HSN Code** (NOT_FOUND, optional): the spec sheet has no HSN code for this product
- **NW-CUT-BMB-01 / HSN Code** (NOT_FOUND, optional): the spec sheet has no HSN code for this product

## Reviewer decisions

- NW-BTL-500-PNK / capacity_ml: REJECT by Demo reviewer (simulated) (Spec sheet says 500 ml, catalogue says 550 ml. Leave blank and ask the supplier to confirm.)

## Inputs (fingerprints)

| File | Role | SHA-256 (first 16) |
| --- | --- | --- |
| marketplace_template.xlsx | template | `3d17af3134715768` |
| supplier_catalogue.pdf | catalogue | `39df42fb09774939` |
| supplier_specs.xlsx | supplier_sheet | `4c6fde74edaa93eb` |

## Notes

- Upload file: `output/marketplace_template_filled.xlsx`. Shaded cells are blank on purpose; each has a comment with the reason.
- Template columns this profile does not handle (left blank): main_image_url.
- Approved listings added to the knowledge base this run: 0.
- Full trail for every cell: `output/lineage.jsonl`.
