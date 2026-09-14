"""Build Expenses.xlsx and Consolidated Expenses.pdf from a claim JSON.

Usage:
    python build_claim.py <claim.json> <input_dir> <output_dir>

The JSON is produced by the model after reading the receipts. This script is
deterministic: it sorts the lines, assigns line numbers and PDF page numbers,
then writes both output files. No amounts are computed or converted here.

Claim JSON shape:
{
  "lines": [
    {
      "date": "2026-07-24",
      "time": "13:00",                 # optional, omit if the receipt has none
      "merchant": "Example Bistro",
      "description": "Dinner",
      "receipt_amount": 51.61,         # null when there is no receipt
      "receipt_ccy": "GBP",            # null when there is no receipt
      "card_gbp": null,                # amount read off the card screen, else null
      "card_ccy": "GBP",               # optional, currency of card_gbp; defaults to GBP
      "evidence": [
        {"file": "Scan ....pdf", "page": 1, "type": "RECEIPT", "amount": 51.61, "ccy": "GBP"}
      ]
    }
  ]
}

evidence[].type is one of RECEIPT, CARD SLIP, AMEX, STATEMENT.
evidence[].page is the 1-based page number inside a source PDF; omit for images.
"""

import json
import os
import sys

import pymupdf
from PIL import Image
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.comments import Comment
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.utils import get_column_letter

# ---------------------------------------------------------------- constants

NAVY_HEX = "1F3864"
NAVY_RGB = (0.12, 0.22, 0.39)

BAND_H = 17.0
BASELINE = 12.93
PAD_L = 4.0
GAP = 5.0
PAD_R = 4.0
NUM_FONT, NUM_SIZE = "Helvetica-Bold", 11.0
LBL_FONT, LBL_SIZE = "Helvetica", 8.0

MAX_PX_H = 2000          # cap on embedded image height
PLACE_DPI = 150.0        # images are placed at 150 dpi

COLUMNS = [
    ("No.", 5), ("Date", 12), ("Merchant", 28), ("Description", 22),
    ("Receipt Amount", 14), ("Receipt Ccy", 10), ("Card Charged", 16),
    ("Claim Amount", 12), ("Claim Ccy", 10), ("PDF Page(s)", 12),
    ("Expense Type", 30), ("Attendees", 40),
]
MONEY_COLS = (5, 7, 8)

# The two columns the user fills in by hand between stage 1 and stage 2.
TYPE_COL, ATTENDEE_COL = 11, 12
USER_FILL = "FFF2CC"

# Shown as a tooltip when the cell is selected, and as a note on the header.
# The attendee example is guidance for whoever fills the sheet, not a format a
# parser depends on: the cell is free text and gets read with judgement.
TYPE_HINT = "\n".join([
    "Pick from the dropdown.",
    "",
    "Food and drink is prefilled as Subsistence. Change it to Client",
    "Entertaining or Staff Entertaining where that is what it was.",
])
ATTENDEE_HINT = "\n".join([
    "Who was there, besides you. You are added automatically.",
    "",
    "Example: John Doe (Hillwood)",
    "Several people: John Doe (Hillwood); Jane Roe (Panattoni)",
    "",
    "Required on every Client or Staff Entertaining line.",
])

# Dropdown values, "CODE - Label". The code is typed verbatim into
# EXPENSE_TYPE$N in PeopleSoft, so the string has to round-trip exactly.
EXPENSE_TYPES = [
    "SUBSIST - Subsistence",
    "CLENT - Client Entertaining",
    "STFENT - Staff Entertaining",
    "WRKLNCH - Working Lunches",
    "PUBTRN - Public Transportation",
    "TAXI - Taxi",
    "PARKING - Parking",
    "TOLLCNG - Tolls/Congestion Charge",
    "RENTCAR - Car Rental",
    "CARFUEL - Car Rental Fuel",
    "HOTEL - Hotel",
    "AIRFARE - Airfare",
    "AIRFDOM - Airfare Domestic",
    "PHONECM - Phone/Comms",
    "POSTAGE - Courier/Postage",
    "CONFSEM - Conferences/Seminars",
    "MBRSHIP - Membership/Subscriptions",
    "ITEQUIP - IT Equipment",
    "LEGALPR - Legal & Professional Fees",
    "OTHER - Other",
]
CCY_ORDER = ("GBP", "EUR")   # these lead the totals block when present


# ---------------------------------------------------------------- helpers

def sort_key(line):
    """Date ascending only.

    Python's sort is stable, so lines keep the order they were written in
    claim.json within a date. Intra-day order is a reading decision, not a
    rule: an untimed daily travel charge belongs where it happened, and only
    whoever read the receipts knows that.
    """
    return line["date"]


def claim_of(line):
    """Card charge wins when it exists, otherwise the receipt stands as-is."""
    if line.get("card_gbp") is not None:
        return line["card_gbp"], line.get("card_ccy") or "GBP"
    return line.get("receipt_amount"), line.get("receipt_ccy")


def total_ccys(lines):
    """Currencies actually claimed, GBP then EUR first, then the rest sorted.

    Hardcoding the list silently drops a currency's total from the sheet the
    moment a batch is not the one the list was written for.
    """
    present = {claim_of(line)[1] for line in lines}
    present.discard(None)
    lead = [c for c in CCY_ORDER if c in present]
    return lead + sorted(present - set(lead))


def page_span(pages):
    if not pages:
        return ""
    if len(pages) == 1:
        return str(pages[0])
    return "%d-%d" % (pages[0], pages[-1])


def stamp(page, number, label):
    """Draw the navy identity band top-left, sized to its own text."""
    num = str(number)
    label_x = PAD_L + pymupdf.get_text_length(num, NUM_FONT, NUM_SIZE) + GAP
    label_w = pymupdf.get_text_length(label, LBL_FONT, LBL_SIZE)
    band = pymupdf.Rect(0, 0, label_x + label_w + PAD_R, BAND_H)

    page.draw_rect(band, color=NAVY_RGB, fill=NAVY_RGB)
    page.insert_text((PAD_L, BASELINE), num,
                     fontname=NUM_FONT, fontsize=NUM_SIZE, color=(1, 1, 1))
    page.insert_text((label_x, BASELINE), label,
                     fontname=LBL_FONT, fontsize=LBL_SIZE, color=(1, 1, 1))


def add_pdf_page(out, src_path, page_no, cache):
    """Copy a source PDF page verbatim so its geometry is preserved."""
    if src_path not in cache:
        cache[src_path] = pymupdf.open(src_path)
    src = cache[src_path]
    out.insert_pdf(src, from_page=page_no - 1, to_page=page_no - 1)
    return out[-1]


def add_image_page(out, src_path, tmp_dir, index):
    """Downsample to the height cap, then place at 150 dpi on its own page."""
    img = Image.open(src_path)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    if img.height > MAX_PX_H:
        scale = MAX_PX_H / img.height
        img = img.resize((round(img.width * scale), MAX_PX_H), Image.LANCZOS)

    tmp = os.path.join(tmp_dir, "_page%03d.jpg" % index)
    img.save(tmp, "JPEG", quality=85)

    w = img.width / PLACE_DPI * 72.0
    h = img.height / PLACE_DPI * 72.0
    page = out.new_page(width=w, height=h)
    page.insert_image(pymupdf.Rect(0, 0, w, h), filename=tmp)
    os.remove(tmp)
    return page


# ---------------------------------------------------------------- outputs

def build_pdf(lines, input_dir, out_path, tmp_dir):
    out = pymupdf.open()
    cache = {}
    page_no = 0

    for line in lines:
        line["pdf_pages"] = []
        for ev in line["evidence"]:
            src = os.path.join(input_dir, ev["file"])
            if not os.path.exists(src):
                raise FileNotFoundError(src)

            page_no += 1
            if src.lower().endswith(".pdf"):
                page = add_pdf_page(out, src, ev.get("page", 1), cache)
            else:
                page = add_image_page(out, src, tmp_dir, page_no)

            label = "%s - %s (%s %.2f)" % (
                ev["type"], line["merchant"], ev["ccy"], ev["amount"])
            stamp(page, line["no"], label)
            line["pdf_pages"].append(page_no)

    out.save(out_path, deflate=True, garbage=3)
    out.close()
    for doc in cache.values():
        doc.close()
    return page_no


def build_xlsx(lines, out_path):
    import datetime as dt

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Expenses"

    head_fill = PatternFill("solid", fgColor=NAVY_HEX)
    head_font = Font(bold=True, color="FFFFFF")
    user_fill = PatternFill("solid", fgColor=USER_FILL)
    for i, (name, width) in enumerate(COLUMNS, start=1):
        cell = ws.cell(1, i, name)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = width
    ws.freeze_panes = "A2"

    row = 2
    for line in lines:
        amount, ccy = claim_of(line)
        ws.cell(row, 1, line["no"])
        d = ws.cell(row, 2, dt.datetime.strptime(line["date"], "%Y-%m-%d").date())
        d.number_format = "DD/MM/YYYY"
        ws.cell(row, 3, line["merchant"])
        ws.cell(row, 4, line["description"])
        ws.cell(row, 5, line.get("receipt_amount"))
        ws.cell(row, 6, line.get("receipt_ccy"))
        ws.cell(row, 7, line.get("card_gbp"))
        ws.cell(row, 8, amount)
        ws.cell(row, 9, ccy)
        ws.cell(row, 10, page_span(line["pdf_pages"]))
        ws.cell(row, TYPE_COL, line.get("expense_type") or "").fill = user_fill
        a = ws.cell(row, ATTENDEE_COL, line.get("attendees") or "")
        a.fill = user_fill
        a.alignment = Alignment(wrap_text=True, vertical="top")
        for col in MONEY_COLS:
            c = ws.cell(row, col)
            c.number_format = "#,##0.00"
            c.alignment = Alignment(horizontal="right")
        row += 1

    last = row - 1
    row += 1
    for ccy in total_ccys(lines):
        ws.cell(row, 7, "Total %s" % ccy).font = Font(bold=True)
        t = ws.cell(row, 8, '=SUMIF(I2:I%d,"%s",H2:H%d)' % (last, ccy, last))
        t.number_format = "#,##0.00"
        t.font = Font(bold=True)
        t.alignment = Alignment(horizontal="right")
        ws.cell(row, 9, ccy)
        row += 1

    # Expense Type is a dropdown off a hidden lookup sheet: a literal DV list
    # of 20 codes blows Excel's 255-character limit.
    lut = wb.create_sheet("Types")
    for i, t in enumerate(EXPENSE_TYPES, start=1):
        lut.cell(i, 1, t)
    lut.sheet_state = "hidden"

    dv = DataValidation(
        type="list",
        formula1="=Types!$A$1:$A$%d" % len(EXPENSE_TYPES),
        allow_blank=True,
        showDropDown=False,      # openpyxl inverts this: False shows the arrow
    )
    dv.errorTitle = "Not an expense type"
    dv.error = "Pick a value from the list."
    dv.promptTitle = "Expense Type"
    dv.prompt = TYPE_HINT
    dv.showInputMessage = True
    ws.add_data_validation(dv)
    tcol = get_column_letter(TYPE_COL)
    dv.add("%s2:%s%d" % (tcol, tcol, last))

    # Attendees takes free text, so this validation exists only to carry the
    # tooltip: "custom" with a formula that is always true never blocks a value.
    adv = DataValidation(type="custom", formula1="TRUE", allow_blank=True)
    adv.promptTitle = "Attendees"
    adv.prompt = ATTENDEE_HINT
    adv.showInputMessage = True
    ws.add_data_validation(adv)
    acol = get_column_letter(ATTENDEE_COL)
    adv.add("%s2:%s%d" % (acol, acol, last))

    # A note on each header, so the guidance is visible without clicking a cell.
    for col, title, body in ((TYPE_COL, "Expense Type", TYPE_HINT),
                             (ATTENDEE_COL, "Attendees", ATTENDEE_HINT)):
        c = ws.cell(1, col)
        c.comment = Comment(title + "\n\n" + body, "cbre-expense-claim")
        c.comment.width = 320
        c.comment.height = 170

    wb.save(out_path)


# ---------------------------------------------------------------- entry

def main():
    if len(sys.argv) != 4:
        print(__doc__)
        return 1

    claim_path, input_dir, output_dir = sys.argv[1:4]
    with open(claim_path, encoding="utf-8") as fh:
        claim = json.load(fh)

    lines = sorted(claim["lines"], key=sort_key)
    for i, line in enumerate(lines, start=1):
        line["no"] = i

    os.makedirs(output_dir, exist_ok=True)
    pdf_path = os.path.join(output_dir, "Consolidated Expenses.pdf")
    xlsx_path = os.path.join(output_dir, "Expenses.xlsx")

    pages = build_pdf(lines, input_dir, pdf_path, output_dir)
    build_xlsx(lines, xlsx_path)

    totals = {}
    for line in lines:
        amount, ccy = claim_of(line)
        totals[ccy] = round(totals.get(ccy, 0) + (amount or 0), 2)

    print("%d lines, %d PDF pages" % (len(lines), pages))
    for ccy in total_ccys(lines):
        print("  Total %s %.2f" % (ccy, totals.get(ccy, 0)))
    print(pdf_path)
    print(xlsx_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
