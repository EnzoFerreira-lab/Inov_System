"""
Verificações estruturais do app.py.

Existem porque os testes usam `import app`, e nesse caminho o bloco
`if __name__ == "__main__"` não executa — então qualquer código escrito depois
dele funciona nos testes e some ao rodar `python app.py`. Foi exatamente o que
aconteceu: duas rotas ficaram abaixo do bloco, os testes passaram, e o sistema
quebrou com erro 500 no primeiro login real.
"""

import io
import os
import re
import unittest

import app as app_modulo

CAMINHO_APP = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.py"
)


class TestOrdemDoArquivo(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with io.open(CAMINHO_APP, encoding="utf-8") as f:
            cls.linhas = f.read().split("\n")

    def linha_do_main(self):
        for numero, linha in enumerate(self.linhas, start=1):
            if linha.startswith("if __name__"):
                return numero
        self.fail("app.py não tem o bloco if __name__ == '__main__'")

    def test_nada_relevante_vem_depois_do_bloco_main(self):
        inicio = self.linha_do_main()
        depois = self.linhas[inicio:]

        orfas = [
            f"linha {inicio + i + 1}: {texto.strip()}"
            for i, texto in enumerate(depois)
            if texto.startswith(("@app.", "def ", "class ", "@"))
        ]

        self.assertEqual(
            orfas, [],
            "há código depois do bloco __main__. Ele nunca executa com "
            "`python app.py`, então a rota ou função não é registrada:\n"
            + "\n".join(orfas),
        )


class TestRotasDosTemplates(unittest.TestCase):
    """
    Todo endpoint citado em url_for() nos templates precisa existir.

    É a checagem que pega a rota que não foi registrada antes de alguém abrir a
    tela e tomar um 500 — url_for só falha na hora de renderizar.
    """

    PADRAO = re.compile(r"url_for\(\s*['\"]([a-zA-Z_][a-zA-Z0-9_]*)['\"]")

    def test_todo_url_for_aponta_para_uma_rota_existente(self):
        pasta = os.path.join(os.path.dirname(CAMINHO_APP), "templates")
        registrados = set(app_modulo.app.view_functions)

        faltando = []
        for arquivo in sorted(os.listdir(pasta)):
            if not arquivo.endswith(".html"):
                continue
            with io.open(os.path.join(pasta, arquivo), encoding="utf-8") as f:
                conteudo = f.read()
            for endpoint in self.PADRAO.findall(conteudo):
                if endpoint not in registrados and endpoint != "static":
                    faltando.append(f"{arquivo}: url_for('{endpoint}')")

        self.assertEqual(faltando, [], "endpoints citados que não existem:\n" + "\n".join(faltando))


if __name__ == "__main__":
    unittest.main()
