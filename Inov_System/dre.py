"""
Motor de cálculo do DRE (Demonstração do Resultado).

Reproduz exatamente a lógica encontrada nas planilhas da contabilidade:

    Receita Bruta Total   = soma das categorias tipo 'receita'
    Custos Total           = soma das categorias tipo 'custo'
    Lucro Bruto             = Receita Bruta Total - Custos Total
    (-) Impostos s/Serviços = Receita Bruta Total * taxa 'impostos_servicos'
    (-) IRPJ e CSLL          = Receita Bruta Total * taxa 'irpj_csll'
    (-) Desp. Administrativa = Custos Total * taxa 'despesa_administrativa'
    (-) Desp. Financeira     = Custos Total * taxa 'despesa_financeira'
    Lucro/Prejuízo Líquido  = Lucro Bruto - as 4 deduções acima

As taxas são buscadas pela vigência (mês/ano do lançamento), então um
reajuste futuro não altera o resultado de meses já fechados.
"""

import re
import unicodedata

from db import conectar


MESES_POR_NOME = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# "Março a Dez/23", "Jan a Dez/2024", "Out a Dez/2022" -> pega o mês final e o ano
PADRAO_FIM_DE_PERIODO = re.compile(r"a\s+([A-Za-zÀ-ÿ]+)\s*/\s*(\d{2,4})\s*$", re.IGNORECASE)


def _sem_acento(texto):
    nfkd = unicodedata.normalize("NFKD", str(texto))
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def fim_do_periodo(descricao):
    """
    Converte a descrição de um período agregado na competência em que ele termina.

        'Março a Dez/23'   -> (2023, 12)
        'Jan a Dez/2024'   -> (2024, 12)
        'Jan a Fev/2022'   -> (2022, 2)

    O mês vem abreviado de formas variadas na planilha ('Dez', 'Agos', 'Julho'),
    então casa por prefixo. Devolve None quando não reconhece — nesse caso quem
    chama usa a taxa vigente mais recente.
    """
    achado = PADRAO_FIM_DE_PERIODO.search(str(descricao or ""))
    if not achado:
        return None

    token = _sem_acento(achado.group(1)).lower()
    candidatos = [(nome, num) for nome, num in MESES_POR_NOME.items() if nome.startswith(token)]
    if len(candidatos) != 1:
        return None

    ano = int(achado.group(2))
    if ano < 100:
        ano += 2000

    return ano, candidatos[0][1]


def _competencia_para_chave(ano, mes):
    return f"{ano:04d}-{mes:02d}"


def buscar_taxas_vigentes(cur, ano, mes):
    """Retorna {chave: {percentual, base_calculo}} válido para o mês/ano informado."""
    competencia = _competencia_para_chave(ano, mes)

    cur.execute("""
        SELECT chave, percentual, base_calculo, vigencia_inicio, vigencia_fim
        FROM taxas
        WHERE vigencia_inicio <= ?
          AND (vigencia_fim IS NULL OR vigencia_fim >= ?)
        ORDER BY vigencia_inicio DESC
    """, (competencia, competencia))

    taxas = {}
    for row in cur.fetchall():
        # Se houver mais de uma linha vigente para a mesma chave (não deveria
        # acontecer se as vigências forem bem cadastradas), fica a mais recente.
        if row["chave"] not in taxas:
            taxas[row["chave"]] = {
                "percentual": row["percentual"],
                "base_calculo": row["base_calculo"],
            }
    return taxas


def montar_bloco(cur, receita_total, custos_total, ano, mes):
    """
    Monta a coluna do DRE para um par (receita, custo), aplicando as taxas
    vigentes na competência informada. Serve tanto para um mês quanto para um
    período agregado — na planilha, as colunas antigas ('Março a Dez/23')
    recebem as mesmas deduções, com as mesmas alíquotas.
    """
    taxas = buscar_taxas_vigentes(cur, ano, mes)

    def aplicar(chave_taxa):
        taxa = taxas.get(chave_taxa)
        if not taxa:
            return 0.0
        base = receita_total if taxa["base_calculo"] == "receita" else custos_total
        return base * (taxa["percentual"] / 100.0)

    impostos_servicos = aplicar("impostos_servicos")
    irpj_csll = aplicar("irpj_csll")
    despesa_administrativa = aplicar("despesa_administrativa")
    despesa_financeira = aplicar("despesa_financeira")

    lucro_bruto = receita_total - custos_total
    deducoes = impostos_servicos + irpj_csll + despesa_administrativa + despesa_financeira

    return {
        "receita_total": receita_total,
        "custos_total": custos_total,
        "lucro_bruto": lucro_bruto,
        "impostos_servicos": impostos_servicos,
        "irpj_csll": irpj_csll,
        "despesa_administrativa": despesa_administrativa,
        "despesa_financeira": despesa_financeira,
        "lucro_liquido": lucro_bruto - deducoes,
    }


def somar_blocos(blocos):
    blocos = list(blocos)
    return {campo: sum(b[campo] for b in blocos) for campo in CAMPOS_TOTAIS}


def calcular_dre_obra(obra_id, meses, incluir_historico=False):
    """
    Calcula o DRE de uma obra para uma lista de competências [(ano, mes), ...].

    Retorna um dicionário com:
      - categorias: lista de categorias com valor por competência
      - totais: dict por competência com receita_total, custos_total, lucro_bruto,
                impostos_servicos, irpj_csll, despesa_administrativa,
                despesa_financeira, lucro_liquido
      - acumulado: mesmos totais, somados em todas as competências pedidas

    Com incluir_historico=True, traz também os períodos agregados da planilha
    (anos antigos sem detalhe mensal) como colunas próprias:
      - periodos_historicos: descrições em ordem cronológica
      - totais_historicos: mesmos campos, por período
      - total_geral: períodos agregados + ano selecionado
      - cada categoria ganha 'historicos' e 'total_historico'
    """
    conn = conectar()
    cur = conn.cursor()

    meses_pedidos = set(meses)

    cur.execute("""
        SELECT id, codigo, nome, tipo, ordem
        FROM categorias_conta
        WHERE ativo = 1
        ORDER BY tipo DESC, ordem
    """)
    categorias = [dict(r) for r in cur.fetchall()]
    categoria_por_id = {c["id"]: c for c in categorias}

    for c in categorias:
        c["valores"] = {}

    cur.execute("""
        SELECT categoria_id, mes, ano, valor
        FROM lancamentos
        WHERE obra_id = ?
    """, (obra_id,))

    lancamentos_por_competencia = {}
    for row in cur.fetchall():
        chave = (row["ano"], row["mes"])
        if chave not in meses_pedidos:
            continue
        lancamentos_por_competencia.setdefault(chave, {})[row["categoria_id"]] = row["valor"]
        if row["categoria_id"] in categoria_por_id:
            categoria_por_id[row["categoria_id"]]["valores"][chave] = row["valor"]

    # Total da conta no período pedido — usado no acumulado da tabela e para
    # saber se a conta ficou sem movimento (a tela permite escondê-las).
    for c in categorias:
        c["total"] = sum(c["valores"].values())

    totais = {}
    for ano, mes in meses:
        chave = (ano, mes)
        valores_mes = lancamentos_por_competencia.get(chave, {})

        receita_total = sum(
            valores_mes.get(c["id"], 0) for c in categorias if c["tipo"] == "receita"
        )
        custos_total = sum(
            valores_mes.get(c["id"], 0) for c in categorias if c["tipo"] == "custo"
        )
        totais[chave] = montar_bloco(cur, receita_total, custos_total, ano, mes)

    acumulado = somar_blocos(totais.values())

    # ---- Períodos agregados (anos antigos que a planilha traz em bloco) ----
    periodos_historicos = []
    totais_historicos = {}

    if incluir_historico:
        for c in categorias:
            c["historicos"] = {}

        cur.execute("""
            SELECT categoria_id, periodo_descricao, valor
            FROM saldos_anteriores
            WHERE obra_id = ?
        """, (obra_id,))

        valores_por_periodo = {}
        for row in cur.fetchall():
            periodo = row["periodo_descricao"]
            valores_por_periodo.setdefault(periodo, {})[row["categoria_id"]] = row["valor"]
            if row["categoria_id"] in categoria_por_id:
                categoria_por_id[row["categoria_id"]]["historicos"][periodo] = row["valor"]

        # Competência de referência quando a descrição não é legível: o fim do
        # período pedido, para as taxas ficarem coerentes com o resto da tela.
        referencia = max(meses) if meses else (2000, 12)

        periodos_historicos = sorted(
            valores_por_periodo, key=lambda p: fim_do_periodo(p) or referencia
        )

        for periodo in periodos_historicos:
            valores = valores_por_periodo[periodo]
            receita_total = sum(valores.get(c["id"], 0) for c in categorias if c["tipo"] == "receita")
            custos_total = sum(valores.get(c["id"], 0) for c in categorias if c["tipo"] == "custo")

            ano_ref, mes_ref = fim_do_periodo(periodo) or referencia
            totais_historicos[periodo] = montar_bloco(cur, receita_total, custos_total, ano_ref, mes_ref)

        for c in categorias:
            c["total_historico"] = sum(c["historicos"].values())

    # Total desde o início da obra: os períodos agregados mais o ano detalhado.
    # É o que a coluna "Acumulado" da planilha mostra — o 'acumulado' acima é
    # só do ano selecionado.
    total_geral = somar_blocos(list(totais.values()) + list(totais_historicos.values()))

    conn.close()

    return {
        "categorias": categorias,
        "totais": totais,
        "acumulado": acumulado,
        "periodos_historicos": periodos_historicos,
        "totais_historicos": totais_historicos,
        "total_geral": total_geral,
    }


def buscar_saldos_anteriores(obra_id):
    """
    Retorna os valores de períodos históricos agregados (sem detalhamento mensal,
    ex: 'Out a Dez/2025') que vieram da planilha original, agrupados por período.
    """
    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        SELECT s.periodo_descricao, c.tipo, SUM(s.valor) AS total
        FROM saldos_anteriores s
        JOIN categorias_conta c ON c.id = s.categoria_id
        WHERE s.obra_id = ?
        GROUP BY s.periodo_descricao, c.tipo
    """, (obra_id,))

    periodos = {}
    for row in cur.fetchall():
        p = periodos.setdefault(row["periodo_descricao"], {"receita_total": 0.0, "custos_total": 0.0})
        if row["tipo"] == "receita":
            p["receita_total"] = row["total"]
        else:
            p["custos_total"] = row["total"]

    conn.close()

    resultado = []
    for periodo, valores in periodos.items():
        resultado.append({
            "periodo": periodo,
            "receita_total": valores["receita_total"],
            "custos_total": valores["custos_total"],
            "resultado": valores["receita_total"] - valores["custos_total"],
        })
    return resultado


CAMPOS_TOTAIS = [
    "receita_total", "custos_total", "lucro_bruto", "impostos_servicos",
    "irpj_csll", "despesa_administrativa", "despesa_financeira", "lucro_liquido",
]


def calcular_dre_consolidado(obra_ids, meses):
    """
    Soma o DRE de várias obras (usado na tela TOTAIS e no dashboard).

    Além do consolidado, devolve em 'por_obra' o acumulado de cada obra
    separadamente — já foi calculado de qualquer forma, e é o que alimenta o
    ranking do dashboard sem precisar de uma segunda passada no banco.
    """
    consolidado_totais = {chave: {campo: 0 for campo in CAMPOS_TOTAIS} for chave in meses}
    por_obra = {}

    for obra_id in obra_ids:
        resultado = calcular_dre_obra(obra_id, meses)
        por_obra[obra_id] = resultado["acumulado"]

        for chave, valores in resultado["totais"].items():
            for campo, valor in valores.items():
                consolidado_totais[chave][campo] += valor

    acumulado = {
        campo: sum(t[campo] for t in consolidado_totais.values())
        for campo in CAMPOS_TOTAIS
    }

    return {"totais": consolidado_totais, "acumulado": acumulado, "por_obra": por_obra}
