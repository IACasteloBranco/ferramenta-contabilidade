# Conferência de Apurações do Simples

Aplicação local para acelerar a conferência em lote de relatórios de apuração do Simples Nacional gerados pelo Domínio. O operador informa a pasta raiz de uma competência, e o sistema organiza as empresas em três grupos:

- **Sem exceções detectadas:** priorizadas para a revisão final e entrega pela equipe.
- **Fila de revisão:** divergências objetivas, com valores e relatórios de origem.
- **Erros de processamento:** relatórios que não permitiram uma análise confiável.

O sistema não recalcula tributos, não substitui o Domínio e não certifica que uma apuração está fiscalmente correta. “Sem exceções detectadas” descreve somente as regras executadas sobre os relatórios disponíveis.

## O que a interface faz

A tela foi organizada para a rotina de fechamento do Simples Nacional:

- **Contextualização do processo:** a abertura explica o papel do DAS — a guia única de arrecadação do Simples — e por que a conferência dos relatórios antes da entrega importa.
- **Análise por competência:** informe uma pasta raiz; o sistema identifica as empresas e os relatórios disponíveis em cada subpasta.
- **Priorização por exceção:** o resultado separa empresas sem exceções detectadas, empresas para revisar e erros de processamento, com contadores no topo da tela.
- **Evidências de revisão:** cada empresa da fila pode ser expandida para consultar a regra apontada, valores esperado e encontrado, fontes e avisos de extração.
- **Resultado exportável:** o lote pode ser baixado como JSON estruturado para registro ou integração posterior.

A interface usa uma identidade visual em tons pastéis de verde para distinguir a área de conferência e deixar os estados do lote mais fáceis de percorrer. A conclusão da entrega e a responsabilidade técnica continuam sendo da equipe contábil.

### Como a conferência se relaciona com a apuração

O DAS é emitido a partir da apuração do Simples Nacional, que considera as receitas da competência e os parâmetros aplicáveis à empresa. Esta ferramenta não emite DAS nem recalcula os tributos: ela compara valores e informações extraídos dos relatórios de apuração, faturamento e acumuladores. Assim, divergências e documentos ausentes chegam à revisão humana antes da etapa de geração ou entrega da guia.

## Interface

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
./scripts/start-ui.sh
```

Abra http://127.0.0.1:8501, informe o diretório da competência e selecione **Analisar relatórios**.

A estrutura para várias empresas é:

```text
/dados/dominio/2026-08/
  001_EMPRESA_A/
    simples_apuracao.pdf
    faturamento_simples.pdf
    resumo_acumuladores.pdf
```

Para uma única empresa, também é possível informar diretamente a pasta que contém os PDFs e preencher a competência na tela. Os nomes `Simples Nacional.pdf` e `Demonstrativo Mensal.pdf`, usados pelo Domínio, são reconhecidos. O primeiro fornece receita, RBT12, anexos, segregações e valor apurado; o segundo fornece saídas e serviços do mês. O `Resumo por Acumulador.pdf` continua pendente de validação de layout, portanto sua ausência leva a empresa à fila de revisão. Extrato do PGDAS-D e guia DAS ainda não participam das regras automáticas.

## Linha de comando

```bash
npm run assess -- --input fixtures/dominio-batch/2026-08 --output output/simples-2026-08.json
```

O JSON de saída contém a competência, resumo, situação por empresa, findings, valores usados, fontes, hashes e avisos de extração.

## Testes

```bash
.venv/bin/python -m unittest discover -s tests -v
npm test
```

## Próxima etapa

Validar o leitor com outros PDFs do Domínio e implementar o layout do Resumo por Acumulador quando houver amostra. Veja o checklist em [DOMINIO_BATCH_ASSESSMENT.md](docs/DOMINIO_BATCH_ASSESSMENT.md).

O pipeline sintético anterior de NF-e foi preservado no código para referência e testes, mas não é exposto pela interface desta versão.
