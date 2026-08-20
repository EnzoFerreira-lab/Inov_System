"""
Testa as duas garantias novas da importação:

  1. um valor lançado à mão não é sobrescrito em silêncio;
  2. toda importação pode ser desfeita, voltando ao estado anterior.
"""

import unittest

from tests.apoio import BaseComBancoTemporario

from dre_import import RegistroImportacao, desfazer_importacao
import datetime


AGORA = datetime.datetime.now().isoformat()


class BaseImportacao(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        self.empresa_id = self.criar_empresa()
        self.obra_id = self.criar_obra(self.empresa_id)
        self.cat_id = self.id_categoria("Salarios e Ordenados")

    def abrir_importacao(self, conn, sobrescrever=False):
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO importacoes (arquivo, empresa_id, criado_em) VALUES (?, ?, ?)",
            ("planilha.xlsx", self.empresa_id, AGORA),
        )
        return cur, RegistroImportacao(cur, cur.lastrowid, sobrescrever), cur.lastrowid

    def valor_atual(self, mes=1, ano=2026):
        with self.conectar() as conn:
            row = conn.execute(
                "SELECT valor, origem FROM lancamentos "
                "WHERE obra_id = ? AND categoria_id = ? AND mes = ? AND ano = ?",
                (self.obra_id, self.cat_id, mes, ano),
            ).fetchone()
            return (row["valor"], row["origem"]) if row else (None, None)


class TestPreservacaoDeLancamentoManual(BaseImportacao):

    def test_valor_manual_nao_e_sobrescrito_por_padrao(self):
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 500.0, origem="manual")

        with self.conectar() as conn:
            cur, registro, _ = self.abrir_importacao(conn)
            gravou = registro.gravar_lancamento(self.obra_id, self.cat_id, 1, 2026, 9999.0, AGORA)
            conn.commit()

        self.assertFalse(gravou)
        self.assertEqual(self.valor_atual(), (500.0, "manual"))
        self.assertEqual(registro.manuais_preservados, 1)
        self.assertEqual(registro.lancamentos_gravados, 0)

    def test_conflito_preservado_fica_registrado_para_a_tela(self):
        self.lancar(self.obra_id, "Salarios e Ordenados", 3, 2026, 500.0, origem="manual")

        with self.conectar() as conn:
            cur, registro, _ = self.abrir_importacao(conn)
            registro.gravar_lancamento(self.obra_id, self.cat_id, 3, 2026, 800.0, AGORA)
            conn.commit()

        self.assertEqual(len(registro.conflitos), 1)
        conflito = registro.conflitos[0]
        self.assertEqual(conflito["valor_manual"], 500.0)
        self.assertEqual(conflito["valor_planilha"], 800.0)
        self.assertEqual((conflito["mes"], conflito["ano"]), (3, 2026))

    def test_com_permissao_explicita_a_planilha_prevalece(self):
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 500.0, origem="manual")

        with self.conectar() as conn:
            cur, registro, _ = self.abrir_importacao(conn, sobrescrever=True)
            gravou = registro.gravar_lancamento(self.obra_id, self.cat_id, 1, 2026, 9999.0, AGORA)
            conn.commit()

        self.assertTrue(gravou)
        self.assertEqual(self.valor_atual(), (9999.0, "importacao"))
        self.assertEqual(registro.manuais_sobrescritos, 1)

    def test_valor_de_importacao_anterior_e_atualizado_normalmente(self):
        """A proteção vale só para lançamento manual, não trava a reimportação."""
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 100.0, origem="importacao")

        with self.conectar() as conn:
            cur, registro, _ = self.abrir_importacao(conn)
            gravou = registro.gravar_lancamento(self.obra_id, self.cat_id, 1, 2026, 250.0, AGORA)
            conn.commit()

        self.assertTrue(gravou)
        self.assertEqual(self.valor_atual(), (250.0, "importacao"))
        self.assertEqual(registro.manuais_preservados, 0)


class TestDesfazerImportacao(BaseImportacao):

    def test_desfazer_restaura_o_valor_anterior(self):
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 100.0, origem="importacao")

        with self.conectar() as conn:
            cur, registro, importacao_id = self.abrir_importacao(conn)
            registro.gravar_lancamento(self.obra_id, self.cat_id, 1, 2026, 777.0, AGORA)
            conn.commit()

        self.assertEqual(self.valor_atual()[0], 777.0)

        with self.conectar() as conn:
            resultado = desfazer_importacao(conn.cursor(), importacao_id)
            conn.commit()

        self.assertEqual(self.valor_atual()[0], 100.0)
        self.assertEqual(resultado["restaurados"], 1)
        self.assertEqual(resultado["removidos"], 0)

    def test_desfazer_remove_o_que_a_importacao_criou(self):
        with self.conectar() as conn:
            cur, registro, importacao_id = self.abrir_importacao(conn)
            registro.gravar_lancamento(self.obra_id, self.cat_id, 4, 2026, 300.0, AGORA)
            conn.commit()

        self.assertEqual(self.valor_atual(mes=4)[0], 300.0)

        with self.conectar() as conn:
            resultado = desfazer_importacao(conn.cursor(), importacao_id)
            conn.commit()

        self.assertEqual(self.valor_atual(mes=4), (None, None))
        self.assertEqual(resultado["removidos"], 1)

    def test_desfazer_devolve_a_origem_manual(self):
        """Desfazer não pode transformar um lançamento manual em importado."""
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 500.0, origem="manual")

        with self.conectar() as conn:
            cur, registro, importacao_id = self.abrir_importacao(conn, sobrescrever=True)
            registro.gravar_lancamento(self.obra_id, self.cat_id, 1, 2026, 999.0, AGORA)
            conn.commit()

        with self.conectar() as conn:
            desfazer_importacao(conn.cursor(), importacao_id)
            conn.commit()

        self.assertEqual(self.valor_atual(), (500.0, "manual"))

    def test_nao_desfaz_duas_vezes(self):
        with self.conectar() as conn:
            cur, registro, importacao_id = self.abrir_importacao(conn)
            registro.gravar_lancamento(self.obra_id, self.cat_id, 5, 2026, 10.0, AGORA)
            conn.commit()

        with self.conectar() as conn:
            desfazer_importacao(conn.cursor(), importacao_id)
            conn.commit()

        with self.conectar() as conn:
            with self.assertRaises(ValueError):
                desfazer_importacao(conn.cursor(), importacao_id)

    def test_desfazer_marca_a_data_no_registro(self):
        with self.conectar() as conn:
            cur, registro, importacao_id = self.abrir_importacao(conn)
            registro.gravar_lancamento(self.obra_id, self.cat_id, 6, 2026, 10.0, AGORA)
            conn.commit()

        with self.conectar() as conn:
            desfazer_importacao(conn.cursor(), importacao_id)
            conn.commit()

        with self.conectar() as conn:
            row = conn.execute(
                "SELECT desfeita_em FROM importacoes WHERE id = ?", (importacao_id,)
            ).fetchone()

        self.assertIsNotNone(row["desfeita_em"])

    def test_saldo_historico_tambem_e_revertido(self):
        with self.conectar() as conn:
            cur, registro, importacao_id = self.abrir_importacao(conn)
            registro.gravar_saldo_anterior(self.obra_id, self.cat_id, "Jan a Dez/2024", 4000.0, AGORA)
            conn.commit()

        with self.conectar() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM saldos_anteriores").fetchone()["c"]
        self.assertEqual(n, 1)

        with self.conectar() as conn:
            desfazer_importacao(conn.cursor(), importacao_id)
            conn.commit()

        with self.conectar() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM saldos_anteriores").fetchone()["c"]
        self.assertEqual(n, 0)


if __name__ == "__main__":
    unittest.main()
