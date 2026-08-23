"""
Testa o miolo da importação do Contimatic — a parte que não depende do layout
do arquivo: resolver conta e centro de custo, somar por competência, atualizar
o DRE e guardar o detalhe lançamento a lançamento.
"""

import datetime
import unittest

from tests.apoio import BaseComBancoTemporario

from contimatic import (
    importar_lancamentos, buscar_partidas, ResolvedorDeContas, _codigo_limpo,
)
from dre_import import RegistroImportacao, desfazer_importacao
from dre import calcular_dre_obra


MESES_2026 = [(2026, m) for m in range(1, 13)]


class BaseContimatic(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        self.empresa_id = self.criar_empresa()
        self.obra_id = self.criar_obra(self.empresa_id, codigo="251", nome="OBRA 251")
        self.zerar_taxas()

    def lancamento(self, conta="311", nome="Salarios e Ordenados", valor=1000.0,
                   dia=15, mes=6, ano=2026, obra="251", **extra):
        base = {
            "obra_codigo": obra,
            "conta_codigo": conta,
            "conta_nome": nome,
            "data": datetime.date(ano, mes, dia),
            "valor": valor,
        }
        base.update(extra)
        return base

    def importar(self, linhas, sobrescrever=False):
        with self.conectar() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO importacoes (arquivo, criado_em) VALUES ('contimatic.xlsx', '2026-01-01')"
            )
            importacao_id = cur.lastrowid
            registro = RegistroImportacao(cur, importacao_id, sobrescrever)
            resumo = importar_lancamentos(cur, linhas, registro, importacao_id)
            conn.commit()
        return resumo, importacao_id

    def valor_no_dre(self, categoria_nome="Salarios e Ordenados", mes=6, ano=2026):
        with self.conectar() as conn:
            row = conn.execute(
                "SELECT valor FROM lancamentos WHERE obra_id=? AND categoria_id=? AND mes=? AND ano=?",
                (self.obra_id, self.id_categoria(categoria_nome), mes, ano),
            ).fetchone()
        return row["valor"] if row else None


class TestCodigoDeConta(unittest.TestCase):

    def test_formatos_do_mesmo_codigo_sao_equivalentes(self):
        for entrada in ["311", "0000311", "311.0", " 311 ", "3.1.1"]:
            with self.subTest(entrada=entrada):
                self.assertEqual(_codigo_limpo(entrada), "311")

    def test_codigo_vazio(self):
        self.assertEqual(_codigo_limpo(None), "")
        self.assertEqual(_codigo_limpo(""), "")


class TestResolucaoDeContas(BaseContimatic):

    def test_conta_casa_pelo_codigo_do_plano(self):
        with self.conectar() as conn:
            resolvedor = ResolvedorDeContas(conn.cursor())
            categoria_id, motivo = resolvedor.resolver("311", "qualquer nome")

        self.assertEqual(categoria_id, self.id_categoria("Salarios e Ordenados"))
        self.assertEqual(motivo, "codigo")

    def test_conta_casa_pelo_nome_quando_o_codigo_nao_bate(self):
        with self.conectar() as conn:
            resolvedor = ResolvedorDeContas(conn.cursor())
            categoria_id, motivo = resolvedor.resolver("99999", "SALARIOS E ORDENADOS")

        self.assertEqual(categoria_id, self.id_categoria("Salarios e Ordenados"))
        self.assertEqual(motivo, "nome")

    def test_de_para_explicito_tem_prioridade(self):
        alvo = self.id_categoria("INSS")
        with self.conectar() as conn:
            conn.execute(
                "INSERT INTO contas_map (conta_codigo, categoria_id, criado_em) VALUES ('311', ?, '2026-01-01')",
                (alvo,),
            )
            conn.commit()

        with self.conectar() as conn:
            categoria_id, motivo = ResolvedorDeContas(conn.cursor()).resolver("311", "Salarios e Ordenados")

        self.assertEqual(categoria_id, alvo)
        self.assertEqual(motivo, "de-para")

    def test_conta_marcada_para_ignorar(self):
        with self.conectar() as conn:
            conn.execute(
                "INSERT INTO contas_map (conta_codigo, ignorar, criado_em) VALUES ('311', 1, '2026-01-01')"
            )
            conn.commit()

        with self.conectar() as conn:
            categoria_id, motivo = ResolvedorDeContas(conn.cursor()).resolver("311", "Salarios")

        self.assertIsNone(categoria_id)
        self.assertEqual(motivo, "ignorada")

    def test_conta_desconhecida_nunca_e_adivinhada(self):
        """Chutar a conta desloca valor entre linhas do DRE — melhor pendência."""
        with self.conectar() as conn:
            resolvedor = ResolvedorDeContas(conn.cursor())
            categoria_id, motivo = resolvedor.resolver("77777", "Conta Que Nao Existe")

        self.assertIsNone(categoria_id)
        self.assertEqual(motivo, "nao_resolvida")


class TestImportacaoDeLancamentos(BaseContimatic):

    def test_soma_os_lancamentos_da_mesma_conta_no_mes(self):
        self.importar([
            self.lancamento(valor=1000.0, dia=5),
            self.lancamento(valor=2500.0, dia=15),
            self.lancamento(valor=643.11, dia=28),
        ])

        self.assertAlmostEqual(self.valor_no_dre(), 4143.11, places=2)

    def test_separa_por_mes_e_por_conta(self):
        self.importar([
            self.lancamento(valor=1000.0, mes=6),
            self.lancamento(valor=1500.0, mes=7),
            self.lancamento(conta="316", nome="INSS", valor=300.0, mes=6),
        ])

        self.assertEqual(self.valor_no_dre(mes=6), 1000.0)
        self.assertEqual(self.valor_no_dre(mes=7), 1500.0)
        self.assertEqual(self.valor_no_dre("INSS", mes=6), 300.0)

    def test_o_detalhe_fica_guardado(self):
        self.importar([
            self.lancamento(valor=1000.0, dia=5, documento="NF 1", historico="Folha"),
            self.lancamento(valor=500.0, dia=20, documento="NF 2", historico="Adiantamento"),
        ])

        with self.conectar() as conn:
            partidas = buscar_partidas(
                conn.cursor(), self.obra_id, self.id_categoria("Salarios e Ordenados"), 2026, 6
            )

        self.assertEqual(len(partidas), 2)
        self.assertEqual(partidas[0]["documento"], "NF 1")
        self.assertEqual(partidas[0]["historico"], "Folha")
        self.assertAlmostEqual(sum(p["valor"] for p in partidas), 1500.0, places=2)

    def test_reimportar_o_mes_substitui_em_vez_de_somar(self):
        self.importar([self.lancamento(valor=1000.0), self.lancamento(valor=500.0)])
        self.assertEqual(self.valor_no_dre(), 1500.0)

        # o contador reenviou o mês, agora sem o segundo lançamento
        self.importar([self.lancamento(valor=1000.0)])

        self.assertEqual(self.valor_no_dre(), 1000.0)

        with self.conectar() as conn:
            partidas = buscar_partidas(
                conn.cursor(), self.obra_id, self.id_categoria("Salarios e Ordenados"), 2026, 6
            )
        self.assertEqual(len(partidas), 1, "o detalhe antigo não foi substituído")

    def test_reimportar_nao_afeta_outra_competencia(self):
        self.importar([self.lancamento(valor=800.0, mes=5), self.lancamento(valor=1000.0, mes=6)])
        self.importar([self.lancamento(valor=1200.0, mes=6)])

        self.assertEqual(self.valor_no_dre(mes=5), 800.0)
        self.assertEqual(self.valor_no_dre(mes=6), 1200.0)

    def test_centro_de_custo_desconhecido_e_reportado(self):
        resumo, _ = self.importar([
            self.lancamento(valor=1000.0),
            self.lancamento(obra="999", valor=777.0),
        ])

        self.assertIn("999", resumo["obras_desconhecidas"])
        self.assertEqual(resumo["obras_desconhecidas"]["999"]["ocorrencias"], 1)
        self.assertEqual(self.valor_no_dre(), 1000.0)

    def test_conta_nao_resolvida_e_reportada_com_o_valor(self):
        resumo, _ = self.importar([
            self.lancamento(conta="88888", nome="Conta Nova", valor=1234.0),
            self.lancamento(conta="88888", nome="Conta Nova", valor=766.0),
        ])

        pendentes = resumo["contas_nao_resolvidas"]
        self.assertEqual(len(pendentes), 1)
        self.assertEqual(pendentes[0]["ocorrencias"], 2)
        self.assertAlmostEqual(pendentes[0]["valor_total"], 2000.0, places=2)

    def test_lancamento_sem_data_e_ignorado_e_contado(self):
        resumo, _ = self.importar([
            self.lancamento(valor=1000.0),
            {"obra_codigo": "251", "conta_codigo": "311", "conta_nome": "Salarios",
             "data": None, "valor": 500.0},
        ])

        self.assertEqual(resumo["ignoradas_sem_data"], 1)
        self.assertEqual(self.valor_no_dre(), 1000.0)

    def test_o_dre_reflete_o_que_foi_importado(self):
        self.definir_taxa("despesa_administrativa", 10.0, "custo")
        self.importar([
            self.lancamento(valor=1000.0, mes=6),
            self.lancamento(conta="2", nome="Serviços prestados", valor=5000.0, mes=6),
        ])

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"][(2026, 6)]

        self.assertEqual(totais["receita_total"], 5000.0)
        self.assertEqual(totais["custos_total"], 1000.0)
        self.assertEqual(totais["lucro_bruto"], 4000.0)
        self.assertAlmostEqual(totais["despesa_administrativa"], 100.0, places=6)


class TestIntegracaoComAsProtecoes(BaseContimatic):
    """A importação do Contimatic usa o mesmo RegistroImportacao da planilha."""

    def test_lancamento_manual_continua_protegido(self):
        self.lancar(self.obra_id, "Salarios e Ordenados", 6, 2026, 999.0, origem="manual")

        self.importar([self.lancamento(valor=1000.0)])

        self.assertEqual(self.valor_no_dre(), 999.0)

    def test_com_permissao_a_importacao_prevalece(self):
        self.lancar(self.obra_id, "Salarios e Ordenados", 6, 2026, 999.0, origem="manual")

        self.importar([self.lancamento(valor=1000.0)], sobrescrever=True)

        self.assertEqual(self.valor_no_dre(), 1000.0)

    def test_desfazer_reverte_o_valor_do_dre(self):
        self.lancar(self.obra_id, "Salarios e Ordenados", 6, 2026, 111.0, origem="importacao")

        _, importacao_id = self.importar([self.lancamento(valor=1000.0)])
        self.assertEqual(self.valor_no_dre(), 1000.0)

        with self.conectar() as conn:
            desfazer_importacao(conn.cursor(), importacao_id)
            conn.commit()

        self.assertEqual(self.valor_no_dre(), 111.0)


if __name__ == "__main__":
    unittest.main()
