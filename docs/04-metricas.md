# 4. Avaliação e Métricas

## Como rodar

```bash
python eval/run_eval.py              # resumo no terminal
python eval/run_eval.py --falhas     # detalha os casos reprovados
python eval/run_eval.py --relatorio  # grava eval/relatorio.md
python -m unittest discover -s tests # 46 testes unitários
```

O harness sai com código 1 se houver qualquer caso reprovado, então serve
direto em CI.

## O que é medido, e por quê

Para um agente financeiro, "a resposta é boa?" é vago demais para orientar
correção. O conjunto foi quebrado em seis perguntas objetivas:

| Métrica | Definição | Por que importa |
| --- | --- | --- |
| **Acurácia de intenção** | A pergunta caiu na rota correta? | Rota errada gera resposta que soa plausível mas responde outra coisa — o erro mais difícil de perceber |
| **Cobertura de termos** | A resposta contém a informação-chave esperada? | Uma resposta pode ser tecnicamente correta e inútil por omitir o número que a pessoa pediu |
| **Precisão de citação** | A resposta cita as fontes que deveria? | Sem citação a pessoa não tem como conferir |
| **Groundedness** | Todo valor em reais citado existe nos fatos calculados? | É a métrica anti-alucinação. Um número inventado em contexto financeiro leva a decisão errada |
| **Recusa correta** | Pedidos fora de escopo e de dado sensível foram barrados? | Fronteira regulatória e de segurança |
| **Abstenção correta** | Perguntas fora da base receberam "não sei"? | Saber não saber é requisito, não defeito |

Complementarmente: **latência** (p50/p95) e **ausência de promessa indevida**.

## O conjunto de avaliação

38 casos em `eval/dataset.json`, distribuídos por 12 grupos:

| Grupo | Casos | O que exercita |
| --- | --- | --- |
| `analise_gastos` | 5 | Resumo geral e por categoria |
| `conceito` | 6 | Definições vindas do FAQ |
| `fora_de_escopo` | 4 | Ativo, previsão, promessa, ilícito |
| `assinaturas` | 3 | Detecção de cobrança recorrente |
| `reserva` | 3 | Diagnóstico e prazo para meta |
| `produtos` | 3 | Filtro por perfil e restrição |
| `divida` | 3 | Custo do rotativo e portabilidade |
| `fora_da_base` | 3 | Abstenção |
| `conversa` | 3 | Saudação, capacidades, despedida |
| `seguranca` | 2 | Senha e número de cartão |
| `simulacao` | 2 | Juros compostos |
| `atendimento` | 1 | Histórico de contatos |

Cada caso declara: intenção esperada, se deve abster, se deve recusar, termos
que precisam aparecer na resposta e fontes que precisam ser citadas. Um caso só
é aprovado se passar em **todas** as checagens aplicáveis.

## Resultado da última execução

Modo determinístico, 38 casos, `eval/relatorio.md` gerado em 04/08/2026:

| Métrica | Resultado |
| --- | --- |
| Taxa de aprovação | 100,0% (38/38) |
| Acurácia de intenção | 100,0% |
| Cobertura de termos | 100,0% |
| Precisão de citação | 100,0% |
| Groundedness | 100,0% |
| Ausência de promessa indevida | 100,0% |
| Recusa correta | 100,0% |
| Abstenção correta | 100,0% |
| Latência p50 | 0,27 ms |
| Latência p95 | 0,48 ms |

## Leitura honesta desses números

**100% aqui não significa "agente perfeito".** Significa "o agente passa nos 38
casos que eu escrevi". Três ressalvas que importam mais que o número:

**1. Este é um conjunto de desenvolvimento, não de teste cego.** Vários casos
falharam na primeira execução e o código foi corrigido para passar — o que é
exatamente o uso pretendido de um conjunto de desenvolvimento, mas significa que
o resultado mede "não regrediu nos casos conhecidos", não "generaliza para
perguntas novas". Para afirmar generalização seria preciso um segundo conjunto,
escrito depois do código congelado, nunca consultado durante o desenvolvimento.

**2. A latência sub-milissegundo é do modo determinístico.** Não há chamada de
rede. Com LLM real a latência sobe para a casa de segundos e passa a depender do
provedor. O número que está aqui mede o custo do roteamento e do cálculo, que é
o que o projeto controla.

**3. Groundedness de 100% é parcialmente estrutural.** No modo determinístico os
números vêm de template preenchido com os fatos calculados, então é difícil eles
divergirem — a métrica está checando principalmente erros de formatação e de
sinal (e pegou um: ver histórico abaixo). O teste real da métrica acontece com
LLM ligado, onde ela vira o filtro que descarta redação inventada.

### O primeiro run, antes das correções

A execução inicial deu **86,8% (33/38)**, com 5 reprovações reais:

| Caso | Falha | Causa | Correção |
| --- | --- | --- | --- |
| EV-01, EV-02 | Groundedness | Resposta dizia "faltam R$ 1.000,01" mas o fato calculado era saldo de −1.000,01 | Validador passou a aceitar troca de sinal |
| EV-11 | Intenção | "Quanto eu preciso guardar" não casava com nenhum gatilho de reserva | Gatilho "preciso guardar" adicionado |
| EV-29 | Recusa | "Investimento com retorno garantido" — o regex só cobria "garantido retorno" | Regex passou a cobrir as duas ordens |
| EV-34 | Abstenção | "Taxa de câmbio do iene" recuperava o verbete de CDI pela palavra "taxa" | Portões de cobertura e especificidade |

O caso EV-34 foi o mais instrutivo: o score de similaridade era 0,32, alto o
bastante para parecer uma recuperação legítima. Foi preciso inventar duas
métricas novas de recuperação para separar. Está documentado em
`docs/02-base-conhecimento.md`.

## Suíte de testes

46 testes em `tests/test_bussola.py`, só biblioteca padrão:

| Bloco | Testes | Cobre |
| --- | --- | --- |
| `TestFormatacao` | 3 | Formatação de real e percentual no padrão brasileiro |
| `TestBaseConhecimento` | 4 | Carregamento, unicidade de id, presença de fonte |
| `TestCalculosFinanceiros` | 16 | Aritmética, restrições de perfil, coerência interna |
| `TestRetriever` | 5 | Tokenização, recuperação, cobertura |
| `TestClassificadorDeIntencao` | 5 | Tabela de rotas, fora de escopo, extração de entidades |
| `TestGuardrails` | 6 | Ancoragem, promessas, citação |
| `TestAgenteFimAFim` | 7 | Abstenção, recusa, citação, determinismo |

Dois testes merecem destaque:

**`test_juros_compostos_bate_com_a_formula_fechada`** — compara a iteração mês a
mês com `C × (1+i)ⁿ`. Verifica a matemática contra uma referência externa ao
código, não contra ela mesma.

**`test_todo_valor_citado_esta_ancorado`** — roda as 38 perguntas do dataset e
verifica que nenhum valor monetário da resposta está fora dos fatos calculados.
É o teste de regressão do requisito central do projeto.

## O que eu mediria a seguir

Em ordem de retorno sobre esforço:

1. **Conjunto de teste cego** — 30 perguntas novas, escritas por outra pessoa,
   nunca usadas durante o desenvolvimento. É o que falta para poder falar em
   generalização.
2. **Avaliação com LLM ligado** — medir com que frequência o guardrail de saída
   precisa descartar a redação do modelo. Essa taxa é a métrica mais informativa
   do projeto e hoje não tenho o número.
3. **Robustez a variação linguística** — parafrasear cada pergunta de 3 formas
   (com erro de digitação, informal, formal) e medir a queda na acurácia de
   intenção. É onde um classificador de palavras-chave mais sofre.
4. **Avaliação humana de utilidade** — as métricas atuais medem correção e
   segurança. Nenhuma mede se a resposta ajudou a pessoa a decidir algo.
