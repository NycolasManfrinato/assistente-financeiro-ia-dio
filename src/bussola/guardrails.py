"""Guardrails de entrada e de saída.

O agente atua em contexto financeiro, onde uma resposta inventada custa caro.
A estratégia tem três camadas:

1. **Pré**: bloqueia pedidos fora de escopo e alerta sobre dado sensível.
2. **Ancoragem**: números nunca vêm do LLM, apenas da camada `financas`.
3. **Pós**: valida a resposta gerada — todo valor monetário citado precisa
   existir no conjunto de números calculados, e expressões de promessa de
   retorno são bloqueadas.

Se a validação de saída falhar, o agente descarta o texto do LLM e usa a
resposta determinística de fallback.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

PROMESSAS_PROIBIDAS = [
    r"\brentabilidade garantida\b",
    r"\bretorno garantido\b",
    r"\blucro garantido\b",
    r"\bganho garantido\b",
    r"\bsem risco (nenhum|algum)\b",
    r"\bcom certeza (vai|voce vai) (render|lucrar|ganhar)\b",
    r"\bvai (dobrar|triplicar) seu dinheiro\b",
    r"\b(recomendo|indico) (comprar|vender) (a acao|acoes|bitcoin)\b",
]

AVISO_DADO_SENSIVEL = (
    "Antes de seguir: nunca compartilhe senha, código de segurança do cartão, "
    "token ou CPF completo em conversas — nem comigo. Eu não preciso desses "
    "dados para ajudar e não vou registrá-los. Se você já enviou algo assim em "
    "outro lugar, vale trocar a senha e acionar o canal oficial do banco."
)

MENSAGENS_FORA_DE_ESCOPO = {
    "recomendacao_ativo": (
        "Não posso indicar ativos específicos para comprar ou vender. Isso é "
        "atividade de consultoria de valores mobiliários, regulada pela CVM e "
        "exercida por profissionais certificados."
    ),
    "previsao_mercado": (
        "Não faço previsão de mercado. Ninguém consegue dizer com segurança se "
        "um ativo vai subir ou cair, e uma resposta inventada aqui te causaria "
        "prejuízo real."
    ),
    "ilicito": (
        "Não ajudo com nada que envolva ocultar renda ou movimentar dinheiro de "
        "forma irregular."
    ),
    "promessa_retorno": (
        "Não trabalho com promessa de retorno. Rentabilidade passada não garante "
        "rentabilidade futura, e nenhum produto de investimento pode assegurar "
        "ganho."
    ),
    "consultoria_tributaria": (
        "Não faço declaração de imposto de renda nem dou orientação tributária "
        "individual. Para isso, procure um contador."
    ),
}

REDIRECIONAMENTO = (
    "O que eu consigo fazer: analisar seus gastos por categoria, diagnosticar "
    "sua reserva de emergência, comparar as características dos produtos do "
    "catálogo, simular juros e mostrar o custo de uma dívida."
)


@dataclass
class Veredito:
    aprovado: bool
    violacoes: list[str] = field(default_factory=list)
    mensagem: str | None = None


# ---------------------------------------------------------------------------
# Pré-processamento
# ---------------------------------------------------------------------------

def resposta_fora_de_escopo(motivo: str | None) -> str:
    base = MENSAGENS_FORA_DE_ESCOPO.get(
        motivo or "", "Esse assunto está fora do que eu consigo cobrir com segurança."
    )
    return f"{base}\n\n{REDIRECIONAMENTO}"


def resposta_dado_sensivel() -> str:
    return f"{AVISO_DADO_SENSIVEL}\n\n{REDIRECIONAMENTO}"


# ---------------------------------------------------------------------------
# Pós-processamento
# ---------------------------------------------------------------------------

_RE_VALOR = re.compile(r"R\$\s*([\d\.]+,\d{2}|\d+)")


def _valores_monetarios(texto: str) -> set[float]:
    encontrados: set[float] = set()
    for bruto in _RE_VALOR.findall(texto):
        limpo = bruto.replace(".", "").replace(",", ".")
        try:
            encontrados.add(round(float(limpo), 2))
        except ValueError:
            continue
    return encontrados


def coletar_numeros_permitidos(valores) -> set[float]:
    """Achata recursivamente uma estrutura de cálculo em um conjunto de números."""
    permitidos: set[float] = set()

    def _andar(no) -> None:
        if isinstance(no, dict):
            for item in no.values():
                _andar(item)
        elif isinstance(no, (list, tuple, set)):
            for item in no:
                _andar(item)
        elif isinstance(no, bool):
            return
        elif isinstance(no, (int, float)):
            permitidos.add(round(float(no), 2))
            # Tolerâncias de redação: arredondamento e troca de sinal
            # ("saldo de -1.000,01" costuma virar "faltam 1.000,01").
            permitidos.add(float(round(no)))
            permitidos.add(round(abs(float(no)), 2))

    _andar(valores)
    return permitidos


def validar_resposta(
    texto: str, numeros_permitidos: set[float], exige_fonte: bool = True
) -> Veredito:
    violacoes: list[str] = []

    minusculo = texto.lower()
    for padrao in PROMESSAS_PROIBIDAS:
        if re.search(padrao, minusculo):
            violacoes.append(f"promessa_proibida:{padrao}")

    citados = _valores_monetarios(texto)
    nao_ancorados = {
        valor
        for valor in citados
        if valor not in numeros_permitidos
        and not any(abs(valor - p) < 0.02 for p in numeros_permitidos)
    }
    if nao_ancorados:
        violacoes.append(
            "valor_nao_ancorado:" + ", ".join(f"{v:.2f}" for v in sorted(nao_ancorados))
        )

    if exige_fonte and "Fonte" not in texto and "fonte" not in texto:
        violacoes.append("sem_citacao_de_fonte")

    return Veredito(aprovado=not violacoes, violacoes=violacoes)
