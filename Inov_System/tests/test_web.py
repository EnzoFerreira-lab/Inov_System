"""
Testa as rotas: autenticação, proteção CSRF e formatação brasileira.
"""

import re
import unittest

from tests.apoio import BaseComBancoTemporario

import app as app_modulo


class BaseWeb(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        app_modulo.app.config["TESTING"] = True
        self.cliente = app_modulo.app.test_client()

        self.empresa_id = self.criar_empresa()
        self.obra_id = self.criar_obra(self.empresa_id)

    def token(self, rota="/"):
        """Lê o token CSRF de um formulário, como um navegador faria."""
        html = self.cliente.get(rota).get_data(as_text=True)
        achado = re.search(r'name="_csrf" value="([^"]+)"', html)
        self.assertIsNotNone(achado, f"nenhum campo CSRF em {rota}")
        return achado.group(1)

    def entrar(self):
        self.cliente.post("/", data={
            "email": "admin@inov.com", "senha": "1234", "_csrf": self.token("/"),
        })


class TestAutenticacao(BaseWeb):

    def test_login_valido_leva_ao_dashboard(self):
        r = self.cliente.post("/", data={
            "email": "admin@inov.com", "senha": "1234", "_csrf": self.token("/"),
        })
        self.assertEqual(r.status_code, 302)
        self.assertIn("/dashboard", r.headers["Location"])

    def test_senha_errada_nao_entra(self):
        r = self.cliente.post("/", data={
            "email": "admin@inov.com", "senha": "errada", "_csrf": self.token("/"),
        }, follow_redirects=True)
        self.assertIn("inválidos", r.get_data(as_text=True))

    def test_rota_interna_exige_login(self):
        for rota in ["/dashboard", "/obras", "/totais", "/categorias", "/taxas"]:
            r = self.cliente.get(rota)
            self.assertEqual(r.status_code, 302, f"{rota} deveria redirecionar")

    def test_logout_encerra_a_sessao(self):
        self.entrar()
        self.assertEqual(self.cliente.get("/dashboard").status_code, 200)
        self.cliente.get("/logout")
        self.assertEqual(self.cliente.get("/dashboard").status_code, 302)


class TestProtecaoCsrf(BaseWeb):

    def setUp(self):
        super().setUp()
        self.entrar()

    def test_post_sem_token_e_recusado(self):
        r = self.cliente.post("/empresas", data={"nome": "SEM TOKEN LTDA"})
        self.assertEqual(r.status_code, 400)

        with self.conectar() as conn:
            n = conn.execute(
                "SELECT COUNT(*) c FROM empresas WHERE nome = 'SEM TOKEN LTDA'"
            ).fetchone()["c"]
        self.assertEqual(n, 0, "empresa foi criada mesmo sem token")

    def test_post_com_token_invalido_e_recusado(self):
        r = self.cliente.post("/empresas", data={"nome": "X", "_csrf": "token-falso"})
        self.assertEqual(r.status_code, 400)

    def test_post_com_token_valido_funciona(self):
        r = self.cliente.post("/empresas", data={
            "nome": "COM TOKEN LTDA", "_csrf": self.token("/empresas"),
        }, follow_redirects=True)
        self.assertEqual(r.status_code, 200)

        with self.conectar() as conn:
            n = conn.execute(
                "SELECT COUNT(*) c FROM empresas WHERE nome = 'COM TOKEN LTDA'"
            ).fetchone()["c"]
        self.assertEqual(n, 1)

    def test_exclusao_de_obra_sem_token_e_recusada(self):
        """A rota mais destrutiva: apaga a obra e todos os lançamentos dela."""
        r = self.cliente.post(f"/obras/{self.obra_id}/excluir")
        self.assertEqual(r.status_code, 400)

        with self.conectar() as conn:
            n = conn.execute("SELECT COUNT(*) c FROM obras WHERE id = ?", (self.obra_id,)).fetchone()["c"]
        self.assertEqual(n, 1, "a obra foi excluída sem token")

    def test_alternar_categoria_nao_aceita_get(self):
        """Regressão: alterava dado por GET, disparável por pré-carregamento."""
        categoria_id = self.id_categoria("Alimentação")
        r = self.cliente.get(f"/categorias/{categoria_id}/alternar-status")
        self.assertEqual(r.status_code, 405)

        with self.conectar() as conn:
            ativo = conn.execute(
                "SELECT ativo FROM categorias_conta WHERE id = ?", (categoria_id,)
            ).fetchone()["ativo"]
        self.assertEqual(ativo, 1, "a categoria foi desativada por um GET")


class TestTelasRenderizam(BaseWeb):

    def setUp(self):
        super().setUp()
        self.entrar()
        self.lancar(self.obra_id, "Serviços prestados", 1, 2026, 10000.0)
        self.lancar(self.obra_id, "Salarios e Ordenados", 1, 2026, 4000.0)

    def test_todas_as_telas_respondem(self):
        rotas = [
            "/dashboard", "/obras", "/empresas", "/categorias", "/taxas",
            "/totais", "/importar-dados", "/lancamentos",
            f"/lancamentos?obra_id={self.obra_id}&mes=1&ano=2026",
            f"/obras/{self.obra_id}?ano=2026",
            f"/obras/{self.obra_id}/editar",
            f"/empresas/{self.empresa_id}/editar",
        ]
        for rota in rotas:
            r = self.cliente.get(rota)
            self.assertEqual(r.status_code, 200, f"{rota} devolveu {r.status_code}")

    def test_exportacoes_geram_arquivo_excel(self):
        for rota in [f"/obras/{self.obra_id}/exportar?ano=2026", "/totais/exportar?ano=2026"]:
            r = self.cliente.get(rota)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(r.data.startswith(b"PK"), f"{rota} não devolveu um .xlsx")

    def test_valores_saem_no_formato_brasileiro(self):
        html = self.cliente.get(f"/obras/{self.obra_id}?ano=2026").get_data(as_text=True)
        self.assertIn("10.000,00", html)
        self.assertNotIn(">10000.00<", html)

    def test_totais_filtra_por_empresa(self):
        """Regressão: o consolidado somava as obras de todas as empresas."""
        outra_empresa = self.criar_empresa("OUTRA CONSTRUTORA")
        outra_obra = self.criar_obra(outra_empresa, "999", "OBRA 999")
        self.lancar(outra_obra, "Serviços prestados", 1, 2026, 50000.0)

        so_a = self.cliente.get(f"/totais?ano=2026&empresa_id={self.empresa_id}").get_data(as_text=True)
        todas = self.cliente.get("/totais?ano=2026").get_data(as_text=True)

        self.assertIn("10.000,00", so_a)
        self.assertNotIn("60.000,00", so_a)
        self.assertIn("60.000,00", todas)


class TestFormatacao(unittest.TestCase):

    def test_moeda_no_padrao_brasileiro(self):
        self.assertEqual(app_modulo.filtro_moeda(1234.5), "1.234,50")
        self.assertEqual(app_modulo.filtro_moeda(1482310.554), "1.482.310,55")
        self.assertEqual(app_modulo.filtro_moeda(-24143.1), "-24.143,10")
        self.assertEqual(app_modulo.filtro_moeda(0), "0,00")
        self.assertEqual(app_modulo.filtro_moeda(None), "0,00")

    def test_moeda_curta(self):
        self.assertEqual(app_modulo.filtro_moeda_curta(1482310.55), "1,48 mi")
        self.assertEqual(app_modulo.filtro_moeda_curta(-3210.0), "-3,2 mil")
        self.assertEqual(app_modulo.filtro_moeda_curta(45.9), "45,90")

    def test_competencia_e_data(self):
        self.assertEqual(app_modulo.filtro_competencia_br("2026-06"), "Jun/2026")
        self.assertEqual(app_modulo.filtro_data_br("2026-06-01"), "01/06/2026")
        self.assertEqual(app_modulo.filtro_data_br(None), "—")

    def test_valor_digitado_aceita_os_formatos_usuais(self):
        casos = {
            "1234.56": 1234.56,
            "1234,56": 1234.56,
            "1.234,56": 1234.56,
            "R$ 1.234,56": 1234.56,
            "1,234.56": 1234.56,
            "": 0.0,
            "abc": 0.0,
            None: 0.0,
        }
        for entrada, esperado in casos.items():
            self.assertEqual(app_modulo.parse_valor_br(entrada), esperado, f"falhou em {entrada!r}")

    def test_valor_invalido_nao_levanta_excecao(self):
        """Regressão: digitar '1.234,56' na grade derrubava a rota com erro 500."""
        for entrada in ["...", "-", ",,,", "1.2.3,4,5"]:
            self.assertIsInstance(app_modulo.parse_valor_br(entrada), float)


if __name__ == "__main__":
    unittest.main()
