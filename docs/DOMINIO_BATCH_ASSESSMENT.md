# Conferência em lote de apurações do Simples Nacional

## Objetivo de negócio

O Fiscal Checker organiza a conferência de apurações já geradas pelo Domínio. Ele não substitui o cálculo tributário do Domínio e não declara que uma empresa está aprovada, correta ou fiscalmente conforme. A saída responde somente se os relatórios recebidos não tiveram exceções detectadas, se precisam de revisão humana ou se não permitiram análise confiável.

```text
Relatórios do Domínio
        ↓
Scanner de fontes → Adapter/extractor → Modelo normalizado → Motor de regras → Classificação
        ↓                                                                  ↓
   hashes, tipo, caminho, status                                      SEM_EXCECOES / REVISAR / ERRO
```

O pipeline é separado do fluxo existente de NF-e, que continua disponível para a conciliação sintética de documentos e escrituração.

## Uso

Execute as fixtures fornecidas:

```bash
npm run assess -- --input fixtures/dominio-batch/2026-08 --output output/simples-2026-08.json
```

Também é possível abrir a interface local e acessar **Apurações Simples**. A tela inicia com as fixtures e permite informar outra pasta da competência. A saída inclui a lista consolidada, os motivos, fontes, valores usados e um download JSON.

A estrutura de entrada para várias empresas é:

```text
input/
  2026-08/
    001_EMPRESA_A/
      simples_apuracao.pdf
      faturamento_simples.pdf
      resumo_acumuladores.pdf
```

Para o protótipo, os mesmos nomes também usam `.json` ou `.synthetic.json`. Cada JSON declara `document_type`, `company`, `period`, `data` e `extraction`. Para uma empresa, a pasta informada pode conter diretamente `Simples Nacional.pdf` e `Demonstrativo Mensal.pdf`; a competência deve ser informada na interface ou por `--period` na CLI. Arquivos de extrato PGDAS-D e guia DAS não entram nas regras atuais.

## Modelo normalizado

`CompanyTaxAssessment`, em `fiscal_engine/assessment/models.py`, contém:

- `company`: id, código, nome e documento quando disponíveis;
- `period`;
- `revenue`: faturamento do período, RBT12, devoluções e cancelamentos;
- `simples`: anexos, Fator R, valor calculado, alíquota efetiva única quando houver e `segments` para as diferentes segregações da apuração;
- `accumulators`;
- `sources`: tipo, caminho, momento do processamento, hash, status e avisos;
- `extraction`: estado consolidado e avisos;
- `source_values` e `field_sources`: valores preservados por relatório para tornar comparações rastreáveis.

Os tipos de relatório reconhecidos são `SIMPLES_APURACAO`, `FATURAMENTO_SIMPLES` e `RESUMO_ACUMULADORES`.

## Adaptadores

`AssessmentExtractor` é o contrato entre fonte e normalização. Os adaptadores atuais são:

| Adaptador | Uso |
| --- | --- |
| `SyntheticAssessmentExtractor` | Fixtures com extensão `.synthetic.json`. |
| `JsonAssessmentExtractor` | Contrato JSON de intercâmbio e testes. |
| `DominioPdfAssessmentExtractor` | Lê os layouts observados de `Simples Nacional.pdf` e `Demonstrativo Mensal.pdf`; outros layouts retornam falha explícita. |

As regras recebem somente `CompanyTaxAssessment`; elas não abrem arquivos nem dependem de PDFs. O adaptador de PDF produz o mesmo `PartialAssessment` usado pelos JSONs. A página de alíquota do período seguinte é ignorada na extração da competência solicitada. Cancelamentos e devoluções ausentes não são presumidos como zero.

## Regras e classificação

| Código | Situação | Fontes usadas |
| --- | --- | --- |
| `REVENUE_MISMATCH` | O faturamento de `SIMPLES_APURACAO` diverge de `FATURAMENTO_SIMPLES`. | Ambos os relatórios. |
| `RBT12_MISSING` | RBT12 ausente da apuração legível. | `SIMPLES_APURACAO`. |
| `UNKNOWN_ACCUMULATOR` | Código de acumulador fora do conjunto conhecido do protótipo. | `RESUMO_ACUMULADORES`. |
| `SOURCE_DOCUMENT_MISSING` | Falta um dos três relatórios obrigatórios. | Tipos esperados e recebidos. |
| `EXTRACTION_FAILED` | Um relatório não pôde ser extraído. | Fonte que falhou. |
| `CANCELLATION_MISMATCH` | Cancelamentos divergentes entre apuração e faturamento. | Ambos os relatórios. |

`EXTRACTION_FAILED` produz `ERRO`. Qualquer outra regra de severidade `warning` produz `REVISAR`. Sem findings relevantes, a situação é `SEM_EXCECOES`. Devoluções presentes e iguais nas fontes não geram finding por si só.

## Fixtures

`fixtures/dominio-batch/2026-08` contém oito empresas:

| Empresa | Resultado | Situação simulada |
| --- | --- | --- |
| A | `SEM_EXCECOES` | Faturamento, RBT12, acumuladores e valor da apuração disponíveis. |
| B | `REVISAR` | `REVENUE_MISMATCH`: 50.000 versus 57.500. |
| C | `REVISAR` | `RBT12_MISSING`. |
| D | `REVISAR` | `UNKNOWN_ACCUMULATOR`. |
| E | `REVISAR` | `SOURCE_DOCUMENT_MISSING`. |
| F | `ERRO` | `EXTRACTION_FAILED`. |
| G | `SEM_EXCECOES` | Devoluções presentes e consistentes. |
| H | `REVISAR` | `CANCELLATION_MISMATCH`. |

Por isso, o resultado demonstrável do conjunto completo é 8 empresas: 2 sem exceções detectadas, 5 para revisar e 1 erro. A distribuição diferente do exemplo conceitual da solicitação resulta da inclusão de todas as oito situações requeridas.

## Cobertura dos PDFs do Domínio

Os dois layouts observados são texto selecionável. O relatório `Simples Nacional.pdf` inclui apuração, memória de cálculo, listagem parcial de produtos, RBT12 e páginas do período seguinte. O `Demonstrativo Mensal.pdf` traz entradas, saídas e serviços; somente saídas e serviços formam a receita comparada pelo motor. A leitura foi validada com essa amostra de uma empresa, mas ainda precisa de variantes autorizadas para confirmar estabilidade de rótulos e paginação.

Antes de ampliar o leitor, validar com mais arquivos autorizados e representativos:

- texto selecionável ou imagem/OCR;
- posição, rótulos e estabilidade dos campos;
- cabeçalhos, tabelas, paginação e variações entre empresas;
- nome, CNPJ e competência;
- receita, RBT12, anexos, Fator R, alíquotas e valor calculado;
- acumuladores, devoluções e cancelamentos;
- se um mesmo relatório muda conforme regime, empresa ou versão do Domínio.

O layout do `Resumo por Acumulador` ainda precisa de amostra. Depois, mapear os códigos reais para o contrato JSON/`PartialAssessment` e adicionar fixtures extraídas de PDFs anonimizados. Não adicionar regras de cálculo tributário ao adaptador: ele só extrai fatos e sua origem.

## Limites atuais

- Os valores e acumuladores são sintéticos e os códigos conhecidos são apenas do protótipo.
- Não há consulta, autenticação ou escrita no Domínio, Thomson Reuters ou portais governamentais.
- A ausência de exception significa somente ausência de exceções nas regras executadas e relatórios disponíveis.
- Apenas os layouts observados de apuração e demonstrativo mensal são lidos; não há OCR nem conferência automática do extrato PGDAS-D ou da guia DAS.
