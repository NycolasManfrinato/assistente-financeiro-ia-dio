"""Orquestrador do agente Bússola.

Fluxo de cada turno:

    pergunta
       -> guardrail de entrada (dado sensível / fora de escopo)
       -> classificação de intenção
       -> roteamento para um handler
            handler = cálculo determinístico + recuperação de trechos
       -> montagem da resposta base (template, sempre disponível)
       -> [opcional] redação pelo LLM com os fatos já calculados
       -> guardrail de saída (ancoragem numérica + promessas proibidas)
       -> resposta final + fontes + traço de auditoria
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from . import config, financas, guardrails, prompts
from .financas import brl, pct
from .intent import Intencao, classificar
from .kb import BaseConhecimento, carregar
from .llm import ProvedorBase, obter_provedor
from .retriever import Indice


@dataclass
class Resposta:
    texto: str
    intencao: str
    confianca: float
    fontes: list[str] = field(default_factory=list)
    fatos: dict[str, Any] = field(default_factory=dict)
    trechos: list[dict[str, str]] = field(default_factory=list)
    provedor: str = "deterministico"
    abstencao: bool = False
    violacoes: list[str] = field(default_factory=list)
    #: No modo determinístico a resposta sai em fração de milissegundo, então
    #: o campo é float — arredondar para int zeraria a métrica.
    latencia_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "texto": self.texto,
            "intencao": self.intencao,
            "confianca": self.confianca,
            "fontes": self.fontes,
            "provedor": self.provedor,
            "abstencao": self.abstencao,
            "violacoes": self.violacoes,
            "latencia_ms": self.latencia_ms,
        }


@dataclass
class _Rascunho:
    """Saída de um handler, antes da redação e validação."""

    texto: str
    fatos: dict[str, Any] = field(default_factory=dict)
    fontes: list[str] = field(default_factory=list)
    usar_llm: bool = True
    abstencao: bool = False


#: Rótulos legíveis para os valores enumerados da base.
ROTULOS = {
    "diaria": "diária",
    "no_vencimento": "só no vencimento",
    "nao_aplicavel": "não se aplica",
    "muito_baixo": "muito baixo",
    "medio": "médio",
    "reserva_emergencia": "reserva de emergência",
    "curto_prazo": "curto prazo",
    "medio_prazo": "médio prazo",
    "longo_prazo": "longo prazo",
    "quitacao_divida": "quitação de dívida",
    "alimentacao": "alimentação",
    "saude": "saúde",
    "educacao": "educação",
    "vestuario": "vestuário",
    "servicos_financeiros": "serviços financeiros",
}


def rotulo(valor: str) -> str:
    return ROTULOS.get(valor, valor.replace("_", " "))


def _linha_fonte(fontes: list[str]) -> str:
    unicas = sorted(set(fontes))
    return "\n\nFonte: " + "; ".join(unicas) if unicas else ""


class AgenteBussola:
    def __init__(
        self,
        base: BaseConhecimento | None = None,
        provedor: ProvedorBase | None = None,
    ) -> None:
        self.kb = base or carregar()
        self.indice = Indice(self.kb.documentos)
        # Índice separado só com o material conceitual: perguntas de definição
        # não devem recuperar a ficha técnica de um produto.
        self.indice_conceitos = Indice(
            [d for d in self.kb.documentos if d.tipo == "conceito"]
        )
        self.provedor = provedor or obter_provedor()
        self._handlers: dict[str, Callable[[str, Intencao], _Rascunho]] = {
            "saudacao": self._h_saudacao,
            "despedida": self._h_despedida,
            "capacidades": self._h_capacidades,
            "gastos_resumo": self._h_gastos_resumo,
            "gastos_categoria": self._h_gastos_categoria,
            "assinaturas": self._h_assinaturas,
            "reserva_emergencia": self._h_reserva,
            "produtos": self._h_produtos,
            "divida": self._h_divida,
            "simulacao": self._h_simulacao,
            "conceito": self._h_conceito,
            "historico_atendimento": self._h_atendimentos,
        }

    # ------------------------------------------------------------------
    # Entrada principal
    # ------------------------------------------------------------------

    def responder(self, pergunta: str) -> Resposta:
        inicio = time.perf_counter()
        intencao = classificar(pergunta)

        if intencao.nome == "risco_seguranca":
            return self._finalizar(
                _Rascunho(guardrails.resposta_dado_sensivel(), usar_llm=False),
                intencao, pergunta, [], inicio,
            )

        if intencao.nome == "fora_de_escopo":
            return self._finalizar(
                _Rascunho(
                    guardrails.resposta_fora_de_escopo(intencao.motivo),
                    usar_llm=False,
                ),
                intencao, pergunta, [], inicio,
            )

        resultados = self.indice.buscar(pergunta, top_k=config.TOP_K)
        relevantes = [
            r
            for r in resultados
            if r.score >= config.LIMIAR_RECUPERACAO
            and r.cobertura >= config.LIMIAR_COBERTURA
            and r.especificidade <= config.LIMIAR_ESPECIFICIDADE
        ]
        trechos = [
            {
                "id": r.documento.id,
                "titulo": r.documento.titulo,
                "texto": r.documento.texto,
                "fonte": r.documento.fonte,
                "score": round(r.score, 4),
            }
            for r in relevantes
        ]

        handler = self._handlers.get(intencao.nome)
        if handler is None:
            rascunho = self._h_desconhecida(pergunta, intencao, trechos)
        else:
            rascunho = handler(pergunta, intencao)

        return self._finalizar(rascunho, intencao, pergunta, trechos, inicio)

    # ------------------------------------------------------------------
    # Redação e validação
    # ------------------------------------------------------------------

    def _finalizar(
        self,
        rascunho: _Rascunho,
        intencao: Intencao,
        pergunta: str,
        trechos: list[dict[str, str]],
        inicio: float,
    ) -> Resposta:
        texto_final = rascunho.texto
        provedor_usado = "deterministico"
        violacoes: list[str] = []

        pode_gerar = (
            rascunho.usar_llm
            and self.provedor.nome != "deterministico"
            and not rascunho.abstencao
        )

        if pode_gerar:
            usuario = prompts.montar_prompt_usuario(
                pergunta=pergunta,
                intencao=intencao.nome,
                fatos=rascunho.fatos,
                trechos=[
                    {k: v for k, v in t.items() if k != "score"} for t in trechos
                ],
                fontes=rascunho.fontes,
            )
            saida = self.provedor.gerar(prompts.SYSTEM_PROMPT, usuario)
            if saida.texto:
                permitidos = guardrails.coletar_numeros_permitidos(rascunho.fatos)
                veredito = guardrails.validar_resposta(
                    saida.texto, permitidos, exige_fonte=bool(rascunho.fontes)
                )
                if veredito.aprovado:
                    texto_final = saida.texto
                    provedor_usado = saida.provedor
                else:
                    # Rejeita a redação do modelo e mantém o template.
                    violacoes = veredito.violacoes
            elif saida.erro:
                violacoes = [f"llm_indisponivel:{saida.erro}"]

        return Resposta(
            texto=texto_final,
            intencao=intencao.nome,
            confianca=intencao.confianca,
            fontes=sorted(set(rascunho.fontes)),
            fatos=rascunho.fatos,
            trechos=trechos,
            provedor=provedor_usado,
            abstencao=rascunho.abstencao,
            violacoes=violacoes,
            latencia_ms=round((time.perf_counter() - inicio) * 1000, 3),
        )

    # ------------------------------------------------------------------
    # Handlers — conversa
    # ------------------------------------------------------------------

    def _h_saudacao(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        return _Rascunho(
            "Oi! Eu sou a Bússola, sua assistente de educação financeira.\n\n"
            "Posso analisar seus gastos, checar sua reserva de emergência, "
            "comparar produtos do catálogo e simular juros. Por onde quer começar?",
            usar_llm=False,
        )

    def _h_despedida(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        return _Rascunho(
            "Por nada! Quando quiser revisar os gastos ou tirar outra dúvida, é só chamar.",
            usar_llm=False,
        )

    def _h_capacidades(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        return _Rascunho(
            "Eu sou a Bússola, uma assistente de educação financeira. Trabalho "
            "apenas com os dados da sua base — não executo nenhuma operação e "
            "nunca peço senha ou código.\n\n"
            "O que eu faço:\n"
            "- Resumo dos seus gastos por categoria e por mês\n"
            "- Diagnóstico da reserva de emergência\n"
            "- Identificação de assinaturas e cobranças recorrentes\n"
            "- Comparação das características dos produtos do catálogo\n"
            "- Simulação de juros compostos e do custo de uma dívida\n"
            "- Explicação de conceitos como CDI, FGC, liquidez e rotativo\n\n"
            "O que eu não faço: indicar ativo específico, prever mercado, "
            "prometer rentabilidade ou fazer declaração de imposto.",
            usar_llm=False,
        )

    # ------------------------------------------------------------------
    # Handlers — gastos
    # ------------------------------------------------------------------

    def _h_gastos_resumo(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        meses = int(intencao.entidades.get("meses", config.JANELA_MESES_PADRAO))
        meses = max(1, min(meses, 12))
        calc = financas.resumo_gastos(self.kb, meses)
        regra = financas.regra_50_30_20(self.kb, meses)
        v = calc.valores
        r = regra.valores

        top = list(v["por_categoria_media_mensal"].items())[:4]
        linhas = "\n".join(
            f"- {rotulo(categoria).capitalize()}: {brl(valor)} por mês"
            for categoria, valor in top
        )

        situacao = (
            f"Sobra {brl(v['saldo_medio_mensal'])} por mês."
            if v["saldo_medio_mensal"] >= 0
            else f"Faltam {brl(abs(v['saldo_medio_mensal']))} por mês para fechar a conta."
        )

        texto = (
            f"Nos últimos {v['meses_analisados']} meses você gastou em média "
            f"{brl(v['media_despesa_mensal'])} por mês, contra uma renda de "
            f"{brl(v['media_receita_mensal'])}. {situacao}\n\n"
            f"Onde o dinheiro foi:\n{linhas}\n\n"
            f"Na régua 50-30-20, suas necessidades estão em {pct(r['necessidades_pct'])} "
            f"da renda (alvo 50%) e seus desejos em {pct(r['desejos_pct'])} (alvo 30%)."
        )

        fontes = calc.fontes + regra.fontes
        return _Rascunho(
            texto + _linha_fonte(fontes),
            fatos={"resumo": v, "regra_50_30_20": r},
            fontes=fontes,
        )

    def _h_gastos_categoria(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        categoria = intencao.entidades.get("categoria")
        if not categoria:
            return self._h_gastos_resumo(pergunta, intencao)

        meses = int(intencao.entidades.get("meses", config.JANELA_MESES_PADRAO))
        meses = max(1, min(meses, 12))
        calc = financas.gastos_da_categoria(self.kb, categoria, meses)
        v = calc.valores

        if v["qtd_transacoes"] == 0:
            return _Rascunho(
                f"Não encontrei nenhum lançamento na categoria "
                f"{rotulo(categoria)} nos últimos {v['meses_analisados']} meses."
                + _linha_fonte(calc.fontes),
                fatos=v,
                fontes=calc.fontes,
            )

        detalhes = "\n".join(
            f"- {descricao}: {brl(valor)}"
            for descricao, valor in list(v["por_descricao"].items())[:5]
        )
        texto = (
            f"Em {rotulo(categoria)} você gastou {brl(v['total'])} nos "
            f"últimos {v['meses_analisados']} meses, ou seja {brl(v['media_mensal'])} "
            f"por mês, em {v['qtd_transacoes']} lançamentos.\n\n"
            f"Composição:\n{detalhes}"
        )
        return _Rascunho(texto + _linha_fonte(calc.fontes), fatos=v, fontes=calc.fontes)

    def _h_assinaturas(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        calc = financas.assinaturas_recorrentes(self.kb)
        v = calc.valores
        ativas = v["assinaturas_ativas"]

        if not ativas:
            return _Rascunho(
                "Não identifiquei cobranças recorrentes de assinatura na sua base."
                + _linha_fonte(calc.fontes),
                fatos=v,
                fontes=calc.fontes,
            )

        linhas = "\n".join(
            f"- {a['descricao']}: {brl(a['valor_mensal'])} por mês "
            f"(cobrada desde {a['primeiro_mes']})"
            for a in ativas
        )
        texto = (
            f"Você tem {len(ativas)} assinaturas ativas em {v['mes_referencia']}, "
            f"somando {brl(v['custo_mensal_assinaturas_ativas'])} por mês — "
            f"{brl(v['custo_anual_assinaturas_ativas'])} em um ano.\n\n"
            f"{linhas}\n\n"
            "Vale olhar quais você realmente usou no último mês. Cancelar o que "
            "está parado é a economia mais rápida de conseguir, porque não exige "
            "mudar nenhum hábito."
        )
        return _Rascunho(texto + _linha_fonte(calc.fontes), fatos=v, fontes=calc.fontes)

    # ------------------------------------------------------------------
    # Handlers — reserva, produtos, dívida
    # ------------------------------------------------------------------

    def _h_reserva(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        calc = financas.diagnostico_reserva(self.kb)
        v = calc.valores

        if v["completa"]:
            texto = (
                f"Sua reserva está completa: {brl(v['valor_atual'])} para uma meta de "
                f"{brl(v['valor_alvo'])}, o equivalente a {v['meta_meses']} meses de "
                f"custo fixo."
            )
            return _Rascunho(
                texto + _linha_fonte(calc.fontes), fatos=v, fontes=calc.fontes
            )

        # Quanto tempo para fechar a meta guardando a sobra atual?
        resumo = financas.resumo_gastos(self.kb, config.JANELA_MESES_PADRAO).valores
        sobra = max(resumo["saldo_medio_mensal"], 0.0)
        prazo = financas.prazo_para_meta(
            v["valor_atual"], v["valor_alvo"], sobra if sobra > 0 else 200.0
        )

        if sobra > 0:
            ritmo = (
                f"Guardando os {brl(sobra)} que sobram por mês, você fecha a meta em "
                f"cerca de {prazo.valores['meses']} meses."
            )
        else:
            ritmo = (
                "Hoje não sobra dinheiro no fim do mês, então a reserva não tem de "
                "onde crescer. O primeiro passo é abrir espaço no orçamento — posso "
                "te mostrar onde estão os maiores gastos."
            )

        texto = (
            f"Sua reserva cobre {str(v['cobertura_meses']).replace('.', ',')} meses "
            f"de custo fixo. Você tem "
            f"{brl(v['valor_atual'])} e a meta de {v['meta_meses']} meses pede "
            f"{brl(v['valor_alvo'])} — faltam {brl(v['falta'])}.\n\n{ritmo}\n\n"
            "Reserva de emergência precisa de liquidez, não de rentabilidade: o "
            "dinheiro tem que estar disponível no dia em que o imprevisto acontece."
        )
        fontes = calc.fontes + ["data/transacoes.csv"]
        return _Rascunho(
            texto + _linha_fonte(fontes),
            fatos={"reserva": v, "prazo": prazo.valores, "sobra_mensal": round(sobra, 2)},
            fontes=fontes,
        )

    def _h_produtos(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        texto_norm = pergunta.lower()
        finalidade = None
        if "reserva" in texto_norm or "emerg" in texto_norm:
            finalidade = "reserva_emergencia"

        calc = financas.produtos_compativeis(self.kb, finalidade)
        v = calc.valores

        if not v["elegiveis"]:
            return _Rascunho(
                "Nenhum produto do catálogo atende ao seu perfil e às suas "
                "restrições para essa finalidade." + _linha_fonte(calc.fontes),
                fatos=v,
                fontes=calc.fontes,
                abstencao=True,
            )

        linhas = []
        for produto in v["elegiveis"]:
            rent = produto["rentabilidade_referencia"] or "sem rentabilidade definida"
            linhas.append(
                f"- **{produto['nome']}** — {rent}, liquidez {rotulo(produto['liquidez'])}, "
                f"risco {rotulo(produto['risco'])}, {produto['tributacao']}"
            )

        bloqueio = ""
        if v["bloqueados"]:
            itens = "; ".join(
                f"{b['nome']} ({b['motivos'][0]})" for b in v["bloqueados"][:3]
            )
            bloqueio = f"\n\nFicaram de fora: {itens}."

        alvo = " para reserva de emergência" if finalidade else ""
        texto = (
            f"Considerando seu perfil {v['perfil_cliente']} e a restrição de não "
            f"aceitar produtos com carência, estes são os produtos do catálogo "
            f"compatíveis{alvo}:\n\n" + "\n".join(linhas) + bloqueio + "\n\n"
            "Comparo características, mas a escolha é sua — e nenhum desses "
            "produtos garante retorno."
        )
        return _Rascunho(texto + _linha_fonte(calc.fontes), fatos=v, fontes=calc.fontes)

    def _h_divida(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        # Saldo: o informado na pergunta ou o estimado pelos juros lançados.
        saldo_informado = intencao.entidades.get("valor")
        if saldo_informado and float(saldo_informado) >= 100:
            saldo = float(saldo_informado)
            origem = "valor que você informou"
        else:
            juros = financas.gastos_da_categoria(
                self.kb, "servicos_financeiros", meses=1
            ).valores
            rotativo = self.kb.produto_por_id("PROD-008")
            saldo = round(juros["total"] / rotativo["taxa_juros_mes"], 2) if juros["total"] else 0.0
            origem = "saldo estimado a partir dos juros lançados na sua fatura"

        if saldo <= 0:
            return _Rascunho(
                "Não encontrei lançamentos de juros de rotativo na sua base, então "
                "não consigo estimar uma dívida de cartão. Se quiser, me diga o "
                "valor e eu simulo o custo." + _linha_fonte(["data/transacoes.csv"]),
                fatos={"saldo": 0.0},
                fontes=["data/transacoes.csv"],
            )

        meses = int(intencao.entidades.get("meses", 12))
        meses = max(1, min(meses, 60))
        calc = financas.comparar_credito(self.kb, saldo, meses)
        v = calc.valores

        texto = (
            f"Trabalhando com {brl(v['saldo'])} de dívida ({origem}), veja o que "
            f"acontece em {meses} meses:\n\n"
            f"- **Rotativo do cartão** ({pct(v['rotativo']['taxa_mensal'], 2)} ao mês): "
            f"vira {brl(v['rotativo']['montante_final'])}, sendo "
            f"{brl(v['rotativo']['juros_pagos'])} só de juros — "
            f"{str(v['rotativo']['multiplicador']).replace('.', ',')}x o valor original.\n"
            f"- **Portabilidade para crédito pessoal** "
            f"({pct(v['portabilidade']['taxa_mensal'], 2)} ao mês): "
            f"vira {brl(v['portabilidade']['montante_final'])}.\n\n"
            f"A diferença entre os dois caminhos é de {brl(v['economia'])}.\n\n"
            "O rotativo é a linha de crédito mais cara que existe. Antes de "
            "investir qualquer valor, faz mais sentido matar essa dívida — "
            "nenhuma aplicação do catálogo rende perto disso."
        )
        return _Rascunho(texto + _linha_fonte(calc.fontes), fatos=v, fontes=calc.fontes)

    def _h_simulacao(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        entidades = intencao.entidades
        capital = float(entidades.get("valor", 1000.0))
        meses = int(entidades.get("meses", 12))
        meses = max(1, min(meses, 600))

        # Taxa de referência: o produto elegível de maior rentabilidade.
        compativeis = financas.produtos_compativeis(self.kb).valores["elegiveis"]
        referencia = next(
            (p for p in compativeis if p["rentabilidade_estimada_ano"]), None
        )
        if referencia is None:
            return _Rascunho(
                "Não tenho um produto com rentabilidade estimada na base para usar "
                "como referência da simulação.",
                abstencao=True,
            )

        taxa_mensal = financas.taxa_anual_para_mensal(
            referencia["rentabilidade_estimada_ano"]
        )
        calc = financas.juros_compostos(capital, taxa_mensal, meses)
        v = calc.valores

        texto = (
            f"Simulando {brl(capital)} por {meses} meses na referência do "
            f"**{referencia['nome']}** ({referencia['rentabilidade_referencia']}, "
            f"estimativa de {pct(referencia['rentabilidade_estimada_ano'])} ao ano):\n\n"
            f"- Montante final: {brl(v['montante_final'])}\n"
            f"- Rendimento bruto: {brl(v['rendimento'])}\n\n"
            "Importante: é uma projeção com taxa constante, sem desconto de "
            "imposto de renda. A taxa real varia com a Selic e o resultado pode "
            "ser diferente."
        )
        fontes = calc.fontes + [referencia["fonte"]]
        return _Rascunho(
            texto + _linha_fonte(fontes),
            fatos={**v, "produto_referencia": referencia},
            fontes=fontes,
        )

    # ------------------------------------------------------------------
    # Handlers — conhecimento
    # ------------------------------------------------------------------

    def _h_conceito(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        resultados = self.indice_conceitos.buscar(pergunta, top_k=2)
        # Além do score, exige que a consulta tenha casado em algum termo
        # discriminativo — senão "taxa de câmbio do iene" recupera o verbete de
        # CDI só pela palavra "taxa".
        relevantes = [
            r
            for r in resultados
            if r.score >= config.LIMIAR_RECUPERACAO
            and r.cobertura >= config.LIMIAR_COBERTURA
            and r.especificidade <= config.LIMIAR_ESPECIFICIDADE
        ]
        if not relevantes:
            # Sem material conceitual: tenta o índice completo antes de desistir.
            gerais = [
                r
                for r in self.indice.buscar(pergunta, top_k=1)
                if r.score >= config.LIMIAR_RECUPERACAO
                and r.cobertura >= config.LIMIAR_COBERTURA
                and r.especificidade <= config.LIMIAR_ESPECIFICIDADE
            ]
            if not gerais:
                return self._abster()
            documento = gerais[0].documento
            return _Rascunho(
                documento.texto + _linha_fonte([documento.fonte]),
                fontes=[documento.fonte],
            )

        principal = relevantes[0].documento
        texto = principal.texto
        fontes = [principal.fonte]

        # Só encadeia um segundo conceito se ele for de fato próximo.
        if len(relevantes) > 1 and relevantes[1].score >= relevantes[0].score * 0.6:
            secundario = relevantes[1].documento
            texto += f"\n\nRelacionado — {secundario.titulo}: {secundario.texto}"
            fontes.append(secundario.fonte)

        return _Rascunho(texto + _linha_fonte(fontes), fatos={}, fontes=fontes)

    def _h_atendimentos(self, pergunta: str, intencao: Intencao) -> _Rascunho:
        atendimentos = sorted(self.kb.atendimentos, key=lambda a: a["data"], reverse=True)
        recentes = atendimentos[:3]
        abertos = [a for a in atendimentos if a["resolvido"] == "nao"]

        linhas = "\n".join(
            f"- {a['data']} ({a['canal']}) — {a['assunto']}: {a['resumo']} "
            f"[{'resolvido' if a['resolvido'] == 'sim' else 'em aberto'}]"
            for a in recentes
        )
        texto = (
            f"Seus três atendimentos mais recentes:\n\n{linhas}\n\n"
            f"No total, {len(abertos)} de {len(atendimentos)} atendimentos "
            f"continuam em aberto."
        )
        return _Rascunho(
            texto + _linha_fonte(["data/historico_atendimento.csv"]),
            fatos={
                "total": len(atendimentos),
                "em_aberto": len(abertos),
                "recentes": recentes,
            },
            fontes=["data/historico_atendimento.csv"],
        )

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _abster(self) -> _Rascunho:
        return _Rascunho(
            "Não encontrei essa informação na minha base, então prefiro não "
            "arriscar uma resposta.\n\n"
            "O que eu consigo fazer: analisar seus gastos por categoria, "
            "diagnosticar a reserva de emergência, listar assinaturas "
            "recorrentes, comparar os produtos do catálogo, simular juros e "
            "explicar conceitos como CDI, FGC, liquidez e rotativo.",
            usar_llm=False,
            abstencao=True,
        )

    def _h_desconhecida(
        self, pergunta: str, intencao: Intencao, trechos: list[dict[str, str]]
    ) -> _Rascunho:
        if not trechos:
            return self._abster()
        # Houve recuperação relevante mesmo sem intenção clara: responde pelo
        # conteúdo recuperado, sem inventar cálculo.
        principal = trechos[0]
        return _Rascunho(
            f"{principal['texto']}" + _linha_fonte([principal["fonte"]]),
            fontes=[principal["fonte"]],
        )
