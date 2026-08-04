"""Configuração central do agente Bússola."""

from __future__ import annotations

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos
# ---------------------------------------------------------------------------

RAIZ = Path(__file__).resolve().parents[2]
DIR_DADOS = RAIZ / "data"
DIR_DOCS = RAIZ / "docs"
DIR_EVAL = RAIZ / "eval"

ARQ_TRANSACOES = DIR_DADOS / "transacoes.csv"
ARQ_PERFIL = DIR_DADOS / "perfil_investidor.json"
ARQ_PRODUTOS = DIR_DADOS / "produtos_financeiros.json"
ARQ_ATENDIMENTOS = DIR_DADOS / "historico_atendimento.csv"
ARQ_FAQ = DIR_DADOS / "faq.json"

# ---------------------------------------------------------------------------
# Identidade do agente
# ---------------------------------------------------------------------------

NOME_AGENTE = "Bússola"
VERSAO = "1.0.0"

# ---------------------------------------------------------------------------
# Parâmetros de recuperação e guardrails
# ---------------------------------------------------------------------------

#: Score mínimo de similaridade para considerar que houve evidência recuperada.
#: Abaixo disso o agente prefere abster-se a arriscar uma resposta.
LIMIAR_RECUPERACAO = 0.12

# --- Portões anti-alucinação da recuperação --------------------------------
#
# Similaridade sozinha não distingue "qual a taxa de câmbio do iene" de "o que
# é CDI": as duas casam com o verbete de CDI, a primeira só pela palavra
# genérica "taxa". Dois portões adicionais resolvem isso.

#: Fração mínima dos termos da pergunta que o documento precisa cobrir.
#: "taxa de câmbio do iene" cobre 1 de 4 termos no verbete de CDI (0,25) —
#: abaixo do limiar, o agente se abstém. Perguntas legítimas do conjunto de
#: avaliação ficam em 0,75 ou mais.
LIMIAR_COBERTURA = 0.5

#: Fração máxima do corpus em que o termo mais discriminativo da consulta pode
#: aparecer. Impede que o casamento aconteça só por uma palavra que está em
#: metade da base.
LIMIAR_ESPECIFICIDADE = 0.35

#: Número máximo de trechos da base enviados como contexto.
TOP_K = 4

#: Número máximo de meses considerados nas análises de gasto.
JANELA_MESES_PADRAO = 3

# ---------------------------------------------------------------------------
# Camada de LLM
# ---------------------------------------------------------------------------

#: "auto" escolhe o primeiro provedor com credencial disponível e cai
#: para o modo determinístico se não houver nenhuma.
PROVEDOR_LLM = os.getenv("BUSSOLA_LLM_PROVIDER", "auto")

MODELO_OPENAI = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MODELO_GEMINI = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")

TEMPERATURA = float(os.getenv("BUSSOLA_TEMPERATURE", "0.2"))
MAX_TOKENS = int(os.getenv("BUSSOLA_MAX_TOKENS", "700"))

TIMEOUT_LLM_SEGUNDOS = int(os.getenv("BUSSOLA_LLM_TIMEOUT", "30"))
