"""Document type schemas for Claude extraction output validation.
No app.* imports — pure Pydantic.
"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class CurrencyCode(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    CAD = "CAD"
    AUD = "AUD"
    JPY = "JPY"
    CHF = "CHF"
    CNY = "CNY"
    INR = "INR"
    MXN = "MXN"


class DocumentType(str, Enum):
    INVOICE = "invoice"
    PURCHASE_ORDER = "purchase_order"
    RECEIPT = "receipt"
    BANK_STATEMENT = "bank_statement"
    IDENTITY_DOCUMENT = "identity_document"
    MEDICAL_RECORD = "medical_record"
    UNKNOWN = "unknown"


class LineItem(BaseModel):
    description: str | None = None
    quantity: float | None = None
    unit_price: float | None = None
    total: float | None = None
    sku: str | None = None


class InvoiceSchema(BaseModel):
    invoice_number: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    vendor_name: str | None = None
    vendor_address: str | None = None
    customer_name: str | None = None
    customer_address: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax_amount: float | None = None
    discount_amount: float | None = None
    total_amount: float | None = None
    currency: CurrencyCode | None = None
    payment_terms: str | None = None
    notes: str | None = None

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def parse_date(cls, v: Any) -> str | None:
        if v is None:
            return None
        if isinstance(v, (date, datetime)):
            return v.isoformat()[:10]
        return str(v)


class PurchaseOrderSchema(BaseModel):
    po_number: str | None = None
    order_date: str | None = None
    delivery_date: str | None = None
    vendor_name: str | None = None
    vendor_address: str | None = None
    customer_name: str | None = None
    customer_address: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax_amount: float | None = None
    total_amount: float | None = None
    currency: CurrencyCode | None = None
    payment_terms: str | None = None
    shipping_method: str | None = None
    notes: str | None = None


class ReceiptSchema(BaseModel):
    receipt_number: str | None = None
    merchant_name: str | None = None
    merchant_address: str | None = None
    transaction_date: str | None = None
    items: list[LineItem] = Field(default_factory=list)
    subtotal: float | None = None
    tax_amount: float | None = None
    tip_amount: float | None = None
    total: float | None = None
    currency: CurrencyCode | None = None
    payment_method: str | None = None


class BankTransaction(BaseModel):
    date: str | None = None
    description: str | None = None
    amount: float | None = None
    transaction_type: str | None = None  # "credit" or "debit"
    balance: float | None = None
    reference: str | None = None


class BankStatementSchema(BaseModel):
    account_number: str | None = None
    account_holder: str | None = None
    bank_name: str | None = None
    statement_period_start: str | None = None
    statement_period_end: str | None = None
    opening_balance: float | None = None
    closing_balance: float | None = None
    total_credits: float | None = None
    total_debits: float | None = None
    transactions: list[BankTransaction] = Field(default_factory=list)
    currency: CurrencyCode | None = None


class IdentityDocumentSchema(BaseModel):
    identity_document_type: str | None = None  # "passport", "drivers_license", "national_id"
    document_number: str | None = None
    full_name: str | None = None
    date_of_birth: str | None = None
    expiry_date: str | None = None
    issue_date: str | None = None
    issuing_country: str | None = None
    issuing_authority: str | None = None
    nationality: str | None = None
    gender: str | None = None
    address: str | None = None


class Diagnosis(BaseModel):
    code: str | None = None  # ICD-10
    description: str | None = None
    category: str | None = None


class Medication(BaseModel):
    name: str | None = None
    dosage: str | None = None
    frequency: str | None = None
    duration: str | None = None


class Procedure(BaseModel):
    code: str | None = None  # CPT
    description: str | None = None
    date: str | None = None


class MedicalRecordSchema(BaseModel):
    patient_name: str | None = None
    date_of_birth: str | None = None
    mrn: str | None = None  # Medical Record Number
    visit_date: str | None = None
    provider_name: str | None = None
    provider_specialty: str | None = None
    facility_name: str | None = None
    chief_complaint: str | None = None
    diagnoses: list[Diagnosis] = Field(default_factory=list)
    medications: list[Medication] = Field(default_factory=list)
    procedures: list[Procedure] = Field(default_factory=list)
    notes: str | None = None


# Map document type string -> schema class
DOCUMENT_TYPE_MAP: dict[str, type[BaseModel]] = {
    DocumentType.INVOICE: InvoiceSchema,
    DocumentType.PURCHASE_ORDER: PurchaseOrderSchema,
    DocumentType.RECEIPT: ReceiptSchema,
    DocumentType.BANK_STATEMENT: BankStatementSchema,
    DocumentType.IDENTITY_DOCUMENT: IdentityDocumentSchema,
    DocumentType.MEDICAL_RECORD: MedicalRecordSchema,
}
