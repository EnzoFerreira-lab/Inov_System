"""
Testa o corte de permissão.

O corte é por AÇÃO, não por obra: todo funcionário enxerga e opera todas as
obras. O que é da administradora são as ações que apagam dado ou mudam o
cálculo de todas as obras de uma vez.
"""

import re
import unittest

from tests.apoio import BaseComBancoTemporario

import app as app_modulo
from werkzeug.security import generate_password_hash


class BasePermissoes(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        app_modulo.app.config["TESTING"] = True

        self.empresa_id = self.criar_empresa()
        self.obra_id = self.criar_obra(self.empresa_id)

        self.criar_usuario("func@inov.com", "Funcionario", "comum")

    def criar_usuario(self, email, nome, papel, senha="senha123", ativo=1):
        with self.conectar() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO usuarios (nome, email, senha_hash, papel, ativo, criado_em)
                VALUES (?, ?, ?, ?, ?, '2026-01-01')
                """,
                (nome, email, generate_password_hash(senha), papel, ativo),
            )
            conn.commit()
            return cur.lastrowid

    def entrar(self, email="admin@inov.com", senha="1234"):
        cliente = app_modulo.app.test_client()
        html = cliente.get("/").get_data(as_text=True)
        token = re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
        cliente.post("/", data={"email": email, "senha": senha, "_csrf": token})
        return cliente

    def token(self, cliente, rota):
        html = cliente.get(rota).get_data(as_text=True)
        achado = re.search(r'name="_csrf" value="([^"]+)"', html)
        return achado.group(1) if achado else ""

    def como_funcionario(self):
        return self.entrar("func@inov.com", "senha123")

    def como_admin(self):
        return self.entrar()


class TestFuncionarioOperaNormalmente(BasePermissoes):
    """O funcionário não é um usuário de segunda classe: ele toca o dia a dia."""

    def setUp(self):
        super().setUp()
        self.cliente = self.como_funcionario()

    def test_ve_todas_as_telas_de_trabalho(self):
        for rota in ["/dashboard", "/obras", "/totais", "/empresas", "/categorias",
                     "/taxas", "/lancamentos", "/importar-dados", "/minha-conta",
                     f"/obras/{self.obra_id}"]:
            with self.subTest(rota=rota):
                self.assertEqual(self.cliente.get(rota).status_code, 200)

    def test_pode_lancar_valores(self):
        categoria_id = self.id_categoria("Salarios e Ordenados")
        self.cliente.post("/lancamentos", data={
            "obra_id": self.obra_id, "mes": 6, "ano": 2026,
            f"valor_{categoria_id}": "1234,56",
            "_csrf": self.token(self.cliente, f"/lancamentos?obra_id={self.obra_id}&mes=6&ano=2026"),
        })

        with self.conectar() as conn:
            row = conn.execute(
                "SELECT valor FROM lancamentos WHERE obra_id=? AND categoria_id=? AND mes=6 AND ano=2026",
                (self.obra_id, categoria_id),
            ).fetchone()

        self.assertIsNotNone(row, "o funcionário não conseguiu lançar")
        self.assertAlmostEqual(row["valor"], 1234.56, places=2)

    def test_pode_cadastrar_empresa_e_obra(self):
        self.cliente.post("/empresas", data={
            "nome": "NOVA CONSTRUTORA", "_csrf": self.token(self.cliente, "/empresas"),
        })
        self.cliente.post("/obras", data={
            "nome": "OBRA NOVA", "codigo": "777", "empresa_id": self.empresa_id,
            "status": "em_andamento", "_csrf": self.token(self.cliente, "/obras"),
        })

        with self.conectar() as conn:
            empresas = conn.execute(
                "SELECT COUNT(*) c FROM empresas WHERE nome='NOVA CONSTRUTORA'").fetchone()["c"]
            obras = conn.execute("SELECT COUNT(*) c FROM obras WHERE codigo='777'").fetchone()["c"]

        self.assertEqual(empresas, 1)
        self.assertEqual(obras, 1)

    def test_pode_exportar(self):
        for rota in [f"/obras/{self.obra_id}/exportar", "/totais/exportar"]:
            with self.subTest(rota=rota):
                self.assertEqual(self.cliente.get(rota).status_code, 200)

    def test_pode_ativar_e_desativar_categoria(self):
        categoria_id = self.id_categoria("Alimentação")
        self.cliente.post(f"/categorias/{categoria_id}/alternar-status",
                          data={"_csrf": self.token(self.cliente, "/categorias")})

        with self.conectar() as conn:
            ativo = conn.execute(
                "SELECT ativo FROM categorias_conta WHERE id=?", (categoria_id,)).fetchone()["ativo"]
        self.assertEqual(ativo, 0)

    def test_pode_trocar_a_propria_senha(self):
        r = self.cliente.post("/minha-conta", data={
            "senha_atual": "senha123", "senha_nova": "novasenha", "senha_confirmacao": "novasenha",
            "_csrf": self.token(self.cliente, "/minha-conta"),
        }, follow_redirects=True)

        self.assertIn("alterada com sucesso", r.get_data(as_text=True))
        self.assertEqual(self.entrar("func@inov.com", "novasenha").get("/dashboard").status_code, 200)


class TestAcoesRestritas(BasePermissoes):
    """Excluir, mexer em taxa e administrar usuários é da dona da empresa."""

    def setUp(self):
        super().setUp()
        self.funcionario = self.como_funcionario()

    def test_funcionario_nao_exclui_obra(self):
        self.funcionario.post(f"/obras/{self.obra_id}/excluir", data={
            "_csrf": self.token(self.funcionario, f"/obras/{self.obra_id}/editar"),
        })

        with self.conectar() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM obras WHERE id=?", (self.obra_id,)).fetchone()["c"]
        self.assertEqual(n, 1, "o funcionário conseguiu excluir a obra")

    def test_funcionario_nao_exclui_empresa(self):
        vazia = self.criar_empresa("EMPRESA SEM OBRA")
        self.funcionario.post(f"/empresas/{vazia}/excluir", data={
            "_csrf": self.token(self.funcionario, f"/empresas/{vazia}/editar"),
        })

        with self.conectar() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM empresas WHERE id=?", (vazia,)).fetchone()["c"]
        self.assertEqual(n, 1, "o funcionário conseguiu excluir a empresa")

    def test_funcionario_nao_cria_vigencia_de_taxa(self):
        with self.conectar() as conn:
            antes = conn.execute("SELECT COUNT(*) c FROM taxas").fetchone()["c"]

        self.funcionario.post("/taxas", data={
            "chave": "irpj_csll", "percentual": "99", "vigencia_inicio": "2026-09",
            "_csrf": self.token(self.funcionario, "/taxas"),
        })

        with self.conectar() as conn:
            depois = conn.execute("SELECT COUNT(*) c FROM taxas").fetchone()["c"]
        self.assertEqual(antes, depois, "o funcionário criou uma vigência de taxa")

    def test_funcionario_ainda_consulta_as_taxas(self):
        """Consultar é preciso: todo mundo tem que saber a alíquota usada no DRE."""
        html = self.funcionario.get("/taxas").get_data(as_text=True)
        self.assertEqual(self.funcionario.get("/taxas").status_code, 200)
        self.assertIn("13,15", html)

    def test_funcionario_nao_acessa_a_tela_de_usuarios(self):
        r = self.funcionario.get("/usuarios", follow_redirects=True)
        self.assertIn("restrita à administradora", r.get_data(as_text=True))

    def test_funcionario_nao_cria_usuario(self):
        self.funcionario.post("/usuarios", data={
            "nome": "Intruso", "email": "intruso@inov.com", "senha": "senha123",
            "papel": "admin", "_csrf": self.token(self.funcionario, "/dashboard"),
        })

        with self.conectar() as conn:
            n = conn.execute(
                "SELECT COUNT(*) c FROM usuarios WHERE email='intruso@inov.com'").fetchone()["c"]
        self.assertEqual(n, 0)

    def test_funcionario_nao_se_promove(self):
        with self.conectar() as conn:
            meu_id = conn.execute(
                "SELECT id FROM usuarios WHERE email='func@inov.com'").fetchone()["id"]

        self.funcionario.post(f"/usuarios/{meu_id}/papel", data={
            "papel": "admin", "_csrf": self.token(self.funcionario, "/dashboard"),
        })

        with self.conectar() as conn:
            papel = conn.execute("SELECT papel FROM usuarios WHERE id=?", (meu_id,)).fetchone()["papel"]
        self.assertEqual(papel, "comum")

    def test_admin_faz_tudo_isso(self):
        admin = self.como_admin()

        self.assertEqual(admin.get("/usuarios").status_code, 200)

        admin.post(f"/obras/{self.obra_id}/excluir", data={
            "_csrf": self.token(admin, f"/obras/{self.obra_id}/editar"),
        })
        with self.conectar() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM obras WHERE id=?", (self.obra_id,)).fetchone()["c"]
        self.assertEqual(n, 0, "a administradora não conseguiu excluir a obra")


class TestGestaoDeUsuarios(BasePermissoes):

    def setUp(self):
        super().setUp()
        self.admin = self.como_admin()

    def test_admin_cria_usuario(self):
        self.admin.post("/usuarios", data={
            "nome": "Maria", "email": "maria@inov.com", "senha": "senha123",
            "papel": "comum", "_csrf": self.token(self.admin, "/usuarios"),
        })

        self.assertEqual(self.entrar("maria@inov.com", "senha123").get("/dashboard").status_code, 200)

    def test_senha_curta_e_recusada(self):
        self.admin.post("/usuarios", data={
            "nome": "Curto", "email": "curto@inov.com", "senha": "123",
            "papel": "comum", "_csrf": self.token(self.admin, "/usuarios"),
        })

        with self.conectar() as conn:
            n = conn.execute(
                "SELECT COUNT(*) c FROM usuarios WHERE email='curto@inov.com'").fetchone()["c"]
        self.assertEqual(n, 0)

    def test_usuario_desativado_nao_entra(self):
        desativado = self.criar_usuario("saiu@inov.com", "Saiu", "comum", ativo=0)
        self.assertIsNotNone(desativado)

        cliente = self.entrar("saiu@inov.com", "senha123")
        self.assertEqual(cliente.get("/dashboard").status_code, 302)

    def test_nao_deixa_o_sistema_sem_administradora(self):
        with self.conectar() as conn:
            admin_id = conn.execute(
                "SELECT id FROM usuarios WHERE email='admin@inov.com'").fetchone()["id"]

        self.admin.post(f"/usuarios/{admin_id}/papel", data={
            "papel": "comum", "_csrf": self.token(self.admin, "/usuarios"),
        })

        with self.conectar() as conn:
            papel = conn.execute("SELECT papel FROM usuarios WHERE id=?", (admin_id,)).fetchone()["papel"]
        self.assertEqual(papel, "admin", "o último admin foi rebaixado")

    def test_admin_nao_desativa_o_proprio_acesso(self):
        with self.conectar() as conn:
            admin_id = conn.execute(
                "SELECT id FROM usuarios WHERE email='admin@inov.com'").fetchone()["id"]

        self.admin.post(f"/usuarios/{admin_id}/alternar-acesso", data={
            "_csrf": self.token(self.admin, "/usuarios"),
        })

        with self.conectar() as conn:
            ativo = conn.execute("SELECT ativo FROM usuarios WHERE id=?", (admin_id,)).fetchone()["ativo"]
        self.assertEqual(ativo, 1)

    def test_admin_redefine_senha_de_outro(self):
        with self.conectar() as conn:
            func_id = conn.execute(
                "SELECT id FROM usuarios WHERE email='func@inov.com'").fetchone()["id"]

        self.admin.post(f"/usuarios/{func_id}/senha", data={
            "senha": "trocada123", "_csrf": self.token(self.admin, "/usuarios"),
        })

        self.assertEqual(self.entrar("func@inov.com", "trocada123").get("/dashboard").status_code, 200)


class TestMigracaoDeUsuarios(BaseComBancoTemporario):

    def test_banco_antigo_ganha_as_colunas_novas(self):
        """A tabela usuarios já existia sem papel/ativo nos bancos em uso."""
        import db

        with self.conectar() as conn:
            conn.execute("DROP TABLE usuarios")
            conn.execute("""
                CREATE TABLE usuarios (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    nome TEXT NOT NULL, email TEXT NOT NULL UNIQUE, senha_hash TEXT NOT NULL
                )
            """)
            conn.execute(
                "INSERT INTO usuarios (nome, email, senha_hash) VALUES ('Antigo', 'antigo@inov.com', 'x')")
            conn.commit()

        db.criar_tabelas()

        with self.conectar() as conn:
            colunas = {r["name"] for r in conn.execute("PRAGMA table_info(usuarios)")}
            usuario = conn.execute(
                "SELECT papel, ativo FROM usuarios WHERE email='antigo@inov.com'").fetchone()

        self.assertLessEqual({"papel", "ativo", "criado_em"}, colunas)
        self.assertEqual(usuario["ativo"], 1)
        # Sem nenhum admin, o usuário mais antigo é promovido para não travar todo mundo.
        self.assertEqual(usuario["papel"], "admin")


if __name__ == "__main__":
    unittest.main()
