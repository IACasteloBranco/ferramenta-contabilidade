"""Leitura dos layouts do Domínio observados nos relatórios de setembro/2026.

O PDF de Simples Nacional reúne vários relatórios. Só a página de apuração da
competência solicitada alimenta o resumo; a alíquota do período seguinte e as
listas parciais de produtos não são tratadas como outra apuração ou como um
resumo completo de acumuladores.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from pypdf import PdfReader

from .models import DocumentType


MONEY = r"\d{1,3}(?:\.\d{3})*,\d{2}"
NUMBER = r"\d+(?:\.\d{3})*,\d+"
CNPJ = r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"
MONTHS = (
    "Janeiro", "Fevereiro", "Mar.o", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace(".", "").replace(",", "."))


def _required(text: str, pattern: str, field: str, flags: int = re.IGNORECASE | re.DOTALL) -> re.Match[str]:
    match = re.search(pattern, text, flags)
    if match is None:
        raise ValueError(f"Campo {field} não encontrado no layout do PDF do Domínio")
    return match


def _identity(text: str) -> dict[str, str]:
    name = _required(text, r"Empresa:\s*([^\r\n]+)", "empresa").group(1).strip()
    name = re.split(r"\s{2,}", name, maxsplit=1)[0].strip()
    cnpj = _required(text, rf"CNPJ:\s*({CNPJ})", "CNPJ").group(1)
    return {"id": re.sub(r"\D", "", cnpj), "name": name, "document": cnpj}


def _period(text: str) -> str:
    match = _required(text, r"Per[^:\r\n]{1,10}:\s*(\d{2})/(\d{4})", "competência")
    return f"{match.group(2)}-{match.group(1)}"


def _apportionment(text: str) -> list[dict]:
    """Preserva cada faixa/segregação sem escolher uma alíquota única."""
    portions: list[dict] = []
    for part in re.split(r"(?=\bAnexo:\s*Anexo\s+[IVX]+)", text):
        if "Receita Tributada Total:" not in part:
            continue
        match = _required(
            part,
            rf"Receita Tributada Total:\s*({MONEY})\s+Al[^:\r\n]*:\s*({NUMBER})\s+Simples Nacional Total:\s*({MONEY})",
            "segregação da apuração",
        )
        annex = _required(part, r"Anexo:\s*Anexo\s+([IVX]+)", "anexo").group(1)
        table = _required(part, r"Tabela:\s*([^\r\n]+)", "tabela").group(1).strip()
        portions.append({
            "annex": annex,
            "table": table,
            "revenue": float(_decimal(match.group(1))),
            "effectiveRate": float(_decimal(match.group(2)) / 100),
            "calculatedAmount": float(_decimal(match.group(3))),
        })
    if not portions:
        raise ValueError("Segregações da apuração não encontradas no PDF do Domínio")
    return portions


def parse_simples_pages(pages: list[str], expected_period: str | None) -> tuple[dict, str, dict, list[str]]:
    candidates = [page for page in pages if "Receita Tributada Total:" in page and "Simples Nacional a recolher:" in page]
    if not candidates:
        raise ValueError("Página principal da apuração não encontrada no PDF do Domínio")
    selected = None
    for page in candidates:
        try:
            period = _period(page)
        except ValueError:
            continue
        if expected_period is None or period == expected_period:
            selected = page
            break
    if selected is None:
        raise ValueError(f"O PDF do Domínio não contém apuração da competência {expected_period}")
    company = _identity(selected)
    period = _period(selected)
    current = _decimal(_required(selected, rf"Regime de Compet[^\r\n]*?\s+({MONEY})", "receita do período").group(1))
    rbt12 = _decimal(_required(selected, rf"\(RBT12\)\s+({MONEY})", "RBT12").group(1))
    total = _decimal(_required(selected, rf"Simples Nacional a recolher:\s*({MONEY})", "valor da apuração").group(1))
    portions = _apportionment(selected)
    warnings: list[str] = []
    if sum((Decimal(str(item["revenue"])) for item in portions), Decimal(0)) != current:
        warnings.append("A soma das receitas segregadas não coincide com a receita da apuração.")
    if abs(sum((Decimal(str(item["calculatedAmount"])) for item in portions), Decimal(0)) - total) > Decimal("0.01"):
        warnings.append("A soma dos valores segregados não coincide com o total da apuração.")
    values = {
        "revenue": {"currentPeriod": float(current), "rbt12": float(rbt12)},
        "simples": {
            "annexes": list(dict.fromkeys(item["annex"] for item in portions)),
            "calculatedAmount": float(total),
            "effectiveRate": portions[0]["effectiveRate"] if len(portions) == 1 else None,
            "segments": portions,
        },
    }
    return company, period, values, warnings


def parse_monthly_pages(pages: list[str], expected_period: str | None) -> tuple[dict, str, dict, list[str]]:
    candidates = [page for page in pages if "DEMONSTRATIVO MENSAL" in page]
    if not candidates:
        raise ValueError("Página do Demonstrativo Mensal não encontrada no PDF do Domínio")
    page = candidates[0]
    company = _identity(page)
    match = _required(page, r"Per[^:\r\n]{1,10}:\s*\d{2}/(\d{2})/(\d{4})\s+a\s+\d{2}/\d{2}/\d{4}", "período")
    period = f"{match.group(2)}-{match.group(1)}"
    if expected_period is not None and period != expected_period:
        raise ValueError(f"Demonstrativo Mensal da competência {period}; esperado {expected_period}")
    month = MONTHS[int(match.group(1)) - 1]
    row = _required(page, rf"^\s*{month}\s+{match.group(2)}\s+({MONEY})\s+({MONEY})\s+({MONEY})", "linha mensal", re.IGNORECASE | re.MULTILINE)
    entries, sales, services = (_decimal(value) for value in row.groups())
    values = {
        "revenue": {"currentPeriod": float(sales + services)},
        "monthly": {"entries": float(entries), "sales": float(sales), "services": float(services)},
    }
    return company, period, values, []


def parse_pdf(path: Path, document_type: DocumentType, expected_period: str | None) -> tuple[dict, str, dict, list[str]]:
    reader = PdfReader(path)
    if reader.is_encrypted:
        raise ValueError("PDF protegido por senha")
    pages = [page.extract_text(extraction_mode="layout") or "" for page in reader.pages]
    if document_type == DocumentType.SIMPLES_APURACAO:
        return parse_simples_pages(pages, expected_period)
    if document_type == DocumentType.FATURAMENTO_SIMPLES:
        return parse_monthly_pages(pages, expected_period)
    if document_type == DocumentType.RESUMO_ACUMULADORES:
        return parse_summary_pages(pages, expected_period)
    if document_type == DocumentType.PGDAS_EXTRATO:
        return parse_pgdas_pages(pages, expected_period)
    if document_type == DocumentType.DAS_GUIA:
        return parse_das_pages(pages, expected_period)
    raise ValueError("Tipo de PDF sem layout validado")


def _summary_classification(section: str, description: str) -> str:
    label = description.upper()
    if "DEVOLU" in label and "COMPR" in label:
        return "purchase_return"
    if "DEVOLU" in label and ("VENDA" in label or "REVEND" in label):
        return "sales_return"
    if section == "ENTRADAS":
        return "entry"
    if "REVENDA" in label or label.startswith("VENDA") or "PRESTACAO DE SERV" in label:
        return "revenue"
    return "unclassified"


def parse_summary_pages(pages: list[str], expected_period: str | None) -> tuple[dict, str, dict, list[str]]:
    candidates = [page for page in pages if "RESUMO POR ACUMULADOR" in page]
    if not candidates:
        raise ValueError("Pagina do Resumo por Acumulador nao encontrada")
    entries: list[dict] = []
    totals: dict[str, Decimal] = {}
    company: dict[str, str] | None = None
    period: str | None = None
    warnings: list[str] = []
    for page in candidates:
        lines = [line.strip() for line in page.splitlines() if line.strip()]
        cnpj = _required(page, rf"CNPJ:\s*({CNPJ})", "CNPJ").group(1)
        name = re.split(r"\s{2,}", lines[0], maxsplit=1)[0].strip()
        page_company = {"id": re.sub(r"\D", "", cnpj), "name": name, "document": cnpj}
        dates = _required(page, r"Per[^:\r\n]{1,10}:\s*(\d{2})/(\d{2})/(\d{4})\s+[^\d\r\n]+\s+(\d{2})/(\d{2})/(\d{4})", "periodo")
        page_period = f"{dates.group(3)}-{dates.group(2)}"
        if (dates.group(2), dates.group(3)) != (dates.group(5), dates.group(6)):
            raise ValueError("Resumo por Acumulador abrange mais de uma competencia")
        if expected_period is not None and page_period != expected_period:
            raise ValueError(f"Resumo por Acumulador da competencia {page_period}; esperado {expected_period}")
        if company is not None and company["id"] != page_company["id"]:
            raise ValueError("Resumo por Acumulador contem empresas diferentes")
        company, period = page_company, page_period
        section = None
        for line in lines:
            if line == "ENTRADAS":
                section = "ENTRADAS"
                continue
            if re.fullmatch(r"SA.DAS", line):
                section = "SAIDAS"
                continue
            if section is None:
                continue
            total_match = re.match(rf"Total:\s*({MONEY})", line)
            if total_match:
                totals[section] = _decimal(total_match.group(1))
                section = None
                continue
            row = re.match(rf"^((?:\d+\s+)+)(.*?)({MONEY})(?=\s|$)", line)
            if not row:
                continue
            codes = re.findall(r"\d+", row.group(1))
            code = codes[-1]
            description = row.group(2).strip()
            if not description:
                continue
            entries.append({
                "code": code,
                "description": description,
                "section": section,
                "amount": float(_decimal(row.group(3))),
                "classification": _summary_classification(section, description),
            })
    if not entries or company is None or period is None:
        raise ValueError("Acumuladores nao encontrados no resumo")
    for section in ("ENTRADAS", "SAIDAS"):
        if section not in totals:
            raise ValueError(f"Total de {section.lower()} nao encontrado no resumo")
        listed = sum((Decimal(str(item["amount"])) for item in entries if item["section"] == section), Decimal(0))
        if listed != totals[section]:
            warnings.append(f"A soma das linhas de {section.lower()} nao coincide com o total do resumo.")
    unclassified = [item["code"] for item in entries if item["classification"] in {"unclassified", "sales_return"}]
    if unclassified:
        warnings.append(f"Saidas que exigem revisao do faturamento: {', '.join(unclassified)}.")
    revenue = sum((Decimal(str(item["amount"])) for item in entries if item["classification"] == "revenue"), Decimal(0))
    purchase_returns = sum((Decimal(str(item["amount"])) for item in entries if item["classification"] == "purchase_return"), Decimal(0))
    values = {
        "revenue": {"currentPeriod": float(revenue)},
        "accumulators": entries,
        "accumulatorSummary": {
            "entriesTotal": float(totals["ENTRADAS"]),
            "outgoingTotal": float(totals["SAIDAS"]),
            "purchaseReturns": float(purchase_returns),
        },
    }
    return company, period, values, warnings


def parse_pgdas_pages(pages: list[str], expected_period: str | None) -> tuple[dict, str, dict, list[str]]:
    first = next((page for page in pages if "Extrato do Simples Nacional" in page), None)
    if first is None:
        raise ValueError("Extrato do PGDAS-D nao encontrado")
    name = _required(first, r"Nome Empresarial:\s*([^\r\n]+)", "nome empresarial").group(1).strip()
    name = re.split(r"\s{2,}", name, maxsplit=1)[0].strip()
    cnpj = _required(first, rf"CNPJ Estabelecimento:\s*({CNPJ})", "CNPJ do estabelecimento").group(1)
    period_match = _required(first, r"\(PA\):\s*(\d{2})/(\d{4})", "competencia")
    period = f"{period_match.group(2)}-{period_match.group(1)}"
    if expected_period is not None and period != expected_period:
        raise ValueError(f"Extrato do PGDAS-D da competencia {period}; esperado {expected_period}")
    current = _decimal(_required(first, rf"Receita Bruta do PA \(RPA\)[^\r\n]*?({MONEY})", "receita do PGDAS-D").group(1))
    rbt12 = _decimal(_required(first, rf"Receita bruta acumulada nos doze meses anteriores ao PA\s+({MONEY})", "RBT12 do PGDAS-D").group(1))
    das_page = next((page for page in pages if "Principal" in page and "Total" in page and "INSS/CPP" in page), None)
    if das_page is None:
        raise ValueError("Total do DAS nao encontrado no extrato do PGDAS-D")
    total = _decimal(_required(das_page, rf"Principal\s+{MONEY}\s+Multa\s+{MONEY}\s+Juros\s+{MONEY}\s+Total\s+({MONEY})", "total do DAS no PGDAS-D").group(1))
    company = {"id": re.sub(r"\D", "", cnpj), "name": name, "document": cnpj}
    return company, period, {"revenue": {"currentPeriod": float(current), "rbt12": float(rbt12)},
                             "simples": {"calculatedAmount": float(total)}}, []


def parse_das_pages(pages: list[str], expected_period: str | None) -> tuple[dict, str, dict, list[str]]:
    first = next((page for page in pages if "Documento de Arrecada" in page), None)
    if first is None:
        raise ValueError("Guia DAS nao encontrada")
    match = _required(first, rf"^\s*({CNPJ})\s+([^\r\n]+)", "empresa na guia DAS", re.MULTILINE)
    cnpj, name = match.group(1), match.group(2).strip()
    period_match = _required(first, r"(?m)^\s*(0[1-9]|1[0-2])/(\d{4})\s*$", "competencia da guia DAS")
    period = f"{period_match.group(2)}-{period_match.group(1)}"
    if expected_period is not None and period != expected_period:
        raise ValueError(f"Guia DAS da competencia {period}; esperado {expected_period}")
    total = _decimal(_required(first, rf"Valor Total do Documento\s+({MONEY})", "valor da guia DAS").group(1))
    company = {"id": re.sub(r"\D", "", cnpj), "name": name, "document": cnpj}
    return company, period, {"simples": {"calculatedAmount": float(total)}}, []
