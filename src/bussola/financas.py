"""Camada determinística de cálculo financeiro.

Regra central do projeto: **todo número que aparece em uma resposta é produzido
aqui, nunca pelo LLM.** O modelo de linguagem recebe os valores já calculados e
só decide como redigi-los. É isso que torna o agente auditável — qualquer
número da resposta pode ser reproduzido rodando a função correspondente.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .kb import BaseConhecimento

CATEGORIAS_NECESSIDADE = {"moradia", "mercado", "transporte", "saude", "educacao"}
CATEGORIAS_DESEJO = {"alimentacao", "lazer", "assinaturas", "vestuario"}
CATEGORIAS_FIXAS = {"moradia", "saude", "educacao"}


@dataclass
class Calculo:
    """Resultado de um cálculo, com os valores e as fontes que o sustentam."""

    tipo: str
    valores: dict[str, Any]
    fontes: list[str] = field(default_factory=list)
    observacoes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _meses_disponiveis(kb: BaseConhecimento) -> list[str]:
    return sorted({t["data"][:7] for t in kb.transacoes})


def _filtrar_periodo(kb: BaseConhecimento, meses: int) -> list[dict[str, Any]]:
    disponiveis = _meses_disponiveis(kb)
    janela = set(disponiveis[-meses:]) if meses > 0 else set(disponiveis)
    return [t for t in kb.transacoes if t["data"][:7] in janela]


def brl(valor: float) -> str:
    """Formata em real brasileiro: 1234.5 -> 'R$ 1.234,50'."""
    inteiro, decimal = f"{abs(valor):,.2f}".split(".")
    inteiro = inteiro.replace(",", ".")
    sinal = "-" if valor < 0 else ""
    return f"{sinal}R$ {inteiro},{decimal}"


def pct(valor: float, casas: int = 1) -> str:
    return f"{valor * 100:.{casas}f}".replace(".", ",") + "%"


# ---------------------------------------------------------------------------
# Análise de gastos
# ---------------------------------------------------------------------------

def resumo_gastos(kb: BaseConhecimento, meses: int = 3) -> Calculo:
    transacoes = _filtrar_periodo(kb, meses)
    debitos = [t for t in transacoes if t["tipo"] == "debito"]
    creditos = [t for t in transacoes if t["tipo"] == "credito"]

    periodo = sorted({t["data"][:7] for t in transacoes})
    n_meses = len(periodo) or 1

    por_categoria: dict[str, float] = defaultdict(float)
    for t in debitos:
        por_categoria[t["categoria"]] += t["valor"]

    total_despesa = sum(t["valor"] for t in debitos)
    total_receita = sum(t["valor"] for t in creditos)

    ranking = sorted(por_categoria.items(), key=lambda item: -item[1])

    return Calculo(
        tipo="resumo_gastos",
        valores={
            "periodo": periodo,
            "meses_analisados": n_meses,
            "total_despesa": round(total_despesa, 2),
            "total_receita": round(total_receita, 2),
            "media_despesa_mensal": round(total_despesa / n_meses, 2),
            "media_receita_mensal": round(total_receita / n_meses, 2),
            "saldo_medio_mensal": round((total_receita - total_despesa) / n_meses, 2),
            "por_categoria": {k: round(v, 2) for k, v in ranking},
            "por_categoria_media_mensal": {
                k: round(v / n_meses, 2) for k, v in ranking
            },
            "maior_categoria": ranking[0][0] if ranking else None,
            "qtd_transacoes": len(transacoes),
        },
        fontes=["data/transacoes.csv"],
    )


def gastos_da_categoria(
    kb: BaseConhecimento, categoria: str, meses: int = 3
) -> Calculo:
    transacoes = _filtrar_periodo(kb, meses)
    da_categoria = [
        t for t in transacoes if t["tipo"] == "debito" and t["categoria"] == categoria
    ]
    periodo = sorted({t["data"][:7] for t in transacoes})
    n_meses = len(periodo) or 1
    total = sum(t["valor"] for t in da_categoria)

    por_descricao: dict[str, float] = defaultdict(float)
    for t in da_categoria:
        por_descricao[t["descricao"]] += t["valor"]

    return Calculo(
        tipo="gastos_categoria",
        valores={
            "categoria": categoria,
            "periodo": periodo,
            "meses_analisados": n_meses,
            "total": round(total, 2),
            "media_mensal": round(total / n_meses, 2),
            "qtd_transacoes": len(da_categoria),
            "por_descricao": {
                k: round(v, 2)
                for k, v in sorted(por_descricao.items(), key=lambda i: -i[1])
            },
        },
        fontes=["data/transacoes.csv"],
    )


def assinaturas_recorrentes(kb: BaseConhecimento) -> Calculo:
    """Identifica cobranças que se repetem em meses distintos."""
    ocorrencias: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for t in kb.transacoes:
        if t["tipo"] == "debito":
            ocorrencias[t["descricao"]].append(t)

    recorrentes = []
    for descricao, itens in ocorrencias.items():
        meses = {i["data"][:7] for i in itens}
        valores = {round(i["valor"], 2) for i in itens}
        # Recorrente = mesmo valor, em pelo menos 2 meses distintos
        if len(meses) >= 2 and len(valores) == 1:
            recorrentes.append(
                {
                    "descricao": descricao,
                    "categoria": itens[0]["categoria"],
                    "valor_mensal": round(itens[0]["valor"], 2),
                    "meses_cobrados": len(meses),
                    "primeiro_mes": min(meses),
                    "ultimo_mes": max(meses),
                }
            )

    recorrentes.sort(key=lambda r: -r["valor_mensal"])
    assinaturas = [r for r in recorrentes if r["categoria"] == "assinaturas"]
    ultimo_mes = max(_meses_disponiveis(kb))
    ativas = [a for a in assinaturas if a["ultimo_mes"] == ultimo_mes]

    return Calculo(
        tipo="assinaturas",
        valores={
            "recorrentes": recorrentes,
            "assinaturas": assinaturas,
            "assinaturas_ativas": ativas,
            "custo_mensal_assinaturas_ativas": round(
                sum(a["valor_mensal"] for a in ativas), 2
            ),
            "custo_anual_assinaturas_ativas": round(
                sum(a["valor_mensal"] for a in ativas) * 12, 2
            ),
            "mes_referencia": ultimo_mes,
        },
        fontes=["data/transacoes.csv"],
    )


def fluxo_mensal(kb: BaseConhecimento) -> Calculo:
    receita: dict[str, float] = defaultdict(float)
    despesa: dict[str, float] = defaultdict(float)
    for t in kb.transacoes:
        alvo = receita if t["tipo"] == "credito" else despesa
        alvo[t["data"][:7]] += t["valor"]

    meses = sorted(set(receita) | set(despesa))
    linhas = [
        {
            "mes": mes,
            "receita": round(receita.get(mes, 0.0), 2),
            "despesa": round(despesa.get(mes, 0.0), 2),
            "saldo": round(receita.get(mes, 0.0) - despesa.get(mes, 0.0), 2),
        }
        for mes in meses
    ]
    meses_negativos = [linha["mes"] for linha in linhas if linha["saldo"] < 0]

    return Calculo(
        tipo="fluxo_mensal",
        valores={
            "linhas": linhas,
            "meses_negativos": meses_negativos,
            "qtd_meses_negativos": len(meses_negativos),
            "saldo_acumulado": round(sum(linha["saldo"] for linha in linhas), 2),
        },
        fontes=["data/transacoes.csv"],
    )


def regra_50_30_20(kb: BaseConhecimento, meses: int = 3) -> Calculo:
    resumo = resumo_gastos(kb, meses).valores
    por_categoria = resumo["por_categoria_media_mensal"]
    receita = resumo["media_receita_mensal"] or 1.0

    necessidades = sum(
        v for k, v in por_categoria.items() if k in CATEGORIAS_NECESSIDADE
    )
    desejos = sum(v for k, v in por_categoria.items() if k in CATEGORIAS_DESEJO)
    outros = sum(
        v
        for k, v in por_categoria.items()
        if k not in CATEGORIAS_NECESSIDADE and k not in CATEGORIAS_DESEJO
    )
    sobra = receita - (necessidades + desejos + outros)

    return Calculo(
        tipo="regra_50_30_20",
        valores={
            "receita_mensal": round(receita, 2),
            "necessidades": round(necessidades, 2),
            "necessidades_pct": round(necessidades / receita, 4),
            "desejos": round(desejos, 2),
            "desejos_pct": round(desejos / receita, 4),
            "outros": round(outros, 2),
            "outros_pct": round(outros / receita, 4),
            "sobra": round(sobra, 2),
            "sobra_pct": round(sobra / receita, 4),
            "alvo": {"necessidades": 0.5, "desejos": 0.3, "poupanca": 0.2},
        },
        fontes=["data/transacoes.csv", "data/faq.json#FAQ-009"],
    )


# ---------------------------------------------------------------------------
# Reserva de emergência e metas
# ---------------------------------------------------------------------------

def diagnostico_reserva(kb: BaseConhecimento) -> Calculo:
    reserva = kb.perfil["reserva_emergencia"]
    atual = float(reserva["valor_atual"])
    custo_fixo = float(reserva["custo_fixo_mensal"])
    meta_meses = int(reserva["meta_meses"])
    alvo = custo_fixo * meta_meses
    falta = max(alvo - atual, 0.0)
    cobertura_meses = atual / custo_fixo if custo_fixo else 0.0

    return Calculo(
        tipo="reserva_emergencia",
        valores={
            "valor_atual": round(atual, 2),
            "custo_fixo_mensal": round(custo_fixo, 2),
            "meta_meses": meta_meses,
            "valor_alvo": round(alvo, 2),
            "falta": round(falta, 2),
            "cobertura_meses": round(cobertura_meses, 1),
            "percentual_da_meta": round(atual / alvo, 4) if alvo else 0.0,
            "completa": falta <= 0,
        },
        fontes=[
            "data/perfil_investidor.json#reserva_emergencia",
            "data/faq.json#FAQ-001",
        ],
    )


def prazo_para_meta(
    valor_atual: float, valor_alvo: float, aporte_mensal: float, taxa_mensal: float = 0.0
) -> Calculo:
    """Quantos meses até atingir a meta, com aportes e juros compostos."""
    if aporte_mensal <= 0 and taxa_mensal <= 0:
        return Calculo(
            tipo="prazo_meta",
            valores={"atingivel": False, "motivo": "aporte mensal precisa ser maior que zero"},
            fontes=[],
        )

    saldo = valor_atual
    meses = 0
    limite = 1200  # 100 anos: se não chegar, é inatingível na prática
    while saldo < valor_alvo and meses < limite:
        saldo = saldo * (1 + taxa_mensal) + aporte_mensal
        meses += 1

    atingivel = saldo >= valor_alvo
    return Calculo(
        tipo="prazo_meta",
        valores={
            "atingivel": atingivel,
            "meses": meses if atingivel else None,
            "anos": round(meses / 12, 1) if atingivel else None,
            "saldo_final": round(saldo, 2) if atingivel else None,
            "valor_alvo": round(valor_alvo, 2),
            "aporte_mensal": round(aporte_mensal, 2),
            "taxa_mensal": taxa_mensal,
            "total_aportado": round(aporte_mensal * meses, 2) if atingivel else None,
        },
        fontes=["data/faq.json#FAQ-010"],
    )


# ---------------------------------------------------------------------------
# Matemática financeira
# ---------------------------------------------------------------------------

def juros_compostos(
    capital: float, taxa_mensal: float, meses: int, aporte_mensal: float = 0.0
) -> Calculo:
    saldo = capital
    evolucao = []
    for mes in range(1, meses + 1):
        saldo = saldo * (1 + taxa_mensal) + aporte_mensal
        if mes % max(meses // 6, 1) == 0 or mes == meses:
            evolucao.append({"mes": mes, "saldo": round(saldo, 2)})

    total_aportado = capital + aporte_mensal * meses
    return Calculo(
        tipo="juros_compostos",
        valores={
            "capital_inicial": round(capital, 2),
            "aporte_mensal": round(aporte_mensal, 2),
            "taxa_mensal": taxa_mensal,
            "taxa_anual_equivalente": round((1 + taxa_mensal) ** 12 - 1, 6),
            "meses": meses,
            "montante_final": round(saldo, 2),
            "total_aportado": round(total_aportado, 2),
            "rendimento": round(saldo - total_aportado, 2),
            "evolucao": evolucao,
        },
        fontes=["data/faq.json#FAQ-010"],
    )


def taxa_anual_para_mensal(taxa_anual: float) -> float:
    return (1 + taxa_anual) ** (1 / 12) - 1


def custo_da_divida(saldo: float, taxa_mensal: float, meses: int) -> Calculo:
    """Quanto uma dívida custa se ficar rolando pelo período informado."""
    montante = saldo * (1 + taxa_mensal) ** meses
    return Calculo(
        tipo="custo_divida",
        valores={
            "saldo_inicial": round(saldo, 2),
            "taxa_mensal": taxa_mensal,
            "meses": meses,
            "montante_final": round(montante, 2),
            "juros_pagos": round(montante - saldo, 2),
            "multiplicador": round(montante / saldo, 2) if saldo else 0.0,
        },
        fontes=["data/faq.json#FAQ-003", "data/faq.json#FAQ-010"],
    )


def comparar_credito(
    kb: BaseConhecimento, saldo: float, meses: int = 12
) -> Calculo:
    """Compara manter o rotativo x portabilidade para crédito pessoal."""
    rotativo = kb.produto_por_id("PROD-008")
    portabilidade = kb.produto_por_id("PROD-007")
    assert rotativo and portabilidade, "produtos de crédito ausentes na base"

    custo_rotativo = custo_da_divida(saldo, rotativo["taxa_juros_mes"], meses).valores
    custo_portado = custo_da_divida(saldo, portabilidade["taxa_juros_mes"], meses).valores

    return Calculo(
        tipo="comparacao_credito",
        valores={
            "saldo": round(saldo, 2),
            "meses": meses,
            "rotativo": {
                "nome": rotativo["nome"],
                "taxa_mensal": rotativo["taxa_juros_mes"],
                **custo_rotativo,
            },
            "portabilidade": {
                "nome": portabilidade["nome"],
                "taxa_mensal": portabilidade["taxa_juros_mes"],
                **custo_portado,
            },
            "economia": round(
                custo_rotativo["montante_final"] - custo_portado["montante_final"], 2
            ),
        },
        fontes=[
            "data/produtos_financeiros.json#PROD-008",
            "data/produtos_financeiros.json#PROD-007",
            "data/faq.json#FAQ-014",
        ],
    )


# ---------------------------------------------------------------------------
# Produtos
# ---------------------------------------------------------------------------

def produtos_compativeis(
    kb: BaseConhecimento, finalidade: str | None = None
) -> Calculo:
    """Filtra o catálogo pelo perfil vigente e pelas restrições do cliente."""
    perfil = kb.perfil["perfil_investidor"]
    restricoes = kb.perfil.get("restricoes", {})
    aceita_carencia = restricoes.get("aceita_produtos_com_carencia", True)

    elegiveis = []
    bloqueados = []
    for produto in kb.produtos:
        motivos = []
        if produto["categoria"] == "credito":
            continue  # crédito não entra em recomendação de aplicação
        if perfil not in produto["perfis_indicados"]:
            motivos.append(f"não indicado para perfil {perfil}")
        if not aceita_carencia and produto["carencia_dias"] > 0:
            motivos.append(f"tem carência de {produto['carencia_dias']} dias")
        if finalidade and finalidade not in produto.get("adequado_para", []):
            motivos.append(f"não adequado para {finalidade}")

        registro = {
            "id": produto["id"],
            "nome": produto["nome"],
            "risco": produto["risco"],
            "liquidez": produto["liquidez"],
            "carencia_dias": produto["carencia_dias"],
            "rentabilidade_referencia": produto["rentabilidade_referencia"],
            "rentabilidade_estimada_ano": produto["rentabilidade_estimada_ano"],
            "tributacao": produto["tributacao"],
            "fonte": produto["fonte"],
        }
        if motivos:
            bloqueados.append({**registro, "motivos": motivos})
        else:
            elegiveis.append(registro)

    elegiveis.sort(key=lambda p: -(p["rentabilidade_estimada_ano"] or 0))

    return Calculo(
        tipo="produtos_compativeis",
        valores={
            "perfil_cliente": perfil,
            "finalidade": finalidade,
            "aceita_carencia": aceita_carencia,
            "elegiveis": elegiveis,
            "bloqueados": bloqueados,
        },
        fontes=["data/perfil_investidor.json", "data/produtos_financeiros.json"],
    )
