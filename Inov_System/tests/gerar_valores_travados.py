"""
Regenera o bloco VALORES_TRAVADOS de tests/test_regressao_dados_reais.py.

Use quando uma importação nova mudar legitimamente os dados de 2026 — depois de
conferir os novos números contra a planilha da contabilidade:

    python -m tests.gerar_valores_travados

Copie a saída por cima dos blocos correspondentes no arquivo de teste.
"""

import sys
from contextlib import closing

from tests.apoio import banco_real_disponivel, BANCO_REAL

import db
from dre import calcular_dre_obra, calcular_dre_consolidado, CAMPOS_TOTAIS

MESES_2026 = [(2026, m) for m in range(1, 13)]
QUANTAS_OBRAS = 3


def main():
    if not banco_real_disponivel():
        print("database.db não encontrado ou sem dados de 2026.", file=sys.stderr)
        return 1

    db.DATABASE = BANCO_REAL

    with closing(db.conectar()) as conn:
        obras = [dict(r) for r in conn.execute("SELECT id, codigo FROM obras ORDER BY id")]

    # As obras de maior receita são as que mais exercitam o cálculo.
    com_movimento = []
    for obra in obras:
        acumulado = calcular_dre_obra(obra["id"], MESES_2026)["acumulado"]
        if acumulado["receita_total"] or acumulado["custos_total"]:
            com_movimento.append((obra["codigo"], acumulado))

    com_movimento.sort(key=lambda x: -x[1]["receita_total"])

    print("VALORES_TRAVADOS = {")
    for codigo, acumulado in com_movimento[:QUANTAS_OBRAS]:
        print(f'    "{codigo}": dict(')
        for campo in CAMPOS_TOTAIS:
            print(f"        {campo}={round(acumulado[campo], 6)!r},")
        print("    ),")
    print("}")

    consolidado = calcular_dre_consolidado([o["id"] for o in obras], MESES_2026)["acumulado"]

    print("\nCONSOLIDADO_TRAVADO_2026 = dict(")
    for campo in CAMPOS_TOTAIS:
        print(f"    {campo}={round(consolidado[campo], 6)!r},")
    print(")")

    return 0


if __name__ == "__main__":
    sys.exit(main())
