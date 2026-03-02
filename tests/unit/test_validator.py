"""Tests for business rule validator."""
import pytest

from app.services.validator import (
    ErrorSeverity,
    ValidationError,
    ValidationResult,
    validate,
    _has_conflicting_dates,
    _has_missing_required_fields,
    TOLERANCE,
)


class TestInvoiceValidation:
    def test_correct_total(self):
        data = {
            "invoice_number": "INV-001",
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "discount_amount": 5.0,
            "total_amount": 105.0,
        }
        result = validate("invoice", data)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_total_mismatch(self):
        data = {
            "invoice_number": "INV-001",
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "discount_amount": 0.0,
            "total_amount": 200.0,  # should be 110
        }
        result = validate("invoice", data)
        assert not result.is_valid
        assert any(e.error_type == "CALCULATION_MISMATCH" for e in result.errors)

    def test_total_within_tolerance(self):
        data = {
            "invoice_number": "INV-001",
            "subtotal": 100.0,
            "tax_amount": 10.0,
            "discount_amount": 0.0,
            "total_amount": 110.01,  # within $0.02 tolerance
        }
        result = validate("invoice", data)
        assert result.is_valid

    def test_negative_total(self):
        data = {
            "invoice_number": "INV-001",
            "total_amount": -50.0,
        }
        result = validate("invoice", data)
        assert not result.is_valid
        assert any(e.error_type == "NEGATIVE_AMOUNT" for e in result.errors)

    def test_due_date_before_invoice_date(self):
        data = {
            "invoice_number": "INV-001",
            "invoice_date": "2025-03-15",
            "due_date": "2025-03-01",
        }
        result = validate("invoice", data)
        assert any(e.error_type == "INVALID_DATE_ORDER" for e in result.errors)

    def test_due_date_after_invoice_date(self):
        data = {
            "invoice_number": "INV-001",
            "invoice_date": "2025-03-01",
            "due_date": "2025-03-15",
        }
        result = validate("invoice", data)
        date_errors = [e for e in result.errors if e.error_type == "INVALID_DATE_ORDER"]
        assert len(date_errors) == 0


class TestPurchaseOrderValidation:
    def test_valid_po(self):
        data = {
            "po_number": "PO-100",
            "order_date": "2025-01-01",
            "delivery_date": "2025-02-01",
            "line_items": [{"quantity": 5, "description": "Widget"}],
        }
        result = validate("purchase_order", data)
        assert result.is_valid

    def test_non_positive_quantity(self):
        data = {
            "po_number": "PO-100",
            "line_items": [{"quantity": 0, "description": "Widget"}],
        }
        result = validate("purchase_order", data)
        assert any(e.error_type == "NON_POSITIVE_QUANTITY" for e in result.errors)

    def test_negative_quantity(self):
        data = {
            "po_number": "PO-100",
            "line_items": [{"quantity": -3, "description": "Bad"}],
        }
        result = validate("purchase_order", data)
        assert any(e.error_type == "NON_POSITIVE_QUANTITY" for e in result.errors)


class TestReceiptValidation:
    def test_total_matches_items(self):
        data = {
            "receipt_number": "R-001",
            "items": [
                {"total": 5.50},
                {"total": 3.25},
            ],
            "total": 8.75,
        }
        result = validate("receipt", data)
        assert result.is_valid

    def test_total_mismatch(self):
        data = {
            "receipt_number": "R-001",
            "items": [
                {"total": 5.50},
                {"total": 3.25},
            ],
            "total": 20.00,
        }
        result = validate("receipt", data)
        assert any(e.error_type == "TOTAL_MISMATCH" for e in result.errors)


class TestBankStatementValidation:
    def test_balance_calculation_correct(self):
        data = {
            "account_number": "1234",
            "opening_balance": 1000.0,
            "closing_balance": 1500.0,
            "total_credits": 700.0,
            "total_debits": 200.0,
        }
        result = validate("bank_statement", data)
        assert result.is_valid

    def test_balance_mismatch(self):
        data = {
            "account_number": "1234",
            "opening_balance": 1000.0,
            "closing_balance": 2000.0,  # should be 1500
            "total_credits": 700.0,
            "total_debits": 200.0,
        }
        result = validate("bank_statement", data)
        assert any(e.error_type == "BALANCE_MISMATCH" for e in result.errors)


class TestIdentityDocumentValidation:
    def test_missing_document_number(self):
        data = {"full_name": "John Doe"}
        result = validate("identity_document", data)
        assert not result.is_valid
        assert any(e.error_type == "MISSING_REQUIRED" for e in result.errors)

    def test_valid_with_number(self):
        data = {"document_number": "AB123456"}
        result = validate("identity_document", data)
        assert result.is_valid

    def test_expiry_before_issue(self):
        data = {
            "document_number": "AB123456",
            "issue_date": "2025-01-01",
            "expiry_date": "2020-01-01",
        }
        result = validate("identity_document", data)
        assert any(e.error_type == "INVALID_DATE_ORDER" for e in result.errors)


class TestMedicalRecordValidation:
    def test_missing_patient_name_is_warning(self):
        data = {"mrn": "MRN-001", "visit_date": "2025-01-01"}
        result = validate("medical_record", data)
        warnings = [e for e in result.errors if e.severity == ErrorSeverity.WARNING]
        assert any(e.field_path == "patient_name" for e in warnings)
        # Warnings don't make is_valid False
        assert result.is_valid

    def test_future_visit_date_is_warning(self):
        data = {
            "mrn": "MRN-001",
            "patient_name": "Jane",
            "visit_date": "2099-12-31",
        }
        result = validate("medical_record", data)
        assert any(e.error_type == "FUTURE_DATE" for e in result.errors)
        assert result.is_valid  # warnings only


class TestReviewTriggers:
    def test_low_confidence_triggers_review(self):
        data = {"invoice_number": "INV-001"}
        result = validate("invoice", data, confidence=0.5)
        assert result.needs_review

    def test_high_value_triggers_review(self):
        data = {
            "invoice_number": "INV-001",
            "total_amount": 15000.0,
            "subtotal": 15000.0,
        }
        result = validate("invoice", data, confidence=0.99)
        assert result.needs_review

    def test_conflicting_dates_trigger_review(self):
        data = {
            "invoice_number": "INV-001",
            "invoice_date": "2025-06-01",
            "due_date": "2025-01-01",
        }
        result = validate("invoice", data, confidence=0.99)
        assert result.needs_review

    def test_missing_id_fields_trigger_review(self):
        data = {"vendor_name": "Acme"}
        result = validate("invoice", data, confidence=0.99)
        assert result.needs_review

    def test_no_review_when_all_good(self):
        data = {
            "invoice_number": "INV-001",
            "subtotal": 100.0,
            "tax_amount": 0.0,
            "total_amount": 100.0,
        }
        result = validate("invoice", data, confidence=0.99)
        assert not result.needs_review


class TestHasConflictingDates:
    def test_no_dates(self):
        assert not _has_conflicting_dates({})

    def test_valid_dates(self):
        assert not _has_conflicting_dates({
            "invoice_date": "2025-01-01",
            "due_date": "2025-02-01",
        })

    def test_conflicting(self):
        assert _has_conflicting_dates({
            "order_date": "2025-06-01",
            "delivery_date": "2025-01-01",
        })


class TestHasMissingRequiredFields:
    def test_has_invoice_number(self):
        assert not _has_missing_required_fields({"invoice_number": "INV-001"})

    def test_has_po_number(self):
        assert not _has_missing_required_fields({"po_number": "PO-100"})

    def test_all_missing(self):
        assert _has_missing_required_fields({"vendor_name": "Acme"})

    def test_empty_data(self):
        assert _has_missing_required_fields({})


class TestUnknownDocType:
    def test_unknown_type_no_errors(self):
        result = validate("unknown_type", {"some": "data"}, confidence=0.99)
        assert result.is_valid
        assert len(result.errors) == 0
