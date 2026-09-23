from __future__ import annotations

from ...models import CompanyTaxAssessment, DocumentType, ValidationFinding


REQUIRED_DOCUMENTS = {DocumentType.SIMPLES_APURACAO, DocumentType.FATURAMENTO_SIMPLES, DocumentType.RESUMO_ACUMULADORES}


def source_documents_rule(assessment: CompanyTaxAssessment) -> list[ValidationFinding]:
    available = {source.document_type for source in assessment.sources}
    missing = sorted(document.value for document in REQUIRED_DOCUMENTS - available)
    if not missing:
        return []
    return [ValidationFinding("SOURCE_DOCUMENT_MISSING", "warning", "Relatório necessário do Domínio não foi recebido para a conferência.",
                              "sources", expected=sorted(document.value for document in REQUIRED_DOCUMENTS), actual=sorted(available), sources=missing)]
