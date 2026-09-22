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
    cnpj = _required(text, r"CNPJ:\s*(\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2})", "CNPJ").group(1)
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
    raise ValueError("PDF de resumo por acumulador ainda não teve layout validado")
