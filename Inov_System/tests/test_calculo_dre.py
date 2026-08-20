"""
Testa a matemática do DRE com números escolhidos a mão, onde o resultado
esperado pode ser conferido de cabeça. É a rede de proteção da regra de
negócio: se alguém mexer no motor de cálculo, isso quebra antes de chegar
num DRE entregue ao cliente.
"""

import unittest

from tests.apoio import BaseComBancoTemporario

from dre import calcular_dre_obra, calcular_dre_consolidado, buscar_taxas_vigentes
import db


MESES_2026 = [(2026, m) for m in range(1, 13)]


class TestCalculoBasico(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        self.empresa_id = self.criar_empresa()
        self.obra_id = self.criar_obra(self.empresa_id)

        # Taxas redondas: 10% sobre receita, 1% sobre receita,
        # 5% sobre custo e 2% sobre custo.
        self.definir_taxa("impostos_servicos", 10.0, "receita")
        self.definir_taxa("irpj_csll", 1.0, "receita")
        self.definir_taxa("despesa_administrativa", 5.0, "custo")
        self.definir_taxa("despesa_financeira", 2.0, "custo")

    def test_receita_menos_custo_da_lucro_bruto(self):
        self.lancar(self.obra_id, "Serviços prestados", 1, 2026, 100000.0)
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 40000.0)

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"][(2026, 1)]

        self.assertEqual(totais["receita_total"], 100000.0)
        self.assertEqual(totais["custos_total"], 40000.0)
        self.assertEqual(totais["lucro_bruto"], 60000.0)

    def test_deducoes_usam_a_base_de_calculo_correta(self):
        """Impostos e IRPJ incidem sobre a receita; adm. e financeira sobre o custo."""
        self.lancar(self.obra_id, "Serviços prestados", 1, 2026, 100000.0)
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 40000.0)

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"][(2026, 1)]

        self.assertAlmostEqual(totais["impostos_servicos"], 10000.0, places=6)   # 10% de 100.000
        self.assertAlmostEqual(totais["irpj_csll"], 1000.0, places=6)            # 1%  de 100.000
        self.assertAlmostEqual(totais["despesa_administrativa"], 2000.0, places=6)  # 5% de 40.000
        self.assertAlmostEqual(totais["despesa_financeira"], 800.0, places=6)    # 2%  de 40.000

    def test_lucro_liquido_desconta_as_quatro_deducoes(self):
        self.lancar(self.obra_id, "Serviços prestados", 1, 2026, 100000.0)
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 40000.0)

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"][(2026, 1)]

        # 60.000 - (10.000 + 1.000 + 2.000 + 800)
        self.assertAlmostEqual(totais["lucro_liquido"], 46200.0, places=6)

    def test_prejuizo_quando_custo_supera_receita(self):
        self.lancar(self.obra_id, "Serviços prestados", 3, 2026, 10000.0)
        self.lancar(self.obra_id, "Salarios e Ordenados", 3, 2026, 25000.0)

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"][(2026, 3)]

        self.assertEqual(totais["lucro_bruto"], -15000.0)
        self.assertLess(totais["lucro_liquido"], -15000.0)

    def test_acumulado_soma_todos_os_meses(self):
        for mes in (1, 2, 3):
            self.lancar(self.obra_id, "Serviços prestados", mes, 2026, 1000.0)
            self.lancar(self.obra_id, "Salarios e Ordenados", mes, 2026, 400.0)

        acumulado = calcular_dre_obra(self.obra_id, MESES_2026)["acumulado"]

        self.assertEqual(acumulado["receita_total"], 3000.0)
        self.assertEqual(acumulado["custos_total"], 1200.0)
        self.assertEqual(acumulado["lucro_bruto"], 1800.0)

    def test_lancamento_de_outro_ano_nao_entra(self):
        self.lancar(self.obra_id, "Serviços prestados", 1, 2025, 999999.0)
        self.lancar(self.obra_id, "Serviços prestados", 1, 2026, 1000.0)

        acumulado = calcular_dre_obra(self.obra_id, MESES_2026)["acumulado"]

        self.assertEqual(acumulado["receita_total"], 1000.0)

    def test_campo_total_por_categoria_bate_com_a_soma_dos_meses(self):
        for mes in (1, 2, 5):
            self.lancar(self.obra_id, "Salarios e Ordenados", mes, 2026, 100.0)

        categorias = calcular_dre_obra(self.obra_id, MESES_2026)["categorias"]
        salarios = next(c for c in categorias if c["nome"] == "Salarios e Ordenados")

        self.assertEqual(salarios["total"], 300.0)
        self.assertEqual(salarios["total"], sum(salarios["valores"].values()))

    def test_categoria_inativa_fica_fora_do_calculo(self):
        self.lancar(self.obra_id, "Serviços prestados", 1, 2026, 5000.0)
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 1000.0)

        with self.conectar() as conn:
            conn.execute("UPDATE categorias_conta SET ativo = 0 WHERE nome = 'Salarios e Ordenados'")
            conn.commit()

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"][(2026, 1)]
        self.assertEqual(totais["custos_total"], 0.0)


class TestVigenciaDeTaxas(BaseComBancoTemporario):
    """
    A vigência é o que garante que reajustar uma taxa hoje não reescreve o
    resultado de meses já fechados e entregues.
    """

    def setUp(self):
        super().setUp()
        self.empresa_id = self.criar_empresa()
        self.obra_id = self.criar_obra(self.empresa_id)
        self.zerar_taxas()

    def test_mes_antigo_mantem_a_taxa_da_epoca(self):
        # 10% até maio/2026; 20% de junho/2026 em diante
        self.definir_taxa("impostos_servicos", 10.0, "receita", inicio="2020-01", fim="2026-05")
        with self.conectar() as conn:
            conn.execute(
                """INSERT INTO taxas (chave, descricao, percentual, base_calculo, vigencia_inicio, vigencia_fim)
                   VALUES ('impostos_servicos', 'nova', 20.0, 'receita', '2026-06', NULL)"""
            )
            conn.commit()

        self.lancar(self.obra_id, "Serviços prestados", 5, 2026, 1000.0)
        self.lancar(self.obra_id, "Serviços prestados", 6, 2026, 1000.0)

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"]

        self.assertAlmostEqual(totais[(2026, 5)]["impostos_servicos"], 100.0, places=6)
        self.assertAlmostEqual(totais[(2026, 6)]["impostos_servicos"], 200.0, places=6)

    def test_taxa_ausente_nao_gera_deducao(self):
        self.lancar(self.obra_id, "Serviços prestados", 1, 2026, 1000.0)

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"][(2026, 1)]

        self.assertEqual(totais["impostos_servicos"], 0.0)
        self.assertEqual(totais["lucro_liquido"], totais["lucro_bruto"])

    def test_busca_de_taxa_respeita_o_limite_da_vigencia(self):
        self.definir_taxa("irpj_csll", 3.0, "receita", inicio="2026-03", fim="2026-04")

        with self.conectar() as conn:
            cur = conn.cursor()
            self.assertNotIn("irpj_csll", buscar_taxas_vigentes(cur, 2026, 2))
            self.assertIn("irpj_csll", buscar_taxas_vigentes(cur, 2026, 3))
            self.assertIn("irpj_csll", buscar_taxas_vigentes(cur, 2026, 4))
            self.assertNotIn("irpj_csll", buscar_taxas_vigentes(cur, 2026, 5))


class TestConsolidado(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        self.zerar_taxas()
        self.definir_taxa("impostos_servicos", 10.0, "receita")

        self.empresa_a = self.criar_empresa("EMPRESA A")
        self.empresa_b = self.criar_empresa("EMPRESA B")
        self.obra_a1 = self.criar_obra(self.empresa_a, "A1", "OBRA A1")
        self.obra_a2 = self.criar_obra(self.empresa_a, "A2", "OBRA A2")
        self.obra_b1 = self.criar_obra(self.empresa_b, "B1", "OBRA B1")

        self.lancar(self.obra_a1, "Serviços prestados", 1, 2026, 1000.0)
        self.lancar(self.obra_a2, "Serviços prestados", 1, 2026, 2000.0)
        self.lancar(self.obra_b1, "Serviços prestados", 1, 2026, 5000.0)

    def test_consolidado_soma_as_obras_pedidas(self):
        resultado = calcular_dre_consolidado([self.obra_a1, self.obra_a2], MESES_2026)
        self.assertEqual(resultado["acumulado"]["receita_total"], 3000.0)

    def test_por_obra_fecha_com_o_acumulado(self):
        ids = [self.obra_a1, self.obra_a2, self.obra_b1]
        resultado = calcular_dre_consolidado(ids, MESES_2026)

        soma = sum(v["lucro_liquido"] for v in resultado["por_obra"].values())
        self.assertAlmostEqual(soma, resultado["acumulado"]["lucro_liquido"], places=6)
        self.assertEqual(set(resultado["por_obra"]), set(ids))

    def test_consolidar_uma_empresa_nao_inclui_a_outra(self):
        """Regressão: /totais somava as obras de todas as empresas juntas."""
        so_empresa_a = calcular_dre_consolidado([self.obra_a1, self.obra_a2], MESES_2026)
        todas = calcular_dre_consolidado([self.obra_a1, self.obra_a2, self.obra_b1], MESES_2026)

        self.assertEqual(so_empresa_a["acumulado"]["receita_total"], 3000.0)
        self.assertEqual(todas["acumulado"]["receita_total"], 8000.0)

    def test_consolidado_sem_obras_devolve_zeros(self):
        resultado = calcular_dre_consolidado([], MESES_2026)
        self.assertEqual(resultado["acumulado"]["receita_total"], 0)
        self.assertEqual(resultado["por_obra"], {})


if __name__ == "__main__":
    unittest.main()
