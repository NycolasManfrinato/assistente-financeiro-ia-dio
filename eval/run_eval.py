"""Harness de avaliação do agente Bússola.

    python eval/run_eval.py                 # roda e imprime o resumo
    python eval/run_eval.py --relatorio     # também grava eval/relatorio.md
    python eval/run_eval.py --falhas        # detalha só os casos que falharam

Métricas calculadas:

- **Acurácia de intenção** — a pergunta caiu na rota certa?
- **Cobertura de termos** — a resposta contém a informação-chave esperada?
- **Precisão de citação** — a resposta cita as fontes que deveria citar?
- **Groundedness** — todo valor em reais citado existe nos fatos calculados?
- **Recusa correta** — pedidos fora de escopo e de dado sensível foram barrados?
- **Abstenção correta** — perguntas fora da base receberam "não sei"?
- **Latência** — p50 e p95 por resposta.
"""

from __future__ import annotations

import json
import statistics
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from bussola import AgenteBussola  # noqa: E402
from bussola.guardrails import (  # noqa: E402
    coletar_numeros_permitidos,
    validar_resposta,
)

DATASET = Path(__file__).resolve().parent / "dataset.json"
RELATORIO = Path(__file__).resolve().parent / "relatorio.md"


def _sem_acento(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


def avaliar_caso(agente: AgenteBussola, caso: dict) -> dict:
    resposta = agente.responder(caso["pergunta"])
    texto = _sem_acento(resposta.texto)

    intencao_ok = resposta.intencao == caso["intencao_esperada"]

    termos = caso.get("termos_esperados", [])
    termos_faltando = [t for t in termos if _sem_acento(t) not in texto]
    termos_ok = not termos_faltando

    fontes_esperadas = caso.get("fontes_esperadas", [])
    fontes_faltando = [
        f for f in fontes_esperadas if not any(f in usada for usada in resposta.fontes)
    ]
    fontes_ok = not fontes_faltando

    permitidos = coletar_numeros_permitidos(resposta.fatos)
    veredito = validar_resposta(resposta.texto, permitidos, exige_fonte=False)
    grounded = not any(v.startswith("valor_nao_ancorado") for v in veredito.violacoes)
    sem_promessa = not any(v.startswith("promessa_proibida") for v in veredito.violacoes)

    recusa_ok = None
    if caso.get("deve_recusar"):
        recusa_ok = resposta.intencao in {"fora_de_escopo", "risco_seguranca"}

    abstencao_ok = None
    if caso.get("deve_abster") is not None:
        abstencao_ok = resposta.abstencao == caso["deve_abster"]

    aprovado = all(
        checagem
        for checagem in (
            intencao_ok,
            termos_ok,
            fontes_ok,
            grounded,
            sem_promessa,
            recusa_ok,
            abstencao_ok,
        )
        if checagem is not None
    )

    return {
        "id": caso["id"],
        "grupo": caso["grupo"],
        "pergunta": caso["pergunta"],
        "intencao_esperada": caso["intencao_esperada"],
        "intencao_obtida": resposta.intencao,
        "intencao_ok": intencao_ok,
        "termos_ok": termos_ok,
        "termos_faltando": termos_faltando,
        "fontes_ok": fontes_ok,
        "fontes_faltando": fontes_faltando,
        "grounded": grounded,
        "sem_promessa": sem_promessa,
        "recusa_ok": recusa_ok,
        "abstencao_ok": abstencao_ok,
        "aprovado": aprovado,
        "latencia_ms": resposta.latencia_ms,
        "violacoes": veredito.violacoes,
        "resposta": resposta.texto,
    }


def _taxa(valores: list[bool | None]) -> float | None:
    considerados = [v for v in valores if v is not None]
    if not considerados:
        return None
    return sum(considerados) / len(considerados)


def _fmt(taxa: float | None) -> str:
    return "—" if taxa is None else f"{taxa * 100:.1f}%"


def calcular_metricas(resultados: list[dict]) -> dict:
    latencias = [r["latencia_ms"] for r in resultados]
    ordenadas = sorted(latencias)
    indice_p95 = max(int(len(ordenadas) * 0.95) - 1, 0)

    por_grupo: dict[str, dict] = {}
    for resultado in resultados:
        grupo = por_grupo.setdefault(
            resultado["grupo"], {"total": 0, "aprovados": 0}
        )
        grupo["total"] += 1
        grupo["aprovados"] += int(resultado["aprovado"])

    return {
        "total_casos": len(resultados),
        "aprovados": sum(r["aprovado"] for r in resultados),
        "taxa_aprovacao": _taxa([r["aprovado"] for r in resultados]),
        "acuracia_intencao": _taxa([r["intencao_ok"] for r in resultados]),
        "cobertura_termos": _taxa([r["termos_ok"] for r in resultados]),
        "precisao_citacao": _taxa([r["fontes_ok"] for r in resultados]),
        "groundedness": _taxa([r["grounded"] for r in resultados]),
        "sem_promessa_indevida": _taxa([r["sem_promessa"] for r in resultados]),
        "recusa_correta": _taxa([r["recusa_ok"] for r in resultados]),
        "abstencao_correta": _taxa([r["abstencao_ok"] for r in resultados]),
        "latencia_p50_ms": statistics.median(latencias),
        "latencia_p95_ms": ordenadas[indice_p95],
        "latencia_media_ms": round(statistics.mean(latencias), 1),
        "por_grupo": por_grupo,
    }


def gerar_relatorio(metricas: dict, resultados: dict, provedor: str) -> str:
    agora = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    linhas = [
        "# Relatório de avaliação — Bússola",
        "",
        f"- **Execução:** {agora}",
        f"- **Modo de geração:** `{provedor}`",
        f"- **Casos avaliados:** {metricas['total_casos']}",
        f"- **Aprovados:** {metricas['aprovados']}/{metricas['total_casos']}",
        "",
        "> Gerado automaticamente por `python eval/run_eval.py --relatorio`.",
        "> Não editar à mão.",
        "",
        "## Métricas",
        "",
        "| Métrica | Resultado | O que mede |",
        "| --- | --- | --- |",
        f"| Taxa de aprovação | {_fmt(metricas['taxa_aprovacao'])} | "
        "casos que passaram em todas as checagens aplicáveis |",
        f"| Acurácia de intenção | {_fmt(metricas['acuracia_intencao'])} | "
        "a pergunta caiu na rota correta |",
        f"| Cobertura de termos | {_fmt(metricas['cobertura_termos'])} | "
        "a resposta contém a informação-chave esperada |",
        f"| Precisão de citação | {_fmt(metricas['precisao_citacao'])} | "
        "a resposta cita as fontes que deveria |",
        f"| Groundedness | {_fmt(metricas['groundedness'])} | "
        "todo valor em reais citado existe nos fatos calculados |",
        f"| Ausência de promessa indevida | {_fmt(metricas['sem_promessa_indevida'])} | "
        "nenhuma promessa de retorno ou indicação de ativo |",
        f"| Recusa correta | {_fmt(metricas['recusa_correta'])} | "
        "pedidos fora de escopo e de dado sensível barrados |",
        f"| Abstenção correta | {_fmt(metricas['abstencao_correta'])} | "
        "perguntas fora da base receberam \"não sei\" |",
        f"| Latência p50 | {metricas['latencia_p50_ms']:.2f} ms | mediana por resposta |",
        f"| Latência p95 | {metricas['latencia_p95_ms']:.2f} ms | cauda de latência |",
        "",
        "## Por grupo de caso",
        "",
        "| Grupo | Aprovados | Total |",
        "| --- | --- | --- |",
    ]
    for grupo, dados in sorted(metricas["por_grupo"].items()):
        linhas.append(f"| {grupo} | {dados['aprovados']} | {dados['total']} |")

    reprovados = [r for r in resultados if not r["aprovado"]]
    linhas += ["", "## Casos reprovados", ""]
    if not reprovados:
        linhas.append("Nenhum caso reprovado nesta execução.")
    else:
        for r in reprovados:
            problemas = []
            if not r["intencao_ok"]:
                problemas.append(
                    f"intenção {r['intencao_obtida']} (esperava {r['intencao_esperada']})"
                )
            if r["termos_faltando"]:
                problemas.append(f"termos ausentes: {r['termos_faltando']}")
            if r["fontes_faltando"]:
                problemas.append(f"fontes ausentes: {r['fontes_faltando']}")
            if not r["grounded"]:
                problemas.append("valor não ancorado")
            if r["recusa_ok"] is False:
                problemas.append("deveria recusar")
            if r["abstencao_ok"] is False:
                problemas.append("abstenção incorreta")
            linhas.append(f"- **{r['id']}** — “{r['pergunta']}” → {'; '.join(problemas)}")

    return "\n".join(linhas) + "\n"


def main() -> int:
    detalhar_falhas = "--falhas" in sys.argv
    gravar = "--relatorio" in sys.argv

    dados = json.loads(DATASET.read_text(encoding="utf-8"))
    agente = AgenteBussola()

    resultados = [avaliar_caso(agente, caso) for caso in dados["casos"]]
    metricas = calcular_metricas(resultados)

    print(f"\nModo de geração: {agente.provedor.nome}")
    print(f"Casos: {metricas['total_casos']} | "
          f"Aprovados: {metricas['aprovados']} "
          f"({_fmt(metricas['taxa_aprovacao'])})\n")
    print(f"  Acurácia de intenção .......... {_fmt(metricas['acuracia_intencao'])}")
    print(f"  Cobertura de termos ........... {_fmt(metricas['cobertura_termos'])}")
    print(f"  Precisão de citação ........... {_fmt(metricas['precisao_citacao'])}")
    print(f"  Groundedness .................. {_fmt(metricas['groundedness'])}")
    print(f"  Sem promessa indevida ......... {_fmt(metricas['sem_promessa_indevida'])}")
    print(f"  Recusa correta ................ {_fmt(metricas['recusa_correta'])}")
    print(f"  Abstenção correta ............. {_fmt(metricas['abstencao_correta'])}")
    print(f"  Latência p50 / p95 ............ "
          f"{metricas['latencia_p50_ms']:.2f} ms / {metricas['latencia_p95_ms']:.2f} ms\n")

    reprovados = [r for r in resultados if not r["aprovado"]]
    if reprovados:
        print(f"Reprovados ({len(reprovados)}):")
        for r in reprovados:
            print(f"  - {r['id']}: {r['pergunta']}")
            if detalhar_falhas:
                print(f"      intenção: {r['intencao_obtida']} "
                      f"(esperava {r['intencao_esperada']})")
                if r["termos_faltando"]:
                    print(f"      termos ausentes: {r['termos_faltando']}")
                if r["fontes_faltando"]:
                    print(f"      fontes ausentes: {r['fontes_faltando']}")
                if r["violacoes"]:
                    print(f"      violações: {r['violacoes']}")
                print(f"      resposta: {r['resposta'][:200]}...")
        print()

    if gravar:
        RELATORIO.write_text(
            gerar_relatorio(metricas, resultados, agente.provedor.nome),
            encoding="utf-8",
        )
        print(f"Relatório gravado em {RELATORIO.relative_to(RAIZ)}\n")

    return 0 if not reprovados else 1


if __name__ == "__main__":
    raise SystemExit(main())
