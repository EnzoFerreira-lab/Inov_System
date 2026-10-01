"""
Conferência dos dados: procura buraco antes que alguém mande o DRE errado.

O caso que deu origem a isto: a planilha importada no início do projeto se
chamava "06-2026" — foi gerada durante junho, com o mês ainda em fechamento.
A coluna de junho veio pela metade, e quatro obras que faturaram em maio e em
julho ficaram zeradas em junho. R$ 1 milhão de receita sumiu do DRE e ninguém
percebeu por meses, porque o sistema tinha o dado para notar mas não olhava.

O sinal procurado é o **mês sanduíche**: a obra teve movimento antes e depois,
mas naquele mês ficou zerada. É forte porque não depende de média nem de
palpite — uma obra que faturou em maio e em julho não some em junho por acaso.

Meses em que a obra ainda não tinha começado, ou já tinha encerrado, não contam:
só o que está entre o primeiro e o último movimento dela no ano.
"""

import datetime

MESES_ABREV = [
    "", "Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
    "Jul", "Ago", "Set", "Out", "Nov", "Dez",
]


def _hoje():
    """
    Isolado numa função para o teste poder fixar a data.

    Sem isso, um teste que monta "agosto e setembro estão vencidos" passa hoje
    e quebra sozinho no mês que vem — teste que apodrece é pior que teste
    nenhum, porque alguém acaba desligando a suíte inteira por causa dele.
    """
    return datetime.date.today()


def detectar_meses_ausentes(cur, ano, hoje=None):
    """
    Meses que já aconteceram e não têm nenhum lançamento.

    Complementa detectar_lacunas, que só enxerga buraco **no meio** — a obra
    tem movimento antes e depois. Um mês no fim da fila, que simplesmente nunca
    foi importado, não tem "depois" para formar o sanduíche e passava batido.
    Foi o caso de agosto e setembro de 2026: o sistema parou em julho e nada
    avisava que dois meses já tinham vencido.

    Só vale para o ano corrente, do primeiro mês com dado até o mês passado.
    Em ano anterior não dá para distinguir "não importaram" de "a obra ainda
    não existia", e o alerta viraria ruído.
    """
    hoje = hoje or _hoje()
    if ano != hoje.year:
        return []

    cur.execute(
        "SELECT DISTINCT mes FROM lancamentos WHERE ano = ? AND valor <> 0 ORDER BY mes",
        (ano,),
    )
    com_dado = [r["mes"] for r in cur.fetchall()]
    if not com_dado:
        return []

    ausentes = [
        mes for mes in range(com_dado[0], hoje.month)
        if mes not in com_dado
    ]

    return [{"mes": m, "mes_nome": MESES_ABREV[m]} for m in ausentes]


def _movimento_por_obra(cur, ano, obra_id=None):
    """{obra_id: {mes: {'receita': x, 'custo': y}}} apenas com valor <> 0."""
    sql = """
        SELECT l.obra_id, l.mes, c.tipo, SUM(l.valor) AS total
        FROM lancamentos l
        JOIN categorias_conta c ON c.id = l.categoria_id
        WHERE l.ano = ? AND l.valor <> 0 AND c.ativo = 1
    """
    parametros = [ano]
    if obra_id:
        sql += " AND l.obra_id = ?"
        parametros.append(obra_id)
    sql += " GROUP BY l.obra_id, l.mes, c.tipo"

    movimento = {}
    for linha in cur.execute(sql, parametros):
        mes = movimento.setdefault(linha["obra_id"], {}).setdefault(
            linha["mes"], {"receita": 0.0, "custo": 0.0}
        )
        mes[linha["tipo"]] = linha["total"]
    return movimento


def detectar_lacunas(cur, ano, obra_id=None):
    """
    Devolve as lacunas encontradas, uma por mês:

        [{
          "mes": 6,
          "mes_nome": "Jun",
          "obras": [{"obra_id":…, "codigo":…, "nome":…,
                     "mes_anterior":5, "receita_anterior":…, "custo_anterior":…,
                     "mes_seguinte":7, "receita_seguinte":…}],
          "receita_de_referencia": 1015002.47,
        }]

    'receita_de_referencia' é a soma do que essas obras faturaram no mês
    anterior — um número real, não uma estimativa do que faltou.
    """
    movimento = _movimento_por_obra(cur, ano, obra_id)
    if not movimento:
        return []

    cur.execute("SELECT id, codigo, nome FROM obras")
    obras = {r["id"]: dict(r) for r in cur.fetchall()}

    por_mes = {}

    for oid, meses in movimento.items():
        ativos = sorted(meses)
        if len(ativos) < 2:
            continue

        primeiro, ultimo = ativos[0], ativos[-1]

        for mes in range(primeiro + 1, ultimo):
            if mes in meses:
                continue

            anterior = max(m for m in ativos if m < mes)
            seguinte = min(m for m in ativos if m > mes)
            obra = obras.get(oid, {"codigo": "?", "nome": "?"})

            por_mes.setdefault(mes, []).append({
                "obra_id": oid,
                "codigo": obra["codigo"],
                "nome": obra["nome"],
                "mes_anterior": anterior,
                "receita_anterior": meses[anterior]["receita"],
                "custo_anterior": meses[anterior]["custo"],
                "mes_seguinte": seguinte,
                "receita_seguinte": meses[seguinte]["receita"],
            })

    lacunas = []
    for mes, lista in sorted(por_mes.items()):
        lista.sort(key=lambda o: -o["receita_anterior"])
        lacunas.append({
            "mes": mes,
            "mes_nome": MESES_ABREV[mes],
            "obras": lista,
            "receita_de_referencia": sum(o["receita_anterior"] for o in lista),
        })

    # O mês com mais dinheiro envolvido aparece primeiro.
    return sorted(lacunas, key=lambda l: -l["receita_de_referencia"])


def resumir_lacunas(lacunas, ausentes=None):
    """Uma frase para o alerta da tela, ou None se não há nada a dizer."""
    ausentes = ausentes or []

    if ausentes and not lacunas:
        meses = ", ".join(m["mes_nome"] for m in ausentes)
        return f"{len(ausentes)} mês(es) já venceram e não foram importados: {meses}."

    if not lacunas:
        return None

    total_obras = sum(len(l["obras"]) for l in lacunas)
    meses = ", ".join(l["mes_nome"] for l in lacunas)

    if len(lacunas) == 1:
        return (
            f"{total_obras} obra(s) ficaram sem lançamento em {meses}, "
            f"mas têm movimento antes e depois."
        )
    return (
        f"{total_obras} lacuna(s) em {len(lacunas)} meses ({meses}): "
        f"obras com movimento antes e depois, mas zeradas no mês."
    )
