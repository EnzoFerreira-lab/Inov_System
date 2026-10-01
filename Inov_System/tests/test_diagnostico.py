"""
Testa a deteção de buraco nos dados.

O caso real: a planilha importada no começo do projeto foi gerada durante
junho/2026, com o mês ainda em fechamento. Quatro obras que faturaram em maio
e em julho ficaram zeradas em junho — R$ 1 milhão de receita sumiu do DRE e
ninguém notou por meses.

O detector tem que achar isso e, igualmente importante, **não** acusar obra
que simplesmente ainda não começou ou já encerrou.
"""

import re
import datetime
import unittest

from tests.apoio import BaseComBancoTemporario

import app as app_modulo
import diagnostico


class BaseLacunas(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        self.empresa_id = self.criar_empresa()
        self.obra = self.criar_obra(self.empresa_id, codigo="314", nome="OBRA 314")

    def lacunas(self, ano=2026, obra_id=None):
        with self.conectar() as conn:
            return diagnostico.detectar_lacunas(conn.cursor(), ano, obra_id)


class TestDetecaoDeLacunas(BaseLacunas):

    def test_mes_sanduiche_e_acusado(self):
        """Faturou em maio e em julho, zerada em junho: junho faltou."""
        self.lancar(self.obra, "Serviços prestados", 5, 2026, 491183.75)
        self.lancar(self.obra, "Serviços prestados", 7, 2026, 299371.97)

        lacunas = self.lacunas()

        self.assertEqual(len(lacunas), 1)
        self.assertEqual(lacunas[0]["mes"], 6)
        self.assertEqual(lacunas[0]["mes_nome"], "Jun")
        self.assertEqual(len(lacunas[0]["obras"]), 1)
        self.assertEqual(lacunas[0]["obras"][0]["codigo"], "314")

    def test_traz_o_valor_dos_meses_vizinhos(self):
        self.lancar(self.obra, "Serviços prestados", 5, 2026, 491183.75)
        self.lancar(self.obra, "Serviços prestados", 7, 2026, 299371.97)

        obra = self.lacunas()[0]["obras"][0]

        self.assertEqual(obra["mes_anterior"], 5)
        self.assertEqual(obra["mes_seguinte"], 7)
        self.assertAlmostEqual(obra["receita_anterior"], 491183.75, places=2)
        self.assertAlmostEqual(obra["receita_seguinte"], 299371.97, places=2)

    def test_referencia_soma_o_mes_anterior_das_obras_afetadas(self):
        """É um número real — o que elas faturaram antes —, não uma estimativa."""
        outra = self.criar_obra(self.empresa_id, codigo="317", nome="OBRA 317")
        for obra_id, valor in [(self.obra, 491183.75), (outra, 252885.93)]:
            self.lancar(obra_id, "Serviços prestados", 5, 2026, valor)
            self.lancar(obra_id, "Serviços prestados", 7, 2026, 1000.0)

        lacuna = self.lacunas()[0]

        self.assertEqual(len(lacuna["obras"]), 2)
        self.assertAlmostEqual(lacuna["receita_de_referencia"], 744069.68, places=2)

    def test_varios_meses_seguidos_viram_lacunas_separadas(self):
        self.lancar(self.obra, "Serviços prestados", 3, 2026, 100.0)
        self.lancar(self.obra, "Serviços prestados", 7, 2026, 100.0)

        meses = {l["mes"] for l in self.lacunas()}
        self.assertEqual(meses, {4, 5, 6})

    def test_custo_sozinho_ja_conta_como_movimento(self):
        """Obra sem faturamento mas com custo também não some do nada."""
        self.lancar(self.obra, "Salarios e Ordenados", 5, 2026, 1000.0)
        self.lancar(self.obra, "Salarios e Ordenados", 7, 2026, 1000.0)

        lacunas = self.lacunas()
        self.assertEqual(len(lacunas), 1)
        self.assertEqual(lacunas[0]["mes"], 6)

    def test_ordena_pelo_mes_de_maior_valor(self):
        self.lancar(self.obra, "Serviços prestados", 1, 2026, 10.0)
        self.lancar(self.obra, "Serviços prestados", 3, 2026, 500000.0)
        self.lancar(self.obra, "Serviços prestados", 5, 2026, 10.0)

        lacunas = self.lacunas()
        # abril vem antes de fevereiro: depois de março, que faturou muito mais
        self.assertEqual(lacunas[0]["mes"], 4)


class TestNaoAcusaFalsoPositivo(BaseLacunas):
    """
    Obra que ainda não começou ou já encerrou não é buraco. Acusar isso faria
    o alerta virar ruído, e alerta que ninguém olha não serve para nada.
    """

    def test_meses_antes_do_primeiro_movimento_nao_contam(self):
        self.lancar(self.obra, "Serviços prestados", 10, 2026, 1000.0)
        self.lancar(self.obra, "Serviços prestados", 11, 2026, 1000.0)

        self.assertEqual(self.lacunas(), [])

    def test_meses_depois_do_ultimo_movimento_nao_contam(self):
        self.lancar(self.obra, "Serviços prestados", 1, 2026, 1000.0)
        self.lancar(self.obra, "Serviços prestados", 2, 2026, 1000.0)

        self.assertEqual(self.lacunas(), [])

    def test_obra_com_um_mes_so_nao_gera_lacuna(self):
        self.lancar(self.obra, "Serviços prestados", 6, 2026, 1000.0)
        self.assertEqual(self.lacunas(), [])

    def test_obra_sem_nenhum_movimento_nao_gera_lacuna(self):
        self.assertEqual(self.lacunas(), [])

    def test_meses_consecutivos_nao_geram_nada(self):
        for mes in range(1, 13):
            self.lancar(self.obra, "Serviços prestados", mes, 2026, 1000.0)
        self.assertEqual(self.lacunas(), [])

    def test_lancamento_zerado_nao_conta_como_movimento(self):
        """A planilha cria linha zerada para mês futuro; isso não é movimento."""
        self.lancar(self.obra, "Serviços prestados", 5, 2026, 1000.0)
        self.lancar(self.obra, "Serviços prestados", 6, 2026, 0.0)
        self.lancar(self.obra, "Serviços prestados", 7, 2026, 1000.0)

        lacunas = self.lacunas()
        self.assertEqual(len(lacunas), 1, "a linha zerada escondeu o buraco de junho")
        self.assertEqual(lacunas[0]["mes"], 6)

    def test_outro_ano_nao_interfere(self):
        self.lancar(self.obra, "Serviços prestados", 5, 2025, 1000.0)
        self.lancar(self.obra, "Serviços prestados", 7, 2026, 1000.0)

        self.assertEqual(self.lacunas(2026), [])
        self.assertEqual(self.lacunas(2025), [])

    def test_categoria_desativada_nao_conta(self):
        self.lancar(self.obra, "Serviços prestados", 5, 2026, 1000.0)
        self.lancar(self.obra, "Serviços prestados", 7, 2026, 1000.0)
        with self.conectar() as conn:
            conn.execute("UPDATE categorias_conta SET ativo = 0 WHERE nome = 'Serviços prestados'")
            conn.commit()

        self.assertEqual(self.lacunas(), [])


class TestFiltroPorObra(BaseLacunas):

    def test_filtra_so_a_obra_pedida(self):
        outra = self.criar_obra(self.empresa_id, codigo="317", nome="OBRA 317")
        for obra_id in (self.obra, outra):
            self.lancar(obra_id, "Serviços prestados", 5, 2026, 1000.0)
            self.lancar(obra_id, "Serviços prestados", 7, 2026, 1000.0)

        self.assertEqual(len(self.lacunas()[0]["obras"]), 2)
        self.assertEqual(len(self.lacunas(obra_id=self.obra)[0]["obras"]), 1)

    def test_obra_sem_lacuna_devolve_vazio(self):
        sem_buraco = self.criar_obra(self.empresa_id, codigo="251", nome="OBRA 251")
        self.lancar(self.obra, "Serviços prestados", 5, 2026, 1000.0)
        self.lancar(self.obra, "Serviços prestados", 7, 2026, 1000.0)
        self.lancar(sem_buraco, "Serviços prestados", 5, 2026, 1000.0)
        self.lancar(sem_buraco, "Serviços prestados", 6, 2026, 1000.0)

        self.assertEqual(self.lacunas(obra_id=sem_buraco), [])


class TestResumo(unittest.TestCase):

    def test_sem_lacuna_nao_ha_resumo(self):
        self.assertIsNone(diagnostico.resumir_lacunas([]))

    def test_resumo_de_um_mes(self):
        texto = diagnostico.resumir_lacunas(
            [{"mes": 6, "mes_nome": "Jun", "obras": [{}, {}], "receita_de_referencia": 0}]
        )
        self.assertIn("Jun", texto)
        self.assertIn("2 obra", texto)


class TestAlertaNaTela(BaseLacunas):

    def setUp(self):
        super().setUp()
        # Data fixa: o alerta de mês vencido compara com hoje, e sem fixar isso
        # o teste passaria agora e quebraria no mês seguinte.
        self._hoje_original = diagnostico._hoje
        diagnostico._hoje = lambda: datetime.date(2026, 10, 1)

        app_modulo.app.config["TESTING"] = True
        self.cliente = app_modulo.app.test_client()
        html = self.cliente.get("/").get_data(as_text=True)
        token = re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
        self.cliente.post("/", data={"email": "admin@inov.com", "senha": "1234", "_csrf": token})

    def tearDown(self):
        diagnostico._hoje = self._hoje_original
        super().tearDown()

    def criar_buraco(self):
        self.lancar(self.obra, "Serviços prestados", 5, 2026, 491183.75)
        self.lancar(self.obra, "Serviços prestados", 7, 2026, 299371.97)

    def test_dashboard_avisa_e_mostra_o_ano(self):
        self.criar_buraco()
        html = self.cliente.get("/dashboard?ano=2026").get_data(as_text=True)

        self.assertIn("card-lacuna", html)
        self.assertIn("Jun/2026", html)

    def test_dashboard_limpo_quando_nao_ha_buraco(self):
        # Todos os meses já vencidos precisam estar preenchidos: senão o outro
        # alerta (mês que venceu e não foi importado) dispara — corretamente.
        for mes in range(5, 10):   # com hoje fixo em 01/10, setembro é o último vencido
            self.lancar(self.obra, "Serviços prestados", mes, 2026, 1000.0)

        html = self.cliente.get("/dashboard?ano=2026").get_data(as_text=True)
        self.assertNotIn("card-lacuna", html)

    def test_dre_da_obra_avisa_com_texto_proprio(self):
        self.criar_buraco()
        html = self.cliente.get(f"/obras/{self.obra}?ano=2026").get_data(as_text=True)

        self.assertIn("card-lacuna", html)
        self.assertIn("Esta obra ficou sem lançamento", html)

    def test_dre_de_outra_obra_nao_herda_o_aviso(self):
        self.criar_buraco()
        limpa = self.criar_obra(self.empresa_id, codigo="251", nome="OBRA 251")
        self.lancar(limpa, "Serviços prestados", 1, 2026, 100.0)
        self.lancar(limpa, "Serviços prestados", 2, 2026, 100.0)

        html = self.cliente.get(f"/obras/{limpa}?ano=2026").get_data(as_text=True)
        self.assertNotIn("card-lacuna", html)


if __name__ == "__main__":
    unittest.main()


class TestMesesVencidosSemImportar(BaseLacunas):
    """
    O detector de sanduíche só enxerga buraco no meio. Um mês que simplesmente
    nunca foi importado fica no fim da fila, sem "depois" para formar o
    sanduíche, e passava batido — foi o caso de agosto e setembro de 2026.
    """

    def ausentes(self, ano=2026, hoje=None):
        with self.conectar() as conn:
            return diagnostico.detectar_meses_ausentes(
                conn.cursor(), ano, hoje or datetime.date(2026, 10, 1)
            )

    def test_acusa_mes_que_ja_venceu_e_esta_vazio(self):
        for mes in (5, 6, 7):
            self.lancar(self.obra, "Serviços prestados", mes, 2026, 1000.0)

        self.assertEqual([m["mes"] for m in self.ausentes()], [8, 9])

    def test_nao_acusa_o_mes_corrente(self):
        """Outubro ainda está acontecendo — cobrar o fechamento dele é ruído."""
        for mes in range(1, 10):
            self.lancar(self.obra, "Serviços prestados", mes, 2026, 1000.0)

        self.assertEqual(self.ausentes(), [])

    def test_nao_acusa_mes_anterior_ao_primeiro_dado(self):
        """A obra começou em maio; janeiro a abril não são buraco."""
        for mes in (5, 6, 7, 8, 9):
            self.lancar(self.obra, "Serviços prestados", mes, 2026, 1000.0)

        self.assertEqual(self.ausentes(), [])

    def test_nao_mexe_com_ano_anterior(self):
        """
        Em ano fechado não dá para separar "não importaram" de "a obra nem
        existia" — acusar isso encheria a tela de alarme falso.
        """
        self.lancar(self.obra, "Serviços prestados", 3, 2025, 1000.0)
        self.assertEqual(self.ausentes(ano=2025), [])

    def test_ano_sem_nenhum_dado_nao_acusa(self):
        self.assertEqual(self.ausentes(), [])

    def test_resumo_cobre_mes_vencido(self):
        texto = diagnostico.resumir_lacunas([], [{"mes": 8, "mes_nome": "Ago"}])
        self.assertIn("Ago", texto)
        self.assertIn("venceram", texto)

    def test_dashboard_avisa_dos_meses_vencidos(self):
        import re as _re
        original = diagnostico._hoje
        diagnostico._hoje = lambda: datetime.date(2026, 10, 1)
        self.addCleanup(lambda: setattr(diagnostico, "_hoje", original))

        for mes in (5, 6, 7):
            self.lancar(self.obra, "Serviços prestados", mes, 2026, 1000.0)

        app_modulo.app.config["TESTING"] = True
        cliente = app_modulo.app.test_client()
        html = cliente.get("/").get_data(as_text=True)
        token = _re.search(r'name="_csrf" value="([^"]+)"', html).group(1)
        cliente.post("/", data={"email": "admin@inov.com", "senha": "1234", "_csrf": token})

        pagina = cliente.get("/dashboard?ano=2026").get_data(as_text=True)
        self.assertIn("já venceram e não foram importados", pagina)
