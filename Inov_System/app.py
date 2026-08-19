from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import os
import re
import calendar
import pandas as pd
import openpyxl
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from db import conectar, criar_tabelas
from dre import calcular_dre_obra, calcular_dre_consolidado, buscar_saldos_anteriores
from dre_import import importar_planilha_dre_real
from dre_export import gerar_excel_dre_obra, gerar_excel_dre_consolidado

app = Flask(__name__)
app.secret_key = os.environ.get("INOV_SECRET_KEY", "chave_secreta_inov_dev")

UPLOAD_FOLDER = "uploads"
EXPORT_FOLDER = "exports"
ALLOWED_EXTENSIONS = {"xlsx", "xls"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["EXPORT_FOLDER"] = EXPORT_FOLDER

MESES_NOME = [
    "", "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
]


def criar_pastas():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(EXPORT_FOLDER, exist_ok=True)
    os.makedirs("static/css", exist_ok=True)
    os.makedirs("static/js", exist_ok=True)
    os.makedirs("templates", exist_ok=True)


def usuario_logado():
    return "usuario_id" in session


def exigir_login():
    if not usuario_logado():
        return redirect(url_for("login"))
    return None


def arquivo_permitido(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def meses_do_ano(ano):
    return [(ano, m) for m in range(1, 13)]


# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        conn = conectar()
        cur = conn.cursor()
        cur.execute("SELECT * FROM usuarios WHERE email = ?", (email,))
        usuario = cur.fetchone()
        conn.close()

        if usuario and check_password_hash(usuario["senha_hash"], senha or ""):
            session["usuario_id"] = usuario["id"]
            session["usuario_nome"] = usuario["nome"]
            return redirect(url_for("dashboard"))

        flash("E-mail ou senha inválidos.", "erro")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

@app.route("/dashboard")
def dashboard():
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    cur.execute("""
        SELECT o.*, e.nome AS empresa_nome
        FROM obras o
        JOIN empresas e ON e.id = o.empresa_id
        ORDER BY o.status = 'encerrada', o.nome
    """)
    obras = [dict(r) for r in cur.fetchall()]
    conn.close()

    ano_atual = request.args.get("ano", type=int)
    if not ano_atual:
        import datetime
        ano_atual = datetime.date.today().year

    obra_ids = [o["id"] for o in obras]
    meses = meses_do_ano(ano_atual)
    resultado = calcular_dre_consolidado(obra_ids, meses) if obra_ids else {
        "totais": {c: {"receita_total": 0, "custos_total": 0, "lucro_bruto": 0, "lucro_liquido": 0} for c in meses},
        "acumulado": {"receita_total": 0, "custos_total": 0, "lucro_bruto": 0, "lucro_liquido": 0},
    }

    labels = [f"{m:02d}/{a}" for a, m in meses]
    valores = [round(resultado["totais"][c]["lucro_liquido"], 2) for c in meses]

    return render_template(
        "dashboard.html",
        obras=obras[:8],
        ano_atual=ano_atual,
        receita_bruta=resultado["acumulado"]["receita_total"],
        custos=resultado["acumulado"]["custos_total"],
        lucro_bruto=resultado["acumulado"]["lucro_bruto"],
        resultado_liquido=resultado["acumulado"]["lucro_liquido"],
        labels=labels,
        valores=valores,
    )


# ---------------------------------------------------------------------------
# Empresas (clientes da contabilidade)
# ---------------------------------------------------------------------------

@app.route("/empresas", methods=["GET", "POST"])
def empresas():
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        cnpj = (request.form.get("cnpj") or "").strip() or None

        if nome:
            try:
                cur.execute("INSERT INTO empresas (nome, cnpj) VALUES (?, ?)", (nome, cnpj))
                conn.commit()
                flash("Empresa cadastrada com sucesso.", "sucesso")
            except Exception:
                flash("Não foi possível cadastrar. Verifique se o CNPJ já existe.", "erro")
        else:
            flash("Informe o nome da empresa.", "erro")

    cur.execute("""
        SELECT e.*, COUNT(o.id) AS total_obras
        FROM empresas e
        LEFT JOIN obras o ON o.empresa_id = e.id
        GROUP BY e.id
        ORDER BY e.nome
    """)
    lista = cur.fetchall()
    conn.close()

    return render_template("empresas.html", empresas=lista)


@app.route("/empresas/<int:empresa_id>/editar", methods=["GET", "POST"])
def editar_empresa(empresa_id):
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        cnpj = (request.form.get("cnpj") or "").strip() or None

        if nome:
            try:
                cur.execute("UPDATE empresas SET nome = ?, cnpj = ? WHERE id = ?", (nome, cnpj, empresa_id))
                conn.commit()
                flash("Empresa atualizada com sucesso.", "sucesso")
                conn.close()
                return redirect(url_for("empresas"))
            except Exception:
                flash("Não foi possível salvar. Verifique se o CNPJ já existe em outra empresa.", "erro")
        else:
            flash("Informe o nome da empresa.", "erro")

    cur.execute("SELECT * FROM empresas WHERE id = ?", (empresa_id,))
    empresa = cur.fetchone()
    conn.close()

    if not empresa:
        flash("Empresa não encontrada.", "erro")
        return redirect(url_for("empresas"))

    return render_template("editar_empresa.html", empresa=empresa)


@app.route("/empresas/<int:empresa_id>/excluir", methods=["POST"])
def excluir_empresa(empresa_id):
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) AS total FROM obras WHERE empresa_id = ?", (empresa_id,))
    total_obras = cur.fetchone()["total"]

    if total_obras > 0:
        flash(f"Não é possível excluir: essa empresa ainda tem {total_obras} obra(s) cadastrada(s). Exclua as obras primeiro.", "erro")
    else:
        cur.execute("DELETE FROM empresas WHERE id = ?", (empresa_id,))
        conn.commit()
        flash("Empresa excluída.", "sucesso")

    conn.close()
    return redirect(url_for("empresas"))


# ---------------------------------------------------------------------------
# Obras (centros de custo)
# ---------------------------------------------------------------------------

@app.route("/obras", methods=["GET", "POST"])
def obras():
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        codigo = (request.form.get("codigo") or "").strip()
        empresa_id = request.form.get("empresa_id")
        status = request.form.get("status") or "em_andamento"
        data_inicio = request.form.get("data_inicio") or None

        if nome and codigo and empresa_id:
            try:
                cur.execute("""
                    INSERT INTO obras (empresa_id, nome, codigo, status, data_inicio)
                    VALUES (?, ?, ?, ?, ?)
                """, (empresa_id, nome, codigo, status, data_inicio))
                conn.commit()
                flash("Obra cadastrada com sucesso.", "sucesso")
            except Exception:
                flash("Não foi possível cadastrar. Verifique se o código já existe.", "erro")
        else:
            flash("Preencha nome, código e empresa.", "erro")

    cur.execute("""
        SELECT o.*, e.nome AS empresa_nome
        FROM obras o
        JOIN empresas e ON e.id = o.empresa_id
        ORDER BY o.status = 'encerrada', o.nome
    """)
    lista = cur.fetchall()

    cur.execute("SELECT * FROM empresas ORDER BY nome")
    empresas_lista = cur.fetchall()

    conn.close()

    return render_template("obras.html", obras=lista, empresas=empresas_lista)


@app.route("/obras/<int:obra_id>/editar", methods=["GET", "POST"])
def editar_obra(obra_id):
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        codigo = (request.form.get("codigo") or "").strip()
        empresa_id = request.form.get("empresa_id")
        status = request.form.get("status") or "em_andamento"
        data_inicio = request.form.get("data_inicio") or None

        if nome and codigo and empresa_id:
            try:
                cur.execute("""
                    UPDATE obras SET nome = ?, codigo = ?, empresa_id = ?, status = ?, data_inicio = ?
                    WHERE id = ?
                """, (nome, codigo, empresa_id, status, data_inicio, obra_id))
                conn.commit()
                flash("Obra atualizada com sucesso.", "sucesso")
                conn.close()
                return redirect(url_for("obras"))
            except Exception:
                flash("Não foi possível salvar. Verifique se o código já existe em outra obra.", "erro")
        else:
            flash("Preencha nome, código e empresa.", "erro")

    cur.execute("SELECT * FROM obras WHERE id = ?", (obra_id,))
    obra = cur.fetchone()
    cur.execute("SELECT * FROM empresas ORDER BY nome")
    empresas_lista = cur.fetchall()
    conn.close()

    if not obra:
        flash("Obra não encontrada.", "erro")
        return redirect(url_for("obras"))

    return render_template("editar_obra.html", obra=obra, empresas=empresas_lista)


@app.route("/obras/<int:obra_id>/excluir", methods=["POST"])
def excluir_obra(obra_id):
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    cur.execute("DELETE FROM lancamentos WHERE obra_id = ?", (obra_id,))
    cur.execute("DELETE FROM saldos_anteriores WHERE obra_id = ?", (obra_id,))
    cur.execute("DELETE FROM obras WHERE id = ?", (obra_id,))
    conn.commit()
    conn.close()

    flash("Obra e todos os seus lançamentos foram excluídos.", "sucesso")
    return redirect(url_for("obras"))


@app.route("/obras/<int:obra_id>")
def obra_dre(obra_id):
    redir = exigir_login()
    if redir:
        return redir

    ano = request.args.get("ano", type=int)
    if not ano:
        import datetime
        ano = datetime.date.today().year

    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        SELECT o.*, e.nome AS empresa_nome
        FROM obras o JOIN empresas e ON e.id = o.empresa_id
        WHERE o.id = ?
    """, (obra_id,))
    obra = cur.fetchone()
    conn.close()

    if not obra:
        flash("Obra não encontrada.", "erro")
        return redirect(url_for("obras"))

    meses = meses_do_ano(ano)
    resultado = calcular_dre_obra(obra_id, meses)
    saldos_anteriores = buscar_saldos_anteriores(obra_id)

    return render_template(
        "obra_dre.html",
        obra=obra,
        ano=ano,
        meses=meses,
        meses_nome=MESES_NOME,
        categorias=resultado["categorias"],
        totais=resultado["totais"],
        acumulado=resultado["acumulado"],
        saldos_anteriores=saldos_anteriores,
    )


@app.route("/obras/<int:obra_id>/exportar")
def exportar_obra_excel(obra_id):
    redir = exigir_login()
    if redir:
        return redir

    ano = request.args.get("ano", type=int)
    if not ano:
        import datetime
        ano = datetime.date.today().year

    conn = conectar()
    cur = conn.cursor()
    cur.execute("""
        SELECT o.*, e.nome AS empresa_nome
        FROM obras o JOIN empresas e ON e.id = o.empresa_id
        WHERE o.id = ?
    """, (obra_id,))
    obra = cur.fetchone()
    conn.close()

    if not obra:
        flash("Obra não encontrada.", "erro")
        return redirect(url_for("obras"))

    meses = meses_do_ano(ano)
    resultado = calcular_dre_obra(obra_id, meses)
    saldos_anteriores = buscar_saldos_anteriores(obra_id)

    buffer = gerar_excel_dre_obra(
        obra, ano, meses, MESES_NOME,
        resultado["categorias"], resultado["totais"], resultado["acumulado"],
        saldos_anteriores,
    )

    nome_arquivo = f"DRE_{obra['codigo']}_{ano}.xlsx"
    return send_file(
        buffer,
        as_attachment=True,
        download_name=nome_arquivo,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Totais consolidados (todas as obras)
# ---------------------------------------------------------------------------

@app.route("/totais")
def totais():
    redir = exigir_login()
    if redir:
        return redir

    ano = request.args.get("ano", type=int)
    if not ano:
        import datetime
        ano = datetime.date.today().year

    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT id FROM obras")
    obra_ids = [r["id"] for r in cur.fetchall()]
    conn.close()

    meses = meses_do_ano(ano)
    resultado = calcular_dre_consolidado(obra_ids, meses)

    return render_template(
        "totais.html",
        ano=ano,
        meses=meses,
        meses_nome=MESES_NOME,
        totais=resultado["totais"],
        acumulado=resultado["acumulado"],
    )


@app.route("/totais/exportar")
def exportar_totais_excel():
    redir = exigir_login()
    if redir:
        return redir

    ano = request.args.get("ano", type=int)
    if not ano:
        import datetime
        ano = datetime.date.today().year

    conn = conectar()
    cur = conn.cursor()
    cur.execute("SELECT id FROM obras")
    obra_ids = [r["id"] for r in cur.fetchall()]
    conn.close()

    meses = meses_do_ano(ano)
    resultado = calcular_dre_consolidado(obra_ids, meses)

    buffer = gerar_excel_dre_consolidado(ano, meses, MESES_NOME, resultado["totais"], resultado["acumulado"])

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"DRE_Consolidado_{ano}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


# ---------------------------------------------------------------------------
# Plano de contas (categorias)
# ---------------------------------------------------------------------------

@app.route("/categorias", methods=["GET", "POST"])
def categorias():
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    if request.method == "POST":
        nome = (request.form.get("nome") or "").strip()
        codigo = (request.form.get("codigo") or "").strip() or None
        tipo = request.form.get("tipo")

        if nome and tipo in ("receita", "custo"):
            cur.execute("SELECT COALESCE(MAX(ordem), 0) + 1 AS prox FROM categorias_conta")
            ordem = cur.fetchone()["prox"]
            try:
                cur.execute("""
                    INSERT INTO categorias_conta (codigo, nome, tipo, ordem, ativo)
                    VALUES (?, ?, ?, ?, 1)
                """, (codigo, nome, tipo, ordem))
                conn.commit()
                flash("Categoria adicionada ao plano de contas.", "sucesso")
            except Exception:
                flash("Já existe uma categoria com esse nome.", "erro")
        else:
            flash("Informe nome e tipo (receita ou custo).", "erro")

    cur.execute("SELECT * FROM categorias_conta ORDER BY tipo DESC, ordem")
    lista = cur.fetchall()
    conn.close()

    return render_template("categorias.html", categorias=lista)


@app.route("/categorias/<int:categoria_id>/alternar-status")
def alternar_status_categoria(categoria_id):
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()
    cur.execute("UPDATE categorias_conta SET ativo = 1 - ativo WHERE id = ?", (categoria_id,))
    conn.commit()
    conn.close()

    flash("Status da categoria atualizado.", "sucesso")
    return redirect(url_for("categorias"))


# ---------------------------------------------------------------------------
# Taxas configuráveis (impostos, IRPJ/CSLL, adm., financeiras)
# ---------------------------------------------------------------------------

@app.route("/taxas", methods=["GET", "POST"])
def taxas():
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    if request.method == "POST":
        chave = request.form.get("chave")
        percentual = request.form.get("percentual")
        vigencia_inicio = request.form.get("vigencia_inicio")

        if chave and percentual and vigencia_inicio:
            cur.execute("""
                SELECT descricao, base_calculo FROM taxas
                WHERE chave = ? ORDER BY vigencia_inicio DESC LIMIT 1
            """, (chave,))
            referencia = cur.fetchone()

            if referencia:
                ano, mes = vigencia_inicio.split("-")
                ano, mes = int(ano), int(mes)
                mes_anterior = mes - 1
                ano_fim = ano
                if mes_anterior == 0:
                    mes_anterior = 12
                    ano_fim -= 1
                fim_anterior = f"{ano_fim:04d}-{mes_anterior:02d}"

                cur.execute("""
                    UPDATE taxas SET vigencia_fim = ?
                    WHERE chave = ? AND vigencia_fim IS NULL
                """, (fim_anterior, chave))

                cur.execute("""
                    INSERT INTO taxas (chave, descricao, percentual, base_calculo, vigencia_inicio, vigencia_fim)
                    VALUES (?, ?, ?, ?, ?, NULL)
                """, (chave, referencia["descricao"], float(percentual), referencia["base_calculo"], vigencia_inicio))

                conn.commit()
                flash("Nova vigência de taxa cadastrada.", "sucesso")
            else:
                flash("Taxa não encontrada.", "erro")
        else:
            flash("Preencha todos os campos.", "erro")

    cur.execute("SELECT * FROM taxas ORDER BY chave, vigencia_inicio DESC")
    lista = cur.fetchall()
    conn.close()

    return render_template("taxas.html", taxas=lista)


# ---------------------------------------------------------------------------
# Lançamentos manuais (grade categoria x valor, para uma obra/mês/ano)
# ---------------------------------------------------------------------------

@app.route("/lancamentos", methods=["GET", "POST"])
def lancamentos_manual():
    redir = exigir_login()
    if redir:
        return redir

    conn = conectar()
    cur = conn.cursor()

    cur.execute("SELECT id, nome, codigo FROM obras ORDER BY nome")
    obras_lista = cur.fetchall()

    obra_id = request.args.get("obra_id", type=int) or request.form.get("obra_id", type=int)
    mes = request.args.get("mes", type=int) or request.form.get("mes", type=int)
    ano = request.args.get("ano", type=int) or request.form.get("ano", type=int)

    if request.method == "POST" and obra_id and mes and ano:
        cur.execute("SELECT id FROM categorias_conta WHERE ativo = 1")
        categoria_ids = [r["id"] for r in cur.fetchall()]

        import datetime
        agora = datetime.datetime.now().isoformat()

        for categoria_id in categoria_ids:
            campo = f"valor_{categoria_id}"
            valor_raw = request.form.get(campo, "").strip().replace(",", ".")
            valor = abs(float(valor_raw)) if valor_raw else 0.0

            cur.execute("""
                INSERT INTO lancamentos (obra_id, categoria_id, mes, ano, valor, origem, atualizado_em)
                VALUES (?, ?, ?, ?, ?, 'manual', ?)
                ON CONFLICT (obra_id, categoria_id, mes, ano)
                DO UPDATE SET valor = excluded.valor, origem = 'manual', atualizado_em = excluded.atualizado_em
            """, (obra_id, categoria_id, mes, ano, valor, agora))

        conn.commit()
        flash("Lançamentos salvos com sucesso.", "sucesso")

    categorias_com_valor = []
    if obra_id and mes and ano:
        cur.execute("""
            SELECT c.id, c.codigo, c.nome, c.tipo,
                   COALESCE(l.valor, 0) AS valor
            FROM categorias_conta c
            LEFT JOIN lancamentos l
                ON l.categoria_id = c.id AND l.obra_id = ? AND l.mes = ? AND l.ano = ?
            WHERE c.ativo = 1
            ORDER BY c.tipo DESC, c.ordem
        """, (obra_id, mes, ano))
        categorias_com_valor = cur.fetchall()

    conn.close()

    return render_template(
        "lancamentos.html",
        obras=obras_lista,
        obra_id=obra_id,
        mes=mes,
        ano=ano,
        meses_nome=MESES_NOME,
        categorias=categorias_com_valor,
    )


# ---------------------------------------------------------------------------
# Importação de dados via planilha
# ---------------------------------------------------------------------------

@app.route("/importar-dados", methods=["GET", "POST"])
def importar_dados():
    redir = exigir_login()
    if redir:
        return redir

    if request.method == "POST":
        arquivo = request.files.get("arquivo")

        if not arquivo or arquivo.filename == "":
            flash("Selecione um arquivo Excel para importar.", "erro")
            return redirect(url_for("importar_dados"))

        if not arquivo_permitido(arquivo.filename):
            flash("Formato inválido. Envie apenas arquivos .xlsx ou .xls.", "erro")
            return redirect(url_for("importar_dados"))

        filename = secure_filename(arquivo.filename)
        caminho_arquivo = os.path.join(app.config["UPLOAD_FOLDER"], filename)
        arquivo.save(caminho_arquivo)

        nomes_abas = []
        try:
            wb_check = openpyxl.load_workbook(caminho_arquivo, read_only=True)
            nomes_abas = wb_check.sheetnames
            wb_check.close()
        except Exception:
            pass

        eh_arquivo_dre_real = any(
            re.search(r"OBRA\s*\d+", nome.upper()) or "DEMAIS OBRAS" in nome.upper()
            for nome in nomes_abas
        )

        if eh_arquivo_dre_real:
            return _importar_arquivo_dre_real(caminho_arquivo)

        try:
            df = pd.read_excel(caminho_arquivo)
            df.columns = [str(col).strip().lower() for col in df.columns]

            colunas_necessarias = ["codigo_obra", "categoria", "mes", "ano", "valor"]
            faltando = [c for c in colunas_necessarias if c not in df.columns]
            if faltando:
                flash("A planilha está faltando estas colunas: " + ", ".join(faltando), "erro")
                return redirect(url_for("importar_dados"))

            conn = conectar()
            cur = conn.cursor()

            cur.execute("SELECT id, codigo FROM obras")
            obra_por_codigo = {r["codigo"]: r["id"] for r in cur.fetchall()}

            cur.execute("SELECT id, codigo, nome FROM categorias_conta")
            todas_categorias = cur.fetchall()
            categoria_por_codigo = {r["codigo"]: r["id"] for r in todas_categorias if r["codigo"]}
            categoria_por_nome = {r["nome"].strip().lower(): r["id"] for r in todas_categorias}

            import datetime
            agora = datetime.datetime.now().isoformat()

            total_ok = 0
            total_ignorados = 0

            for _, linha in df.iterrows():
                codigo_obra = str(linha.get("codigo_obra", "")).strip()
                categoria_ref = str(linha.get("categoria", "")).strip()

                obra_id = obra_por_codigo.get(codigo_obra)
                categoria_id = categoria_por_codigo.get(categoria_ref) or categoria_por_nome.get(categoria_ref.lower())

                if not obra_id or not categoria_id:
                    total_ignorados += 1
                    continue

                try:
                    mes = int(float(linha["mes"]))
                    ano = int(float(linha["ano"]))
                    valor_bruto = linha["valor"]
                    if isinstance(valor_bruto, str):
                        valor = float(valor_bruto.replace("R$", "").replace(".", "").replace(",", ".").strip())
                    else:
                        valor = float(valor_bruto)
                    valor = abs(valor)
                except (ValueError, TypeError):
                    total_ignorados += 1
                    continue

                if mes < 1 or mes > 12:
                    total_ignorados += 1
                    continue

                cur.execute("""
                    INSERT INTO lancamentos (obra_id, categoria_id, mes, ano, valor, origem, atualizado_em)
                    VALUES (?, ?, ?, ?, ?, 'importacao', ?)
                    ON CONFLICT (obra_id, categoria_id, mes, ano)
                    DO UPDATE SET valor = excluded.valor, origem = 'importacao', atualizado_em = excluded.atualizado_em
                """, (obra_id, categoria_id, mes, ano, valor, agora))
                total_ok += 1

            conn.commit()
            conn.close()

            msg = f"Importação concluída. {total_ok} lançamento(s) importado(s)."
            if total_ignorados:
                msg += f" {total_ignorados} linha(s) ignorada(s) (obra ou categoria não encontrada)."
            flash(msg, "sucesso")
            return redirect(url_for("importar_dados"))

        except Exception as e:
            flash(f"Erro ao processar a planilha: {str(e)}", "erro")
            return redirect(url_for("importar_dados"))

    return render_template("importar_dados.html")


def _detectar_nome_empresa(caminho_arquivo, nomes_abas):
    wb = openpyxl.load_workbook(caminho_arquivo, data_only=True)
    for nome_aba in nomes_abas:
        if re.search(r"OBRA\s*\d+", nome_aba.upper()) or "DEMAIS OBRAS" in nome_aba.upper():
            ws = wb[nome_aba]
            for r in range(1, 4):
                for c in (1, 2):
                    valor = ws.cell(row=r, column=c).value
                    if valor and len(str(valor).strip()) > 4 and "DEMONSTRAÇÃO" not in str(valor).upper():
                        return str(valor).strip()
    return "Empresa Importada"


def _obter_ou_criar_empresa(cur, nome_empresa):
    cur.execute("SELECT id FROM empresas WHERE nome = ?", (nome_empresa,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute("INSERT INTO empresas (nome, cnpj) VALUES (?, NULL)", (nome_empresa,))
    return cur.lastrowid


def _importar_arquivo_dre_real(caminho_arquivo):
    conn = conectar()
    cur = conn.cursor()

    wb_check = openpyxl.load_workbook(caminho_arquivo, read_only=True)
    nomes_abas = wb_check.sheetnames
    wb_check.close()

    nome_empresa = _detectar_nome_empresa(caminho_arquivo, nomes_abas)
    empresa_id = _obter_ou_criar_empresa(cur, nome_empresa)
    conn.commit()

    try:
        resumo = importar_planilha_dre_real(caminho_arquivo, cur, empresa_id)
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        flash(f"Erro ao processar o arquivo: {str(e)}", "erro")
        return redirect(url_for("importar_dados"))

    conn.close()

    partes = [
        f"Empresa: {nome_empresa}.",
        f"{len(resumo['abas_processadas'])} obra(s) lida(s).",
        f"{resumo['lancamentos_gravados']} lançamento(s) gravado(s).",
    ]
    if resumo["obras_criadas"]:
        partes.append(f"{len(resumo['obras_criadas'])} obra(s) nova(s) cadastrada(s) automaticamente.")
    if resumo["categorias_criadas"]:
        partes.append(f"{len(resumo['categorias_criadas'])} categoria(s) nova(s) no plano de contas.")
    if resumo["saldos_anteriores_gravados"]:
        partes.append(f"{resumo['saldos_anteriores_gravados']} valor(es) de período histórico (sem mês definido) também gravado(s) — veja na tela de cada obra.")
    if resumo["abas_ignoradas"]:
        partes.append(f"{len(resumo['abas_ignoradas'])} aba(s) ignorada(s) (veja detalhes abaixo).")

    flash(" ".join(partes), "sucesso")

    for nome_aba, motivo in resumo["abas_ignoradas"]:
        flash(f"Aba '{nome_aba}' ignorada: {motivo}", "erro")

    return redirect(url_for("importar_dados"))


if __name__ == "__main__":
    criar_pastas()
    criar_tabelas()
    app.run(debug=True)
