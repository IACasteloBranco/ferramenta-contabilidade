"""Combina dados extraídos, mantendo a origem de cada valor."""

from __future__ import annotations

from .extractors import PartialAssessment
from .models import CompanyTaxAssessment, DocumentType, ExtractionStatus


def _number(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Valor numérico inválido no relatório")
    return float(value)


def normalize(partials: list[PartialAssessment], fallback_company: dict[str, str | None], period: str) -> CompanyTaxAssessment:
    company = dict(fallback_company)
    revenue = {"currentPeriod": None, "rbt12": None, "returns": None, "cancellations": None}
    simples = {"annexes": None, "factorR": None, "calculatedAmount": None, "effectiveRate": None,
               "segments": []}
    accumulators: list[dict] = []
    source_values: dict[str, dict] = {}
    field_sources: dict[str, list[str]] = {}
    warnings: list[str] = []
    statuses = []
    sources = []
    identified_company: dict[str, str] = {}

    priority = {DocumentType.SIMPLES_APURACAO: 0, DocumentType.FATURAMENTO_SIMPLES: 1,
                DocumentType.RESUMO_ACUMULADORES: 2, DocumentType.PGDAS_EXTRATO: 3,
                DocumentType.DAS_GUIA: 4}
    for partial in sorted(partials, key=lambda item: priority.get(item.source.document_type, 99)):
        source = partial.source
        sources.append(source)
        statuses.append(partial.extraction_status)
        warnings.extend(partial.warnings)
        if partial.company:
            for key in ("id", "code", "name", "document"):
                value = partial.company.get(key)
                if value is not None:
                    value = str(value)
                    if key in identified_company and identified_company[key] != value:
                        warnings.append(f"Divergência de {key} entre os relatórios da empresa.")
                        source.extraction_status = ExtractionStatus.PARTIAL
                        statuses[-1] = ExtractionStatus.PARTIAL
                    elif key not in identified_company:
                        company[key] = value
                        identified_company[key] = value
        if partial.period and partial.period != period:
            warnings.append(f"Competência {partial.period} no relatório {source.document_type}; esperado {period}.")
        values = partial.values
        if not isinstance(values, dict):
            source.extraction_status = ExtractionStatus.FAILED
            statuses[-1] = ExtractionStatus.FAILED
            warnings.append(f"Dados inválidos em {source.document_type}.")
            continue
        source_values[source.document_type] = values
        source_revenue = values.get("revenue") or {}
        if isinstance(source_revenue, dict):
            for key in revenue:
                if key in source_revenue:
                    try:
                        number = _number(source_revenue[key])
                    except ValueError as exc:
                        source.extraction_status = ExtractionStatus.FAILED
                        statuses[-1] = ExtractionStatus.FAILED
                        warnings.append(f"{source.document_type}: {exc}")
                        continue
                    field = f"revenue.{key}"
                    field_sources.setdefault(field, []).append(source.document_type)
                    if revenue[key] is None:
                        revenue[key] = number
        source_simples = values.get("simples") or {}
        if isinstance(source_simples, dict):
            for key in simples:
                if key in source_simples:
                    value = source_simples[key]
                    if key == "segments":
                        if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
                            source.extraction_status = ExtractionStatus.FAILED
                            statuses[-1] = ExtractionStatus.FAILED
                            warnings.append(f"Segregações inválidas em {source.document_type}.")
                            continue
                        simples["segments"].extend(value)
                        field_sources.setdefault("simples.segments", []).append(source.document_type)
                        continue
                    if key != "annexes":
                        try:
                            value = _number(value)
                        except ValueError as exc:
                            source.extraction_status = ExtractionStatus.FAILED
                            statuses[-1] = ExtractionStatus.FAILED
                            warnings.append(f"{source.document_type}: {exc}")
                            continue
                    simples[key] = value if simples[key] is None else simples[key]
                    field_sources.setdefault(f"simples.{key}", []).append(source.document_type)
        source_accumulators = values.get("accumulators") or []
        if source_accumulators:
            if not isinstance(source_accumulators, list) or not all(isinstance(item, dict) for item in source_accumulators):
                source.extraction_status = ExtractionStatus.FAILED
                statuses[-1] = ExtractionStatus.FAILED
                warnings.append(f"Acumuladores inválidos em {source.document_type}.")
            else:
                accumulators.extend(source_accumulators)
                field_sources.setdefault("accumulators", []).append(source.document_type)

    extraction_status = (ExtractionStatus.FAILED if ExtractionStatus.FAILED in statuses else
                         ExtractionStatus.PARTIAL if ExtractionStatus.PARTIAL in statuses else ExtractionStatus.COMPLETE)
    return CompanyTaxAssessment(company, period, revenue, simples, accumulators, sources,
                                {"status": extraction_status, "warnings": warnings}, source_values, field_sources)
