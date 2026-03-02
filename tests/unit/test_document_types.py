"""Tests for document type schemas."""
from datetime import date, datetime

import pytest

from app.schemas.document_types import (
    DOCUMENT_TYPE_MAP,
    BankStatementSchema,
    BankTransaction,
    CurrencyCode,
    Diagnosis,
    DocumentType,
    IdentityDocumentSchema,
    InvoiceSchema,
    LineItem,
    MedicalRecordSchema,
    Medication,
    Procedure,
    PurchaseOrderSchema,
    ReceiptSchema,
)


class TestCurrencyCode:
    def test_usd(self):
        assert CurrencyCode.USD == "USD"

    def test_all_values(self):
        expected = {"USD", "EUR", "GBP", "CAD", "AUD", "JPY", "CHF", "CNY", "INR", "MXN"}
        assert {c.value for c in CurrencyCode} == expected

    def test_string_enum(self):
        assert isinstance(CurrencyCode.EUR, str)
        assert CurrencyCode.EUR == "EUR"


class TestDocumentType:
    def test_all_types(self):
        expected = {
            "invoice", "purchase_order", "receipt",
            "bank_statement", "identity_document", "medical_record", "unknown",
        }
        assert {dt.value for dt in DocumentType} == expected

    def test_unknown_type(self):
        assert DocumentType.UNKNOWN == "unknown"


class TestLineItem:
    def test_all_optional(self):
        item = LineItem()
        assert item.description is None
        assert item.quantity is None
        assert item.unit_price is None
        assert item.total is None
        assert item.sku is None

    def test_with_values(self):
        item = LineItem(description="Widget", quantity=3, unit_price=9.99, total=29.97, sku="W-001")
        assert item.description == "Widget"
        assert item.quantity == 3
        assert item.total == 29.97


class TestInvoiceSchema:
    def test_defaults_to_none(self):
        inv = InvoiceSchema()
        assert inv.invoice_number is None
        assert inv.vendor_name is None
        assert inv.total_amount is None
        assert inv.currency is None
        assert inv.line_items == []

    def test_full_invoice(self):
        inv = InvoiceSchema(
            invoice_number="INV-001",
            invoice_date="2025-01-15",
            due_date="2025-02-15",
            vendor_name="Acme Corp",
            total_amount=1500.00,
            currency=CurrencyCode.USD,
            line_items=[LineItem(description="Service", total=1500.0)],
        )
        assert inv.invoice_number == "INV-001"
        assert inv.currency == CurrencyCode.USD

    def test_date_validator_date_object(self):
        inv = InvoiceSchema(invoice_date=date(2025, 6, 15))
        assert inv.invoice_date == "2025-06-15"

    def test_date_validator_datetime_object(self):
        inv = InvoiceSchema(invoice_date=datetime(2025, 6, 15, 10, 30))
        assert inv.invoice_date == "2025-06-15"

    def test_date_validator_string_passthrough(self):
        inv = InvoiceSchema(invoice_date="01/15/2025")
        assert inv.invoice_date == "01/15/2025"

    def test_date_validator_none(self):
        inv = InvoiceSchema(invoice_date=None)
        assert inv.invoice_date is None

    def test_due_date_validator(self):
        inv = InvoiceSchema(due_date=date(2025, 3, 1))
        assert inv.due_date == "2025-03-01"


class TestPurchaseOrderSchema:
    def test_defaults(self):
        po = PurchaseOrderSchema()
        assert po.po_number is None
        assert po.shipping_method is None
        assert po.line_items == []

    def test_with_values(self):
        po = PurchaseOrderSchema(
            po_number="PO-100",
            order_date="2025-01-01",
            vendor_name="Supplier Inc",
            total_amount=500.0,
        )
        assert po.po_number == "PO-100"


class TestReceiptSchema:
    def test_defaults(self):
        r = ReceiptSchema()
        assert r.receipt_number is None
        assert r.items == []
        assert r.tip_amount is None

    def test_with_items(self):
        r = ReceiptSchema(
            merchant_name="Coffee Shop",
            items=[LineItem(description="Latte", total=5.50)],
            total=5.50,
        )
        assert r.merchant_name == "Coffee Shop"
        assert len(r.items) == 1


class TestBankTransaction:
    def test_defaults(self):
        tx = BankTransaction()
        assert tx.date is None
        assert tx.transaction_type is None

    def test_with_values(self):
        tx = BankTransaction(
            date="2025-01-15",
            description="Deposit",
            amount=1000.0,
            transaction_type="credit",
            balance=5000.0,
        )
        assert tx.transaction_type == "credit"


class TestBankStatementSchema:
    def test_defaults(self):
        bs = BankStatementSchema()
        assert bs.transactions == []
        assert bs.opening_balance is None

    def test_with_transactions(self):
        bs = BankStatementSchema(
            bank_name="First Bank",
            opening_balance=1000.0,
            closing_balance=1500.0,
            transactions=[BankTransaction(amount=500.0, transaction_type="credit")],
        )
        assert len(bs.transactions) == 1


class TestIdentityDocumentSchema:
    def test_defaults(self):
        doc = IdentityDocumentSchema()
        assert doc.document_number is None
        assert doc.identity_document_type is None

    def test_passport(self):
        doc = IdentityDocumentSchema(
            identity_document_type="passport",
            document_number="AB1234567",
            full_name="John Doe",
            issuing_country="US",
        )
        assert doc.identity_document_type == "passport"


class TestMedicalRecordSchema:
    def test_defaults(self):
        mr = MedicalRecordSchema()
        assert mr.diagnoses == []
        assert mr.medications == []
        assert mr.procedures == []

    def test_with_nested(self):
        mr = MedicalRecordSchema(
            patient_name="Jane Doe",
            diagnoses=[Diagnosis(code="J06.9", description="URI")],
            medications=[Medication(name="Amoxicillin", dosage="500mg")],
            procedures=[Procedure(code="99213", description="Office visit")],
        )
        assert len(mr.diagnoses) == 1
        assert mr.diagnoses[0].code == "J06.9"
        assert mr.medications[0].name == "Amoxicillin"


class TestDocumentTypeMap:
    def test_has_all_six_types(self):
        assert len(DOCUMENT_TYPE_MAP) == 6

    def test_invoice_mapping(self):
        assert DOCUMENT_TYPE_MAP[DocumentType.INVOICE] is InvoiceSchema

    def test_purchase_order_mapping(self):
        assert DOCUMENT_TYPE_MAP[DocumentType.PURCHASE_ORDER] is PurchaseOrderSchema

    def test_receipt_mapping(self):
        assert DOCUMENT_TYPE_MAP[DocumentType.RECEIPT] is ReceiptSchema

    def test_bank_statement_mapping(self):
        assert DOCUMENT_TYPE_MAP[DocumentType.BANK_STATEMENT] is BankStatementSchema

    def test_identity_document_mapping(self):
        assert DOCUMENT_TYPE_MAP[DocumentType.IDENTITY_DOCUMENT] is IdentityDocumentSchema

    def test_medical_record_mapping(self):
        assert DOCUMENT_TYPE_MAP[DocumentType.MEDICAL_RECORD] is MedicalRecordSchema

    def test_unknown_not_in_map(self):
        assert DocumentType.UNKNOWN not in DOCUMENT_TYPE_MAP
