"""Business rule validation per document type."""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class ErrorSeverity(str, Enum):
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class ValidationError:
    field_path: str
    error_type: str
    message: str
    severity: ErrorSeverity = ErrorSeverity.ERROR


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)
    needs_review: bool = False
    confidence: float = 1.0


# REVIEW_TRIGGERS: return True if document needs human review
REVIEW_TRIGGERS: list[Callable[[dict[str, Any], float], bool]] = [
    # 1. Low confidence
    lambda data, conf: conf < 0.7,
    # 2. High-value document
    lambda data, conf: (data.get("total_amount") or 0) > 10000,
    # 3. Conflicting dates (invoice: due_date < invoice_date)
    lambda data, conf: _has_conflicting_dates(data),
    # 4. Missing required fields
    lambda data, conf: _has_missing_required_fields(data),
]

TOLERANCE = 0.02  # $0.02 tolerance for monetary calculations


def validate(doc_type: str, data: dict[str, Any], confidence: float = 1.0) -> ValidationResult:
    """Run business rule validation for the given document type.

    Returns:
        ValidationResult with errors and needs_review flag
    """
    errors: list[ValidationError] = []

    validators = {
        "invoice": _validate_invoice,
        "purchase_order": _validate_purchase_order,
        "receipt": _validate_receipt,
        "bank_statement": _validate_bank_statement,
        "identity_document": _validate_identity_document,
        "medical_record": _validate_medical_record,
    }

    validator_fn = validators.get(doc_type)
    if validator_fn:
        errors = validator_fn(data)

    # Check review triggers
    needs_review = any(trigger(data, confidence) for trigger in REVIEW_TRIGGERS)
    is_valid = not any(e.severity == ErrorSeverity.ERROR for e in errors)

    return ValidationResult(
        is_valid=is_valid,
        errors=errors,
        needs_review=needs_review,
        confidence=confidence,
    )


def _validate_invoice(data: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []

    subtotal = data.get("subtotal") or 0
    tax = data.get("tax_amount") or 0
    discount = data.get("discount_amount") or 0
    total = data.get("total_amount")

    if total is not None:
        expected = subtotal + tax - discount
        if abs(total - expected) > TOLERANCE:
            errors.append(ValidationError(
                field_path="total_amount",
                error_type="CALCULATION_MISMATCH",
                message=f"Total {total} != subtotal {subtotal} + tax {tax} - discount {discount} = {expected:.2f} (tolerance +/-${TOLERANCE})",
            ))

        if total < 0:
            errors.append(ValidationError(
                field_path="total_amount",
                error_type="NEGATIVE_AMOUNT",
                message="Total amount cannot be negative",
            ))

    # Date validation
    errors.extend(_validate_date_order(data, "invoice_date", "due_date"))

    return errors


def _validate_purchase_order(data: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []
    errors.extend(_validate_date_order(data, "order_date", "delivery_date"))

    for i, item in enumerate(data.get("line_items", [])):
        qty = item.get("quantity")
        if qty is not None and qty <= 0:
            errors.append(ValidationError(
                field_path=f"line_items[{i}].quantity",
                error_type="NON_POSITIVE_QUANTITY",
                message=f"Quantity must be positive, got {qty}",
            ))

    return errors


def _validate_receipt(data: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []

    items = data.get("items", [])
    if items:
        items_sum = sum((item.get("total") or 0) for item in items)
        total = data.get("total")
        if total is not None and abs(total - items_sum) > 0.01:
            errors.append(ValidationError(
                field_path="total",
                error_type="TOTAL_MISMATCH",
                message=f"Total {total} != sum of items {items_sum:.2f} (tolerance +/-$0.01)",
            ))

    return errors


def _validate_bank_statement(data: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []

    opening = data.get("opening_balance")
    closing = data.get("closing_balance")
    credits = data.get("total_credits") or 0
    debits = data.get("total_debits") or 0

    if opening is not None and closing is not None:
        expected_closing = opening + credits - debits
        if abs(closing - expected_closing) > 0.01:
            errors.append(ValidationError(
                field_path="closing_balance",
                error_type="BALANCE_MISMATCH",
                message=f"Closing balance {closing} != opening {opening} + credits {credits} - debits {debits} = {expected_closing:.2f}",
            ))

    return errors


def _validate_identity_document(data: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []

    if not data.get("document_number"):
        errors.append(ValidationError(
            field_path="document_number",
            error_type="MISSING_REQUIRED",
            message="Document number is required",
            severity=ErrorSeverity.ERROR,
        ))

    errors.extend(_validate_date_order(data, "issue_date", "expiry_date"))

    return errors


def _validate_medical_record(data: dict[str, Any]) -> list[ValidationError]:
    errors: list[ValidationError] = []

    required_fields = ["patient_name", "visit_date"]
    for field_name in required_fields:
        if not data.get(field_name):
            errors.append(ValidationError(
                field_path=field_name,
                error_type="MISSING_REQUIRED",
                message=f"{field_name} is required",
                severity=ErrorSeverity.WARNING,
            ))

    # visit_date should not be in the future
    visit_date_str = data.get("visit_date")
    if visit_date_str:
        try:
            visit_date = date.fromisoformat(visit_date_str[:10])
            if visit_date > date.today():
                errors.append(ValidationError(
                    field_path="visit_date",
                    error_type="FUTURE_DATE",
                    message=f"Visit date {visit_date} is in the future",
                    severity=ErrorSeverity.WARNING,
                ))
        except ValueError:
            pass

    return errors


def _validate_date_order(data: dict[str, Any], start_field: str, end_field: str) -> list[ValidationError]:
    """Validate that start_date <= end_date."""
    errors: list[ValidationError] = []
    start_str = data.get(start_field)
    end_str = data.get(end_field)

    if start_str and end_str:
        try:
            start = date.fromisoformat(start_str[:10])
            end = date.fromisoformat(end_str[:10])
            if end < start:
                errors.append(ValidationError(
                    field_path=end_field,
                    error_type="INVALID_DATE_ORDER",
                    message=f"{end_field} ({end}) must be >= {start_field} ({start})",
                ))
        except ValueError:
            pass

    return errors


def _has_conflicting_dates(data: dict[str, Any]) -> bool:
    """Check for date conflicts in document."""
    pairs = [
        ("invoice_date", "due_date"),
        ("order_date", "delivery_date"),
        ("issue_date", "expiry_date"),
    ]
    for start_field, end_field in pairs:
        errors = _validate_date_order(data, start_field, end_field)
        if errors:
            return True
    return False


def _has_missing_required_fields(data: dict[str, Any]) -> bool:
    """Check if critical identifying fields are all missing."""
    id_fields = [
        "invoice_number", "po_number", "receipt_number",
        "document_number", "mrn", "account_number",
    ]
    return not any(data.get(f) for f in id_fields)
