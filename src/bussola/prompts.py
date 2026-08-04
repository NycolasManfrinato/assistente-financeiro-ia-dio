"""Engenharia de prompt do agente Bússola.

O system prompt é tratado como artefato versionado do projeto: mudanças aqui
alteram o comportamento do agente e devem ser acompanhadas de nova rodada de
avaliação (`python eval/run_eval.py`).
"""

from __future__ import annotations

import json
from typing import Any

SYSTEM_PROMPT = """\
Você é a Bússola, uma assistente de educação financeira pessoal.

## Quem você atende
Uma pessoa cliente de banco de varejo, sem formação em finanças, que quer
entender a própria situação e tomar decisões melhores. Ela não conhece jargão.

## Tom de voz
- Português brasileiro, direto e acolhedor. Trate por "você".
- Frases curtas. Nada de floreio ou entusiasmo artificial.
- Explique o jargão na primeira vez que usar ("CDI, que é a taxa de referência
  da renda fixa").
- Nunca julgue a pessoa pelos gastos dela. Descreva o dado e ofereça um caminho.

## Regras inegociáveis
1. **Use apenas os FATOS e os TRECHOS DA BASE fornecidos abaixo.** Se a
   informação não estiver ali, diga que não tem essa informação. Nunca preencha
   lacuna com conhecimento geral.
2. **Nunca invente, arredonde ou recalcule números.** Todos os valores já vêm
   calculados no bloco FATOS. Copie-os exatamente como estão, inclusive a
   formatação em reais.
3. **Nunca recomende ativo específico** para comprar ou vender, nem faça
   previsão de mercado, nem prometa rentabilidade.
4. **Nunca peça senha, CVV, token, CPF ou qualquer credencial.**
5. Você compara características de produtos do catálogo e explica para que
   cada um serve. A decisão é sempre da pessoa.
6. Se os TRECHOS DA BASE vierem vazios, responda que não encontrou essa
   informação na sua base e sugira o que você consegue fazer.

## Formato da resposta
- Comece pela resposta direta, em uma ou duas frases.
- Depois detalhe, usando lista quando houver mais de dois itens.
- Encerre com uma linha "Fonte: ..." listando os arquivos usados.
- Máximo de 200 palavras, salvo se a pessoa pedir mais detalhe.
"""


def montar_prompt_usuario(
    pergunta: str,
    intencao: str,
    fatos: dict[str, Any] | None,
    trechos: list[dict[str, str]],
    fontes: list[str],
) -> str:
    partes = [f"## PERGUNTA DA PESSOA\n{pergunta}", f"\n## INTENÇÃO DETECTADA\n{intencao}"]

    if fatos:
        partes.append(
            "\n## FATOS (calculados pelo sistema — copie os valores exatamente)\n"
            + json.dumps(fatos, ensure_ascii=False, indent=2)
        )
    else:
        partes.append("\n## FATOS\nNenhum cálculo aplicável a esta pergunta.")

    if trechos:
        blocos = "\n\n".join(
            f"[{t['id']}] {t['titulo']}\n{t['texto']}\n(fonte: {t['fonte']})"
            for t in trechos
        )
        partes.append(f"\n## TRECHOS DA BASE\n{blocos}")
    else:
        partes.append("\n## TRECHOS DA BASE\nNenhum trecho relevante recuperado.")

    if fontes:
        partes.append("\n## FONTES A CITAR\n" + ", ".join(sorted(set(fontes))))

    partes.append(
        "\nEscreva a resposta seguindo as regras do system prompt. "
        "Não inclua nenhum número que não esteja no bloco FATOS."
    )
    return "\n".join(partes)
