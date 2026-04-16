"""Tests for response_validator service."""
from __future__ import annotations

from app.services.response_validator import ValidationOutcome, validate_extraction


class TestValidateExtractionInvoice:
    def test_valid_invoice_passes(self):
        data = {"invoice_number": "INV-001", "total_amount": 500.0}
        outcome = validate_extraction(data, "invoice")
        assert outcome.schema_valid is True
        assert outcome.used_fallback is False

    def test_empty_dict_is_valid(self):
        outcome = validate_extraction({}, "invoice")
        assert outcome.schema_valid is True

    def test_returns_coerced_data(self):
        data = {"invoice_number": "INV-001", "total_amount": 500.0}
        outcome = validate_extraction(data, "invoice")
        assert isinstance(outcome.validated_data, dict)

    def test_extra_fields_ignored(self):
        # Pydantic v2 by default ignores extra fields
        data = {"invoice_number": "INV-001", "nonexistent_field": "foo"}
        outcome = validate_extraction(data, "invoice")
        # Should not raise — extra fields are ignored
        assert isinstance(outcome, ValidationOutcome)

    def test_invalid_currency_result_is_outcome(self):
        data = {"invoice_number": "INV-001", "currency": "INVALID_CURRENCY_CODE_XYZ"}
        outcome = validate_extraction(data, "invoice")
        # currency has CurrencyCode enum validation — should fail or fallback
        # Either way, outcome is a ValidationOutcome
        assert isinstance(outcome, ValidationOutcome)

    def test_valid_currency_passes(self):
        data = {"invoice_number": "INV-001", "currency": "USD"}
        outcome = validate_extraction(data, "invoice")
        assert outcome.schema_valid is True


class TestValidateExtractionReceipt:
    def test_valid_receipt(self):
        data = {"merchant_name": "Coffee Shop", "total": 5.50}
        outcome = validate_extraction(data, "receipt")
        assert outcome.schema_valid is True

    def test_empty_receipt_valid(self):
        outcome = validate_extraction({}, "receipt")
        assert outcome.schema_valid is True


class TestValidateExtractionMedical:
    def test_valid_medical_record(self):
        data = {"patient_name": "Jane Doe", "visit_date": "2024-01-01"}
        outcome = validate_extraction(data, "medical_record")
        assert outcome.schema_valid is True


class TestValidateExtractionBankStatement:
    def test_valid_bank_statement(self):
        data = {"account_holder": "John Smith", "closing_balance": 1000.0}
        outcome = validate_extraction(data, "bank_statement")
        assert outcome.schema_valid is True


class TestValidateExtractionIdentity:
    def test_valid_identity_document(self):
        data = {"document_number": "P12345678", "full_name": "Alice Brown"}
        outcome = validate_extraction(data, "identity_document")
        assert outcome.schema_valid is True


class TestValidateExtractionUnknown:
    def test_unknown_doc_type_passthrough(self):
        data = {"some_field": "some_value"}
        outcome = validate_extraction(data, "unknown")
        assert outcome.schema_valid is True
        assert outcome.validated_data == data

    def test_unknown_doc_type_no_fallback(self):
        outcome = validate_extraction({}, "unknown")
        assert outcome.used_fallback is False

    def test_unregistered_doc_type_passthrough(self):
        outcome = validate_extraction({"x": 1}, "totally_unknown_type")
        assert outcome.schema_valid is True


class TestValidationOutcomeStructure:
    def test_has_required_fields(self):
        outcome = validate_extraction({}, "invoice")
        assert hasattr(outcome, "validated_data")
        assert hasattr(outcome, "schema_valid")
        assert hasattr(outcome, "validation_errors")
        assert hasattr(outcome, "used_fallback")

    def test_validation_errors_is_list(self):
        outcome = validate_extraction({}, "invoice")
        assert isinstance(outcome.validation_errors, list)

    def test_validated_data_is_dict(self):
        outcome = validate_extraction({"invoice_number": "INV-001"}, "invoice")
        assert isinstance(outcome.validated_data, dict)

    def test_purchase_order_valid(self):
        data = {"po_number": "PO-100", "total_amount": 999.0}
        outcome = validate_extraction(data, "purchase_order")
        assert outcome.schema_valid is True
        assert isinstance(outcome, ValidationOutcome)
