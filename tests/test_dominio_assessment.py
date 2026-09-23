from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fiscal_engine.assessment.dominio_pdf import (parse_das_pages, parse_monthly_pages, parse_pgdas_pages,
                                                   parse_simples_pages, parse_summary_pages)
from fiscal_engine.assessment.extractors import extract
from fiscal_engine.assessment.models import AssessmentStatus, DocumentType
from fiscal_engine.assessment.normalization import normalize
from fiscal_engine.assessment.service import assess_batch, discover_sources
from fiscal_engine.assessment.validation.results import classify
from fiscal_engine.assessment.validation.rules import (accumulators_rule, cancellation_match_rule,
                                                        extraction_status_rule, rbt12_required_rule,
                                                        revenue_match_rule, source_documents_rule,
                                                        source_consistency_rule)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures/dominio-batch/2026-08"


def assessment_for(folder: str):
    sources = discover_sources(FIXTURES)[folder]
    partials = [extract(source) for source in sources]
    return normalize(partials, {"id": folder, "code": None, "name": folder, "document": None}, "2026-08")


class AssessmentRuleTests(unittest.TestCase):
    def test_revenue_rule_preserves_values_and_sources(self):
        finding = revenue_match_rule(assessment_for("002_EMPRESA_B"))[0]
        self.assertEqual((finding.code, finding.expected, finding.actual), ("REVENUE_MISMATCH", 50000, 57500))
        self.assertEqual(finding.sources, [DocumentType.SIMPLES_APURACAO, DocumentType.FATURAMENTO_SIMPLES])

    def test_rbt12_rule(self):
        findings = rbt12_required_rule(assessment_for("003_EMPRESA_C"))
        self.assertEqual([item.code for item in findings], ["RBT12_MISSING"])

    def test_unknown_accumulator_rule(self):
        findings = accumulators_rule(assessment_for("004_EMPRESA_D"))
        self.assertEqual(findings[0].code, "UNKNOWN_ACCUMULATOR")
        self.assertEqual(findings[0].actual, "AJUSTE_NAO_MAPEADO")
        assessment = assessment_for("004_EMPRESA_D")
        assessment.accumulators.append({"code": "28", "description": "REVENDA", "section": "SAIDAS"})
        self.assertEqual(len(accumulators_rule(assessment)), 1)

    def test_required_document_rule(self):
        findings = source_documents_rule(assessment_for("005_EMPRESA_E"))
        self.assertEqual(findings[0].code, "SOURCE_DOCUMENT_MISSING")
        self.assertEqual(findings[0].sources, [DocumentType.RESUMO_ACUMULADORES])
        assessment = assessment_for("001_EMPRESA_A")
        assessment.sources[0].file_path = "simples_apuracao.pdf"
        self.assertFalse(source_documents_rule(assessment))

    def test_extraction_failure_is_error_and_does_not_add_dependent_rbt12_finding(self):
        assessment = assessment_for("006_EMPRESA_F")
        self.assertEqual([item.code for item in extraction_status_rule(assessment)], ["EXTRACTION_FAILED"])
        self.assertFalse(rbt12_required_rule(assessment))

    def test_returns_do_not_create_exception_when_reports_are_consistent(self):
        assessment = assessment_for("007_EMPRESA_G")
        self.assertEqual(assessment.revenue["returns"], 2000)
        self.assertFalse(revenue_match_rule(assessment))
        self.assertFalse(cancellation_match_rule(assessment))

    def test_cancellation_mismatch(self):
        findings = cancellation_match_rule(assessment_for("008_EMPRESA_H"))
        self.assertEqual((findings[0].code, findings[0].expected, findings[0].actual),
                         ("CANCELLATION_MISMATCH", 1000, 1500))

    def test_pgdas_difference_is_reported_with_sources(self):
        assessment = assessment_for("001_EMPRESA_A")
        assessment.source_values[DocumentType.PGDAS_EXTRATO] = {
            "revenue": {"currentPeriod": 50001, "rbt12": 420000},
            "simples": {"calculatedAmount": 3250},
        }
        findings = source_consistency_rule(assessment)
        self.assertEqual([item.code for item in findings], ["PGDAS_REVENUE_MISMATCH"])
        self.assertEqual(findings[0].sources, [DocumentType.SIMPLES_APURACAO, DocumentType.PGDAS_EXTRATO])

    def test_classification(self):
        self.assertEqual(classify([]), AssessmentStatus.SEM_EXCECOES)
        self.assertEqual(classify(rbt12_required_rule(assessment_for("003_EMPRESA_C"))), AssessmentStatus.REVISAR)
        self.assertEqual(classify(extraction_status_rule(assessment_for("006_EMPRESA_F"))), AssessmentStatus.ERRO)


class DominioPdfLayoutTests(unittest.TestCase):
    def test_simples_page_keeps_multiple_rates_and_ignores_next_period(self):
        current = """Empresa: EMPRESA TESTE                                      Página: 0001
CNPJ: 11.111.111/0001-11
Período: 08/2026
Receita Bruta do período de Apuração (RPA) -
Regime de Competência                    100,00          0,00          100,00
ao período de apuração (RBT12)           2.000,00        0,00        2.000,00
Anexo: Anexo I - Comércio
Tabela: Tabela 1 - Sem substituição tributária
Receita Tributada Total: 70,00 Alíquota: 5,000000 Simples Nacional Total: 3,50
Anexo: Anexo I - Comércio
Tabela: Tabela 4 - Substituição tributária
Receita Tributada Total: 30,00 Alíquota: 3,000000 Simples Nacional Total: 0,90
Simples Nacional a recolher: 4,40"""
        next_period = current.replace("08/2026", "09/2026").replace("100,00", "900,00")
        company, period, values, warnings = parse_simples_pages([next_period, current], "2026-08")
        self.assertEqual((company["name"], period), ("EMPRESA TESTE", "2026-08"))
        self.assertEqual(values["revenue"], {"currentPeriod": 100.0, "rbt12": 2000.0})
        self.assertEqual([item["revenue"] for item in values["simples"]["segments"]], [70.0, 30.0])
        self.assertIsNone(values["simples"]["effectiveRate"])
        self.assertEqual(warnings, [])

    def test_monthly_page_uses_sales_and_services_but_not_entries(self):
        page = """Empresa: EMPRESA TESTE                         Emissão: 22/09/2026
CNPJ: 11.111.111/0001-11
Período: 01/08/2026 a 31/08/2026
DEMONSTRATIVO MENSAL
Mês Ano Entradas R$ Saídas R$ Serviços R$
Agosto 2026 40,00 70,00 30,00"""
        _, period, values, _ = parse_monthly_pages([page], "2026-08")
        self.assertEqual(period, "2026-08")
        self.assertEqual(values["revenue"]["currentPeriod"], 100.0)
        self.assertEqual(values["monthly"]["entries"], 40.0)
        with self.assertRaisesRegex(ValueError, "esperado 2026-09"):
            parse_monthly_pages([page], "2026-09")


    def test_summary_excludes_purchase_return_from_revenue(self):
        page = """EMPRESA TESTE LTDA                                  Pagina: 1/1
CNPJ: 11.111.111/0001-11
Periodo: 01/08/2026 ate 31/08/2026
RESUMO POR ACUMULADOR
ENTRADAS
Codigo Descricao Vlr Contabil
1 COMPRAS NORMAIS 14.678,12 0,00
Total: 14.678,12
SAIDAS
Codigo Descricao Vlr Contabil
13 DEVOLUCAO DE COMPRAS 296,42 0,00
1 16 REVENDA NORMAL 3.014,00 0,00
27 REVENDA NA UF 48.275,23 0,00
1 28 REVENDA NA UF (ST) 5.952,73 0,00
Total: 57.538,38"""
        company, period, values, warnings = parse_summary_pages([page], "2026-08")
        self.assertEqual((company["name"], period), ("EMPRESA TESTE LTDA", "2026-08"))
        self.assertEqual(values["revenue"]["currentPeriod"], 57241.96)
        self.assertEqual(values["accumulatorSummary"]["outgoingTotal"], 57538.38)
        self.assertEqual(values["accumulatorSummary"]["purchaseReturns"], 296.42)
        self.assertEqual([item["code"] for item in values["accumulators"]], ["1", "13", "16", "27", "28"])
        self.assertEqual(warnings, [])
        with self.assertRaisesRegex(ValueError, "esperado 2026-09"):
            parse_summary_pages([page], "2026-09")

    def test_government_documents_keep_period_and_amount(self):
        pgdas_first = """Extrato do Simples Nacional
CNPJ Basico: 11.111.111 Nome Empresarial: EMPRESA TESTE LTDA
Periodo de Apuracao (PA): 08/2026
Receita Bruta do PA (RPA) - Competencia 57.241,96 0,00 57.241,96
Receita bruta acumulada nos doze meses anteriores ao PA 497.459,70 0,00 497.459,70
CNPJ Estabelecimento: 11.111.111/0001-11"""
        pgdas_last = """INSS/CPP
Principal 3.668,77 Multa 0,00 Juros 0,00 Total 3.668,77"""
        _, period, values, _ = parse_pgdas_pages([pgdas_first, pgdas_last], "2026-08")
        self.assertEqual(period, "2026-08")
        self.assertEqual(values["revenue"]["rbt12"], 497459.70)
        self.assertEqual(values["simples"]["calculatedAmount"], 3668.77)
        das = """Documento de Arrecadacao do Simples Nacional
11.111.111/0001-11 EMPRESA TESTE LTDA
08/2026
Valor Total do Documento
3.668,77"""
        _, period, values, _ = parse_das_pages([das], "2026-08")
        self.assertEqual(period, "2026-08")
        self.assertEqual(values["simples"]["calculatedAmount"], 3668.77)


class AssessmentBatchTests(unittest.TestCase):
    def test_end_to_end_fixture_batch(self):
        result = assess_batch(FIXTURES)
        self.assertEqual(result["summary"], {"total": 8, "withoutExceptions": 2, "review": 5, "errors": 1})
        companies = {item["company"]["name"]: item for item in result["companies"]}
        self.assertEqual(companies["EMPRESA A"]["status"], AssessmentStatus.SEM_EXCECOES)
        self.assertEqual(companies["EMPRESA G"]["status"], AssessmentStatus.SEM_EXCECOES)
        self.assertEqual(companies["EMPRESA F"]["status"], AssessmentStatus.ERRO)
        self.assertEqual([item["code"] for item in companies["EMPRESA B"]["findings"]], ["REVENUE_MISMATCH"])
        self.assertEqual(companies["EMPRESA B"]["assessment"]["sources"][0]["extraction_status"], "complete")
        self.assertEqual(companies["EMPRESA B"]["assessment"]["sources"][0]["company_id"], "empresa-b")
        self.assertEqual(companies["EMPRESA B"]["assessment"]["sources"][0]["period"], "2026-08")
        self.assertEqual(companies["EMPRESA B"]["assessment"]["source_values"]["SIMPLES_APURACAO"]["revenue"]["currentPeriod"], 50000)
        self.assertEqual(companies["EMPRESA B"]["findings"][0]["sources"], ["SIMPLES_APURACAO", "FATURAMENTO_SIMPLES"])
        json.dumps(result, ensure_ascii=False)

    def test_discovery_catalogues_a_future_pdf_without_inferring_its_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary) / "2026-08" / "001_EMPRESA_TESTE"
            folder.mkdir(parents=True)
            (folder / "simples_apuracao.pdf").write_bytes(b"%PDF-synthetic")
            sources = discover_sources(folder.parent)
            self.assertEqual(sources["001_EMPRESA_TESTE"][0].document_type, DocumentType.SIMPLES_APURACAO)
            result = assess_batch(folder.parent)
            item = result["companies"][0]
            self.assertEqual(item["status"], AssessmentStatus.ERRO)
            self.assertIn("EXTRACTION_FAILED", [finding["code"] for finding in item["findings"]])
            self.assertIn("catalogado", item["assessment"]["extraction"]["warnings"][0])

    def test_invalid_json_is_an_extraction_error_without_stopping_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / "2026-08"
            target.mkdir()
            good = target / "001_BOA"
            bad = target / "002_RUIM"
            good.mkdir()
            bad.mkdir()
            for source in (FIXTURES / "001_EMPRESA_A").iterdir():
                (good / source.name.replace(".synthetic", "")).write_bytes(source.read_bytes())
            (bad / "simples_apuracao.json").write_text("{invalido", encoding="utf-8")
            result = assess_batch(target)
            self.assertEqual(result["summary"]["total"], 2)
            self.assertEqual(result["summary"]["withoutExceptions"], 1)
            self.assertEqual(result["summary"]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
