"""Classificação de intenção por regras.

Um classificador baseado em palavras-chave, não em LLM. O motivo é o mesmo do
retriever: o roteamento precisa ser determinístico e testável. Se a intenção
fosse decidida pelo modelo, a mesma pergunta poderia cair em rotas diferentes
entre execuções e a avaliação perderia sentido.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .retriever import normalizar

CATEGORIAS_CONHECIDAS = {
    "alimentacao": ["alimentacao", "comida", "restaurante", "delivery", "ifood", "comer"],
    "mercado": ["mercado", "supermercado", "compras de casa"],
    "transporte": ["transporte", "uber", "combustivel", "gasolina", "carro", "onibus"],
    "moradia": ["moradia", "aluguel", "condominio", "casa", "energia", "luz", "internet"],
    "saude": ["saude", "farmacia", "remedio", "plano de saude", "medico"],
    "educacao": ["educacao", "curso", "faculdade", "mensalidade", "estudo"],
    "lazer": ["lazer", "cinema", "evento", "diversao", "passeio"],
    "assinaturas": ["assinatura", "streaming", "netflix", "spotify", "academia", "recorrente"],
    "vestuario": ["vestuario", "roupa", "roupas", "loja de roupa"],
    "servicos_financeiros": ["juros", "tarifa", "servico financeiro"],
}

# Cada intenção tem gatilhos fortes (peso 2) e fracos (peso 1).
REGRAS: dict[str, dict[str, list[str]]] = {
    "saudacao": {
        "fortes": ["ola", "oi", "bom dia", "boa tarde", "boa noite", "e ai"],
        "fracos": ["tudo bem", "como vai"],
    },
    "despedida": {
        "fortes": ["tchau", "ate mais", "obrigado", "obrigada", "valeu"],
        "fracos": ["ate logo"],
    },
    "capacidades": {
        "fortes": ["o que voce faz", "o que vc faz", "como funciona voce", "quem e voce",
                   "no que pode ajudar", "o que voce sabe", "suas funcoes"],
        "fracos": ["ajuda", "menu"],
    },
    "gastos_resumo": {
        "fortes": ["resumo dos gastos", "quanto gastei", "quanto eu gastei",
                   "quanto eu gasto", "meus gastos", "onde vai meu dinheiro",
                   "para onde vai meu dinheiro", "extrato", "balanco", "orcamento",
                   "50 30 20", "gasto por categoria", "resumo financeiro"],
        "fracos": ["gasto", "gastos", "gastei", "gastando", "despesa", "despesas",
                   "dinheiro"],
    },
    "gastos_categoria": {
        "fortes": ["quanto gastei com", "quanto gasto com", "gastos com", "gasto com"],
        "fracos": [],
    },
    "assinaturas": {
        "fortes": ["assinatura", "assinaturas", "streaming", "cobranca recorrente",
                   "cobrancas recorrentes", "recorrentes", "cancelar servico"],
        "fracos": ["mensalidade", "netflix", "spotify"],
    },
    "reserva_emergencia": {
        "fortes": ["reserva de emergencia", "reserva emergencia", "colchao financeiro",
                   "quanto guardar", "guardar dinheiro", "preciso guardar",
                   "preciso ter guardado", "quanto juntar"],
        "fracos": ["reserva", "emergencia", "imprevisto"],
    },
    "produtos": {
        "fortes": ["onde investir", "onde aplicar", "que produto", "qual produto",
                   "qual investimento", "melhor investimento", "opcoes de investimento",
                   "cdb", "tesouro", "poupanca", "lci", "fundo"],
        "fracos": ["investir", "investimento", "aplicar", "rendimento", "render"],
    },
    "divida": {
        "fortes": ["rotativo", "divida do cartao", "fatura do cartao", "juros do cartao",
                   "quitar divida", "sair do vermelho", "parcelar fatura", "portabilidade"],
        "fracos": ["divida", "dividas", "fatura", "cartao", "devendo", "atrasado"],
    },
    "simulacao": {
        "fortes": ["simular", "simulacao", "se eu aplicar", "se eu investir",
                   "quanto rende", "quanto vou ter", "em quanto tempo", "quanto tempo",
                   "juros compostos", "projecao"],
        "fracos": ["simule", "calcule", "calcular"],
    },
    "conceito": {
        "fortes": ["o que e", "o que sao", "qual a diferenca", "diferenca entre",
                   "como funciona", "significa", "explique", "explica"],
        "fracos": ["cdi", "selic", "fgc", "ipca", "liquidez", "carencia", "suitability",
                   "imposto", "ir", "tributacao"],
    },
    "historico_atendimento": {
        "fortes": ["ultimo atendimento", "atendimentos anteriores", "ja falei com",
                   "historico de atendimento", "chamados", "protocolo"],
        "fracos": ["atendimento", "suporte"],
    },
}

# Padrões que devem ser recusados independentemente do resto.
FORA_DE_ESCOPO = [
    (r"\b(qual|quais|que)\s+(acao|acoes|ativo|ativos|papel|papeis)\b.*\b(comprar|investir|indicar|recomenda)", "recomendacao_ativo"),
    (r"\b(compro|vendo|compra|venda)\s+(acao|acoes|bitcoin|cripto|dolar)", "recomendacao_ativo"),
    (r"\b(vai|vao)\s+(subir|cair|valorizar|desvalorizar)\b", "previsao_mercado"),
    (r"\b(previsao|prever|palpite)\b.*\b(bolsa|mercado|dolar|bitcoin|ibovespa)\b", "previsao_mercado"),
    (r"\b(sonegar|sonegacao|nao declarar|esconder do (leao|fisco)|caixa dois)\b", "ilicito"),
    (r"\b(lavagem de dinheiro|laranja)\b", "ilicito"),
    (r"\bgarantia de\s+(retorno|lucro|rentabilidade)\b", "promessa_retorno"),
    (r"\b(retorno|lucro|rentabilidade|ganho)\s+garantid[oa]\b", "promessa_retorno"),
    (r"\bgarantid[oa]\s+(retorno|lucro|rentabilidade|ganho)\b", "promessa_retorno"),
    (r"\bsem risco\b.*\b(investir|investimento|aplicar|aplicacao)\b", "promessa_retorno"),
    (r"\bdeclaracao de (imposto de renda|ir)\b.*\b(preencher|fazer|entregar)\b", "consultoria_tributaria"),
]

# Padrões de risco de segurança / dado sensível.
RISCO_SEGURANCA = [
    (r"\b(minha|meu)\s+(senha|pin)\b", "senha"),
    (r"\bsenha\s+(e|eh|:)\s*\S+", "senha"),
    (r"\b\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\b", "numero_cartao"),
    (r"\b(cvv|codigo de seguranca)\b", "cvv"),
    (r"\b(token|codigo do sms)\b", "token"),
    (r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "cpf"),
]


@dataclass
class Intencao:
    nome: str
    confianca: float
    entidades: dict[str, str] = field(default_factory=dict)
    motivo: str | None = None


def _pontuar(texto: str, regras: dict[str, list[str]]) -> int:
    score = 0
    for gatilho in regras["fortes"]:
        if gatilho in texto:
            score += 2
    for gatilho in regras["fracos"]:
        if re.search(rf"\b{re.escape(gatilho)}\b", texto):
            score += 1
    return score


def _extrair_categoria(texto: str) -> str | None:
    for categoria, termos in CATEGORIAS_CONHECIDAS.items():
        for termo in termos:
            if re.search(rf"\b{re.escape(termo)}", texto):
                return categoria
    return None


def _extrair_numeros(texto_original: str) -> dict[str, str]:
    entidades: dict[str, str] = {}

    # Valores em reais: "R$ 1.500,00", "1500 reais", "500"
    valor = re.search(
        r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+(?:,\d{2})?|\d+(?:,\d{2})?)\s*(?:reais)?",
        texto_original.lower(),
    )
    if valor:
        bruto = valor.group(1).replace(".", "").replace(",", ".")
        entidades["valor"] = bruto

    prazo = re.search(r"(\d+)\s*(mes|meses|ano|anos)", texto_original.lower())
    if prazo:
        quantidade = int(prazo.group(1))
        meses = quantidade * 12 if prazo.group(2).startswith("ano") else quantidade
        entidades["meses"] = str(meses)

    return entidades


def intencao_pede_numero(texto: str) -> bool:
    """Distingue 'o que é rotativo' (conceito) de 'quanto pago de rotativo' (cálculo)."""
    marcadores = ("quanto", "meu ", "meus ", "minha ", "minhas ", "eu tenho",
                  "eu gasto", "eu gastei", "eu pago", "simul", "calcul")
    return any(m in texto for m in marcadores)


def classificar(pergunta: str) -> Intencao:
    texto = normalizar(pergunta)
    texto = re.sub(r"\s+", " ", texto).strip()

    for padrao, motivo in RISCO_SEGURANCA:
        if re.search(padrao, texto):
            return Intencao("risco_seguranca", 1.0, motivo=motivo)

    for padrao, motivo in FORA_DE_ESCOPO:
        if re.search(padrao, texto):
            return Intencao("fora_de_escopo", 1.0, motivo=motivo)

    pontuacoes = {nome: _pontuar(texto, regras) for nome, regras in REGRAS.items()}
    melhor = max(pontuacoes, key=lambda nome: pontuacoes[nome])
    maior = pontuacoes[melhor]

    if maior == 0:
        return Intencao("desconhecida", 0.0)

    categoria = _extrair_categoria(texto)

    # --- Desempates explícitos -------------------------------------------
    # Cada regra abaixo existe porque um caso real do dataset de avaliação
    # caía na rota errada sem ela.

    # "quanto gastei com X" é mais específico que o resumo geral.
    if melhor == "gastos_resumo" and categoria and pontuacoes["gastos_categoria"] > 0:
        melhor = "gastos_categoria"
    if melhor == "gastos_categoria" and not categoria:
        melhor = "gastos_resumo"

    # Assinatura é sempre a rota de assinaturas, mesmo com palavra de gasto.
    if pontuacoes["assinaturas"] >= 2:
        melhor = "assinaturas"

    # Pergunta de definição ganha da rota operacional: "como funciona o
    # rotativo" quer explicação, não simulação de dívida.
    marcadores_definicao = ("o que e ", "o que sao ", "como funciona", "diferenca entre",
                            "qual a diferenca", "explique", "explica ", "significa")
    if any(texto.startswith(m) or f" {m}" in texto for m in marcadores_definicao):
        if pontuacoes["conceito"] > 0 and not intencao_pede_numero(texto):
            melhor = "conceito"

    # "onde investir" quer catálogo de produtos, mesmo citando reserva.
    gatilhos_produto = ("onde investir", "onde aplicar", "que produto", "qual produto",
                        "qual investimento", "melhor investimento", "opcoes de investimento",
                        "onde guardar", "onde deixar")
    if any(g in texto for g in gatilhos_produto):
        melhor = "produtos"

    total = sum(pontuacoes.values()) or 1
    confianca = round(min(maior / total + 0.1 * maior, 1.0), 3)

    entidades = _extrair_numeros(pergunta)
    if categoria:
        entidades["categoria"] = categoria

    return Intencao(melhor, confianca, entidades)
