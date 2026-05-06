from datetime import datetime, timedelta
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.schemas.common import ContactChannel, ProcessingStatus, utcnow


MalwareStatus = Literal["pending", "clean", "infected", "failed", "quarantined"]
ReviewStatus = Literal["pending", "approved", "corrected", "rejected"]


class DocumentUploadInitRequest(BaseModel):
    original_filename: str
    file_type: str
    file_size_bytes: int
    sha256: str
    upload_channel: ContactChannel | None = None
    document_type_hint: str | None = None


class MedicalDocument(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    patient_id: UUID
    original_filename: str
    file_type: str
    document_type: str | None = None
    malware_scan_status: MalwareStatus = "pending"
    ocr_status: ProcessingStatus = "blocked"
    extraction_status: ProcessingStatus = "blocked"
    review_status: ReviewStatus = "pending"
    created_at: datetime = Field(default_factory=utcnow)


class UploadTarget(BaseModel):
    method: Literal["PUT", "POST"] = "PUT"
    url: str
    expires_at: datetime = Field(default_factory=lambda: utcnow() + timedelta(minutes=15))
    headers: dict[str, str] = Field(default_factory=dict)


class DocumentUploadInitResponse(BaseModel):
    document: MedicalDocument
    upload: UploadTarget


class ExtractedMedicalFact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    fact_type: str
    label: str
    value: str
    unit: str | None = None
    effective_date: str | None = None
    confidence: float = 0.0
    source_page: int | None = None
    source_text_span: dict[str, Any] | None = None
    review_status: ReviewStatus = "pending"
    corrected_value: str | None = None


class DocumentDetailResponse(BaseModel):
    document: MedicalDocument
    facts: list[ExtractedMedicalFact] = Field(default_factory=list)


class DocumentProcessingStatus(BaseModel):
    document_id: UUID
    malware_scan_status: MalwareStatus = "pending"
    ocr_status: ProcessingStatus = "blocked"
    extraction_status: ProcessingStatus = "blocked"
    blocked_reason: str = "malware_scan_not_clean"
    runs: list[dict[str, Any]] = Field(default_factory=list)


class FactReview(BaseModel):
    fact_id: UUID
    review_status: ReviewStatus
    corrected_value: str | None = None


class DocumentReviewRequest(BaseModel):
    facts: list[FactReview]


class PatientQuestionRequest(BaseModel):
    question: str
    allowed_document_ids: list[UUID] | None = None


class PatientQuestionResponse(BaseModel):
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    audit_log_id: UUID
