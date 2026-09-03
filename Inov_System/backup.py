"""
Backup do banco.

O database.db guarda a contabilidade real e não é versionado — sem cópia, um
arquivo corrompido ou apagado leva embora todo o histórico. Aqui a cópia é feita
com a API de backup do SQLite, que funciona com o sistema no ar: ela lida com a
transação em andamento, coisa que copiar o arquivo por fora não faz.

Uso:
    python -m backup                 # gera uma cópia agora
    python -m backup --listar        # mostra o que existe
"""

import os
import sqlite3
import datetime
from contextlib import closing

import db

PASTA_BACKUPS = "backups"
MANTER = 20  # cópias mais recentes que ficam guardadas


def caminho_da_pasta(pasta=PASTA_BACKUPS):
    os.makedirs(pasta, exist_ok=True)
    return pasta


def gerar_backup(pasta=PASTA_BACKUPS, motivo="manual"):
    """
    Copia o banco para backups/inov_<data>_<motivo>.db e devolve o caminho.

    Usa sqlite3.Connection.backup: a cópia sai consistente mesmo se alguém
    estiver gravando no meio, ao contrário de um shutil.copy do arquivo.
    """
    pasta = caminho_da_pasta(pasta)

    carimbo = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    destino = os.path.join(pasta, f"inov_{carimbo}_{motivo}.db")

    with closing(db.conectar()) as origem, closing(sqlite3.connect(destino)) as copia:
        origem.backup(copia)

    limpar_antigos(pasta)
    return destino


def listar_backups(pasta=PASTA_BACKUPS):
    """Backups existentes, do mais novo para o mais antigo."""
    if not os.path.isdir(pasta):
        return []

    arquivos = []
    for nome in os.listdir(pasta):
        if not nome.endswith(".db"):
            continue
        caminho = os.path.join(pasta, nome)
        info = os.stat(caminho)
        arquivos.append({
            "nome": nome,
            "caminho": caminho,
            "bytes": info.st_size,
            "criado_em": datetime.datetime.fromtimestamp(info.st_mtime),
        })

    return sorted(arquivos, key=lambda a: a["criado_em"], reverse=True)


def limpar_antigos(pasta=PASTA_BACKUPS, manter=MANTER):
    """Mantém só as cópias mais recentes, para a pasta não crescer sem limite."""
    removidos = 0
    for antigo in listar_backups(pasta)[manter:]:
        try:
            os.remove(antigo["caminho"])
            removidos += 1
        except OSError:
            pass
    return removidos


def backup_do_dia_ja_existe(pasta=PASTA_BACKUPS):
    hoje = datetime.date.today()
    return any(b["criado_em"].date() == hoje for b in listar_backups(pasta))


def backup_diario(pasta=PASTA_BACKUPS):
    """
    Gera no máximo uma cópia automática por dia. Chamado na inicialização do
    sistema: sem agendador externo, subir o servidor é o gatilho mais confiável
    que existe aqui.
    """
    if backup_do_dia_ja_existe(pasta):
        return None
    return gerar_backup(pasta, motivo="diario")


def _formatar_tamanho(n):
    for unidade in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unidade}"
        n /= 1024
    return f"{n:.1f} TB"


if __name__ == "__main__":
    import sys

    if "--listar" in sys.argv:
        copias = listar_backups()
        if not copias:
            print("Nenhum backup ainda. Rode: python -m backup")
        for b in copias:
            print(f"  {b['criado_em']:%d/%m/%Y %H:%M}  {_formatar_tamanho(b['bytes']):>9}  {b['nome']}")
    else:
        destino = gerar_backup()
        print(f"Backup gerado: {destino} ({_formatar_tamanho(os.path.getsize(destino))})")
