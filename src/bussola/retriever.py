"""Recuperação de trechos da base de conhecimento.

Implementação de TF-IDF com similaridade de cosseno escrita à mão, sem
dependências externas. A escolha é deliberada: o repositório precisa rodar
com `python app.py` em qualquer máquina, e o volume de documentos (dezenas,
não milhões) não justifica um índice vetorial.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass

from .kb import Documento

# Stopwords do português que só adicionam ruído ao índice.
STOPWORDS = {
    "a", "ao", "aos", "as", "à", "às", "com", "como", "da", "das", "de", "do",
    "dos", "e", "é", "em", "entre", "essa", "esse", "esta", "este", "eu", "foi",
    "for", "isso", "já", "mais", "mas", "me", "meu", "minha", "muito", "na",
    "nas", "no", "nos", "num", "numa", "o", "os", "ou", "para", "pela", "pelo",
    "por", "qual", "quando", "que", "se", "sem", "ser", "seu", "sua", "são",
    "só", "também", "tem", "um", "uma", "vou", "eh", "pra", "pro", "the",
    "of", "sobre", "quanto", "quais", "onde", "qualquer", "seria", "posso",
    "devo", "tenho", "quero", "gostaria", "poderia", "favor", "voce", "você",
}

SUFIXOS_PLURAL = ("oes", "aes", "ais", "eis", "ns", "es", "s")


def normalizar(texto: str) -> str:
    """Minúsculas, sem acento e sem pontuação."""
    texto = texto.lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9%\s]", " ", texto)


def _radical(token: str) -> str:
    """Stemming bem leve: remove marca de plural comum do português."""
    if len(token) <= 4:
        return token
    for sufixo in SUFIXOS_PLURAL:
        if token.endswith(sufixo) and len(token) - len(sufixo) >= 3:
            return token[: -len(sufixo)]
    return token


def tokenizar(texto: str) -> list[str]:
    tokens = normalizar(texto).split()
    return [_radical(t) for t in tokens if t not in STOPWORDS and len(t) > 1]


@dataclass
class Resultado:
    documento: Documento
    score: float
    #: Termos da consulta que existem no documento, com a fração do corpus em
    #: que cada um aparece. Um termo presente em poucos documentos é
    #: discriminativo; um presente em quase todos não diz nada.
    termos_casados: dict[str, float] = None  # type: ignore[assignment]
    #: Quantidade de termos de conteúdo da consulta (após stopwords).
    total_termos_consulta: int = 0

    @property
    def especificidade(self) -> float:
        """Menor fração de corpus entre os termos casados (0 = muito específico).

        Responde a "a pergunta casou em algum termo que realmente distingue
        este documento dos outros?".
        """
        if not self.termos_casados:
            return 1.0
        return min(self.termos_casados.values())

    @property
    def cobertura(self) -> float:
        """Fração dos termos da consulta que o documento cobre.

        Responde a "este documento fala do que a pergunta perguntou, ou só de
        um pedaço solto dela?". "taxa de câmbio do iene" cobre 1 de 4 termos no
        verbete de CDI — sinal claro de que a base não tem essa resposta.
        """
        if not self.total_termos_consulta:
            return 0.0
        return len(self.termos_casados or {}) / self.total_termos_consulta


class Indice:
    """Índice TF-IDF em memória."""

    def __init__(self, documentos: list[Documento]) -> None:
        self.documentos = documentos
        self._tf: list[Counter[str]] = []
        self._idf: dict[str, float] = {}
        self._df: Counter[str] = Counter()
        self._normas: list[float] = []
        self._construir()

    def _construir(self) -> None:
        total = len(self.documentos)
        frequencia_doc: Counter[str] = Counter()

        for doc in self.documentos:
            # Título e tags pesam mais que o corpo: repetimos o título para
            # dar peso extra sem precisar de um esquema de campos separado.
            tags = " ".join(doc.metadados.get("tags", []) or [])
            bruto = f"{doc.titulo} {doc.titulo} {tags} {tags} {doc.texto}"
            tokens = tokenizar(bruto)
            contagem = Counter(tokens)
            self._tf.append(contagem)
            frequencia_doc.update(contagem.keys())

        self._df = frequencia_doc
        for termo, freq in frequencia_doc.items():
            # IDF suavizado
            self._idf[termo] = math.log((total + 1) / (freq + 1)) + 1.0

        for contagem in self._tf:
            self._normas.append(math.sqrt(sum(
                (peso * self._idf.get(termo, 0.0)) ** 2
                for termo, peso in contagem.items()
            )))

    def buscar(self, consulta: str, top_k: int = 4) -> list[Resultado]:
        tokens = tokenizar(consulta)
        if not tokens:
            return []

        consulta_tf = Counter(tokens)
        pesos_consulta = {
            termo: freq * self._idf.get(termo, 0.0)
            for termo, freq in consulta_tf.items()
        }
        norma_consulta = math.sqrt(sum(p * p for p in pesos_consulta.values()))
        if norma_consulta == 0:
            return []

        total_docs = len(self.documentos) or 1
        resultados: list[Resultado] = []
        for indice, contagem in enumerate(self._tf):
            norma_doc = self._normas[indice]
            if norma_doc == 0:
                continue
            produto = sum(
                peso * contagem.get(termo, 0) * self._idf.get(termo, 0.0)
                for termo, peso in pesos_consulta.items()
            )
            if produto <= 0:
                continue
            score = produto / (norma_consulta * norma_doc)
            casados = {
                termo: self._df.get(termo, 0) / total_docs
                for termo in pesos_consulta
                if contagem.get(termo, 0) > 0
            }
            resultados.append(
                Resultado(
                    self.documentos[indice],
                    score,
                    termos_casados=casados,
                    total_termos_consulta=len(pesos_consulta),
                )
            )

        resultados.sort(key=lambda r: r.score, reverse=True)
        return resultados[:top_k]
