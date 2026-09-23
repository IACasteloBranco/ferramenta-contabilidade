"""Tela única da conferência por exceção de apurações do Simples."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from fiscal_engine.assessment.service import assess_batch


def _html(markup: str) -> str:
    """Mantém textos HTML legíveis mesmo quando o navegador erra a codificação."""
    return markup.encode("ascii", "xmlcharrefreplace").decode("ascii")


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _company_rows(companies: list[dict]) -> list[dict]:
    return [
        {
            "Empresa": item["company"]["name"],
            "CNPJ": item["company"].get("document") or "—",
            "Motivos": "; ".join(finding["code"] for finding in item["findings"]) or "Nenhuma exceção detectada",
        }
        for item in companies
    ]


def _details(companies: list[dict]) -> None:
    for item in companies:
        with st.expander(item["company"]["name"]):
            summary_values = item["assessment"]["source_values"].get("RESUMO_ACUMULADORES", {})
            summary = summary_values.get("accumulatorSummary")
            if summary:
                st.write({
                    "Saídas totais": _money(summary.get("outgoingTotal")),
                    "Devolução de compras": _money(summary.get("purchaseReturns")),
                    "Vendas consideradas": _money(summary_values.get("revenue", {}).get("currentPeriod")),
                })
            for finding in item["findings"]:
                st.markdown(f"**{finding['code']}** — {finding['message']}")
                if finding["expected"] is not None or finding["actual"] is not None:
                    st.write({"Esperado": finding["expected"], "Encontrado": finding["actual"], "Fontes": finding["sources"]})
            st.caption("Dados e relatórios usados na análise")
            st.json({
                "sources": item["assessment"]["sources"],
                "source_values": item["assessment"]["source_values"],
                "warnings": item["assessment"]["extraction"]["warnings"],
            })


def simples_assessment_page(fixtures: Path) -> None:
    st.markdown(_html(
        """
        <section class="hero" aria-label="Apresentação da conferência">
          <div class="hero-copy">
            <p class="hero-context">Conferência de apurações do Simples Nacional</p>
            <h1>Antes do DAS, veja onde a competência pede atenção.</h1>
            <p>Leia os relatórios do Domínio de todas as empresas de uma vez, encontre divergências objetivas e deixe a revisão humana apenas para o que realmente precisa dela.</p>
          </div>
          <aside class="hero-ledger" aria-label="Como a conferência funciona">
            <p class="ledger-title">Leitura do lote</p>
            <div class="ledger-step"><strong>1</strong><span>Localize os relatórios da competência.</span></div>
            <div class="ledger-step"><strong>2</strong><span>Compare os valores e documentos disponíveis.</span></div>
            <div class="ledger-step"><strong>3</strong><span>Direcione somente as exceções para revisão.</span></div>
          </aside>
        </section>
        """),
        unsafe_allow_html=True,
    )
    st.markdown(_html(
        """
        <section class="explainer">
          <h2>Uma pausa de conferência antes da entrega.</h2>
          <p>O DAS reúne em uma única guia os tributos da empresa no Simples. Sua apuração parte das receitas e das informações da competência. Esta ferramenta não emite a guia nem recalcula impostos: ela compara os relatórios de apuração, faturamento e acumuladores para tornar visíveis divergências e ausências que merecem uma decisão da equipe contábil.</p>
        </section>
        """),
        unsafe_allow_html=True,
    )
    st.info("A ferramenta verifica a consistência entre os relatórios disponíveis; ela não recalcula tributos, não substitui o Domínio e não certifica a apuração tributária.")

    st.markdown(_html('<h2 class="section-heading">Comece por uma competência</h2><p class="section-intro">Informe a pasta que contém uma subpasta para cada empresa do lote.</p>'), unsafe_allow_html=True)
    with st.form("assessment_input"):
        path_value = st.text_input(
            "Diretório raiz da competência",
            value=str(fixtures),
            help="Ex.: /dados/dominio/2026-08. Cada empresa deve ficar em sua própria subpasta.",
        )
        period_value = st.text_input("Competência (AAAA-MM)", value=fixtures.name)
        st.caption("Relatórios necessários: Simples Nacional, Demonstrativo Mensal e Resumo por Acumulador. O extrato do PGDAS-D e a guia DAS são opcionais, para conferência após a transmissão. Para várias empresas, use uma subpasta por empresa.")
        submitted = st.form_submit_button("Analisar relatórios", type="primary")
    if submitted:
        try:
            st.session_state["simples_batch"] = assess_batch(Path(path_value), period_value)
            st.session_state["simples_path"] = path_value
        except (OSError, ValueError, TypeError) as exc:
            st.error(f"Não foi possível analisar a pasta: {exc}")
            return

    result = st.session_state.get("simples_batch")
    if not result:
        st.markdown(_html("<div class='quiet-state'><strong>Ainda não há uma análise nesta tela.</strong><br>Use as fixtures para experimentar o fluxo ou informe a pasta com os relatórios do Domínio.</div>"), unsafe_allow_html=True)
        return

    summary = result["summary"]
    st.subheader(f"Competência {result['period']}")
    a, b, c, d = st.columns(4)
    a.metric("Empresas processadas", summary["total"])
    b.metric("Sem exceções detectadas", summary["withoutExceptions"])
    c.metric("Para revisar", summary["review"])
    d.metric("Erro de processamento", summary["errors"])

    ready = [item for item in result["companies"] if item["status"] == "SEM_EXCECOES"]
    review = [item for item in result["companies"] if item["status"] == "REVISAR"]
    errors = [item for item in result["companies"] if item["status"] == "ERRO"]

    st.subheader("Sem exceções detectadas · priorizar entrega")
    st.caption("Estes relatórios não tiveram exceções nas regras executadas. A decisão de entrega continua sendo da equipe responsável.")
    st.dataframe(_company_rows(ready), hide_index=True, width="stretch")
    _details(ready)

    st.subheader("Fila de revisão")
    if review:
        st.dataframe(_company_rows(review), hide_index=True, width="stretch")
        _details(review)
    else:
        st.caption("Nenhuma empresa entrou na fila de revisão.")

    st.subheader("Erros de processamento")
    if errors:
        st.dataframe(_company_rows(errors), hide_index=True, width="stretch")
        _details(errors)
    else:
        st.caption("Nenhum erro de processamento.")

    st.download_button(
        "Baixar resultado estruturado JSON",
        json.dumps(result, ensure_ascii=False, indent=2),
        file_name=f"simples-{result['period']}.json",
        mime="application/json",
    )
