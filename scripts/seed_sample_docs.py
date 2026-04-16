"""Create sample test fixture files for development and testing.

Usage:
    python -m scripts.seed_sample_docs
    python -m scripts.seed_sample_docs --output-dir tests/fixtures
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

FIXTURES_DIR = Path(__file__).parent.parent / "tests" / "fixtures"

# Minimal valid PDF (blank single page)
MINIMAL_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\n"
    b"startxref\n190\n%%EOF\n"
)

# 1x1 white PNG
MINIMAL_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx"
    b"\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N"
    b"\x00\x00\x00\x00IEND\xaeB`\x82"
)

# Minimal EML
MINIMAL_EML = (
    b"From: sender@example.com\r\n"
    b"To: recipient@example.com\r\n"
    b"Subject: Test Invoice Email\r\n"
    b"Date: Mon, 01 Mar 2026 12:00:00 +0000\r\n"
    b"Content-Type: text/plain; charset=utf-8\r\n"
    b"\r\n"
    b"Please find attached invoice #INV-2026-001 for $1,250.00.\r\n"
    b"Vendor: ABC Maintenance LLC\r\n"
    b"Due Date: March 15, 2026\r\n"
)

SAMPLE_INVOICE_TEXT = """INVOICE

Invoice Number: INV-2026-0042
Date: March 1, 2026
Due Date: March 31, 2026

From:
ABC Maintenance LLC
123 Main Street
Portland, OR 97201

Bill To:
Cascade Property Management
456 Oak Avenue, Suite 200
Portland, OR 97204

Description                    Qty    Unit Price    Amount
Plumbing repair - Unit 4B       1      $450.00     $450.00
HVAC filter replacement         12      $25.00     $300.00
Parking lot sweeping             1     $200.00     $200.00

                              Subtotal:            $950.00
                              Tax (8.5%):           $80.75
                              Total:             $1,030.75

Payment Terms: Net 30
"""

SAMPLE_RECEIPT_TEXT = """RECEIPT

Home Depot
Store #4821
1234 Commercial Ave
Portland, OR 97201
(503) 555-0100

Date: 02/28/2026
Receipt #: 4821-2026-88432

Description           Qty   Price    Amount
PVC Pipe 3/4"          4    $3.49    $13.96
Pipe Cement             1    $6.99     $6.99
Teflon Tape             2    $1.29     $2.58

                    Subtotal:        $23.53
                    Tax (8.5%):       $2.00
                    Total:           $25.53

Payment: VISA **** 4821
"""

SAMPLE_LEAD_CAPTURE_TEXT = """LEAD CAPTURE FORM

First Name: Sarah
Last Name: Johnson
Email: sarah.johnson@email.com
Phone: (503) 555-0199
Company: Johnson & Associates

Property Interest: 2BR apartment downtown
Budget Range: $1,500 - $2,000/month
Move-in Date: April 1, 2026
Bedrooms Needed: 2
Pet Owner: Yes (1 cat)

Source: Walk-in
Notes: Interested in units with in-unit laundry. Flexible on move date.
"""

SAMPLE_EXTRACTED_INVOICE = {
    "document_type": "vendor_invoice",
    "invoice_number": "INV-2026-0042",
    "invoice_date": "2026-03-01",
    "due_date": "2026-03-31",
    "vendor_name": "ABC Maintenance LLC",
    "vendor_address": "123 Main Street, Portland, OR 97201",
    "bill_to_name": "Cascade Property Management",
    "bill_to_address": "456 Oak Avenue, Suite 200, Portland, OR 97204",
    "currency": "USD",
    "line_items": [
        {
            "line_number": 1,
            "description": "Plumbing repair - Unit 4B",
            "quantity": "1",
            "unit_price": "450.00",
            "amount": "450.00",
        },
        {
            "line_number": 2,
            "description": "HVAC filter replacement",
            "quantity": "12",
            "unit_price": "25.00",
            "amount": "300.00",
        },
        {
            "line_number": 3,
            "description": "Parking lot sweeping",
            "quantity": "1",
            "unit_price": "200.00",
            "amount": "200.00",
        },
    ],
    "subtotal": "950.00",
    "tax_total": "80.75",
    "discount_amount": "0",
    "total_amount": "1030.75",
    "payment_terms": "Net 30",
    "confidence_score": 0.95,
}


def create_fixtures(output_dir: Path) -> None:
    """Write sample fixture files to the output directory."""
    output_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, bytes] = {
        "sample_invoice.pdf": MINIMAL_PDF,
        "sample_receipt.png": MINIMAL_PNG,
        "sample_email.eml": MINIMAL_EML,
        "sample_invoice_text.txt": SAMPLE_INVOICE_TEXT.encode("utf-8"),
        "sample_receipt_text.txt": SAMPLE_RECEIPT_TEXT.encode("utf-8"),
        "sample_lead_capture_text.txt": SAMPLE_LEAD_CAPTURE_TEXT.encode("utf-8"),
        "sample_extracted_invoice.json": json.dumps(
            SAMPLE_EXTRACTED_INVOICE, indent=2
        ).encode("utf-8"),
    }

    for filename, content in files.items():
        filepath = output_dir / filename
        filepath.write_bytes(content)
        print(f"  Created: {filepath}")

    print(f"\n{len(files)} fixture files created in {output_dir}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sample test fixtures")
    parser.add_argument(
        "--output-dir", type=Path, default=FIXTURES_DIR,
        help=f"Output directory (default: {FIXTURES_DIR})",
    )
    args = parser.parse_args()

    create_fixtures(args.output_dir)


if __name__ == "__main__":
    main()
