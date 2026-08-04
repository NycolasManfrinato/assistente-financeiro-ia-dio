"""Interface de chat da Bússola em Streamlit.

    pip install -r requirements.txt
    streamlit run src/app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from bussola import AgenteBussola, NOME_AGENTE, VERSAO  # noqa: E402
from bussola.financas import brl  # noqa: E402

st.set_page_config(page_title=f"{NOME_AGENTE} — educação financeira", page_icon="🧭")

SUGESTOES = [
    "Quanto eu gastei nos últimos meses?",
    "Minha reserva de emergência está ok?",
    "Tenho muitas assinaturas?",
    "Quanto pago de juros no rotativo?",
    "Onde guardar minha reserva?",
    "O que é CDI?",
]


@st.cache_resource(show_spinner="Carregando a base de conhecimento...")
def carregar_agente() -> AgenteBussola:
    return AgenteBussola()


agente = carregar_agente()

# ---------------------------------------------------------------------------
# Barra lateral
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🧭 " + NOME_AGENTE)
    st.caption(f"v{VERSAO} — Lab DIO: Assistente Virtual com IA")

    modo = agente.provedor.nome
    if modo == "deterministico":
        st.info(
            "**Modo determinístico**\n\n"
            "As respostas são montadas a partir dos cálculos da base, sem "
            "chamar nenhum modelo. Defina `OPENAI_API_KEY` ou `GEMINI_API_KEY` "
            "para ativar a redação por LLM."
        )
    else:
        st.success(f"**Modo generativo** — provedor `{modo}`")

    st.divider()

    perfil = agente.kb.perfil
    reserva = perfil["reserva_emergencia"]
    st.subheader("Cliente da base")
    st.write(f"Perfil: **{perfil['perfil_investidor']}**")
    st.write(f"Renda líquida: **{brl(perfil['renda_mensal_liquida'])}**")
    st.write(f"Reserva atual: **{brl(reserva['valor_atual'])}**")
    st.caption("Dados fictícios, criados apenas para o desafio.")

    st.divider()
    st.caption(
        "A Bússola não indica ativos, não prevê mercado e não executa "
        "operações. Conteúdo educacional."
    )

    if st.button("Limpar conversa", use_container_width=True):
        st.session_state.mensagens = []
        st.rerun()

# ---------------------------------------------------------------------------
# Conversa
# ---------------------------------------------------------------------------

st.title("Bússola")
st.caption("Assistente de educação financeira pessoal")

if "mensagens" not in st.session_state:
    st.session_state.mensagens = []

if not st.session_state.mensagens:
    st.markdown("**Por onde quer começar?**")
    colunas = st.columns(2)
    for indice, sugestao in enumerate(SUGESTOES):
        if colunas[indice % 2].button(sugestao, use_container_width=True):
            st.session_state.pendente = sugestao
            st.rerun()

for mensagem in st.session_state.mensagens:
    with st.chat_message(mensagem["papel"]):
        st.markdown(mensagem["texto"])
        if mensagem.get("meta"):
            with st.expander("Como cheguei nessa resposta"):
                st.json(mensagem["meta"])

pergunta = st.chat_input("Escreva sua pergunta...")
if "pendente" in st.session_state:
    pergunta = st.session_state.pop("pendente")

if pergunta:
    st.session_state.mensagens.append({"papel": "user", "texto": pergunta})
    with st.chat_message("user"):
        st.markdown(pergunta)

    with st.chat_message("assistant"):
        with st.spinner("Consultando a base..."):
            resposta = agente.responder(pergunta)
        st.markdown(resposta.texto)

        meta = {
            "intencao": resposta.intencao,
            "confianca": resposta.confianca,
            "provedor": resposta.provedor,
            "abstencao": resposta.abstencao,
            "latencia_ms": resposta.latencia_ms,
            "fontes": resposta.fontes,
            "trechos_recuperados": [
                {"id": t["id"], "titulo": t["titulo"], "score": t["score"]}
                for t in resposta.trechos
            ],
            "violacoes_guardrail": resposta.violacoes,
        }
        with st.expander("Como cheguei nessa resposta"):
            st.json(meta)

    st.session_state.mensagens.append(
        {"papel": "assistant", "texto": resposta.texto, "meta": meta}
    )
