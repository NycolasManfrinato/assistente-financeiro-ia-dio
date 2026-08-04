"""Interface de linha de comando da Bússola.

Roda sem nenhuma dependência externa:

    python src/cli.py                  # modo conversa
    python src/cli.py "o que é CDI?"   # pergunta única
    python src/cli.py --debug          # mostra intenção, fontes e latência
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bussola import AgenteBussola, NOME_AGENTE, VERSAO  # noqa: E402

FAIXA = "─" * 68

SUGESTOES = [
    "Quanto eu gastei nos últimos meses?",
    "Minha reserva de emergência está ok?",
    "Tenho muitas assinaturas?",
    "Quanto pago de juros no rotativo?",
    "Onde guardar minha reserva?",
    "O que é CDI?",
]


def _imprimir_resposta(resposta, debug: bool) -> None:
    print(f"\n{NOME_AGENTE}:\n{resposta.texto}\n")
    if debug:
        print(FAIXA)
        print(
            f"intenção={resposta.intencao} | confiança={resposta.confianca} | "
            f"provedor={resposta.provedor} | abstenção={resposta.abstencao} | "
            f"{resposta.latencia_ms} ms"
        )
        if resposta.trechos:
            recuperados = ", ".join(
                f"{t['id']}({t['score']})" for t in resposta.trechos
            )
            print(f"recuperados: {recuperados}")
        if resposta.violacoes:
            print(f"violações do guardrail de saída: {resposta.violacoes}")
        print(FAIXA)


def main() -> int:
    argumentos = [a for a in sys.argv[1:] if a != "--debug"]
    debug = "--debug" in sys.argv

    agente = AgenteBussola()

    if argumentos:
        _imprimir_resposta(agente.responder(" ".join(argumentos)), debug)
        return 0

    print(FAIXA)
    print(f"{NOME_AGENTE} v{VERSAO} — assistente de educação financeira")
    print(f"Modo de geração: {agente.provedor.nome}")
    print(FAIXA)
    print("Experimente perguntar:")
    for sugestao in SUGESTOES:
        print(f"  • {sugestao}")
    print("\nDigite 'sair' para encerrar.\n")

    while True:
        try:
            pergunta = input("Você: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nAté mais!")
            return 0

        if not pergunta:
            continue
        if pergunta.lower() in {"sair", "exit", "quit"}:
            print("\nAté mais!")
            return 0

        _imprimir_resposta(agente.responder(pergunta), debug)


if __name__ == "__main__":
    raise SystemExit(main())
