"""Carregamento da base de conhecimento e montagem dos documentos recuperáveis.

Toda informação que o agente pode usar em uma resposta passa por aqui e recebe
um `id` e uma `fonte`. Isso é o que permite, mais adiante, verificar se uma
resposta está de fato ancorada na base (groundedness).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from . import config


@dataclass(frozen=True)
class Documento:
    """Unidade recuperável da base de conhecimento."""

    id: str
    titulo: str
    texto: str
    fonte: str
    tipo: str
    metadados: dict[str, Any] = field(default_factory=dict)


@dataclass
class BaseConhecimento:
    transacoes: list[dict[str, Any]]
    perfil: dict[str, Any]
    produtos: list[dict[str, Any]]
    indexadores: dict[str, float]
    atendimentos: list[dict[str, Any]]
    faq: list[dict[str, Any]]
    documentos: list[Documento]

    def documento_por_id(self, doc_id: str) -> Documento | None:
        for doc in self.documentos:
            if doc.id == doc_id:
                return doc
        return None

    def produto_por_id(self, produto_id: str) -> dict[str, Any] | None:
        for produto in self.produtos:
            if produto["id"] == produto_id:
                return produto
        return None


def _ler_csv(caminho) -> list[dict[str, Any]]:
    with open(caminho, encoding="utf-8", newline="") as arquivo:
        return list(csv.DictReader(arquivo))


def _ler_json(caminho) -> Any:
    with open(caminho, encoding="utf-8") as arquivo:
        return json.load(arquivo)


def _reais(valor: float) -> str:
    inteiro, decimal = f"{valor:,.2f}".split(".")
    return f"R$ {inteiro.replace(',', '.')},{decimal}"


def _texto_produto(produto: dict[str, Any]) -> str:
    partes = [
        produto["nome"],
        produto["resumo"],
        f"categoria {produto['categoria']}",
        f"risco {produto['risco']}",
        f"liquidez {produto['liquidez']}",
        f"carencia de {produto['carencia_dias']} dias",
        f"aplicacao minima {_reais(produto['aplicacao_minima'])}",
        f"perfis indicados {', '.join(produto['perfis_indicados']) or 'nenhum'}",
        f"tributacao {produto['tributacao']}",
    ]
    if produto.get("rentabilidade_referencia"):
        partes.append(f"rentabilidade {produto['rentabilidade_referencia']}")
    if produto.get("taxa_juros_mes") is not None:
        partes.append(f"taxa de juros {produto['taxa_juros_mes'] * 100:.2f}% ao mes")
    if produto.get("adequado_para"):
        partes.append(f"adequado para {', '.join(produto['adequado_para'])}")
    return ". ".join(partes)


def _montar_documentos(
    produtos: list[dict[str, Any]],
    faq: list[dict[str, Any]],
    atendimentos: list[dict[str, Any]],
) -> list[Documento]:
    documentos: list[Documento] = []

    for item in faq:
        documentos.append(
            Documento(
                id=item["id"],
                titulo=item["titulo"],
                texto=item["conteudo"],
                fonte=item["fonte"],
                tipo="conceito",
                metadados={"tags": item.get("tags", [])},
            )
        )

    for produto in produtos:
        documentos.append(
            Documento(
                id=produto["id"],
                titulo=produto["nome"],
                texto=_texto_produto(produto),
                fonte=produto["fonte"],
                tipo="produto",
                metadados=produto,
            )
        )

    for atendimento in atendimentos:
        documentos.append(
            Documento(
                id=atendimento["id_atendimento"],
                titulo=f"Atendimento {atendimento['data']} - {atendimento['assunto']}",
                texto=(
                    f"Em {atendimento['data']} pelo canal {atendimento['canal']}, "
                    f"assunto {atendimento['assunto']}: {atendimento['resumo']}. "
                    f"Resolvido: {atendimento['resolvido']}."
                ),
                fonte=f"data/historico_atendimento.csv#{atendimento['id_atendimento']}",
                tipo="atendimento",
                metadados=atendimento,
            )
        )

    return documentos


@lru_cache(maxsize=1)
def carregar() -> BaseConhecimento:
    """Carrega a base inteira em memória (cacheada por processo)."""
    transacoes_brutas = _ler_csv(config.ARQ_TRANSACOES)
    transacoes = [
        {**linha, "valor": float(linha["valor"])} for linha in transacoes_brutas
    ]

    perfil = _ler_json(config.ARQ_PERFIL)

    produtos_raw = _ler_json(config.ARQ_PRODUTOS)
    produtos = produtos_raw["produtos"]
    indexadores = produtos_raw["_meta"]["indexadores_referencia"]

    atendimentos = _ler_csv(config.ARQ_ATENDIMENTOS)
    faq = _ler_json(config.ARQ_FAQ)["itens"]

    return BaseConhecimento(
        transacoes=transacoes,
        perfil=perfil,
        produtos=produtos,
        indexadores=indexadores,
        atendimentos=atendimentos,
        faq=faq,
        documentos=_montar_documentos(produtos, faq, atendimentos),
    )
