"""Adaptadores de relatórios para o contrato normalizado de apuração."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from pypdf.errors import PdfReadError

from .dominio_pdf import parse_pdf
from .models import DocumentType, ExtractionStatus, SourceDocument


def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class PartialAssessment:
    source: SourceDocument
    company: dict
    period: str | None
    values: dict
    extraction_status: ExtractionStatus
    warnings: list[str]


class AssessmentExtractor(Protocol):
    def supports(self, source: SourceDocument) -> bool: ...

    def extract(self, source: SourceDocument) -> PartialAssessment: ...


class JsonAssessmentExtractor:
    """Lê o contrato JSON de intercâmbio e as fixtures de desenvolvimento."""

    def supports(self, source: SourceDocument) -> bool:
        return Path(source.file_path).suffix.lower() == ".json" and not source.file_path.endswith(".synthetic.json")

    def extract(self, source: SourceDocument) -> PartialAssessment:
        path = Path(source.file_path)
        try:
            raw = path.read_bytes()
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise ValueError("O relatório JSON deve conter um objeto")
            declared_type = payload.get("document_type")
            if declared_type and declared_type != source.document_type:
                raise ValueError("Tipo informado no JSON diverge do nome do relatório")
            extraction = payload.get("extraction") or {}
            status = ExtractionStatus(extraction.get("status", "complete"))
            warnings = extraction.get("warnings", [])
            if not isinstance(warnings, list) or not all(isinstance(item, str) for item in warnings):
                raise ValueError("Avisos de extração inválidos")
            source.sha256 = hashlib.sha256(raw).hexdigest()
            source.extraction_status = status
            source.warnings = list(warnings)
            source.company_id = str((payload.get("company") or {}).get("id")) if (payload.get("company") or {}).get("id") is not None else source.company_id
            source.period = payload.get("period") or source.period
            return PartialAssessment(source, payload.get("company") or {}, payload.get("period"),
                                     payload.get("data") or {}, status, list(warnings))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            source.extraction_status = ExtractionStatus.FAILED
            source.warnings = [f"Falha ao extrair JSON: {exc}"]
            return PartialAssessment(source, {}, None, {}, ExtractionStatus.FAILED, source.warnings)


class SyntheticAssessmentExtractor(JsonAssessmentExtractor):
    """Adaptador das fixtures. Mantém o mesmo contrato, com extensão explícita."""

    def supports(self, source: SourceDocument) -> bool:
        return source.file_path.endswith(".synthetic.json")


class DominioPdfAssessmentExtractor:
    """Lê os layouts validados de apuração e demonstrativo mensal do Domínio."""

    def supports(self, source: SourceDocument) -> bool:
        return Path(source.file_path).suffix.lower() == ".pdf"

    def extract(self, source: SourceDocument) -> PartialAssessment:
        path = Path(source.file_path)
        try:
            company, period, values, warnings = parse_pdf(path, source.document_type, source.period)
            source.sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
            source.company_id = company["id"]
            source.period = period
            source.extraction_status = ExtractionStatus.PARTIAL if warnings else ExtractionStatus.COMPLETE
            source.warnings = warnings
            return PartialAssessment(source, company, period, values, source.extraction_status, warnings)
        except (OSError, ValueError, PdfReadError) as exc:
            source.extraction_status = ExtractionStatus.FAILED
            source.warnings = [f"PDF do Domínio catalogado, mas não foi possível extrair seu layout: {exc}"]
            return PartialAssessment(source, {}, None, {}, ExtractionStatus.FAILED, source.warnings)


EXTRACTORS: list[AssessmentExtractor] = [SyntheticAssessmentExtractor(), JsonAssessmentExtractor(), DominioPdfAssessmentExtractor()]


def extract(source: SourceDocument) -> PartialAssessment:
    extractor = next((item for item in EXTRACTORS if item.supports(source)), None)
    if extractor is None:
        source.extraction_status = ExtractionStatus.FAILED
        source.warnings = ["Formato de relatório não suportado"]
        return PartialAssessment(source, {}, None, {}, ExtractionStatus.FAILED, source.warnings)
    return extractor.extract(source)
