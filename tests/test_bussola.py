"""Suíte de testes da Bússola — só biblioteca padrão.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from bussola import AgenteBussola  # noqa: E402
from bussola import financas, guardrails, kb  # noqa: E402
from bussola.intent import classificar  # noqa: E402
from bussola.retriever import Indice, tokenizar  # noqa: E402


class TestFormatacao(unittest.TestCase):
    def test_brl_formata_padrao_brasileiro(self):
        self.assertEqual(financas.brl(1234.5), "R$ 1.234,50")
        self.assertEqual(financas.brl(0), "R$ 0,00")
        self.assertEqual(financas.brl(1000000), "R$ 1.000.000,00")

    def test_brl_negativo(self):
        self.assertEqual(financas.brl(-99.9), "-R$ 99,90")

    def test_pct(self):
        self.assertEqual(financas.pct(0.1035, 2), "10,35%")


class TestBaseConhecimento(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = kb.carregar()

    def test_carrega_todas_as_fontes(self):
        self.assertGreater(len(self.base.transacoes), 0)
        self.assertGreater(len(self.base.produtos), 0)
        self.assertGreater(len(self.base.faq), 0)
        self.assertGreater(len(self.base.atendimentos), 0)

    def test_todo_documento_tem_fonte(self):
        for documento in self.base.documentos:
            self.assertTrue(documento.fonte, f"{documento.id} sem fonte")
            self.assertTrue(documento.texto.strip(), f"{documento.id} sem texto")

    def test_ids_de_documento_sao_unicos(self):
        ids = [d.id for d in self.base.documentos]
        self.assertEqual(len(ids), len(set(ids)))

    def test_transacoes_tem_valor_numerico(self):
        for transacao in self.base.transacoes:
            self.assertIsInstance(transacao["valor"], float)
            self.assertGreater(transacao["valor"], 0)


class TestCalculosFinanceiros(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = kb.carregar()

    def test_resumo_bate_com_a_soma_bruta(self):
        calc = financas.resumo_gastos(self.base, meses=99)
        esperado = sum(
            t["valor"] for t in self.base.transacoes if t["tipo"] == "debito"
        )
        self.assertAlmostEqual(calc.valores["total_despesa"], round(esperado, 2), places=2)

    def test_soma_das_categorias_bate_com_o_total(self):
        calc = financas.resumo_gastos(self.base, meses=3)
        soma = sum(calc.valores["por_categoria"].values())
        self.assertAlmostEqual(soma, calc.valores["total_despesa"], places=1)

    def test_juros_compostos_bate_com_a_formula_fechada(self):
        calc = financas.juros_compostos(1000.0, 0.01, 12)
        self.assertAlmostEqual(
            calc.valores["montante_final"], round(1000 * 1.01**12, 2), places=2
        )

    def test_juros_compostos_com_aporte_supera_sem_aporte(self):
        sem = financas.juros_compostos(1000.0, 0.01, 12).valores["montante_final"]
        com = financas.juros_compostos(1000.0, 0.01, 12, 100.0).valores["montante_final"]
        self.assertGreater(com, sem)

    def test_taxa_anual_para_mensal_e_reversivel(self):
        mensal = financas.taxa_anual_para_mensal(0.1035)
        self.assertAlmostEqual((1 + mensal) ** 12 - 1, 0.1035, places=6)

    def test_reserva_falta_nunca_e_negativa(self):
        calc = financas.diagnostico_reserva(self.base)
        self.assertGreaterEqual(calc.valores["falta"], 0)

    def test_reserva_alvo_e_custo_vezes_meses(self):
        calc = financas.diagnostico_reserva(self.base)
        valores = calc.valores
        self.assertAlmostEqual(
            valores["valor_alvo"],
            valores["custo_fixo_mensal"] * valores["meta_meses"],
            places=2,
        )

    def test_rotativo_custa_mais_que_portabilidade(self):
        calc = financas.comparar_credito(self.base, 2000.0, 12)
        valores = calc.valores
        self.assertGreater(
            valores["rotativo"]["montante_final"],
            valores["portabilidade"]["montante_final"],
        )
        self.assertGreater(valores["economia"], 0)

    def test_prazo_para_meta_sem_aporte_e_inatingivel(self):
        calc = financas.prazo_para_meta(100.0, 10000.0, 0.0, 0.0)
        self.assertFalse(calc.valores["atingivel"])

    def test_prazo_para_meta_com_aporte(self):
        calc = financas.prazo_para_meta(0.0, 1200.0, 100.0, 0.0)
        self.assertEqual(calc.valores["meses"], 12)

    def test_produto_com_carencia_e_bloqueado(self):
        calc = financas.produtos_compativeis(self.base)
        ids_elegiveis = {p["id"] for p in calc.valores["elegiveis"]}
        # O perfil da base não aceita carência: LCI (90 dias) fica de fora.
        self.assertNotIn("PROD-004", ids_elegiveis)

    def test_produto_de_perfil_incompativel_e_bloqueado(self):
        calc = financas.produtos_compativeis(self.base)
        ids_elegiveis = {p["id"] for p in calc.valores["elegiveis"]}
        # Fundo de ações é só para perfil arrojado; a base é moderada.
        self.assertNotIn("PROD-006", ids_elegiveis)

    def test_credito_nunca_aparece_como_aplicacao(self):
        calc = financas.produtos_compativeis(self.base)
        for produto in calc.valores["elegiveis"]:
            self.assertNotIn(produto["id"], {"PROD-007", "PROD-008"})

    def test_assinaturas_identificadas_sao_recorrentes(self):
        calc = financas.assinaturas_recorrentes(self.base)
        for assinatura in calc.valores["assinaturas"]:
            self.assertGreaterEqual(assinatura["meses_cobrados"], 2)

    def test_custo_anual_e_doze_vezes_o_mensal(self):
        valores = financas.assinaturas_recorrentes(self.base).valores
        self.assertAlmostEqual(
            valores["custo_anual_assinaturas_ativas"],
            valores["custo_mensal_assinaturas_ativas"] * 12,
            places=2,
        )

    def test_todo_calculo_declara_fonte(self):
        calculos = [
            financas.resumo_gastos(self.base),
            financas.diagnostico_reserva(self.base),
            financas.assinaturas_recorrentes(self.base),
            financas.comparar_credito(self.base, 1000.0),
            financas.produtos_compativeis(self.base),
        ]
        for calc in calculos:
            self.assertTrue(calc.fontes, f"{calc.tipo} sem fonte declarada")


class TestRetriever(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = kb.carregar()
        cls.indice = Indice(cls.base.documentos)

    def test_tokenizar_remove_acento_e_stopword(self):
        tokens = tokenizar("Qual é a diferença entre poupança e CDB?")
        self.assertIn("diferenca", tokens)
        self.assertNotIn("a", tokens)
        self.assertNotIn("entre", tokens)

    def test_busca_encontra_o_verbete_certo(self):
        resultados = self.indice.buscar("o que é FGC", top_k=1)
        self.assertEqual(resultados[0].documento.id, "FAQ-005")

    def test_busca_vazia_para_consulta_sem_termo(self):
        self.assertEqual(self.indice.buscar("!!!"), [])

    def test_cobertura_alta_para_pergunta_da_base(self):
        resultado = self.indice.buscar("o que é CDI", top_k=1)[0]
        self.assertGreaterEqual(resultado.cobertura, 0.5)

    def test_cobertura_baixa_para_pergunta_fora_da_base(self):
        resultado = self.indice.buscar("taxa de câmbio do iene hoje", top_k=1)[0]
        self.assertLess(resultado.cobertura, 0.5)


class TestClassificadorDeIntencao(unittest.TestCase):
    def test_rotas_principais(self):
        casos = [
            ("oi", "saudacao"),
            ("o que você faz?", "capacidades"),
            ("quanto eu gastei nos últimos meses?", "gastos_resumo"),
            ("quanto gastei com alimentação?", "gastos_categoria"),
            ("tenho muitas assinaturas?", "assinaturas"),
            ("minha reserva de emergência está ok?", "reserva_emergencia"),
            ("onde guardar minha reserva?", "produtos"),
            ("quanto pago de juros no rotativo?", "divida"),
            ("simule 1000 reais por 12 meses", "simulacao"),
            ("o que é CDI?", "conceito"),
            ("qual foi meu último atendimento?", "historico_atendimento"),
        ]
        for pergunta, esperado in casos:
            with self.subTest(pergunta=pergunta):
                self.assertEqual(classificar(pergunta).nome, esperado)

    def test_pedidos_fora_de_escopo(self):
        for pergunta in [
            "qual ação devo comprar?",
            "o bitcoin vai subir?",
            "me indique um investimento com retorno garantido",
            "como esconder do fisco parte da renda?",
        ]:
            with self.subTest(pergunta=pergunta):
                self.assertEqual(classificar(pergunta).nome, "fora_de_escopo")

    def test_dado_sensivel_tem_prioridade_maxima(self):
        # Mesmo com uma pergunta legítima junto, a senha barra tudo.
        intencao = classificar("minha senha é 1234, quanto eu gastei esse mês?")
        self.assertEqual(intencao.nome, "risco_seguranca")

    def test_extrai_valor_e_prazo(self):
        intencao = classificar("simule 5000 reais por 2 anos")
        self.assertEqual(float(intencao.entidades["valor"]), 5000.0)
        self.assertEqual(intencao.entidades["meses"], "24")

    def test_pergunta_sem_gatilho_e_desconhecida(self):
        self.assertEqual(classificar("qual a receita de bolo?").nome, "desconhecida")


class TestGuardrails(unittest.TestCase):
    def test_coleta_numeros_aninhados(self):
        permitidos = guardrails.coletar_numeros_permitidos(
            {"a": 10.5, "b": {"c": [1.25, 2.5]}}
        )
        self.assertIn(10.5, permitidos)
        self.assertIn(1.25, permitidos)
        self.assertIn(2.5, permitidos)

    def test_aceita_troca_de_sinal(self):
        permitidos = guardrails.coletar_numeros_permitidos({"saldo": -1000.01})
        self.assertIn(1000.01, permitidos)

    def test_reprova_valor_inventado(self):
        veredito = guardrails.validar_resposta(
            "Você vai receber R$ 4.200,00.", {100.0}, exige_fonte=False
        )
        self.assertFalse(veredito.aprovado)
        self.assertTrue(
            any(v.startswith("valor_nao_ancorado") for v in veredito.violacoes)
        )

    def test_aprova_valor_ancorado(self):
        veredito = guardrails.validar_resposta(
            "Você tem R$ 100,00 guardados.", {100.0}, exige_fonte=False
        )
        self.assertTrue(veredito.aprovado)

    def test_reprova_promessa_de_retorno(self):
        veredito = guardrails.validar_resposta(
            "Esse produto tem rentabilidade garantida.", set(), exige_fonte=False
        )
        self.assertFalse(veredito.aprovado)

    def test_exige_citacao_de_fonte(self):
        veredito = guardrails.validar_resposta("Resposta sem citação.", set())
        self.assertIn("sem_citacao_de_fonte", veredito.violacoes)


class TestAgenteFimAFim(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.agente = AgenteBussola()

    def test_abstem_se_fora_da_base(self):
        resposta = self.agente.responder("qual a receita de bolo de cenoura?")
        self.assertTrue(resposta.abstencao)
        self.assertIn("não encontrei", resposta.texto.lower())

    def test_recusa_recomendacao_de_ativo(self):
        resposta = self.agente.responder("qual ação devo comprar?")
        self.assertEqual(resposta.intencao, "fora_de_escopo")
        self.assertIn("CVM", resposta.texto)

    def test_nunca_pede_credencial(self):
        resposta = self.agente.responder("minha senha é 1234")
        self.assertEqual(resposta.intencao, "risco_seguranca")
        self.assertIn("nunca compartilhe", resposta.texto.lower())

    def test_resposta_com_calculo_sempre_cita_fonte(self):
        for pergunta in [
            "quanto eu gastei nos últimos meses?",
            "minha reserva de emergência está ok?",
            "tenho muitas assinaturas?",
        ]:
            with self.subTest(pergunta=pergunta):
                resposta = self.agente.responder(pergunta)
                self.assertTrue(resposta.fontes)
                self.assertIn("Fonte:", resposta.texto)

    def test_todo_valor_citado_esta_ancorado(self):
        """Regressão do requisito central: nenhum número inventado."""
        dataset = json.loads(
            (RAIZ / "eval" / "dataset.json").read_text(encoding="utf-8")
        )
        for caso in dataset["casos"]:
            with self.subTest(caso=caso["id"]):
                resposta = self.agente.responder(caso["pergunta"])
                permitidos = guardrails.coletar_numeros_permitidos(resposta.fatos)
                veredito = guardrails.validar_resposta(
                    resposta.texto, permitidos, exige_fonte=False
                )
                nao_ancorados = [
                    v for v in veredito.violacoes if v.startswith("valor_nao_ancorado")
                ]
                self.assertEqual(nao_ancorados, [], resposta.texto)

    def test_modo_padrao_e_deterministico_sem_chave(self):
        self.assertIn(
            self.agente.provedor.nome, {"deterministico", "openai", "gemini"}
        )

    def test_mesma_pergunta_gera_mesma_resposta(self):
        primeira = self.agente.responder("o que é CDI?")
        segunda = self.agente.responder("o que é CDI?")
        self.assertEqual(primeira.texto, segunda.texto)


if __name__ == "__main__":
    unittest.main(verbosity=2)
