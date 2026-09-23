"""Compara os fatos declarados nos relatórios recebidos."""

from __future__ import annotations

from decimal import Decimal

from ...models import CompanyTaxAssessment, DocumentType, ValidationFinding
from .common import source_value


def source_consistency_rule(assessment: CompanyTaxAssessment) -> list[ValidationFinding]:
    checks = [
        (DocumentType.SIMPLES_APURACAO, DocumentType.RESUMO_ACUMULADORES,
         "revenue.currentPeriod", "ACCUMULATOR_REVENUE_MISMATCH",
         "Receita da apuração diverge das vendas no Resumo por Acumulador."),
        (DocumentType.FATURAMENTO_SIMPLES, DocumentType.RESUMO_ACUMULADORES,
         "revenue.currentPeriod", "FATURAMENTO_ACUMULADORES_MISMATCH",
         "Faturamento mensal diverge das vendas no Resumo por Acumulador."),
        (DocumentType.FATURAMENTO_SIMPLES, DocumentType.RESUMO_ACUMULADORES,
         "monthly.entries|accumulatorSummary.entriesTotal", "ENTRIES_MISMATCH",
         "Entradas do Demonstrativo Mensal divergem do Resumo por Acumulador."),
        (DocumentType.SIMPLES_APURACAO, DocumentType.PGDAS_EXTRATO,
         "revenue.currentPeriod", "PGDAS_REVENUE_MISMATCH",
         "Receita da apuração no Domínio diverge da declarada no PGDAS-D."),
        (DocumentType.SIMPLES_APURACAO, DocumentType.PGDAS_EXTRATO,
         "revenue.rbt12", "PGDAS_RBT12_MISMATCH",
         "RBT12 do Domínio diverge do extrato do PGDAS-D."),
        (DocumentType.SIMPLES_APURACAO, DocumentType.PGDAS_EXTRATO,
         "simples.calculatedAmount", "PGDAS_AMOUNT_MISMATCH",
         "Valor apurado no Domínio diverge do extrato do PGDAS-D."),
        (DocumentType.PGDAS_EXTRATO, DocumentType.DAS_GUIA,
         "simples.calculatedAmount", "DAS_AMOUNT_MISMATCH",
         "Valor no extrato do PGDAS-D diverge da guia DAS."),
    ]
    findings = []
    for left, right, field, code, message in checks:
        left_field, right_field = (field.split("|", 1) if "|" in field else (field, field))
        expected = source_value(assessment, left, left_field)
        actual = source_value(assessment, right, right_field)
        if expected is None or actual is None:
            continue
        if abs(Decimal(str(expected)) - Decimal(str(actual))) < Decimal("0.005"):
            continue
        findings.append(ValidationFinding(code, "warning", message, right_field,
                                          expected=expected, actual=actual, sources=[left, right]))
    return findings
