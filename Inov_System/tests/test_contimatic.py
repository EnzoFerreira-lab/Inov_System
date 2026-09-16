"""
Testa a importação do DRE por centro de custo do Contimatic.

O arquivo de exemplo é montado aqui, reproduzindo o relatório real linha por
linha — inclusive as armadilhas do formato: nome de conta com hífen, conta sem
código, nome cortado pela largura da coluna, estorno positivo em conta de custo
e três jeitos diferentes de escrever o cabeçalho do centro de custo.
"""

import os
import unittest
import tempfile

from openpyxl import Workbook

from tests.apoio import BaseComBancoTemporario

import contimatic
from contimatic import (
    ler_relatorio, conferir_totais, importar_linhas, buscar_partidas,
    ResolvedorDeContas, chave_da_conta, _codigo_limpo, _valor_da_celula,
)
from dre_import import RegistroImportacao, desfazer_importacao
from dre import calcular_dre_obra


# Transcrito dos relatórios reais.
RELATORIO = [
    ("DEPTO TECNICO", None),
    ("Custos", None),
    ("Salarios e Ordenados - 311", -7936.28),
    ("Medicina Ocupacional e Assist médica - 31", -693.00),
    ("Custos Total...", -8629.28),
    ("= Prejuízo Bruto", -8629.28),
    ("Despesas Administrativas", None),
    ("Serviços prestados por terceiros - 222", -1513.61),
    ("Despesas Administrativas Total...", -1513.61),
    ("= Prejuízo", -10142.89),

    ("DEMAIS OBRAS", None),
    ("Custos", None),
    ("Locação de Maqs, Ferramentas e Equipamen", -245.97),
    ("Custos Total...", -245.97),
    ("= Prejuízo", -245.97),

    ("OBRA: 251 ESTHER TOERS", None),
    ("Custos", None),
    ("Salarios e Ordenados - 311", -26468.83),
    ("Horas Extras - 499", -3443.29),
    ("Custos Total...", -29912.12),
    ("= Prejuízo", -29912.12),

    ("OBRA: 318 VISTA BROOKLIN - ADOLPHO", None),
    ("Receitas Brutas", None),
    ("Servicos prestados - mercado interno - 25", 217704.60),
    ("Receitas Brutas Total...", 217704.60),
    ("Deduções", None),
    ("INSS S/ FATURAMENTO - 544", -5878.02),
    ("Deduções Total...", -5878.02),
    ("= Receita Líquida", 211826.58),
    ("Custos", None),
    ("Salarios e Ordenados - 311", -28270.19),
    ("Equipamento de Segurança - EPIs - 360", -1200.00),
    ("Despesas com Radio e Telefonia Celular -", -254.40),
    ("Custos Total...", -29724.59),
    ("= Lucro Bruto", 182102.0),
    ("= Lucro", 182102.0),

    ("OBRA: 320 SPLEND MOEMA - EXTO", None),
    ("Custos", None),
    ("Salarios e Ordenados - 311", -4429.88),
    ("Alimentação - 320", 25.60),          # estorno: positivo em conta de custo
    ("Custos Total...", -4404.28),
    ("= Prejuízo", -4404.28),
]


def gerar_arquivo(linhas=RELATORIO, pasta=None):
    pasta = pasta or tempfile.mkdtemp(prefix="inov_contimatic_")
    caminho = os.path.join(pasta, "relatorio.xlsx")

    wb = Workbook()
    ws = wb.active
    ws.title = "DRE Centro de Custo"
    for rotulo, valor in linhas:
        ws.append([rotulo, valor])
    wb.save(caminho)

    return caminho


class TestLeituraDoArquivo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.leitura = ler_relatorio(gerar_arquivo())

    def test_reconhece_os_tres_formatos_de_cabecalho(self):
        """'DEPTO TECNICO', 'DEMAIS OBRAS' e 'OBRA: <n> <nome>'."""
        self.assertEqual(
            set(self.leitura["obras"]), {"DEPTO-TEC", "DEMAIS", "251", "318", "320"}
        )

    def test_nome_da_obra_sai_sem_o_prefixo(self):
        self.assertEqual(self.leitura["obras"]["318"], "VISTA BROOKLIN - ADOLPHO")

    def test_cabecalho_com_traco_depois_do_numero(self):
        leitura = ler_relatorio(gerar_arquivo([
            ("OBRA: 319 - BOSQUE VILA NOVA - R YAZBEK", None),
            ("Custos", None),
            ("Ferias - 315", -10.0),
        ]))
        self.assertEqual(leitura["obras"]["319"], "BOSQUE VILA NOVA - R YAZBEK")

    def test_separa_as_secoes(self):
        secoes = {l["secao"] for l in self.leitura["linhas"]}
        self.assertEqual(
            secoes, {"receita", "deducao", "custo", "despesa_administrativa"}
        )

    def test_codigo_e_o_ultimo_numero_mesmo_com_traco_no_nome(self):
        """'Servicos prestados - mercado interno - 25' tem hífen no próprio nome."""
        linha = next(l for l in self.leitura["linhas"] if l["conta_codigo"] == "25")
        self.assertEqual(linha["conta_nome"], "Servicos prestados - mercado interno")

        epi = next(l for l in self.leitura["linhas"] if l["conta_codigo"] == "360")
        self.assertEqual(epi["conta_nome"], "Equipamento de Segurança - EPIs")

    def test_conta_sem_codigo_e_lida_assim_mesmo(self):
        linha = next(
            l for l in self.leitura["linhas"]
            if l["conta_nome"].startswith("Locação de Maqs")
        )
        self.assertIsNone(linha["conta_codigo"])
        self.assertAlmostEqual(linha["valor"], -245.97, places=2)

    def test_hifen_solto_no_fim_nao_vira_parte_do_nome(self):
        """A coluna estreita corta o nome e deixa o traço sobrando."""
        linha = next(
            l for l in self.leitura["linhas"]
            if l["conta_nome"].startswith("Despesas com Radio")
        )
        self.assertEqual(linha["conta_nome"], "Despesas com Radio e Telefonia Celular")
        self.assertIsNone(linha["conta_codigo"])

    def test_linhas_de_total_e_resultado_nao_viram_conta(self):
        nomes = {l["conta_nome"] for l in self.leitura["linhas"]}
        for indevido in ["Custos Total...", "= Lucro Bruto", "= Prejuízo", "= Receita Líquida"]:
            self.assertNotIn(indevido, nomes)

    def test_estorno_positivo_em_custo_e_preservado(self):
        linha = next(
            l for l in self.leitura["linhas"]
            if l["obra_codigo"] == "320" and l["conta_codigo"] == "320"
        )
        self.assertAlmostEqual(linha["valor"], 25.60, places=2)

    def test_arquivo_sem_nada_reconhecivel_avisa(self):
        caminho = gerar_arquivo([("qualquer coisa", None), ("outra linha", 10.0)])
        leitura = ler_relatorio(caminho)
        self.assertEqual(leitura["linhas"], [])
        self.assertTrue(leitura["avisos"])


class TestConferenciaDeTotais(unittest.TestCase):
    """
    O relatório declara "Custos Total..." por obra. Somar as contas lidas e
    comparar é o que pega linha não lida ou lida duas vezes — antes de gravar.
    """

    def test_relatorio_integro_nao_acusa_divergencia(self):
        self.assertEqual(conferir_totais(ler_relatorio(gerar_arquivo())), [])

    def test_total_que_nao_fecha_e_acusado(self):
        adulterado = [
            ("OBRA: 251 ESTHER TOERS", None),
            ("Custos", None),
            ("Salarios e Ordenados - 311", -100.0),
            ("Custos Total...", -999.0),      # o relatório afirma outra coisa
            ("= Prejuízo", -999.0),
        ]
        divergencias = conferir_totais(ler_relatorio(gerar_arquivo(adulterado)))

        self.assertEqual(len(divergencias), 1)
        self.assertEqual(divergencias[0]["obra_codigo"], "251")
        self.assertAlmostEqual(divergencias[0]["declarado"], -999.0, places=2)
        self.assertAlmostEqual(divergencias[0]["lido"], -100.0, places=2)


class TestValorDaCelula(unittest.TestCase):

    def test_numero_vem_direto(self):
        self.assertEqual(_valor_da_celula(-7936.28), -7936.28)

    def test_formato_contabil_em_texto(self):
        """Se a coluna vier como texto, o negativo aparece entre parênteses."""
        self.assertAlmostEqual(_valor_da_celula("(7.936,28)"), -7936.28, places=2)
        self.assertAlmostEqual(_valor_da_celula("217.704,60"), 217704.60, places=2)
        self.assertAlmostEqual(_valor_da_celula("(7,936.28)"), -7936.28, places=2)

    def test_texto_sem_numero_devolve_nada(self):
        for entrada in [None, "", "Custos", "-", "..."]:
            self.assertIsNone(_valor_da_celula(entrada))


class TestChaveDaConta(unittest.TestCase):

    def test_codigo_manda_quando_existe(self):
        self.assertEqual(chave_da_conta("311", "Salarios"), "311")
        self.assertEqual(chave_da_conta("0000311", "Salarios"), "311")

    def test_sem_codigo_a_chave_vem_do_nome(self):
        """Sem isso a conta não vira nem pendência e some do DRE em silêncio."""
        chave = chave_da_conta(None, "Locação de Maqs, Ferramentas e Equipamen")
        self.assertTrue(chave.startswith("nome:"))
        self.assertEqual(chave, chave_da_conta("", "LOCAÇÃO DE MAQS, FERRAMENTAS E EQUIPAMEN"))

    def test_sem_codigo_e_sem_nome_nao_ha_chave(self):
        self.assertEqual(chave_da_conta(None, None), "")


class BaseImportacao(BaseComBancoTemporario):

    def setUp(self):
        super().setUp()
        self.empresa_id = self.criar_empresa()
        self.obra_251 = self.criar_obra(self.empresa_id, codigo="251", nome="OBRA 251")
        self.obra_318 = self.criar_obra(self.empresa_id, codigo="318", nome="OBRA 318")
        self.zerar_taxas()

        self.leitura = ler_relatorio(gerar_arquivo())

    def importar(self, competencia=(2026, 7), sobrescrever=False, linhas=None):
        with self.conectar() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO importacoes (arquivo, criado_em) VALUES ('contimatic.xlsx', '2026-01-01')"
            )
            importacao_id = cur.lastrowid
            resumo = importar_linhas(
                cur,
                linhas if linhas is not None else self.leitura["linhas"],
                competencia,
                RegistroImportacao(cur, importacao_id, sobrescrever),
                importacao_id,
                empresa_id=self.empresa_id,
            )
            conn.commit()
        return resumo, importacao_id

    def valor(self, obra_id, categoria_nome, mes=7, ano=2026):
        with self.conectar() as conn:
            linha = conn.execute(
                "SELECT valor FROM lancamentos WHERE obra_id=? AND categoria_id=? AND mes=? AND ano=?",
                (obra_id, self.id_categoria(categoria_nome), mes, ano),
            ).fetchone()
        return linha["valor"] if linha else None


class TestImportacao(BaseImportacao):

    def test_grava_na_competencia_escolhida(self):
        """O relatório não traz data: o mês vem da tela."""
        self.importar(competencia=(2026, 3))

        self.assertAlmostEqual(self.valor(self.obra_251, "Salarios e Ordenados", mes=3), 26468.83, places=2)
        self.assertIsNone(self.valor(self.obra_251, "Salarios e Ordenados", mes=7))

    def test_valor_entra_como_magnitude(self):
        """No relatório o custo é negativo; no sistema o sinal vem do tipo."""
        self.importar()
        self.assertAlmostEqual(self.valor(self.obra_251, "Salarios e Ordenados"), 26468.83, places=2)

    def test_obra_nova_e_criada_com_o_nome_do_relatorio(self):
        resumo, _ = self.importar()

        with self.conectar() as conn:
            obra = conn.execute("SELECT nome FROM obras WHERE codigo = '320'").fetchone()

        self.assertIsNotNone(obra, "a obra 320 não foi criada")
        self.assertIn("SPLEND MOEMA", obra["nome"])
        self.assertTrue(resumo["obras_criadas"])

    def test_obra_existente_nao_tem_o_nome_sobrescrito(self):
        self.importar()
        with self.conectar() as conn:
            nome = conn.execute("SELECT nome FROM obras WHERE codigo='251'").fetchone()["nome"]
        self.assertEqual(nome, "OBRA 251")

    def test_reimportar_substitui_em_vez_de_somar(self):
        self.importar()
        primeiro = self.valor(self.obra_251, "Salarios e Ordenados")

        self.importar()
        self.assertAlmostEqual(self.valor(self.obra_251, "Salarios e Ordenados"), primeiro, places=2)

    def test_reimportar_nao_duplica_o_detalhe(self):
        self.importar()
        self.importar()

        with self.conectar() as conn:
            partidas = buscar_partidas(
                conn.cursor(), self.obra_251, self.id_categoria("Salarios e Ordenados"), 2026, 7
            )
        self.assertEqual(len(partidas), 1)

    def test_detalhe_guarda_a_conta_e_a_secao_de_origem(self):
        self.importar()

        with self.conectar() as conn:
            partidas = buscar_partidas(
                conn.cursor(), self.obra_251, self.id_categoria("Salarios e Ordenados"), 2026, 7
            )

        self.assertEqual(partidas[0]["conta_codigo"], "311")
        self.assertEqual(partidas[0]["secao"], "custo")

    def test_dre_reflete_o_relatorio(self):
        self.importar()
        totais = calcular_dre_obra(self.obra_251, [(2026, m) for m in range(1, 13)])["totais"][(2026, 7)]
        self.assertAlmostEqual(totais["custos_total"], 26468.83 + 3443.29, places=2)


class TestContasPendentes(BaseImportacao):
    """
    Conta que o sistema não sabe classificar NÃO entra no DRE. É de propósito:
    chutar a categoria desloca dinheiro entre linhas sem gerar erro nenhum.
    """

    def test_conta_desconhecida_fica_pendente_e_nao_entra(self):
        resumo, _ = self.importar()
        chaves = {p["chave"] for p in resumo["pendencias"]}

        self.assertIn("25", chaves, "a conta de receita 25 deveria ficar pendente")
        self.assertEqual(
            self.valor(self.obra_318, "Serviços prestados"), None,
            "o valor entrou no DRE sem alguém confirmar a categoria",
        )

    def test_deducao_e_despesa_administrativa_nao_entram_sozinhas(self):
        """O DRE já calcula imposto e despesa adm. por alíquota — entraria em dobro."""
        resumo, _ = self.importar()
        por_chave = {p["chave"]: p for p in resumo["pendencias"]}

        self.assertEqual(por_chave["544"]["motivo"], "secao_sem_equivalente")
        self.assertEqual(por_chave["222"]["motivo"], "secao_sem_equivalente")

    def test_conta_sem_codigo_tambem_vira_pendencia(self):
        resumo, _ = self.importar()
        chaves = {p["chave"] for p in resumo["pendencias"]}
        self.assertTrue(any(c.startswith("nome:") for c in chaves))

    def test_pendencia_traz_valor_e_obras_afetadas(self):
        resumo, _ = self.importar()
        pendencia = next(p for p in resumo["pendencias"] if p["chave"] == "25")

        self.assertAlmostEqual(pendencia["valor_total"], 217704.60, places=2)
        self.assertEqual(pendencia["obras"], ["318"])

    def test_de_para_resolve_e_o_valor_passa_a_entrar(self):
        self.importar()

        with self.conectar() as conn:
            conn.execute(
                "INSERT INTO contas_map (conta_codigo, categoria_id, criado_em) VALUES ('25', ?, '2026')",
                (self.id_categoria("Serviços prestados"),),
            )
            conn.commit()

        self.importar()
        self.assertAlmostEqual(self.valor(self.obra_318, "Serviços prestados"), 217704.60, places=2)

    def test_conta_marcada_para_ignorar_para_de_incomodar(self):
        with self.conectar() as conn:
            conn.execute(
                "INSERT INTO contas_map (conta_codigo, ignorar, criado_em) VALUES ('544', 1, '2026')"
            )
            conn.commit()

        resumo, _ = self.importar()
        self.assertNotIn("544", {p["chave"] for p in resumo["pendencias"]})


class TestSugestoes(BaseImportacao):

    def sugerir(self, nome, tipo=None):
        with self.conectar() as conn:
            return ResolvedorDeContas(conn.cursor()).sugerir(nome, tipo)

    def test_nome_cortado_pela_coluna_e_reconhecido_pelo_prefixo(self):
        sugestao = self.sugerir("Locação de Máqs, Ferramentas e Equipamen", "custo")
        self.assertIsNotNone(sugestao)
        self.assertEqual(sugestao["categoria_nome"], "Locação de Máqs, Ferramentas e Equipamentos")

    def test_nome_detalhado_casa_com_o_resumido(self):
        sugestao = self.sugerir("Serviços prestados - mercado interno", "receita")
        self.assertIsNotNone(sugestao)
        self.assertEqual(sugestao["categoria_nome"], "Serviços prestados")

    def test_sugestao_nunca_atravessa_de_despesa_para_receita(self):
        """
        "Serviços prestados por terceiros" é despesa e quase casa por prefixo com
        a receita "Serviços prestados" — sugerir isso viraria gasto em faturamento.
        """
        self.assertIsNone(self.sugerir("Serviços prestados por terceiros", "custo"))

    def test_sem_nada_parecido_nao_inventa(self):
        self.assertIsNone(self.sugerir("INSS S/ FATURAMENTO", "custo"))


class TestProtecoesContinuamValendo(BaseImportacao):

    def test_lancamento_manual_e_preservado(self):
        self.lancar(self.obra_251, "Salarios e Ordenados", 7, 2026, 999.0, origem="manual")
        self.importar()
        self.assertAlmostEqual(self.valor(self.obra_251, "Salarios e Ordenados"), 999.0, places=2)

    def test_com_permissao_o_relatorio_prevalece(self):
        self.lancar(self.obra_251, "Salarios e Ordenados", 7, 2026, 999.0, origem="manual")
        self.importar(sobrescrever=True)
        self.assertAlmostEqual(self.valor(self.obra_251, "Salarios e Ordenados"), 26468.83, places=2)

    def test_desfazer_devolve_o_valor_anterior(self):
        self.lancar(self.obra_251, "Salarios e Ordenados", 7, 2026, 111.0, origem="importacao")

        _, importacao_id = self.importar()
        self.assertAlmostEqual(self.valor(self.obra_251, "Salarios e Ordenados"), 26468.83, places=2)

        with self.conectar() as conn:
            desfazer_importacao(conn.cursor(), importacao_id)
            conn.commit()

        self.assertAlmostEqual(self.valor(self.obra_251, "Salarios e Ordenados"), 111.0, places=2)


if __name__ == "__main__":
    unittest.main()
