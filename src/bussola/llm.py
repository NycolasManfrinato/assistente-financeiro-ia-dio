"""Camada de LLM plugável.

O agente funciona em dois modos:

- **determinístico** (padrão, sem nenhuma chave): as respostas são montadas por
  template a partir dos fatos calculados. Roda em qualquer máquina, sem custo e
  sem rede — é o modo usado na avaliação automatizada, porque é reprodutível.
- **generativo**: se houver `OPENAI_API_KEY` ou `GEMINI_API_KEY` no ambiente, o
  mesmo contexto é enviado ao modelo, que apenas redige. Os fatos continuam
  vindo da camada determinística.

A chamada HTTP usa apenas a biblioteca padrão para não obrigar quem clonar o
repositório a instalar SDKs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass

from . import config


@dataclass
class RespostaLLM:
    texto: str | None
    provedor: str
    erro: str | None = None


class ProvedorBase:
    nome = "base"

    def disponivel(self) -> bool:
        raise NotImplementedError

    def gerar(self, system: str, usuario: str) -> RespostaLLM:
        raise NotImplementedError


class ProvedorDeterministico(ProvedorBase):
    """Não gera texto: sinaliza ao agente que ele deve usar o template."""

    nome = "deterministico"

    def disponivel(self) -> bool:
        return True

    def gerar(self, system: str, usuario: str) -> RespostaLLM:
        return RespostaLLM(texto=None, provedor=self.nome)


def _post_json(url: str, payload: dict, headers: dict) -> dict:
    dados = json.dumps(payload).encode("utf-8")
    requisicao = urllib.request.Request(url, data=dados, headers=headers, method="POST")
    with urllib.request.urlopen(
        requisicao, timeout=config.TIMEOUT_LLM_SEGUNDOS
    ) as resposta:
        return json.loads(resposta.read().decode("utf-8"))


class ProvedorOpenAI(ProvedorBase):
    nome = "openai"

    def disponivel(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY"))

    def gerar(self, system: str, usuario: str) -> RespostaLLM:
        try:
            corpo = _post_json(
                "https://api.openai.com/v1/chat/completions",
                {
                    "model": config.MODELO_OPENAI,
                    "temperature": config.TEMPERATURA,
                    "max_tokens": config.MAX_TOKENS,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": usuario},
                    ],
                },
                {
                    "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}",
                    "Content-Type": "application/json",
                },
            )
            texto = corpo["choices"][0]["message"]["content"].strip()
            return RespostaLLM(texto=texto, provedor=self.nome)
        except (urllib.error.URLError, KeyError, IndexError, TimeoutError) as erro:
            return RespostaLLM(texto=None, provedor=self.nome, erro=str(erro))


class ProvedorGemini(ProvedorBase):
    nome = "gemini"

    def disponivel(self) -> bool:
        return bool(os.getenv("GEMINI_API_KEY"))

    def gerar(self, system: str, usuario: str) -> RespostaLLM:
        try:
            url = (
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{config.MODELO_GEMINI}:generateContent"
                f"?key={os.environ['GEMINI_API_KEY']}"
            )
            corpo = _post_json(
                url,
                {
                    "systemInstruction": {"parts": [{"text": system}]},
                    "contents": [{"role": "user", "parts": [{"text": usuario}]}],
                    "generationConfig": {
                        "temperature": config.TEMPERATURA,
                        "maxOutputTokens": config.MAX_TOKENS,
                    },
                },
                {"Content-Type": "application/json"},
            )
            texto = corpo["candidates"][0]["content"]["parts"][0]["text"].strip()
            return RespostaLLM(texto=texto, provedor=self.nome)
        except (urllib.error.URLError, KeyError, IndexError, TimeoutError) as erro:
            return RespostaLLM(texto=None, provedor=self.nome, erro=str(erro))


PROVEDORES: dict[str, type[ProvedorBase]] = {
    "openai": ProvedorOpenAI,
    "gemini": ProvedorGemini,
    "deterministico": ProvedorDeterministico,
}


def obter_provedor(nome: str | None = None) -> ProvedorBase:
    escolha = (nome or config.PROVEDOR_LLM).lower()

    if escolha != "auto":
        classe = PROVEDORES.get(escolha, ProvedorDeterministico)
        provedor = classe()
        return provedor if provedor.disponivel() else ProvedorDeterministico()

    for classe in (ProvedorOpenAI, ProvedorGemini):
        provedor = classe()
        if provedor.disponivel():
            return provedor
    return ProvedorDeterministico()
