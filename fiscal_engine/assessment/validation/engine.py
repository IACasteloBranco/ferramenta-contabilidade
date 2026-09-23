"""Orquestrador das regras; não lê arquivos nem conhece PDF."""

from __future__ import annotations

from ..models import CompanyTaxAssessment, ValidationFinding
from .rules import (accumulators_rule, cancellation_match_rule, extraction_status_rule,
                    rbt12_required_rule, revenue_match_rule, source_documents_rule, source_consistency_rule)

RULES = [extraction_status_rule, source_documents_rule, revenue_match_rule, rbt12_required_rule,
         accumulators_rule, cancellation_match_rule, source_consistency_rule]


def validate(assessment: CompanyTaxAssessment) -> list[ValidationFinding]:
    return [finding for rule in RULES for finding in rule(assessment)]
