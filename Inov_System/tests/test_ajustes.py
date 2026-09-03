"""
Testa os ajustes finos: Departamento Técnico sem as taxas de obra, comparação
com o ano anterior, revisão/mesclagem de categorias e backup do banco.
"""

import os
import re
import unittest

from tests.apoio import BaseComBancoTemporario

import app as app_modulo
import backup
import db
from dre import calcular_dre_obra

MESES_2026 = [(2026, m) for m in range(1, 13)]


class TestDeptoTecnicoSemTaxas(BaseComBancoTemporario):
    """
    As 4 taxas do DRE foram pensadas para uma obra que fatura. O Departamento
    Técnico é despesa administrativa da empresa — cobrar dele uma taxa
    administrativa calculada sobre o próprio custo não faz sentido contábil.
    """

    def setUp(self):
        super().setUp()
        self.empresa_id = self.criar_empresa()
        self.obra_id = self.criar_obra(self.empresa_id, codigo="251", nome="OBRA 251")
        self.depto_id = self.criar_obra(self.empresa_id, codigo="DEPTO-TEC",
                                        nome="Departamento Técnico (Administrativo)")

        self.zerar_taxas()
        self.definir_taxa("despesa_administrativa", 10.0, "custo")
        self.definir_taxa("impostos_servicos", 13.0, "receita")

    def marcar_sem_taxas(self, obra_id):
        with self.conectar() as conn:
            conn.execute("UPDATE obras SET aplica_taxas = 0 WHERE id = ?", (obra_id,))
            conn.commit()

    def test_obra_normal_recebe_as_taxas(self):
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 1000.0)

        totais = calcular_dre_obra(self.obra_id, MESES_2026)["totais"][(2026, 1)]
        self.assertAlmostEqual(totais["despesa_administrativa"], 100.0, places=6)

    def test_centro_sem_faturamento_nao_recebe_taxa(self):
        self.marcar_sem_taxas(self.depto_id)
        self.lancar(self.depto_id, "Salarios e Ordenados", 1, 2026, 1000.0)

        totais = calcular_dre_obra(self.depto_id, MESES_2026)["totais"][(2026, 1)]

        self.assertEqual(totais["custos_total"], 1000.0)
        self.assertEqual(totais["despesa_administrativa"], 0.0)
        self.assertEqual(totais["impostos_servicos"], 0.0)
        self.assertEqual(totais["lucro_liquido"], totais["lucro_bruto"])

    def test_periodo_agregado_tambem_fica_sem_taxa(self):
        self.marcar_sem_taxas(self.depto_id)
        with self.conectar() as conn:
            conn.execute(
                """
                INSERT INTO saldos_anteriores
                    (obra_id, categoria_id, periodo_descricao, valor, origem, atualizado_em)
                VALUES (?, ?, 'Jan a Dez/2025', 5000.0, 'importacao', '2026-01-01')
                """,
                (self.depto_id, self.id_categoria("Salarios e Ordenados")),
            )
            conn.commit()

        resultado = calcular_dre_obra(self.depto_id, MESES_2026, incluir_historico=True)
        bloco = resultado["totais_historicos"]["Jan a Dez/2025"]

        self.assertEqual(bloco["custos_total"], 5000.0)
        self.assertEqual(bloco["despesa_administrativa"], 0.0)

    def test_migracao_marca_depto_existente(self):
        with self.conectar() as conn:
            conn.execute("UPDATE obras SET aplica_taxas = 1 WHERE id = ?", (self.depto_id,))
            conn.execute("ALTER TABLE obras RENAME COLUMN aplica_taxas TO aplica_taxas_old")
            conn.commit()

        db.criar_tabelas()  # deve recriar a coluna e marcar o Depto Técnico

        with self.conectar() as conn:
            aplica = conn.execute(
                "SELECT aplica_taxas FROM obras WHERE id = ?", (self.depto_id,)).fetchone()["aplica_taxas"]
        self.assertEqual(aplica, 0, "a migração não marcou o Departamento Técnico")


class TestComparativoAnual(BaseComBancoTemporario):

    def test_calcula_diferenca_e_percentual(self):
        atual = {"receita_total": 1200.0, "custos_total": 800.0,
                 "lucro_bruto": 400.0, "lucro_liquido": 300.0}
        anterior = {"receita_total": 1000.0, "custos_total": 1000.0,
                    "lucro_bruto": 0.0, "lucro_liquido": -100.0}

        linhas = {l["campo"]: l for l in app_modulo.montar_comparativo(atual, anterior, 2025)["linhas"]}

        self.assertAlmostEqual(linhas["receita_total"]["diferenca"], 200.0)
        self.assertAlmostEqual(linhas["receita_total"]["percentual"], 20.0)
        self.assertAlmostEqual(linhas["custos_total"]["percentual"], -20.0)

    def test_ano_anterior_zerado_nao_vira_percentual(self):
        """Dividir por zero não dá 'aumento de 100%', dá informação inexistente."""
        comparativo = app_modulo.montar_comparativo(
            {"receita_total": 500.0}, {"receita_total": 0.0}, 2025
        )
        receita = next(l for l in comparativo["linhas"] if l["campo"] == "receita_total")

        self.assertIsNone(receita["percentual"])
        self.assertEqual(receita["diferenca"], 500.0)

    def test_em_custo_subir_e_ruim(self):
        comparativo = app_modulo.montar_comparativo({}, {}, 2025)
        por_campo = {l["campo"]: l for l in comparativo["linhas"]}

        self.assertFalse(por_campo["custos_total"]["subir_e_bom"])
        self.assertTrue(por_campo["receita_total"]["subir_e_bom"])


class TestRevisaoDeCategorias(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        self.empresa_id = self.criar_empresa()
        self.obra_id = self.criar_obra(self.empresa_id)
        self.outra_obra = self.criar_obra(self.empresa_id, codigo="252", nome="OBRA 252")

    def criar_categoria(self, nome, tipo="custo", codigo=None, origem="importacao"):
        with self.conectar() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO categorias_conta (codigo, nome, tipo, ordem, ativo, origem)
                VALUES (?, ?, ?, 99, 1, ?)
                """,
                (codigo, nome, tipo, origem),
            )
            conn.commit()
            return cur.lastrowid

    def test_categoria_importada_fica_marcada(self):
        with self.conectar() as conn:
            origem = conn.execute(
                "SELECT origem FROM categorias_conta WHERE nome = 'Salarios e Ordenados'"
            ).fetchone()["origem"]
        self.assertEqual(origem, "manual", "conta do plano padrão não deveria ser 'importacao'")

    def test_sugere_nomes_parecidos_do_mesmo_tipo(self):
        categorias = [
            {"id": 1, "nome": "Seguro Riscos Execução de Serv. Trab.", "tipo": "custo", "usos": 5},
            {"id": 2, "nome": "Seguro Riscos Execução de Serviços", "tipo": "custo", "usos": 0},
            {"id": 3, "nome": "Alimentação", "tipo": "custo", "usos": 3},
        ]
        pares = app_modulo._sugerir_duplicatas(categorias)

        self.assertEqual(len(pares), 1)
        # Sugere manter a que já tem histórico
        self.assertEqual(pares[0]["manter"]["id"], 1)
        self.assertEqual(pares[0]["mesclar"]["id"], 2)

    def test_nao_sugere_juntar_receita_com_custo(self):
        categorias = [
            {"id": 1, "nome": "Locações", "tipo": "receita", "usos": 0},
            {"id": 2, "nome": "Locação", "tipo": "custo", "usos": 0},
        ]
        self.assertEqual(app_modulo._sugerir_duplicatas(categorias), [])

    def test_mesclagem_move_o_historico(self):
        destino = self.id_categoria("Salarios e Ordenados")
        origem = self.criar_categoria("Salarios e Ordenado")

        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 100.0)
        with self.conectar() as conn:
            conn.execute(
                """
                INSERT INTO lancamentos (obra_id, categoria_id, mes, ano, valor, origem, atualizado_em)
                VALUES (?, ?, 2, 2026, 250.0, 'importacao', '2026-01-01')
                """,
                (self.obra_id, origem),
            )
            conn.commit()

        with self.conectar() as conn:
            cur = conn.cursor()
            app_modulo._mesclar_categoria(cur, origem, destino)
            cur.execute("DELETE FROM categorias_conta WHERE id = ?", (origem,))
            conn.commit()

        with self.conectar() as conn:
            valores = {r["mes"]: r["valor"] for r in conn.execute(
                "SELECT mes, valor FROM lancamentos WHERE categoria_id = ?", (destino,))}

        self.assertEqual(valores[1], 100.0)
        self.assertEqual(valores[2], 250.0, "o lançamento da conta mesclada se perdeu")

    def test_mesclagem_soma_quando_a_competencia_colide(self):
        """Sem somar, a restrição de unicidade barraria e o valor sumiria."""
        destino = self.id_categoria("Salarios e Ordenados")
        origem = self.criar_categoria("Salarios duplicado")

        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 100.0)
        with self.conectar() as conn:
            conn.execute(
                """
                INSERT INTO lancamentos (obra_id, categoria_id, mes, ano, valor, origem, atualizado_em)
                VALUES (?, ?, 1, 2026, 40.0, 'importacao', '2026-01-01')
                """,
                (self.obra_id, origem),
            )
            conn.commit()

        with self.conectar() as conn:
            cur = conn.cursor()
            app_modulo._mesclar_categoria(cur, origem, destino)
            conn.commit()

        with self.conectar() as conn:
            valor = conn.execute(
                "SELECT valor FROM lancamentos WHERE categoria_id=? AND mes=1 AND ano=2026",
                (destino,)).fetchone()["valor"]
            sobrou = conn.execute(
                "SELECT COUNT(*) c FROM lancamentos WHERE categoria_id=?", (origem,)).fetchone()["c"]

        self.assertAlmostEqual(valor, 140.0, places=2)
        self.assertEqual(sobrou, 0)


class TestBackup(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        self.pasta = os.path.join(self.pasta, "backups")

    def test_gera_copia_utilizavel(self):
        self.criar_empresa("EMPRESA DO BACKUP")

        destino = backup.gerar_backup(self.pasta)

        self.assertTrue(os.path.isfile(destino))

        import sqlite3
        from contextlib import closing
        with closing(sqlite3.connect(destino)) as conn:
            n = conn.execute(
                "SELECT COUNT(*) FROM empresas WHERE nome='EMPRESA DO BACKUP'").fetchone()[0]
        self.assertEqual(n, 1, "a cópia não tem os dados do banco")

    def test_lista_do_mais_novo_para_o_mais_antigo(self):
        import time
        backup.gerar_backup(self.pasta)
        time.sleep(1.1)
        segundo = backup.gerar_backup(self.pasta)

        copias = backup.listar_backups(self.pasta)
        self.assertGreaterEqual(len(copias), 2)
        self.assertEqual(copias[0]["caminho"], segundo)

    def test_mantem_so_as_mais_recentes(self):
        for _ in range(5):
            backup.gerar_backup(self.pasta)

        backup.limpar_antigos(self.pasta, manter=2)

        self.assertLessEqual(len(backup.listar_backups(self.pasta)), 2)

    def test_backup_diario_nao_repete_no_mesmo_dia(self):
        primeiro = backup.backup_diario(self.pasta)
        segundo = backup.backup_diario(self.pasta)

        self.assertIsNotNone(primeiro)
        self.assertIsNone(segundo, "gerou duas cópias automáticas no mesmo dia")

    def test_pasta_inexistente_lista_vazio(self):
        self.assertEqual(backup.listar_backups(os.path.join(self.pasta, "nao-existe")), [])


class TestBackupNaWeb(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        app_modulo.app.config["TESTING"] = True
        self.cliente = app_modulo.app.test_client()
        html = self.cliente.get("/").get_data(as_text=True)
        token = re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
        self.cliente.post("/", data={"email": "admin@inov.com", "senha": "1234", "_csrf": token})

    def test_tela_de_backup_abre_para_admin(self):
        self.assertEqual(self.cliente.get("/backups").status_code, 200)

    def test_download_recusa_caminho_de_fora_da_pasta(self):
        r = self.cliente.get("/backups/..%2F..%2Fdatabase.db/baixar")
        self.assertIn(r.status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
