"""
Regressão contra o banco real (database.db), que é o que foi conferido célula
a célula com a planilha da contabilidade.

Dois tipos de verificação:

  * **Invariantes** — relações que precisam valer sempre, com qualquer dado
    (lucro bruto = receita - custos, consolidado = soma das obras, etc.).
    Não dependem de valores específicos e não envelhecem.

  * **Valores travados** — números concretos de 2026, congelados no estado
    validado. É o que pega uma alteração no motor de cálculo que mude o
    resultado sem ninguém perceber.

Se uma importação nova mudar legitimamente os dados de 2026, os valores
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

MESES_2026 = [(2026, m) for m in range(1, 13)]

# Gerado a partir do banco validado. Ver instruções no topo do arquivo.
VALORES_TRAVADOS = {
    "305": dict(
        receita_total=1792029.83,
        custos_total=754231.77,
        lucro_bruto=1037798.06,
        impostos_servicos=235651.922645,
        irpj_csll=21862.763926,
        despesa_administrativa=41935.286412,
        despesa_financeira=75.423177,
        lucro_liquido=738272.66384,
    ),
    "314": dict(
        receita_total=1192793.72,
        custos_total=250697.30,
        lucro_bruto=942096.42,
        impostos_servicos=156852.374180,
        irpj_csll=14552.083384,
        despesa_administrativa=13938.769880,
        despesa_financeira=25.069730,
        lucro_liquido=756728.122826,
    ),
    "310": dict(
        receita_total=1089949.60,
        custos_total=297308.62,
        lucro_bruto=792640.98,
        impostos_servicos=143328.372400,
        irpj_csll=13297.385120,
        despesa_administrativa=16530.359272,
        despesa_financeira=29.730862,
        lucro_liquido=619455.132346,
    ),
}

CONSOLIDADO_TRAVADO_2026 = dict(
    receita_total=6645582.39,
    custos_total=6154322.50,
    lucro_bruto=491259.89,
    impostos_servicos=873894.084285,
    irpj_csll=81076.105158,
    despesa_administrativa=342180.331000,
    despesa_financeira=615.432250,
    lucro_liquido=-806506.062693,
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

            acumulado = calcular_dre_obra(obra_id, MESES_2026)["acumulado"]

            for campo, valor_esperado in esperado.items():
                with self.subTest(obra=codigo, campo=campo):
                    self.assertAlmostEqual(
                        acumulado[campo], valor_esperado, places=2,
                        msg=f"obra {codigo}, {campo}: o cálculo mudou",
                    )

    def test_consolidado_de_2026_nao_mudou(self):
        acumulado = calcular_dre_consolidado(self.todas_as_obras(), MESES_2026)["acumulado"]

        for campo, valor_esperado in CONSOLIDADO_TRAVADO_2026.items():
            with self.subTest(campo=campo):
                self.assertAlmostEqual(
                    acumulado[campo], valor_esperado, places=2,
                    msg=f"consolidado, {campo}: o cálculo mudou",
                )


class TestInvariantes(BaseDadosReais):
    """Relações que precisam valer para qualquer dado, hoje e depois."""

    def test_lucro_bruto_e_sempre_receita_menos_custos(self):
        for obra_id in self.todas_as_obras()[:15]:
            resultado = calcular_dre_obra(obra_id, MESES_2026)
            for competencia, t in resultado["totais"].items():
                with self.subTest(obra=obra_id, competencia=competencia):
                    self.assertAlmostEqual(
                        t["lucro_bruto"], t["receita_total"] - t["custos_total"], places=6
                    )

    def test_lucro_liquido_e_o_bruto_menos_as_quatro_deducoes(self):
        for obra_id in self.todas_as_obras()[:15]:
            resultado = calcular_dre_obra(obra_id, MESES_2026)
            for competencia, t in resultado["totais"].items():
                deducoes = (t["impostos_servicos"] + t["irpj_csll"]
                            + t["despesa_administrativa"] + t["despesa_financeira"])
                with self.subTest(obra=obra_id, competencia=competencia):
                    self.assertAlmostEqual(t["lucro_liquido"], t["lucro_bruto"] - deducoes, places=6)

    def test_acumulado_e_a_soma_das_competencias(self):
        obra_id = self.todas_as_obras()[0]
        resultado = calcular_dre_obra(obra_id, MESES_2026)

        for campo in resultado["acumulado"]:
            with self.subTest(campo=campo):
                soma = sum(t[campo] for t in resultado["totais"].values())
                self.assertAlmostEqual(resultado["acumulado"][campo], soma, places=6)

    def test_consolidado_fecha_com_a_soma_das_obras(self):
        ids = self.todas_as_obras()
        resultado = calcular_dre_consolidado(ids, MESES_2026)

        for campo in resultado["acumulado"]:
            with self.subTest(campo=campo):
                soma = sum(v[campo] for v in resultado["por_obra"].values())
                self.assertAlmostEqual(resultado["acumulado"][campo], soma, places=4)

    def test_motor_concorda_com_a_soma_direta_no_banco(self):
        """O DRE tem que refletir exatamente o que está gravado em lancamentos."""
        ids = self.todas_as_obras()
        resultado = calcular_dre_consolidado(ids, MESES_2026)

        with closing(db.conectar()) as conn:
            linhas = conn.execute("""
                SELECT c.tipo, SUM(l.valor) AS total
                FROM lancamentos l
                JOIN categorias_conta c ON c.id = l.categoria_id
                WHERE l.ano = 2026 AND c.ativo = 1
                GROUP BY c.tipo
            """).fetchall()

        por_tipo = {r["tipo"]: r["total"] for r in linhas}

        self.assertAlmostEqual(
            resultado["acumulado"]["receita_total"], por_tipo.get("receita", 0), places=2
        )
        self.assertAlmostEqual(
            resultado["acumulado"]["custos_total"], por_tipo.get("custo", 0), places=2
        )

    def test_total_por_categoria_bate_com_os_meses(self):
        for obra_id in self.todas_as_obras()[:10]:
            categorias = calcular_dre_obra(obra_id, MESES_2026)["categorias"]
            for cat in categorias:
                with self.subTest(obra=obra_id, categoria=cat["nome"]):
                    self.assertAlmostEqual(cat["total"], sum(cat["valores"].values()), places=6)


if __name__ == "__main__":
    unittest.main()
