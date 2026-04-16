"""Tests for app/schemas/extraction_models.py Pydantic schemas."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.schemas.extraction_models import (
    ContractExtraction,
    InvoiceExtraction,
    MedicalRecordExtraction,
    ReceiptExtraction,
)


class TestInvoiceExtraction:
    def test_all_fields(self):
        data = {
            "invoice_number": "INV-001",
            "vendor_name": "Acme Corp",
            "vendor_address": "123 Main St",
            "invoice_date": "2024-01-15",
            "due_date": "2024-02-15",
            "line_items": [
                {"description": "Widget", "quantity": 2.0, "unit_price": "10.00", "total": "20.00"}
            ],
            "subtotal": "20.00",
            "tax": "2.00",
            "total": "22.00",
            "currency": "USD",
            "field_confidence": {"invoice_number": 0.99, "total": 0.95},
        }
        inv = InvoiceExtraction.model_validate(data)
        assert inv.invoice_number == "INV-001"
        assert inv.vendor_name == "Acme Corp"
        assert inv.invoice_date == date(2024, 1, 15)
        assert inv.due_date == date(2024, 2, 15)
        assert inv.total == Decimal("22.00")
        assert len(inv.line_items) == 1
        assert inv.field_confidence["total"] == 0.95

    def test_minimal_fields_all_none(self):
        inv = InvoiceExtraction()
        assert inv.invoice_number is None
        assert inv.vendor_name is None
        assert inv.invoice_date is None
        assert inv.line_items == []
        assert inv.field_confidence == {}

    def test_decimal_fields_accept_string_numbers(self):
        inv = InvoiceExtraction.model_validate(
            {"subtotal": "100.50", "tax": "8.25", "total": "108.75"}
        )
        assert inv.subtotal == Decimal("100.50")
        assert inv.tax == Decimal("8.25")
        assert inv.total == Decimal("108.75")

    def test_date_fields_accept_iso_strings(self):
        inv = InvoiceExtraction.model_validate(
            {"invoice_date": "2025-06-01", "due_date": "2025-07-01"}
        )
        assert inv.invoice_date == date(2025, 6, 1)
        assert inv.due_date == date(2025, 7, 1)

    def test_field_confidence_validates_as_dict_of_floats(self):
        inv = InvoiceExtraction.model_validate(
            {"field_confidence": {"invoice_number": 0.9, "vendor_name": 0.8}}
        )
        assert inv.field_confidence["invoice_number"] == 0.9
        assert inv.field_confidence["vendor_name"] == 0.8


class TestContractExtraction:
    def test_contract_extraction(self):
        data = {
            "parties": ["Acme Corp", "Bob Inc"],
            "effective_date": "2024-03-01",
            "expiry_date": "2025-03-01",
            "contract_type": "service_agreement",
            "key_terms": ["net 30 payment", "auto-renewal"],
            "obligations": ["Acme will deliver", "Bob will pay"],
            "payment_terms": "Net 30",
            "field_confidence": {"parties": 0.97},
        }
        contract = ContractExtraction.model_validate(data)
        assert contract.parties == ["Acme Corp", "Bob Inc"]
        assert contract.effective_date == date(2024, 3, 1)
        assert contract.contract_type == "service_agreement"
        assert len(contract.key_terms) == 2
        assert contract.field_confidence["parties"] == 0.97

    def test_contract_defaults(self):
        contract = ContractExtraction()
        assert contract.parties == []
        assert contract.key_terms == []
        assert contract.obligations == []
        assert contract.effective_date is None


class TestReceiptExtraction:
    def test_receipt_extraction(self):
        data = {
            "merchant_name": "Coffee Shop",
            "merchant_address": "456 Oak Ave",
            "transaction_date": "2024-05-10",
            "items": [{"name": "Latte", "price": "5.50"}, {"name": "Muffin", "price": "3.25"}],
            "subtotal": "8.75",
            "tax": "0.70",
            "total": "9.45",
            "payment_method": "credit_card",
            "field_confidence": {"total": 0.98},
        }
        receipt = ReceiptExtraction.model_validate(data)
        assert receipt.merchant_name == "Coffee Shop"
        assert receipt.transaction_date == date(2024, 5, 10)
        assert len(receipt.items) == 2
        assert receipt.items[0].price == Decimal("5.50")
        assert receipt.total == Decimal("9.45")
        assert receipt.payment_method == "credit_card"

    def test_receipt_defaults(self):
        receipt = ReceiptExtraction()
        assert receipt.items == []
        assert receipt.merchant_name is None


class TestMedicalRecordExtraction:
    def test_medical_record_extraction(self):
        data = {
            "patient_name": "John Doe",
            "date_of_birth": "1980-04-22",
            "diagnoses": ["Hypertension", "Type 2 Diabetes"],
            "medications": ["Metformin 500mg", "Lisinopril 10mg"],
            "procedures": ["Blood glucose test"],
            "provider_name": "Dr. Smith",
            "visit_date": "2024-11-20",
            "field_confidence": {"patient_name": 0.99},
        }
        record = MedicalRecordExtraction.model_validate(data)
        assert record.patient_name == "John Doe"
        assert record.date_of_birth == date(1980, 4, 22)
        assert record.visit_date == date(2024, 11, 20)
        assert "Hypertension" in record.diagnoses
        assert record.provider_name == "Dr. Smith"

    def test_medical_record_defaults(self):
        record = MedicalRecordExtraction()
        assert record.patient_name is None
        assert record.diagnoses == []
        assert record.medications == []
        assert record.procedures == []
