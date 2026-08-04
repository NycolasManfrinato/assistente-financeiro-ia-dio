"""Gerador determinístico da base de transações mockadas do agente Bússola.

Executar a partir da raiz do repositório:

    python data/gerar_dados.py

Reescreve `data/transacoes.csv` sempre com o mesmo conteúdo (seed fixa),
para que a base de conhecimento seja reprodutível e versionável.
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 20260804
MESES = [(2026, 2), (2026, 3), (2026, 4), (2026, 5), (2026, 6), (2026, 7)]

SAIDA = Path(__file__).resolve().parent / "transacoes.csv"

# (categoria, descricao, valor_min, valor_max, ocorrencias_no_mes)
GASTOS_VARIAVEIS = [
    ("alimentacao", "Restaurante", 28.0, 145.0, 9),
    ("alimentacao", "Delivery de comida", 32.0, 98.0, 6),
    ("mercado", "Supermercado", 110.0, 480.0, 4),
    ("transporte", "Aplicativo de transporte", 12.0, 68.0, 8),
    ("transporte", "Posto de combustivel", 90.0, 240.0, 2),
    ("lazer", "Cinema e eventos", 35.0, 180.0, 2),
    ("vestuario", "Loja de roupas", 79.0, 320.0, 1),
    ("saude", "Farmacia", 24.0, 160.0, 2),
]

# (categoria, descricao, valor, dia_do_mes)
GASTOS_FIXOS = [
    ("moradia", "Aluguel", 1850.0, 5),
    ("moradia", "Condominio", 420.0, 5),
    ("moradia", "Energia eletrica", 168.0, 12),
    ("moradia", "Internet banda larga", 119.9, 15),
    ("saude", "Plano de saude", 512.0, 10),
    ("educacao", "Mensalidade curso", 389.0, 8),
    ("transporte", "Seguro do carro", 210.0, 20),
]

ASSINATURAS = [
    ("assinaturas", "Streaming de video A", 39.9, 3),
    ("assinaturas", "Streaming de video B", 34.9, 7),
    ("assinaturas", "Streaming de musica", 21.9, 11),
    ("assinaturas", "Armazenamento em nuvem", 12.99, 14),
    ("assinaturas", "Academia", 109.9, 6),
    ("assinaturas", "Aplicativo de produtividade", 29.9, 18),
]

RENDA = [("salario", "Salario liquido", 6800.0, 5)]


def _dia_valido(ano: int, mes: int, dia: int) -> date:
    """Ajusta o dia para não estourar o fim do mês."""
    proximo = date(ano + (mes // 12), (mes % 12) + 1, 1)
    ultimo_dia = (proximo - timedelta(days=1)).day
    return date(ano, mes, min(dia, ultimo_dia))


def gerar_linhas() -> list[dict]:
    rng = random.Random(SEED)
    linhas: list[dict] = []
    seq = 0

    for indice_mes, (ano, mes) in enumerate(MESES):
        # Renda
        for categoria, descricao, valor, dia in RENDA:
            seq += 1
            linhas.append(
                {
                    "id_transacao": f"TX{seq:05d}",
                    "data": _dia_valido(ano, mes, dia).isoformat(),
                    "descricao": descricao,
                    "categoria": categoria,
                    "tipo": "credito",
                    "valor": round(valor, 2),
                    "canal": "ted",
                }
            )

        # Gastos fixos
        for categoria, descricao, valor, dia in GASTOS_FIXOS:
            seq += 1
            # Energia varia com a estação
            ajuste = 1.0 + (0.10 * rng.uniform(-1, 1)) if categoria == "moradia" else 1.0
            linhas.append(
                {
                    "id_transacao": f"TX{seq:05d}",
                    "data": _dia_valido(ano, mes, dia).isoformat(),
                    "descricao": descricao,
                    "categoria": categoria,
                    "tipo": "debito",
                    "valor": round(valor * ajuste, 2),
                    "canal": "debito_automatico",
                }
            )

        # Assinaturas: começam com 3 e vão acumulando ao longo dos meses
        # (esse é o "insight" que o agente deve conseguir enxergar)
        ativas = ASSINATURAS[: min(3 + indice_mes, len(ASSINATURAS))]
        for categoria, descricao, valor, dia in ativas:
            seq += 1
            linhas.append(
                {
                    "id_transacao": f"TX{seq:05d}",
                    "data": _dia_valido(ano, mes, dia).isoformat(),
                    "descricao": descricao,
                    "categoria": categoria,
                    "tipo": "debito",
                    "valor": round(valor, 2),
                    "canal": "cartao_credito",
                }
            )

        # Gastos variáveis
        for categoria, descricao, minimo, maximo, ocorrencias in GASTOS_VARIAVEIS:
            for _ in range(ocorrencias):
                seq += 1
                dia = rng.randint(1, 28)
                linhas.append(
                    {
                        "id_transacao": f"TX{seq:05d}",
                        "data": _dia_valido(ano, mes, dia).isoformat(),
                        "descricao": descricao,
                        "categoria": categoria,
                        "tipo": "debito",
                        "valor": round(rng.uniform(minimo, maximo), 2),
                        "canal": rng.choice(["cartao_credito", "cartao_debito", "pix"]),
                    }
                )

        # Juros de rotativo a partir do 4º mês (mai/jun/jul de 2026)
        if indice_mes >= 3:
            seq += 1
            base_divida = 1850.0 * (1.145 ** (indice_mes - 3))
            linhas.append(
                {
                    "id_transacao": f"TX{seq:05d}",
                    "data": _dia_valido(ano, mes, 22).isoformat(),
                    "descricao": "Juros rotativo cartao de credito",
                    "categoria": "servicos_financeiros",
                    "tipo": "debito",
                    "valor": round(base_divida * 0.145, 2),
                    "canal": "cartao_credito",
                }
            )

    linhas.sort(key=lambda linha: (linha["data"], linha["id_transacao"]))
    return linhas


def main() -> None:
    linhas = gerar_linhas()
    campos = ["id_transacao", "data", "descricao", "categoria", "tipo", "valor", "canal"]
    with SAIDA.open("w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.DictWriter(arquivo, fieldnames=campos)
        escritor.writeheader()
        escritor.writerows(linhas)
    print(f"{len(linhas)} transacoes escritas em {SAIDA}")


if __name__ == "__main__":
    main()
