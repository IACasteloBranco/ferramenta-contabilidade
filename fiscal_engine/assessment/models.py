"""Modelo normalizado, independente do formato dos relatórios de origem."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dataclass_field
from enum import StrEnum
from typing import Any


class DocumentType(StrEnum):
    SIMPLES_APURACAO = "SIMPLES_APURACAO"
    FATURAMENTO_SIMPLES = "FATURAMENTO_SIMPLES"
    RESUMO_ACUMULADORES = "RESUMO_ACUMULADORES"
    PGDAS_EXTRATO = "PGDAS_EXTRATO"
    DAS_GUIA = "DAS_GUIA"


class ExtractionStatus(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    FAILED = "failed"
    CATALOGUED = "catalogued"


class AssessmentStatus(StrEnum):
    SEM_EXCECOES = "SEM_EXCECOES"
    REVISAR = "REVISAR"
    ERRO = "ERRO"


@dataclass
class SourceDocument:
    document_type: DocumentType
    file_path: str
    processed_at: str
    company_id: str | None = None
    period: str | None = None
    sha256: str | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.CATALOGUED
    warnings: list[str] = dataclass_field(default_factory=list)


@dataclass
class ValidationFinding:
    code: str
    severity: str
    message: str
    field: str | None = None
    expected: Any = None
    actual: Any = None
    sources: list[str] = dataclass_field(default_factory=list)


@dataclass
class CompanyTaxAssessment:
    company: dict[str, str | None]
    period: str
    revenue: dict[str, float | None]
    simples: dict[str, Any]
    accumulators: list[dict[str, Any]]
    sources: list[SourceDocument]
    extraction: dict[str, Any]
    # Mantém os valores declarados por tipo de relatório, sem escolher uma fonte
    # como verdade fiscal. As regras usam este mapa para comparações explicáveis.
    source_values: dict[str, dict[str, Any]] = dataclass_field(default_factory=dict)
    field_sources: dict[str, list[str]] = dataclass_field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["sources"] = [asdict(source) for source in self.sources]
        return value
