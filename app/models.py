from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class Provenance(BaseModel):
    doc_name: str
    page: Optional[int] = None
    snippet: str


class FieldResult(BaseModel):
    value: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Optional[Provenance] = None


class PropertyAddress(BaseModel):
    address: str
    confidence: float = Field(ge=0.0, le=1.0)
    provenance: Optional[Provenance] = None


class TokenUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    estimated_cost_usd: Optional[float] = None


class ExtractionResult(BaseModel):
    request_id: str
    cache_hit: bool
    broker_name: FieldResult
    broker_email: FieldResult
    brokerage: FieldResult
    complete_brokerage_address: FieldResult
    property_addresses: list[PropertyAddress]
    latency_ms: float
    token_usage: Optional[TokenUsage] = None
    errors: list[str] = Field(default_factory=list)


class SubmissionResult(BaseModel):
    submission_id: str
    result: ExtractionResult


class BatchExtractionResult(BaseModel):
    submissions: list[SubmissionResult]
    total: int


class MetricsResponse(BaseModel):
    total_requests: int
    cache_hits: int
    cache_misses: int
    cache_hit_rate: float
    total_tokens_used: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float
    avg_cost_per_request_usd: float
    total_latency_ms: float
    avg_latency_ms: float
    errors_by_type: dict[str, int]
    error_rate: float
