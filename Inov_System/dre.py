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

from db import conectar


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


def calcular_dre_obra(obra_id, meses):
    """
    Calcula o DRE de uma obra para uma lista de competências [(ano, mes), ...].

    Retorna um dicionário com:
      - categorias: lista de categorias com valor por competência
      - totais: dict por competência com receita_total, custos_total, lucro_bruto,
                impostos_servicos, irpj_csll, despesa_administrativa,
                despesa_financeira, lucro_liquido
      - acumulado: mesmos totais, somados em todas as competências pedidas
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
        lucro_bruto = receita_total - custos_total

        taxas = buscar_taxas_vigentes(cur, ano, mes)

        def aplicar(chave_taxa, base_receita, base_custo):
            taxa = taxas.get(chave_taxa)
            if not taxa:
                return 0.0
            base = base_receita if taxa["base_calculo"] == "receita" else base_custo
            return base * (taxa["percentual"] / 100.0)

        impostos_servicos = aplicar("impostos_servicos", receita_total, custos_total)
        irpj_csll = aplicar("irpj_csll", receita_total, custos_total)
        despesa_administrativa = aplicar("despesa_administrativa", receita_total, custos_total)
        despesa_financeira = aplicar("despesa_financeira", receita_total, custos_total)

        deducoes = impostos_servicos + irpj_csll + despesa_administrativa + despesa_financeira
        lucro_liquido = lucro_bruto - deducoes

        totais[chave] = {
            "receita_total": receita_total,
            "custos_total": custos_total,
            "lucro_bruto": lucro_bruto,
            "impostos_servicos": impostos_servicos,
            "irpj_csll": irpj_csll,
            "despesa_administrativa": despesa_administrativa,
            "despesa_financeira": despesa_financeira,
            "lucro_liquido": lucro_liquido,
        }

    acumulado = {
        "receita_total": sum(t["receita_total"] for t in totais.values()),
        "custos_total": sum(t["custos_total"] for t in totais.values()),
        "lucro_bruto": sum(t["lucro_bruto"] for t in totais.values()),
        "impostos_servicos": sum(t["impostos_servicos"] for t in totais.values()),
        "irpj_csll": sum(t["irpj_csll"] for t in totais.values()),
        "despesa_administrativa": sum(t["despesa_administrativa"] for t in totais.values()),
        "despesa_financeira": sum(t["despesa_financeira"] for t in totais.values()),
        "lucro_liquido": sum(t["lucro_liquido"] for t in totais.values()),
    }

    conn.close()

    return {
        "categorias": categorias,
        "totais": totais,
        "acumulado": acumulado,
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


def calcular_dre_consolidado(obra_ids, meses):
    """Soma o DRE de várias obras (usado na tela TOTAIS)."""
    consolidado_totais = {chave: {
        "receita_total": 0, "custos_total": 0, "lucro_bruto": 0,
        "impostos_servicos": 0, "irpj_csll": 0,
        "despesa_administrativa": 0, "despesa_financeira": 0,
        "lucro_liquido": 0,
    } for chave in meses}

    for obra_id in obra_ids:
        resultado = calcular_dre_obra(obra_id, meses)
        for chave, valores in resultado["totais"].items():
            for campo, valor in valores.items():
                consolidado_totais[chave][campo] += valor

    acumulado = {
        campo: sum(t[campo] for t in consolidado_totais.values())
        for campo in ["receita_total", "custos_total", "lucro_bruto", "impostos_servicos",
                      "irpj_csll", "despesa_administrativa", "despesa_financeira", "lucro_liquido"]
    }

    return {"totais": consolidado_totais, "acumulado": acumulado}
