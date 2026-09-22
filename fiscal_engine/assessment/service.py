"""Descoberta, extração, normalização e conferência em lote."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from .extractors import extract
from .models import (AssessmentStatus, CompanyTaxAssessment, DocumentType, ExtractionStatus,
                     SourceDocument, ValidationFinding)
from .normalization import normalize
from .validation import validate
from .validation.results import classify


NAME_TO_TYPE = {
    "simples_apuracao": DocumentType.SIMPLES_APURACAO,
    "simples nacional": DocumentType.SIMPLES_APURACAO,
    "faturamento_simples": DocumentType.FATURAMENTO_SIMPLES,
    "demonstrativo mensal": DocumentType.FATURAMENTO_SIMPLES,
    "resumo_acumuladores": DocumentType.RESUMO_ACUMULADORES,
    "resumo por acumulador": DocumentType.RESUMO_ACUMULADORES,
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _report_type(path: Path) -> DocumentType | None:
    name = path.name.lower()
    for stem, document_type in NAME_TO_TYPE.items():
        if name == f"{stem}.pdf" or name == f"{stem}.json" or name == f"{stem}.synthetic.json":
            return document_type
    return None


def discover_sources(input_dir: Path) -> dict[str, list[SourceDocument]]:
    """Encontra relatórios conhecidos em subpastas ou em uma pasta de empresa."""
    if not input_dir.is_dir():
        raise ValueError(f"Pasta de entrada não encontrada: {input_dir}")
    grouped: dict[str, list[SourceDocument]] = {}
    direct_reports = [path for path in input_dir.iterdir() if path.is_file() and _report_type(path) is not None]
    paths = direct_reports if direct_reports else input_dir.rglob("*")
    for path in sorted(paths):
        if not path.is_file() or path.suffix.lower() not in {".json", ".pdf"}:
            continue
        document_type = _report_type(path)
        if document_type is None:
            continue
        company_folder = path.parent.name
        source = SourceDocument(document_type, str(path), now())
        grouped.setdefault(company_folder, []).append(source)
    return grouped


def _fallback_company(folder: str) -> dict[str, str | None]:
    match = re.match(r"(?P<code>\d+)[_-](?P<name>.+)", folder)
    return {"id": folder, "code": match.group("code") if match else None,
            "name": (match.group("name").replace("_", " ") if match else folder), "document": None}


def _failure_result(folder: str, period: str, error: Exception) -> dict:
    source = SourceDocument(DocumentType.SIMPLES_APURACAO, folder, now(), extraction_status=ExtractionStatus.FAILED,
                            warnings=[str(error)])
    assessment = CompanyTaxAssessment(_fallback_company(folder), period,
                                      {"currentPeriod": None, "rbt12": None, "returns": None, "cancellations": None},
                                      {"annexes": None, "factorR": None, "calculatedAmount": None, "effectiveRate": None}, [], [source],
                                      {"status": ExtractionStatus.FAILED, "warnings": [str(error)]})
    findings = [ValidationFinding("EXTRACTION_FAILED", "error", "Não foi possível produzir uma análise confiável porque houve falha de extração.",
                                  "extraction.status", sources=[DocumentType.SIMPLES_APURACAO])]
    return {"company": assessment.company, "period": period, "status": AssessmentStatus.ERRO,
            "findings": [item.__dict__ for item in findings], "assessment": assessment.to_dict()}


def assess_batch(input_dir: Path, period: str | None = None) -> dict:
    input_dir = input_dir.resolve()
    actual_period = period or input_dir.name
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", actual_period):
        raise ValueError("Competência inválida; use AAAA-MM ou informe --period")
    companies = []
    for folder, sources in discover_sources(input_dir).items():
        try:
            for source in sources:
                source.company_id = folder
                source.period = actual_period
            partials = [extract(source) for source in sources]
            assessment = normalize(partials, _fallback_company(folder), actual_period)
            findings = validate(assessment)
            companies.append({"company": assessment.company, "period": actual_period, "status": classify(findings),
                              "findings": [item.__dict__ for item in findings], "assessment": assessment.to_dict()})
        except (OSError, ValueError, TypeError, KeyError) as exc:
            companies.append(_failure_result(folder, actual_period, exc))
    companies.sort(key=lambda item: (item["company"]["name"] or "", item["company"]["id"] or ""))
    counts = Counter(item["status"] for item in companies)
    return {"period": actual_period, "processed_at": now(),
            "summary": {"total": len(companies), "withoutExceptions": counts[AssessmentStatus.SEM_EXCECOES],
                        "review": counts[AssessmentStatus.REVISAR], "errors": counts[AssessmentStatus.ERRO]},
            "companies": companies}


def write_result(result: dict, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
