"""
Regressão contra o banco real (database.db), que é o que foi conferido célula
a célula com a planilha da contabilidade.

Dois tipos de verificação:

  * **Invariantes** — relações que precisam valer sempre, com qualquer dado
    (lucro bruto = receita - custos, consolidado = soma das obras, etc.).
    Não dependem de valores específicos e não envelhecem.

  * **Valores travados** — números concretos de um ano fechado, congelados no estado
    validado. É o que pega uma alteração no motor de cálculo que mude o
    resultado sem ninguém perceber.

Se uma importação nova mudar legitimamente os dados do ano travado, os valores
travados vão acusar diferença. Nesse caso, confira os novos números contra a
planilha e regenere o bloco VALORES_TRAVADOS com:

    python -m tests.gerar_valores_travados

Os testes são pulados automaticamente quando o database.db não está presente
(ele não é versionado, por conter dados do cliente).
"""

import unittest
from contextlib import closing

from tests.apoio import banco_real_disponivel, BANCO_REAL

import db
from dre import calcular_dre_obra, calcular_dre_consolidado

# Ano de referência: 2024, um ano FECHADO.
#
# Antes isto usava 2026 e ficava vermelho toda vez que um relatório novo do
# Contimatic entrava — acusava dado novo como se fosse defeito e virava ruído
# que ninguém olha. Um ano que não recebe mais importação mantém o alarme
# útil: se ficar vermelho, foi o cálculo que mudou.
ANO_TRAVADO = 2024
MESES_TRAVADOS = [(ANO_TRAVADO, m) for m in range(1, 13)]

# Gerado a partir do banco validado. Ver instruções no topo do arquivo.
VALORES_TRAVADOS = {
    "285": dict(
        receita_total=1748907.67,
        custos_total=389167.75,
        lucro_bruto=1359739.92,
        impostos_servicos=229981.358605,
        irpj_csll=21336.673574,
        despesa_administrativa=21637.7269,
        despesa_financeira=38.916775,
        lucro_liquido=1086745.244146,
    ),
    "275": dict(
        receita_total=374503.5,
        custos_total=140286.39,
        lucro_bruto=234217.11,
        impostos_servicos=49247.21025,
        irpj_csll=4568.9427,
        despesa_administrativa=7799.923284,
        despesa_financeira=14.028639,
        lucro_liquido=172587.005127,
    ),
    "265": dict(
        receita_total=172252.53,
        custos_total=30042.84,
        lucro_bruto=142209.69,
        impostos_servicos=22651.207695,
        irpj_csll=2101.480866,
        despesa_administrativa=1670.381904,
        despesa_financeira=3.004284,
        lucro_liquido=115783.615251,
    ),
}

CONSOLIDADO_TRAVADO = dict(
    receita_total=2313026.32,
    custos_total=581398.42,
    lucro_bruto=1731627.9,
    impostos_servicos=304162.96108,
    irpj_csll=28218.921104,
    despesa_administrativa=32325.752152,
    despesa_financeira=58.139842,
    lucro_liquido=1366862.125822,
)


@unittest.skipUnless(banco_real_disponivel(), "database.db não disponível nesta máquina")
class BaseDadosReais(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls._banco_original = db.DATABASE
        db.DATABASE = BANCO_REAL

    @classmethod
    def tearDownClass(cls):
        db.DATABASE = cls._banco_original

    def obra_por_codigo(self, codigo):
        with closing(db.conectar()) as conn:
            row = conn.execute("SELECT id FROM obras WHERE codigo = ?", (codigo,)).fetchone()
        return row["id"] if row else None

    def todas_as_obras(self):
        with closing(db.conectar()) as conn:
            return [r["id"] for r in conn.execute("SELECT id FROM obras").fetchall()]


class TestValoresTravados(BaseDadosReais):

    def test_dre_das_obras_validadas_nao_mudou(self):
        for codigo, esperado in VALORES_TRAVADOS.items():
            obra_id = self.obra_por_codigo(codigo)
            if obra_id is None:
                self.skipTest(f"obra {codigo} não existe neste banco")

            acumulado = calcular_dre_obra(obra_id, MESES_TRAVADOS)["acumulado"]

            for campo, valor_esperado in esperado.items():
                with self.subTest(obra=codigo, campo=campo):
                    self.assertAlmostEqual(
                        acumulado[campo], valor_esperado, places=2,
                        msg=f"obra {codigo}, {campo}: o cálculo mudou",
                    )

    def test_consolidado_do_ano_travado_nao_mudou(self):
        acumulado = calcular_dre_consolidado(self.todas_as_obras(), MESES_TRAVADOS)["acumulado"]

        for campo, valor_esperado in CONSOLIDADO_TRAVADO.items():
            with self.subTest(campo=campo):
                self.assertAlmostEqual(
                    acumulado[campo], valor_esperado, places=2,
                    msg=f"consolidado de {ANO_TRAVADO}, {campo}: o cálculo mudou",
                )


class TestTotalGeralContraAPlanilha(BaseDadosReais):
    """
    A coluna "Acumulado" da planilha soma os períodos agregados MAIS os meses —
    o sistema mostrava só o ano, e era isso que a contabilidade lia como
    "não puxou os anos antigos". Os valores abaixo foram conferidos célula a
    célula na aba OBRA 251 do arquivo de Jun/2026.
    """

    # Soma das três colunas agregadas da aba OBRA 251 — "Março a Dez/23",
    # "Jan a Dez/24" e "Jan a Dez/2025" — conferida célula a célula.
    #
    # São blocos históricos: não recebem importação nova, então este valor é
    # estável. A coluna "Acumulado" inteira da planilha não serve de âncora,
    # porque ela inclui o ano corrente, que muda a cada relatório importado.
    PERIODOS_OBRA_251 = [
        ("Custos Total", "custos_total", 1026862.34),
        ("Lucro/Prejuízo Líquido", "lucro_liquido", -1084058.57),
    ]

    def test_periodos_agregados_da_obra_251_batem_com_a_planilha(self):
        obra_id = self.obra_por_codigo("251")
        if obra_id is None:
            self.skipTest("obra 251 não existe neste banco")

        resultado = calcular_dre_obra(obra_id, MESES_TRAVADOS, incluir_historico=True)
        blocos = resultado["totais_historicos"].values()

        for rotulo, campo, esperado in self.PERIODOS_OBRA_251:
            with self.subTest(linha=rotulo):
                self.assertAlmostEqual(sum(b[campo] for b in blocos), esperado, places=2)

    def test_total_geral_e_o_ano_mais_os_periodos(self):
        obra_id = self.obra_por_codigo("251")
        if obra_id is None:
            self.skipTest("obra 251 não existe neste banco")

        resultado = calcular_dre_obra(obra_id, MESES_TRAVADOS, incluir_historico=True)

        for campo in resultado["total_geral"]:
            with self.subTest(campo=campo):
                soma = resultado["acumulado"][campo] + sum(
                    b[campo] for b in resultado["totais_historicos"].values()
                )
                self.assertAlmostEqual(resultado["total_geral"][campo], soma, places=6)

    def test_toda_obra_com_periodo_agregado_tem_a_descricao_legivel(self):
        """Se a descrição não for legível, a taxa da época não pode ser achada."""
        from dre import fim_do_periodo

        with closing(db.conectar()) as conn:
            periodos = [r["periodo_descricao"] for r in conn.execute(
                "SELECT DISTINCT periodo_descricao FROM saldos_anteriores")]

        ilegiveis = [p for p in periodos if fim_do_periodo(p) is None]
        self.assertEqual(ilegiveis, [], f"períodos que o sistema não sabe datar: {ilegiveis}")


class TestInvariantes(BaseDadosReais):
    """Relações que precisam valer para qualquer dado, hoje e depois."""

    def test_lucro_bruto_e_sempre_receita_menos_custos(self):
        for obra_id in self.todas_as_obras()[:15]:
            resultado = calcular_dre_obra(obra_id, MESES_TRAVADOS)
            for competencia, t in resultado["totais"].items():
                with self.subTest(obra=obra_id, competencia=competencia):
                    self.assertAlmostEqual(
                        t["lucro_bruto"], t["receita_total"] - t["custos_total"], places=6
                    )

    def test_lucro_liquido_e_o_bruto_menos_as_quatro_deducoes(self):
        for obra_id in self.todas_as_obras()[:15]:
            resultado = calcular_dre_obra(obra_id, MESES_TRAVADOS)
            for competencia, t in resultado["totais"].items():
                deducoes = (t["impostos_servicos"] + t["irpj_csll"]
                            + t["despesa_administrativa"] + t["despesa_financeira"])
                with self.subTest(obra=obra_id, competencia=competencia):
                    self.assertAlmostEqual(t["lucro_liquido"], t["lucro_bruto"] - deducoes, places=6)

    def test_acumulado_e_a_soma_das_competencias(self):
        obra_id = self.todas_as_obras()[0]
        resultado = calcular_dre_obra(obra_id, MESES_TRAVADOS)

        for campo in resultado["acumulado"]:
            with self.subTest(campo=campo):
                soma = sum(t[campo] for t in resultado["totais"].values())
                self.assertAlmostEqual(resultado["acumulado"][campo], soma, places=6)

    def test_consolidado_fecha_com_a_soma_das_obras(self):
        ids = self.todas_as_obras()
        resultado = calcular_dre_consolidado(ids, MESES_TRAVADOS)

        for campo in resultado["acumulado"]:
            with self.subTest(campo=campo):
                soma = sum(v[campo] for v in resultado["por_obra"].values())
                self.assertAlmostEqual(resultado["acumulado"][campo], soma, places=4)

    def test_motor_concorda_com_a_soma_direta_no_banco(self):
        """O DRE tem que refletir exatamente o que está gravado em lancamentos."""
        ids = self.todas_as_obras()
        resultado = calcular_dre_consolidado(ids, MESES_TRAVADOS)

        with closing(db.conectar()) as conn:
            linhas = conn.execute("""
                SELECT c.tipo, SUM(l.valor) AS total
                FROM lancamentos l
                JOIN categorias_conta c ON c.id = l.categoria_id
                WHERE l.ano = ? AND c.ativo = 1
                GROUP BY c.tipo
            """, (ANO_TRAVADO,)).fetchall()

        por_tipo = {r["tipo"]: r["total"] for r in linhas}

        self.assertAlmostEqual(
            resultado["acumulado"]["receita_total"], por_tipo.get("receita", 0), places=2
        )
        self.assertAlmostEqual(
            resultado["acumulado"]["custos_total"], por_tipo.get("custo", 0), places=2
        )

    def test_total_por_categoria_bate_com_os_meses(self):
        for obra_id in self.todas_as_obras()[:10]:
            categorias = calcular_dre_obra(obra_id, MESES_TRAVADOS)["categorias"]
            for cat in categorias:
                with self.subTest(obra=obra_id, categoria=cat["nome"]):
                    self.assertAlmostEqual(cat["total"], sum(cat["valores"].values()), places=6)


if __name__ == "__main__":
    unittest.main()
