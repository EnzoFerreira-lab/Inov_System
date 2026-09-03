"""
Camada de banco de dados do sistema INOV.

Modelo de dados (v2) — desenhado a partir do DRE real usado pela contabilidade:

    empresas          -> clientes da contabilidade (ex: BELA NOVA CONSTRUTORA LTDA)
    obras             -> centro de custo (ex: OBRA 251 - ESTHER TOWERS), pertence a uma empresa
    categorias_conta  -> plano de contas fixo (Receita/Custo), com código, igual à planilha
    lancamentos       -> 1 valor por (obra, categoria, mês, ano) — igual a uma célula da planilha
    taxas             -> percentuais configuráveis (Impostos, IRPJ/CSLL, Adm, Financeiras),
                         com vigência para permitir reajuste sem perder o histórico
    usuarios          -> login do sistema
"""

import sqlite3
from datetime import datetime

DATABASE = "database.db"


def conectar():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def criar_tabelas():
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha_hash TEXT NOT NULL,
            papel TEXT NOT NULL DEFAULT 'comum' CHECK (papel IN ('admin', 'comum')),
            ativo INTEGER NOT NULL DEFAULT 1,
            criado_em TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cnpj TEXT UNIQUE
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS obras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            codigo TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'em_andamento',
            data_inicio TEXT,
            aplica_taxas INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (empresa_id) REFERENCES empresas(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS categorias_conta (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT,
            nome TEXT NOT NULL UNIQUE,
            tipo TEXT NOT NULL CHECK (tipo IN ('receita', 'custo')),
            ordem INTEGER NOT NULL DEFAULT 0,
            ativo INTEGER NOT NULL DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obra_id INTEGER NOT NULL,
            categoria_id INTEGER NOT NULL,
            mes INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
            ano INTEGER NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            origem TEXT NOT NULL DEFAULT 'manual',
            atualizado_em TEXT,
            FOREIGN KEY (obra_id) REFERENCES obras(id),
            FOREIGN KEY (categoria_id) REFERENCES categorias_conta(id),
            UNIQUE (obra_id, categoria_id, mes, ano)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS saldos_anteriores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obra_id INTEGER NOT NULL,
            categoria_id INTEGER NOT NULL,
            periodo_descricao TEXT NOT NULL,
            valor REAL NOT NULL DEFAULT 0,
            origem TEXT NOT NULL DEFAULT 'importacao',
            atualizado_em TEXT,
            FOREIGN KEY (obra_id) REFERENCES obras(id),
            FOREIGN KEY (categoria_id) REFERENCES categorias_conta(id),
            UNIQUE (obra_id, categoria_id, periodo_descricao)
        )
    """)

    # Lançamento contábil individual vindo do relatório analítico do Contimatic.
    # A tabela 'lancamentos' guarda o total de cada célula do DRE; aqui fica o
    # detalhe que formou esse total, para dar pra clicar num valor e ver de onde
    # ele veio — que é justamente o que um relatório analítico serve pra responder.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS partidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            obra_id INTEGER NOT NULL,
            categoria_id INTEGER NOT NULL,
            mes INTEGER NOT NULL CHECK (mes BETWEEN 1 AND 12),
            ano INTEGER NOT NULL,
            data TEXT,
            documento TEXT,
            historico TEXT,
            conta_codigo TEXT,
            conta_nome TEXT,
            valor REAL NOT NULL DEFAULT 0,
            importacao_id INTEGER,
            FOREIGN KEY (obra_id) REFERENCES obras(id),
            FOREIGN KEY (categoria_id) REFERENCES categorias_conta(id),
            FOREIGN KEY (importacao_id) REFERENCES importacoes(id)
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_partidas_celula
        ON partidas (obra_id, categoria_id, ano, mes)
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_partidas_importacao
        ON partidas (importacao_id)
    """)

    # De-para entre a conta contábil do Contimatic e a categoria do plano de
    # contas. A primeira tentativa é casar pelo código que já está em
    # categorias_conta; esta tabela cobre os casos em que os códigos divergem,
    # resolvidos uma vez na tela de revisão e lembrados daí em diante.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS contas_map (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conta_codigo TEXT NOT NULL UNIQUE,
            conta_nome TEXT,
            categoria_id INTEGER,
            ignorar INTEGER NOT NULL DEFAULT 0,
            criado_em TEXT,
            FOREIGN KEY (categoria_id) REFERENCES categorias_conta(id)
        )
    """)

    # Cada importação vira um registro, e cada valor que ela alterou guarda o
    # estado anterior. É o que permite desfazer um arquivo enviado por engano
    # sem restaurar o banco inteiro.
    cur.execute("""
        CREATE TABLE IF NOT EXISTS importacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            arquivo TEXT NOT NULL,
            empresa_id INTEGER,
            usuario_id INTEGER,
            criado_em TEXT NOT NULL,
            lancamentos_gravados INTEGER NOT NULL DEFAULT 0,
            saldos_gravados INTEGER NOT NULL DEFAULT 0,
            manuais_preservados INTEGER NOT NULL DEFAULT 0,
            manuais_sobrescritos INTEGER NOT NULL DEFAULT 0,
            desfeita_em TEXT,
            FOREIGN KEY (empresa_id) REFERENCES empresas(id),
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS importacao_itens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            importacao_id INTEGER NOT NULL,
            tabela TEXT NOT NULL CHECK (tabela IN ('lancamentos', 'saldos_anteriores')),
            obra_id INTEGER NOT NULL,
            categoria_id INTEGER NOT NULL,
            mes INTEGER,
            ano INTEGER,
            periodo_descricao TEXT,
            existia INTEGER NOT NULL,
            valor_anterior REAL,
            origem_anterior TEXT,
            FOREIGN KEY (importacao_id) REFERENCES importacoes(id)
        )
    """)

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_importacao_itens_importacao
        ON importacao_itens (importacao_id)
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS taxas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chave TEXT NOT NULL CHECK (chave IN (
                'impostos_servicos', 'irpj_csll', 'despesa_administrativa', 'despesa_financeira'
            )),
            descricao TEXT NOT NULL,
            percentual REAL NOT NULL,
            base_calculo TEXT NOT NULL CHECK (base_calculo IN ('receita', 'custo')),
            vigencia_inicio TEXT NOT NULL,
            vigencia_fim TEXT
        )
    """)

    conn.commit()

    _migrar_usuarios(cur)
    _migrar_obras(cur)
    _migrar_categorias(cur)
    conn.commit()

    _seed_usuario_admin(cur)
    _seed_plano_de_contas(cur)
    _seed_taxas(cur)

    conn.commit()
    conn.close()


def _migrar_usuarios(cur):
    """
    Acrescenta papel/ativo/criado_em na tabela de usuários que já existe.

    CREATE TABLE IF NOT EXISTS não altera uma tabela criada antes, então os
    bancos em uso precisam do ALTER explícito — sem isso o sistema subiria
    consultando uma coluna inexistente.
    """
    colunas = {r["name"] for r in cur.execute("PRAGMA table_info(usuarios)")}

    if "papel" not in colunas:
        cur.execute("ALTER TABLE usuarios ADD COLUMN papel TEXT NOT NULL DEFAULT 'comum'")
    if "ativo" not in colunas:
        cur.execute("ALTER TABLE usuarios ADD COLUMN ativo INTEGER NOT NULL DEFAULT 1")
    if "criado_em" not in colunas:
        cur.execute("ALTER TABLE usuarios ADD COLUMN criado_em TEXT")

    # Trava de segurança: um banco sem nenhum admin deixaria todo mundo sem
    # acesso às ações da dona da empresa, inclusive a de promover alguém.
    cur.execute("SELECT COUNT(*) AS n FROM usuarios WHERE papel = 'admin' AND ativo = 1")
    if cur.fetchone()["n"] == 0:
        cur.execute("SELECT id FROM usuarios ORDER BY id LIMIT 1")
        primeiro = cur.fetchone()
        if primeiro:
            cur.execute("UPDATE usuarios SET papel = 'admin' WHERE id = ?", (primeiro["id"],))


def _migrar_obras(cur):
    """
    Acrescenta 'aplica_taxas' às obras já cadastradas.

    As 4 taxas do DRE (impostos, IRPJ/CSLL, administrativa e financeira) foram
    pensadas para uma obra que fatura. O Departamento Técnico é despesa
    administrativa da própria empresa — cobrar dele uma taxa administrativa
    calculada sobre o próprio custo administrativo não faz sentido contábil.
    """
    colunas = {r["name"] for r in cur.execute("PRAGMA table_info(obras)")}

    if "aplica_taxas" not in colunas:
        cur.execute("ALTER TABLE obras ADD COLUMN aplica_taxas INTEGER NOT NULL DEFAULT 1")
        cur.execute("""
            UPDATE obras SET aplica_taxas = 0
            WHERE codigo = 'DEPTO-TEC'
               OR UPPER(nome) LIKE '%DEPARTAMENTO T%'
               OR UPPER(nome) LIKE '%DEPTO T%'
        """)


def _migrar_categorias(cur):
    """
    Marca quais categorias nasceram de uma importação, para a tela de revisão
    saber o que destacar.

    Como a coluna não existia, a origem das que já estão no banco é deduzida:
    o que não está no plano de contas padrão veio da planilha.
    """
    colunas = {r["name"] for r in cur.execute("PRAGMA table_info(categorias_conta)")}
    if "origem" in colunas:
        return

    cur.execute("ALTER TABLE categorias_conta ADD COLUMN origem TEXT NOT NULL DEFAULT 'manual'")

    nomes_padrao = {_chave_de_nome(nome) for _, nome, _ in PLANO_DE_CONTAS_PADRAO}
    for linha in cur.execute("SELECT id, nome FROM categorias_conta").fetchall():
        if _chave_de_nome(linha["nome"]) not in nomes_padrao:
            cur.execute(
                "UPDATE categorias_conta SET origem = 'importacao' WHERE id = ?", (linha["id"],)
            )


def _chave_de_nome(nome):
    """Normaliza para comparar nome de conta ignorando acento, caixa e espaço."""
    import re
    import unicodedata

    nfkd = unicodedata.normalize("NFKD", str(nome))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sem_acento).strip().lower()


def _seed_usuario_admin(cur):
    from datetime import datetime as _dt
    from werkzeug.security import generate_password_hash

    cur.execute("SELECT id FROM usuarios WHERE email = ?", ("admin@inov.com",))
    if not cur.fetchone():
        cur.execute(
            """
            INSERT INTO usuarios (nome, email, senha_hash, papel, ativo, criado_em)
            VALUES (?, ?, ?, 'admin', 1, ?)
            """,
            ("Administrador", "admin@inov.com", generate_password_hash("1234"),
             _dt.now().isoformat()),
        )


# Plano de contas extraído das abas de OBRA do arquivo real do cliente
# (06-2026__DRE_-_CENTRO_DE_CUSTO.xlsx). Mantém os mesmos nomes e códigos
# usados pela contabilidade, na mesma ordem em que aparecem na planilha.
PLANO_DE_CONTAS_PADRAO = [
    # (codigo, nome, tipo)
    ("2", "Serviços prestados", "receita"),
    ("450", "Locação de Equipamentos", "receita"),

    ("320", "Alimentação", "custo"),
    ("322", "Combustíveis", "custo"),
    (None, "Despesa com Radio e Telefonia Celular", "custo"),
    ("360", "Equipamento de Segurança - EPIs", "custo"),
    ("315", "Ferias", "custo"),
    ("317", "FGTS", "custo"),
    ("499", "Horas Extras", "custo"),
    ("318", "Indenizações e Aviso Prévio", "custo"),
    ("369", "Indenizações Trabalhistas Judiciais", "custo"),
    ("316", "INSS", "custo"),
    ("328", "Locação de Andaimes", "custo"),
    (None, "Locação de Máqs, Ferramentas e Equipamentos", "custo"),
    ("394", "Manutenção de Equipamento", "custo"),
    ("510", "Manutenção de Veículos", "custo"),
    (None, "Medicina Ocupacional e Assist. Médica", "custo"),
    ("364", "Móveis Não Imobilizado", "custo"),
    ("361", "Peças, Ferramentas e Acessórios", "custo"),
    ("313", "Premios e Gratificacoes", "custo"),
    ("311", "Salarios e Ordenados", "custo"),
    ("324", "Serviços de Terceiros", "custo"),
    (None, "Seguro Riscos Execução de Serv. Trab.", "custo"),
    ("425", "Uniformes", "custo"),
    ("321", "Vale Transporte e Condução", "custo"),
    ("314", "Provisão 13º Salario", "custo"),
    ("849", "Cursos e treinamentos", "custo"),
    (None, "Confraternização de Funcionários", "custo"),
]


def _seed_plano_de_contas(cur):
    cur.execute("SELECT COUNT(*) AS n FROM categorias_conta")
    if cur.fetchone()["n"] > 0:
        return

    for ordem, (codigo, nome, tipo) in enumerate(PLANO_DE_CONTAS_PADRAO):
        cur.execute(
            """
            INSERT INTO categorias_conta (codigo, nome, tipo, ordem, ativo)
            VALUES (?, ?, ?, ?, 1)
            """,
            (codigo, nome, tipo, ordem),
        )


# Taxas conforme a planilha atual do cliente. Todas com vigência iniciando
# em 2020-01 (histórico) e sem data de fim (vigência atual em aberto).
TAXAS_PADRAO = [
    ("impostos_servicos", "Impostos sobre Serviços", 13.15, "receita"),
    ("irpj_csll", "IRPJ e CSLL", 1.22, "receita"),
    ("despesa_administrativa", "Despesas Administrativas/Técnico (Taxa Adm. Prevista)", 5.56, "custo"),
    ("despesa_financeira", "Despesas Financeiras", 0.01, "custo"),
]


def _seed_taxas(cur):
    cur.execute("SELECT COUNT(*) AS n FROM taxas")
    if cur.fetchone()["n"] > 0:
        return

    for chave, descricao, percentual, base in TAXAS_PADRAO:
        cur.execute(
            """
            INSERT INTO taxas (chave, descricao, percentual, base_calculo, vigencia_inicio, vigencia_fim)
            VALUES (?, ?, ?, ?, '2020-01', NULL)
            """,
            (chave, descricao, percentual, base),
        )
