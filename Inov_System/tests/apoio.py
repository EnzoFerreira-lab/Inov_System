"""
Apoio para os testes: banco temporário, isolado do database.db real.

Todos os módulos leem a variável db.DATABASE em tempo de execução (conectar()
resolve o caminho a cada chamada), então trocar essa variável basta para
redirecionar o sistema inteiro para um banco descartável.
"""

import os
import sys
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import closing

# Permite rodar com "python -m unittest" a partir da pasta do projeto
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db  # noqa: E402

PASTA_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BANCO_REAL = os.path.join(PASTA_PROJETO, "database.db")


class BaseComBancoTemporario(unittest.TestCase):
    """Cria um banco vazio com o schema e os seeds antes de cada teste."""

    def setUp(self):
        self.pasta = tempfile.mkdtemp(prefix="inov_teste_")
        self.caminho_banco = os.path.join(self.pasta, "teste.db")

        self._banco_original = db.DATABASE
        db.DATABASE = self.caminho_banco

        db.criar_tabelas()

    def tearDown(self):
        db.DATABASE = self._banco_original
        shutil.rmtree(self.pasta, ignore_errors=True)

    def conectar(self):
        # closing() e não a própria conexão: "with sqlite3.connect(...)" gerencia
        # a transação mas NÃO fecha o arquivo — o que vazava um handle por uso e
        # deixava o banco temporário preso no Windows na hora de apagar a pasta.
        return closing(db.conectar())

    # -- montagem de cenário ------------------------------------------------

    def criar_empresa(self, nome="CONSTRUTORA TESTE LTDA"):
        with self.conectar() as conn:
            cur = conn.cursor()
            cur.execute("INSERT INTO empresas (nome) VALUES (?)", (nome,))
            conn.commit()
            return cur.lastrowid

    def criar_obra(self, empresa_id, codigo="001", nome="OBRA 001 - TESTE"):
        with self.conectar() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO obras (empresa_id, nome, codigo) VALUES (?, ?, ?)",
                (empresa_id, nome, codigo),
            )
            conn.commit()
            return cur.lastrowid

    def id_categoria(self, nome):
        with self.conectar() as conn:
            row = conn.execute(
                "SELECT id FROM categorias_conta WHERE nome = ?", (nome,)
            ).fetchone()
            if not row:
                raise AssertionError(f"Categoria '{nome}' não existe no plano de contas semeado.")
            return row["id"]

    def lancar(self, obra_id, categoria_nome, mes, ano, valor, origem="importacao"):
        with self.conectar() as conn:
            conn.execute(
                """
                INSERT INTO lancamentos (obra_id, categoria_id, mes, ano, valor, origem, atualizado_em)
                VALUES (?, ?, ?, ?, ?, ?, '2026-01-01T00:00:00')
                ON CONFLICT (obra_id, categoria_id, mes, ano)
                DO UPDATE SET valor = excluded.valor, origem = excluded.origem
                """,
                (obra_id, self.id_categoria(categoria_nome), mes, ano, valor, origem),
            )
            conn.commit()

    def definir_taxa(self, chave, percentual, base, inicio="2020-01", fim=None):
        """Substitui a vigência aberta de uma taxa, para o teste ter valores redondos."""
        with self.conectar() as conn:
            conn.execute("DELETE FROM taxas WHERE chave = ?", (chave,))
            conn.execute(
                """
                INSERT INTO taxas (chave, descricao, percentual, base_calculo, vigencia_inicio, vigencia_fim)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (chave, chave, percentual, base, inicio, fim),
            )
            conn.commit()

    def zerar_taxas(self):
        with self.conectar() as conn:
            conn.execute("DELETE FROM taxas")
            conn.commit()


def banco_real_disponivel():
    """
    O database.db não é versionado (contém dados do cliente). Os testes de
    regressão contra os números reais só rodam na máquina que tem o arquivo.
    """
    if not os.path.exists(BANCO_REAL):
        return False
    try:
        with closing(sqlite3.connect(BANCO_REAL)) as conn:
            n = conn.execute("SELECT COUNT(*) FROM lancamentos WHERE ano = 2026").fetchone()[0]
        return n > 0
    except sqlite3.Error:
        return False
