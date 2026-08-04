# 5. Pitch

Roteiro para gravação de 3 minutos. Cada bloco tem tempo alvo e o que precisa
estar na tela.

---

## Bloco 1 — O problema (0:00 – 0:35)

**Tela:** gráfico do fluxo mensal da base, seis barras, todas negativas.

> A pessoa que mais precisa de orientação financeira é justamente a que menos
> tem acesso a ela. Consultoria personalizada é cara e costuma exigir patrimônio
> mínimo. O conteúdo gratuito é genérico e não olha para os dados de ninguém.
>
> No meio dessa lacuna acontece isto: [aponta o gráfico] seis meses seguidos
> gastando mais do que ganha. Não é um mês ruim, é um padrão. E quando o padrão
> se instala, entra o rotativo do cartão — a linha de crédito mais cara do
> mercado brasileiro, quase 15% ao mês.
>
> A pessoa não precisa de mais um conteúdo sobre educação financeira. Ela precisa
> de alguém que olhe para o extrato dela e explique o que está acontecendo.

---

## Bloco 2 — A solução (0:35 – 1:15)

**Tela:** interface do chat, pergunta "Tenho muitas assinaturas?" sendo digitada
e a resposta aparecendo.

> Essa é a Bússola. Ela lê os dados financeiros da pessoa e responde em
> linguagem natural sobre a situação dela.
>
> [resposta na tela] Seis assinaturas ativas, R$ 249,49 por mês, quase R$ 3.000
> por ano. E olha o detalhe: em fevereiro eram três. Elas foram entrando uma por
> uma, e nenhuma sozinha parecia cara.
>
> Repare no tom. Ela não disse "você está gastando demais". Descreveu o dado e
> ofereceu um caminho: cancelar o que está parado é a economia mais rápida
> porque não exige mudar hábito nenhum. Quem já se sente mal com a própria
> situação financeira não volta a conversar com um assistente que soa como uma
> repreensão.

---

## Bloco 3 — O diferencial (1:15 – 2:15)

**Tela:** diagrama de arquitetura, destacando o bloco "camada de cálculo
determinística".

> Aqui está a decisão de engenharia central do projeto: **o modelo de linguagem
> nunca toca em número.**
>
> Toda a matemática — somas, médias, juros compostos, custo da dívida — acontece
> em código Python testado. O LLM recebe os valores prontos e tem uma única
> tarefa: redigir. Ele não soma, não arredonda, não recalcula.
>
> Isso muda três coisas. Primeiro, auditabilidade: qualquer número da resposta
> pode ser reproduzido rodando a função correspondente. Segundo, toda resposta
> cita a fonte — o arquivo e o registro exatos de onde a informação veio.
>
> **Tela:** exemplo de recusa aparecendo no chat.
>
> Terceiro, o agente sabe quando calar a boca. Ele não indica ação, não prevê
> mercado, não promete rentabilidade. Se perguntarem algo fora da base, ele diz
> que não sabe em vez de inventar. E se alguém mandar uma senha no chat, ele
> interrompe e avisa sobre o risco — porque um assistente financeiro que aceita
> senha normalizado é o roteiro de um golpe.
>
> Tem ainda uma última rede: quando o LLM redige, a resposta passa por um
> validador que confere se todo valor citado existe nos fatos calculados.
> Reprovou, o texto do modelo é descartado e o template assume. A alucinação
> não chega no usuário.

---

## Bloco 4 — Prova e fechamento (2:15 – 3:00)

**Tela:** terminal rodando `python eval/run_eval.py`.

> E isso não é promessa, é medido. Trinta e oito casos de avaliação, seis
> métricas: acurácia de roteamento, ancoragem numérica, precisão de citação,
> recusa correta, abstenção correta e cobertura de informação. Mais 46 testes
> unitários.
>
> Na primeira execução passaram 33 de 38. As cinco falhas viraram cinco
> correções — inclusive uma que me obrigou a inventar duas métricas novas de
> recuperação, porque a similaridade sozinha achava que "taxa de câmbio do iene"
> era uma pergunta sobre CDI.
>
> Uma ressalva honesta: esse é um conjunto de desenvolvimento, não de teste
> cego. Ele prova que o agente não regride, não que ele generaliza. O próximo
> passo é escrever trinta perguntas novas que o código nunca viu.
>
> A Bússola roda sem nenhuma chave de API — clone e execute. Com uma chave de
> OpenAI ou Gemini, o mesmo contexto vai para o modelo, que só melhora a
> redação. Os fatos continuam vindo do mesmo lugar.
>
> Educação financeira que olha para o seu extrato, cita a fonte e admite o que
> não sabe. Obrigado.

---

## Checklist de gravação

- [ ] Testar o áudio antes; áudio ruim derruba pitch bom
- [ ] Deixar o Streamlit já rodando — não gravar tela de carregamento
- [ ] Cronometrar: 3 minutos passam rápido, o bloco 3 é o que costuma estourar
- [ ] Ter as perguntas já digitadas em um bloco de notas para copiar e colar
- [ ] Gravar em 1080p, fonte do terminal em tamanho legível

## Perguntas prováveis da banca

**"Por que não usar RAG com banco vetorial?"**
33 documentos. Um índice vetorial adicionaria dependência, tempo de subida e
uma peça a mais para dar errado, sem ganho mensurável nessa escala. TF-IDF com
cosseno resolve, roda em fração de milissegundo e cabe em um arquivo que dá para
ler inteiro. Em outra escala a resposta muda.

**"Por que o classificador de intenção não é o LLM?"**
Porque aí a mesma pergunta poderia cair em rotas diferentes entre execuções, e a
métrica de acurácia de roteamento perderia sentido. O custo é declarar os
desempates na mão; o ganho é que cada desempate virou caso de teste.

**"E se o usuário perguntar algo que você não previu?"**
Ele se abstém. Foi uma escolha: em contexto financeiro, "não sei" custa menos
que uma resposta plausível e errada. Três casos da avaliação testam exatamente
isso.

**"100% de aprovação não é suspeito?"**
É, e está documentado. O conjunto é de desenvolvimento — os casos que falharam
viraram correção. O número diz "não regrediu", não "generaliza". Falta um
conjunto cego, e isso está listado como próximo passo em `docs/04-metricas.md`.
