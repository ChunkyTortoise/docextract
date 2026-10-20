"""Pydantic schemas for structured document extraction output."""
from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class LineItem(BaseModel):
    description: str
    quantity: float | None = None
    unit_price: Decimal | None = None
    total: Decimal | None = None


class InvoiceExtraction(BaseModel):
    invoice_number: str | None = None
    vendor_name: str | None = None
    vendor_address: str | None = None
    invoice_date: date | None = None
    due_date: date | None = None
    line_items: list[LineItem] = []
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    currency: str | None = None
    field_confidence: dict[str, float] = {}


class ContractExtraction(BaseModel):
    parties: list[str] = []
    effective_date: date | None = None
    expiry_date: date | None = None
    contract_type: str | None = None
    key_terms: list[str] = []
    obligations: list[str] = []
    payment_terms: str | None = None
    field_confidence: dict[str, float] = {}


class ReceiptItem(BaseModel):
    name: str
    price: Decimal | None = None


class ReceiptExtraction(BaseModel):
    merchant_name: str | None = None
    merchant_address: str | None = None
    transaction_date: date | None = None
    items: list[ReceiptItem] = []
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    payment_method: str | None = None
    field_confidence: dict[str, float] = {}


class MedicalRecordExtraction(BaseModel):
    patient_name: str | None = None
    date_of_birth: date | None = None
    diagnoses: list[str] = []
    medications: list[str] = []
    procedures: list[str] = []
    provider_name: str | None = None
    visit_date: date | None = None
    field_confidence: dict[str, float] = {}


class StructuredExtractionResponse(BaseModel):
    doc_id: str
    doc_type: str
    extraction: (
        InvoiceExtraction
        | ContractExtraction
        | ReceiptExtraction
        | MedicalRecordExtraction
        | None
    )
    error: str | None = None
    latency_ms: float
    model_used: str
    retry_count: int = 0


class BatchExtractionResult(BaseModel):
    results: list[StructuredExtractionResponse]
    total: int
    successful: int
    failed: int
    total_latency_ms: float
