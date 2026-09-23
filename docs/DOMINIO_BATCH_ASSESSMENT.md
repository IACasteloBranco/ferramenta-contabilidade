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

Os arquivos `.json` e `.synthetic.json` continuam disponíveis para demonstração. Para uma empresa, a pasta informada deve conter os três relatórios necessários do Domínio: Simples Nacional, Demonstrativo Mensal e Resumo por Acumulador. O scanner também reconhece o extrato do PGDAS-D e a guia DAS, caso já tenham sido gerados após a transmissão; eles são opcionais. O scanner reconhece os títulos mesmo com nomes genéricos; informe a competência na interface ou por `--period` na CLI.

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

Os tipos de relatório reconhecidos são `SIMPLES_APURACAO`, `FATURAMENTO_SIMPLES`, `RESUMO_ACUMULADORES`, `PGDAS_EXTRATO` e `DAS_GUIA`.

## Adaptadores

`AssessmentExtractor` é o contrato entre fonte e normalização. Os adaptadores atuais são:

| Adaptador | Uso |
| --- | --- |
| `SyntheticAssessmentExtractor` | Fixtures com extensão `.synthetic.json`. |
| `JsonAssessmentExtractor` | Contrato JSON de intercâmbio e testes. |
| `DominioPdfAssessmentExtractor` | Lê os três layouts necessários do Domínio e, opcionalmente, o extrato PGDAS-D e a guia DAS; devolve falha explícita para PDFs fora dos formatos validados. |

As regras recebem somente `CompanyTaxAssessment`; elas não abrem arquivos nem dependem de PDFs. O adaptador de PDF produz o mesmo `PartialAssessment` usado pelos JSONs. A página de alíquota do período seguinte é ignorada na extração da competência solicitada. Cancelamentos e devoluções ausentes não são presumidos como zero.

## Regras e classificação

| Código | Situação | Fontes usadas |
| --- | --- | --- |
| `REVENUE_MISMATCH` | O faturamento de `SIMPLES_APURACAO` diverge de `FATURAMENTO_SIMPLES`. | Ambos os relatórios. |
| `RBT12_MISSING` | RBT12 ausente da apuração legível. | `SIMPLES_APURACAO`. |
| `UNKNOWN_ACCUMULATOR` | Código textual não reconhecido nas fixtures; códigos numéricos do Domínio são preservados. | `RESUMO_ACUMULADORES`. |
| `SOURCE_DOCUMENT_MISSING` | Falta um dos três relatórios necessários do Domínio. | Tipos esperados e recebidos. |
| `EXTRACTION_FAILED` | Um relatório não pôde ser extraído. | Fonte que falhou. |
| `EXTRACTION_PARTIAL` | Um PDF tem linhas ou dados que exigem revisão da extração. | Fonte parcial. |
| `CANCELLATION_MISMATCH` | Cancelamentos divergentes entre apuração e faturamento. | Ambos os relatórios. |
| `ACCUMULATOR_REVENUE_MISMATCH`, `FATURAMENTO_ACUMULADORES_MISMATCH`, `ENTRIES_MISMATCH` | Comparam receita e entradas do Resumo por Acumulador aos outros relatórios Domínio. | Relatórios Domínio. |
| `PGDAS_REVENUE_MISMATCH`, `PGDAS_RBT12_MISMATCH`, `PGDAS_AMOUNT_MISMATCH`, `DAS_AMOUNT_MISMATCH` | Comparam receita, RBT12 e valor final com o extrato PGDAS-D e a guia DAS. | Domínio, PGDAS-D e DAS. |

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

## Cobertura dos PDFs

Os três layouts necessários do Domínio, além dos dois documentos opcionais, têm texto selecionável nas amostras observadas. O Resumo por Acumulador separa entradas e saídas por código; a receita considera as linhas de venda e não inclui devolução de compras. O relatório Simples Nacional contém páginas do período seguinte, que são ignoradas na extração da competência solicitada.

Antes de ampliar o leitor, validar com mais arquivos autorizados e representativos:

- texto selecionável ou imagem/OCR;
- posição, rótulos e estabilidade dos campos;
- cabeçalhos, tabelas, paginação e variações entre empresas;
- nome, CNPJ e competência;
- receita, RBT12, anexos, Fator R, alíquotas e valor calculado;
- acumuladores, devoluções e cancelamentos;
- se um mesmo relatório muda conforme regime, empresa ou versão do Domínio.

Os códigos numéricos de acumulador são preservados com descrição e valor. Linhas de saída sem classificação conhecida geram revisão; não se presume que componham faturamento. Validar mais amostras antes de ampliar as categorias.

## Limites atuais

- As fixtures JSON são sintéticas. O leitor PDF foi validado com uma empresa e uma competência; códigos de outros clientes podem ter descrições diferentes.
- Não há consulta, autenticação ou escrita no Domínio, Thomson Reuters ou portais governamentais.
- A ausência de exceções significa somente ausência de exceções nas regras executadas e relatórios disponíveis.
- Apenas os layouts observados dos três relatórios necessários e dos dois documentos opcionais são lidos; não há OCR nem recálculo tributário.
