# 2. Base de Conhecimento

## Princípio: tudo que o agente pode dizer tem um endereço

Cada informação recuperável carrega um `id` e uma `fonte`. Não é enfeite: é o
que permite a métrica de *groundedness* verificar depois se a resposta está
ancorada, e o que permite a pessoa perguntar "de onde você tirou isso?".

Formato da citação: `arquivo#id` — por exemplo `data/faq.json#FAQ-004` ou
`data/produtos_financeiros.json#PROD-002`.

## As cinco fontes

| Arquivo | Formato | Registros | O que contém |
| --- | --- | --- | --- |
| `data/transacoes.csv` | CSV | 285 lançamentos | 6 meses de extrato (fev–jul/2026) |
| `data/perfil_investidor.json` | JSON | 1 cliente | Perfil, suitability, objetivos, restrições, reserva |
| `data/produtos_financeiros.json` | JSON | 8 produtos | Catálogo com risco, liquidez, carência, tributação |
| `data/historico_atendimento.csv` | CSV | 10 atendimentos | Contatos anteriores e status de resolução |
| `data/faq.json` | JSON | 15 verbetes | Conceitos financeiros e limites do agente |

Todos os dados são **fictícios**, gerados para o desafio. Nenhuma informação
real de pessoa alguma foi usada.

### `transacoes.csv`

Colunas: `id_transacao, data, descricao, categoria, tipo, valor, canal`.

Gerado por `data/gerar_dados.py` com semente fixa, então o CSV é reprodutível:
rodar o script de novo devolve exatamente o mesmo arquivo. A base não é aleatória
— ela conta uma história que o agente precisa conseguir enxergar:

| Padrão embutido | Como aparece nos dados | O que o agente deve detectar |
| --- | --- | --- |
| Orçamento no vermelho | Despesa média de R$ 7.800,01 contra renda de R$ 6.800,00 | Déficit de R$ 1.000,01 por mês |
| Déficit em todos os 6 meses | Saldo negativo de fev a jul | Não é um mês ruim, é um padrão |
| Assinaturas se acumulando | 3 assinaturas em fevereiro, 6 em julho | R$ 249,49/mês, R$ 2.993,88/ano |
| Rotativo entrando em cena | Juros lançados a partir de maio/2026 | Dívida estimada de R$ 2.425,38 |
| Reserva insuficiente | R$ 9.200 para uma meta de R$ 24.600 | Cobre 2,2 dos 6 meses de custo fixo |

O encadeamento é proposital: o déficit mensal alimenta o rotativo, o rotativo
consome a sobra que iria para a reserva, e a reserva insuficiente é o que faz o
próximo imprevisto virar mais dívida. É esse ciclo que o agente precisa
conseguir explicar.

### `perfil_investidor.json`

Além do óbvio (perfil moderado, renda, objetivos), traz dois campos que o
agente **usa como restrição dura** na hora de listar produtos:

```json
"restricoes": {
  "aceita_renda_variavel": true,
  "percentual_maximo_renda_variavel": 20,
  "aceita_produtos_com_carencia": false
}
```

Por causa de `aceita_produtos_com_carencia: false`, a LCI (carência de 90 dias)
nunca aparece como elegível — e o agente diz por quê. Há teste cobrindo isso
(`test_produto_com_carencia_e_bloqueado`).

### `produtos_financeiros.json`

Oito produtos, incluindo dois de **crédito** (rotativo e portabilidade) que
existem para o agente conseguir comparar o custo de uma dívida. Eles são
filtrados fora de qualquer lista de aplicação — crédito não é investimento, e há
teste garantindo isso.

O bloco `_meta.indexadores_referencia` guarda CDI, Selic e IPCA da data de
referência, para que as simulações tenham lastro declarado.

### `faq.json`

Quinze verbetes conceituais com `tags` para reforçar a recuperação. Três deles
não são sobre finanças, e sim sobre os limites do próprio agente — FAQ-012 (por
que não indica ações) e FAQ-015 (como trata dados pessoais). Isso faz o agente
conseguir explicar a própria recusa em vez de só recusar.

## Como a base vira contexto recuperável

`kb.py` transforma produtos, verbetes e atendimentos em objetos `Documento`
uniformes:

```python
@dataclass(frozen=True)
class Documento:
    id: str          # FAQ-004, PROD-002, AT0009
    titulo: str
    texto: str
    fonte: str       # data/faq.json#FAQ-004
    tipo: str        # conceito | produto | atendimento
    metadados: dict
```

Total: **33 documentos** — 15 conceitos, 8 produtos, 10 atendimentos.

As transações ficam de fora do índice textual de propósito: 285 linhas de
extrato não são recuperadas por similaridade, são **agregadas por cálculo**.
Perguntar "quanto gastei com alimentação" não deve retornar as linhas mais
parecidas com a pergunta; deve somar as linhas da categoria.

## Estratégia de recuperação

TF-IDF com similaridade de cosseno, escrito à mão em `retriever.py`, sem
dependências. Com 33 documentos, um índice vetorial seria peso morto.

**Pré-processamento:** minúsculas, remoção de acentos, remoção de pontuação,
stopwords do português, stemming leve de plural. Título e tags entram
duplicados no índice para pesar mais que o corpo do texto.

**Dois índices:**

- `indice` — todos os 33 documentos.
- `indice_conceitos` — só os 15 verbetes. Perguntas de definição consultam este,
  para que "o que é liquidez" não recupere a ficha técnica de um produto.

**Três portões antes de um trecho virar contexto:**

| Portão | Limiar | Pergunta que responde |
| --- | --- | --- |
| Score de similaridade | ≥ 0,12 | Tem alguma relação? |
| Cobertura | ≥ 0,50 | O documento cobre a maior parte dos termos da pergunta? |
| Especificidade | ≤ 0,35 | O casamento veio de algum termo discriminativo? |

O caso que motivou os dois últimos portões: *"Qual é a taxa de câmbio do iene
hoje?"* casa com o verbete de CDI com score 0,32 — alto o suficiente para passar
pelo limiar de similaridade — mas apenas pela palavra genérica "taxa". A
cobertura expõe o problema: 1 termo casado de 4 (0,25), abaixo do limiar. O
agente se abstém, que é a resposta correta.

Perguntas legítimas do conjunto de avaliação ficam com cobertura de 0,75 ou
mais. A separação é limpa.

## Manutenção

Para adaptar a outro domínio:

1. Troque os arquivos em `data/` mantendo os campos `id` e `fonte`.
2. Ajuste `CATEGORIAS_CONHECIDAS` e `REGRAS` em `intent.py`.
3. Reescreva os cálculos de `financas.py` para o domínio novo.
4. Atualize `eval/dataset.json` e rode `python eval/run_eval.py`.

O passo 4 não é opcional: sem ele não há como saber se a troca melhorou ou
piorou o agente.
