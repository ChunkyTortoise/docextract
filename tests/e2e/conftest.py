"""E2E test fixtures: API key guard and synthetic PDF generators."""
from __future__ import annotations

import os

import pytest
from fpdf import FPDF
from fpdf.enums import XPos, YPos


@pytest.fixture
def skip_without_api_key():
    """Skip the test if ANTHROPIC_API_KEY is not set in the environment."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("e2e: ANTHROPIC_API_KEY not set")


def _nl(pdf: FPDF, h: float, text: str, **kwargs) -> None:
    """Shorthand: cell that moves to the next line."""
    pdf.cell(0, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, **kwargs)


def _nl_w(pdf: FPDF, w: float, h: float, text: str, **kwargs) -> None:
    """Shorthand: fixed-width cell that moves to the next line."""
    pdf.cell(w, h, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT, **kwargs)


@pytest.fixture
def synthetic_invoice_pdf() -> bytes:
    """Generate a minimal but realistic 2-page invoice PDF using fpdf2."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- Page 1: invoice header + line items ---
    pdf.add_page()
    pdf.set_font("Helvetica", "B", size=20)
    _nl(pdf, 12, "INVOICE", align="C")
    pdf.ln(4)

    pdf.set_font("Helvetica", size=11)
    _nl(pdf, 8, "Vendor: Acme Supplies Inc.")
    _nl(pdf, 8, "123 Commerce Street, San Francisco, CA 94105")
    _nl(pdf, 8, "Phone: (415) 555-0100  |  Email: billing@acme-supplies.example.com")
    pdf.ln(4)

    _nl(pdf, 8, "Invoice Number: INV-2024-00842")
    _nl(pdf, 8, "Invoice Date: 2024-03-15")
    _nl(pdf, 8, "Due Date: 2024-04-14")
    pdf.ln(4)

    _nl(pdf, 8, "Bill To:")
    _nl(pdf, 8, "  GlobalTech Solutions LLC")
    _nl(pdf, 8, "  456 Enterprise Blvd, Austin, TX 78701")
    pdf.ln(6)

    # Line items header
    pdf.set_font("Helvetica", "B", size=11)
    pdf.cell(90, 8, "Description", border=1)
    pdf.cell(25, 8, "Qty", border=1, align="C")
    pdf.cell(35, 8, "Unit Price", border=1, align="R")
    pdf.cell(40, 8, "Amount", border=1, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # Line items
    line_items = [
        ("Widget Model A - Standard", 10, 49.99),
        ("Widget Model B - Premium", 5, 129.95),
        ("Shipping & Handling", 1, 25.00),
        ("Extended Warranty (1yr)", 3, 39.99),
    ]
    pdf.set_font("Helvetica", size=11)
    for desc, qty, unit in line_items:
        amount = qty * unit
        pdf.cell(90, 8, desc, border=1)
        pdf.cell(25, 8, str(qty), border=1, align="C")
        pdf.cell(35, 8, f"${unit:.2f}", border=1, align="R")
        pdf.cell(40, 8, f"${amount:.2f}", border=1, align="R",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    subtotal = sum(q * u for _, q, u in line_items)
    tax = round(subtotal * 0.0875, 2)
    total = round(subtotal + tax, 2)

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", size=11)
    pdf.cell(150, 8, "Subtotal:", align="R")
    pdf.cell(40, 8, f"${subtotal:.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(150, 8, "Tax (8.75%):", align="R")
    pdf.cell(40, 8, f"${tax:.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(150, 8, "Total Amount Due:", align="R")
    pdf.cell(40, 8, f"${total:.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # --- Page 2: payment terms + notes ---
    pdf.add_page()
    pdf.set_font("Helvetica", "B", size=14)
    _nl(pdf, 10, "Payment Terms & Remittance")
    pdf.ln(2)

    pdf.set_font("Helvetica", size=11)
    pdf.multi_cell(
        0,
        8,
        "Payment is due within 30 days of the invoice date. "
        "Please reference Invoice Number INV-2024-00842 on all remittances.\n\n"
        "Wire Transfer:\n"
        "  Bank: First National Bank\n"
        "  Account Name: Acme Supplies Inc.\n"
        "  Account Number: 1234567890\n"
        "  Routing Number: 021000021\n\n"
        "Thank you for your business.",
    )

    return bytes(pdf.output())


@pytest.fixture
def synthetic_bank_statement_pdf() -> bytes:
    """Generate a minimal but realistic 2-page bank statement PDF using fpdf2."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    # --- Page 1: account summary + transactions ---
    pdf.add_page()
    pdf.set_font("Helvetica", "B", size=18)
    _nl(pdf, 12, "BANK STATEMENT", align="C")
    pdf.ln(2)

    pdf.set_font("Helvetica", size=11)
    _nl(pdf, 8, "First National Bank", align="C")
    _nl(pdf, 8, "Member FDIC  |  www.firstnational.example.com", align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", size=11)
    pdf.cell(60, 8, "Account Holder:")
    pdf.set_font("Helvetica", size=11)
    _nl(pdf, 8, "Jane M. Doe")

    pdf.set_font("Helvetica", "B", size=11)
    pdf.cell(60, 8, "Account Number:")
    pdf.set_font("Helvetica", size=11)
    _nl(pdf, 8, "****  ****  7823")

    pdf.set_font("Helvetica", "B", size=11)
    pdf.cell(60, 8, "Statement Period:")
    pdf.set_font("Helvetica", size=11)
    _nl(pdf, 8, "2024-02-01 to 2024-02-29")

    pdf.set_font("Helvetica", "B", size=11)
    pdf.cell(60, 8, "Opening Balance:")
    pdf.set_font("Helvetica", size=11)
    _nl(pdf, 8, "$4,250.00")
    pdf.ln(4)

    # Transaction table
    pdf.set_font("Helvetica", "B", size=11)
    pdf.cell(35, 8, "Date", border=1)
    pdf.cell(85, 8, "Description", border=1)
    pdf.cell(35, 8, "Debit", border=1, align="R")
    pdf.cell(35, 8, "Credit", border=1, align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    transactions = [
        ("2024-02-02", "Direct Deposit - Employer", None, 3200.00),
        ("2024-02-05", "Grocery Store #1402", 87.34, None),
        ("2024-02-08", "Electric Utility Bill", 124.56, None),
        ("2024-02-12", "Online Transfer - Savings", 500.00, None),
        ("2024-02-14", "Restaurant POS", 42.10, None),
        ("2024-02-18", "Gas Station", 58.22, None),
        ("2024-02-20", "Freelance Payment Rcvd", None, 750.00),
        ("2024-02-25", "Rent Payment", 1500.00, None),
        ("2024-02-28", "ATM Withdrawal", 200.00, None),
    ]

    pdf.set_font("Helvetica", size=10)
    for date, desc, debit, credit in transactions:
        debit_str = f"${debit:.2f}" if debit else ""
        credit_str = f"${credit:.2f}" if credit else ""
        pdf.cell(35, 8, date, border=1)
        pdf.cell(85, 8, desc, border=1)
        pdf.cell(35, 8, debit_str, border=1, align="R")
        pdf.cell(35, 8, credit_str, border=1, align="R",
                 new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    total_debits = sum(d for _, _, d, _ in transactions if d)
    total_credits = sum(c for _, _, _, c in transactions if c)
    closing_balance = 4250.00 - total_debits + total_credits

    pdf.ln(4)
    pdf.set_font("Helvetica", "B", size=11)
    pdf.cell(155, 8, "Total Debits:", align="R")
    pdf.cell(35, 8, f"${total_debits:.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(155, 8, "Total Credits:", align="R")
    pdf.cell(35, 8, f"${total_credits:.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.cell(155, 8, "Closing Balance:", align="R")
    pdf.cell(35, 8, f"${closing_balance:.2f}", align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # --- Page 2: disclosures ---
    pdf.add_page()
    pdf.set_font("Helvetica", "B", size=14)
    _nl(pdf, 10, "Account Information & Disclosures")
    pdf.ln(2)

    pdf.set_font("Helvetica", size=10)
    pdf.multi_cell(
        0,
        7,
        "This statement covers all transactions for the period shown above. "
        "Please review your statement promptly and report any discrepancies "
        "within 60 days.\n\n"
        "Account Type: Checking - Personal\n"
        "Interest Rate: 0.01% APY\n"
        "Minimum Balance Requirement: $100.00\n"
        "Monthly Maintenance Fee: $0.00 (waived - direct deposit active)\n\n"
        "For questions call 1-800-555-2600 or visit any branch location.\n"
        "First National Bank, 789 Main Street, Chicago, IL 60601.",
    )

    return bytes(pdf.output())
