"""Schemas used as OpenAI Structured Output contracts."""
from typing import Literal
from pydantic import BaseModel

Category = Literal["security", "error_handling", "testing"]
Severity = Literal["critical", "high", "medium", "low"]


class Finding(BaseModel):
    path: str
    line: int
    category: Category
    severity: Severity
    title: str
    explanation: str
    recommendation: str
    confidence: float


class FindingsResponse(BaseModel):
    findings: list[Finding]


class UnderstandingResponse(BaseModel):
    summary: str
    change_types: list[str]
    areas_to_watch: list[str]
