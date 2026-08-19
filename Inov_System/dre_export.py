"""
Geração do DRE em Excel para download — mesma estrutura da tela, formatada
pra impressão/envio por e-mail.
"""

import io
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

FONTE_PADRAO = "Arial"

FORMATO_MOEDA = '#,##0.00;(#,##0.00);"-"'

COR_CABECALHO = "1D4ED8"
COR_DESTAQUE = "EEF1F8"
COR_NEGATIVO = "B42318"


def _estilo_titulo(cell, tamanho=14, cor="FFFFFF", negrito=True, fundo=None):
    cell.font = Font(name=FONTE_PADRAO, size=tamanho, bold=negrito, color=cor)
    if fundo:
        cell.fill = PatternFill("solid", fgColor=fundo)


def _linha_valores(ws, linha, rotulo, valores, negrito=False, moeda=True, fundo=None, cor_texto=None):
    cell = ws.cell(row=linha, column=1, value=rotulo)
    cell.font = Font(name=FONTE_PADRAO, bold=negrito, color=cor_texto or "000000")
    if fundo:
        cell.fill = PatternFill("solid", fgColor=fundo)

    for i, v in enumerate(valores, start=2):
        c = ws.cell(row=linha, column=i, value=round(v, 2) if v is not None else None)
        c.font = Font(name=FONTE_PADRAO, bold=negrito, color=cor_texto or "000000")
        if moeda:
            c.number_format = FORMATO_MOEDA
        c.alignment = Alignment(horizontal="right")
        if fundo:
            c.fill = PatternFill("solid", fgColor=fundo)


def gerar_excel_dre_obra(obra, ano, meses, meses_nome, categorias, totais, acumulado, saldos_anteriores=None):
    wb = Workbook()
    ws = wb.active
    ws.title = f"DRE {obra['codigo']}"[:31]

    ws.merge_cells("A1:N1")
    ws["A1"] = obra["nome"]
    _estilo_titulo(ws["A1"], tamanho=14, fundo=COR_CABECALHO)
    ws.row_dimensions[1].height = 24

    ws.merge_cells("A2:N2")
    ws["A2"] = f"{obra['empresa_nome']} · Código {obra['codigo']} · DRE {ano}"
    ws["A2"].font = Font(name=FONTE_PADRAO, size=10, italic=True)

    linha = 4
    cabecalho = ["Categoria"] + [f"{meses_nome[m][:3]}/{a}" for a, m in meses] + ["Acumulado"]
    for i, texto in enumerate(cabecalho, start=1):
        c = ws.cell(row=linha, column=i, value=texto)
        c.font = Font(name=FONTE_PADRAO, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=COR_CABECALHO)
        c.alignment = Alignment(horizontal="center" if i > 1 else "left")
    linha += 1

    def valores_categoria(cat):
        vals = [cat["valores"].get((a, m), 0) for a, m in meses]
        return vals + [sum(vals)]

    ws.cell(row=linha, column=1, value="Receitas Brutas").font = Font(name=FONTE_PADRAO, bold=True)
    linha += 1
    for cat in categorias:
        if cat["tipo"] != "receita":
            continue
        nome = cat["nome"] + (f" - {cat['codigo']}" if cat["codigo"] else "")
        _linha_valores(ws, linha, nome, valores_categoria(cat))
        linha += 1

    vals_receita = [totais[(a, m)]["receita_total"] for a, m in meses] + [acumulado["receita_total"]]
    _linha_valores(ws, linha, "= Receitas Brutas Total", vals_receita, negrito=True, fundo=COR_DESTAQUE)
    linha += 1

    ws.cell(row=linha, column=1, value="Custos").font = Font(name=FONTE_PADRAO, bold=True)
    linha += 1
    for cat in categorias:
        if cat["tipo"] != "custo":
            continue
        nome = cat["nome"] + (f" - {cat['codigo']}" if cat["codigo"] else "")
        vals = [-v for v in valores_categoria(cat)]
        _linha_valores(ws, linha, nome, vals, cor_texto=COR_NEGATIVO)
        linha += 1

    vals_custo = [-totais[(a, m)]["custos_total"] for a, m in meses] + [-acumulado["custos_total"]]
    _linha_valores(ws, linha, "= Custos Total", vals_custo, negrito=True, fundo=COR_DESTAQUE, cor_texto=COR_NEGATIVO)
    linha += 1

    vals_bruto = [totais[(a, m)]["lucro_bruto"] for a, m in meses] + [acumulado["lucro_bruto"]]
    _linha_valores(ws, linha, "= Lucro / Prejuízo Bruto", vals_bruto, negrito=True, fundo=COR_DESTAQUE)
    linha += 1

    for chave, rotulo in [
        ("impostos_servicos", "(-) Impostos s/ Serviços"),
        ("irpj_csll", "(-) IRPJ e CSLL"),
        ("despesa_administrativa", "(-) Desp. Administrativas/Técnico"),
        ("despesa_financeira", "(-) Despesas Financeiras"),
    ]:
        vals = [-totais[(a, m)][chave] for a, m in meses] + [-acumulado[chave]]
        _linha_valores(ws, linha, rotulo, vals, cor_texto=COR_NEGATIVO)
        linha += 1

    vals_liquido = [totais[(a, m)]["lucro_liquido"] for a, m in meses] + [acumulado["lucro_liquido"]]
    _linha_valores(ws, linha, "LUCRO/PREJUÍZO LÍQUIDO DA OBRA", vals_liquido, negrito=True, fundo="FFE8A3")
    linha += 1

    if saldos_anteriores:
        linha += 2
        ws.cell(row=linha, column=1, value="Períodos históricos (sem detalhamento mensal)").font = Font(
            name=FONTE_PADRAO, bold=True
        )
        linha += 1
        for i, texto in enumerate(["Período", "Receita", "Custos", "Resultado"], start=1):
            c = ws.cell(row=linha, column=i, value=texto)
            c.font = Font(name=FONTE_PADRAO, bold=True)
        linha += 1
        for s in saldos_anteriores:
            ws.cell(row=linha, column=1, value=s["periodo"])
            ws.cell(row=linha, column=2, value=round(s["receita_total"], 2)).number_format = FORMATO_MOEDA
            ws.cell(row=linha, column=3, value=round(-s["custos_total"], 2)).number_format = FORMATO_MOEDA
            ws.cell(row=linha, column=4, value=round(s["resultado"], 2)).number_format = FORMATO_MOEDA
            linha += 1

    ws.column_dimensions["A"].width = 34
    for i in range(2, len(cabecalho) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 13
    ws.freeze_panes = "B5"

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer


def gerar_excel_dre_consolidado(ano, meses, meses_nome, totais, acumulado):
    wb = Workbook()
    ws = wb.active
    ws.title = "Totais Consolidado"

    ws.merge_cells("A1:N1")
    ws["A1"] = f"DRE Consolidado — Todas as Obras — {ano}"
    _estilo_titulo(ws["A1"], tamanho=14, fundo=COR_CABECALHO)
    ws.row_dimensions[1].height = 24

    linha = 3
    cabecalho = ["Linha"] + [f"{meses_nome[m][:3]}/{a}" for a, m in meses] + ["Acumulado"]
    for i, texto in enumerate(cabecalho, start=1):
        c = ws.cell(row=linha, column=i, value=texto)
        c.font = Font(name=FONTE_PADRAO, bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor=COR_CABECALHO)
        c.alignment = Alignment(horizontal="center" if i > 1 else "left")
    linha += 1

    vals_receita = [totais[(a, m)]["receita_total"] for a, m in meses] + [acumulado["receita_total"]]
    _linha_valores(ws, linha, "Receitas Brutas Total", vals_receita, negrito=True, fundo=COR_DESTAQUE)
    linha += 1

    vals_custo = [-totais[(a, m)]["custos_total"] for a, m in meses] + [-acumulado["custos_total"]]
    _linha_valores(ws, linha, "Custos Total", vals_custo, negrito=True, fundo=COR_DESTAQUE, cor_texto=COR_NEGATIVO)
    linha += 1

    vals_bruto = [totais[(a, m)]["lucro_bruto"] for a, m in meses] + [acumulado["lucro_bruto"]]
    _linha_valores(ws, linha, "= Lucro / Prejuízo Bruto", vals_bruto, negrito=True, fundo=COR_DESTAQUE)
    linha += 1

    for chave, rotulo in [
        ("impostos_servicos", "(-) Impostos s/ Serviços"),
        ("irpj_csll", "(-) IRPJ e CSLL"),
        ("despesa_administrativa", "(-) Desp. Administrativas/Técnico"),
        ("despesa_financeira", "(-) Despesas Financeiras"),
    ]:
        vals = [-totais[(a, m)][chave] for a, m in meses] + [-acumulado[chave]]
        _linha_valores(ws, linha, rotulo, vals, cor_texto=COR_NEGATIVO)
        linha += 1

    vals_liquido = [totais[(a, m)]["lucro_liquido"] for a, m in meses] + [acumulado["lucro_liquido"]]
    _linha_valores(ws, linha, "LUCRO/PREJUÍZO LÍQUIDO CONSOLIDADO", vals_liquido, negrito=True, fundo="FFE8A3")

    ws.column_dimensions["A"].width = 34
    for i in range(2, len(cabecalho) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 13
    ws.freeze_panes = "B4"

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return buffer
