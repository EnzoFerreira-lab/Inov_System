from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import sqlite3
import os
import pandas as pd
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = "chave_secreta_inov"

DATABASE = "database.db"
UPLOAD_FOLDER = "uploads"
EXPORT_FOLDER = "exports"
ALLOWED_EXTENSIONS = {"xlsx", "xls"}

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["EXPORT_FOLDER"] = EXPORT_FOLDER


def conectar():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn


def criar_tabelas():
    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            senha TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS centros_custo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            codigo TEXT NOT NULL UNIQUE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS empresas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            cnpj TEXT NOT NULL UNIQUE,
            centro_custo_id INTEGER,
            FOREIGN KEY (centro_custo_id) REFERENCES centros_custo(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lancamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            empresa_id INTEGER NOT NULL,
            centro_custo_id INTEGER NOT NULL,
            mes INTEGER NOT NULL,
            ano INTEGER NOT NULL,
            tipo_conta TEXT NOT NULL,
            conta_nome TEXT NOT NULL,
            descricao TEXT,
            valor REAL NOT NULL,
            FOREIGN KEY (empresa_id) REFERENCES empresas(id),
            FOREIGN KEY (centro_custo_id) REFERENCES centros_custo(id)
        )
    """)

    cursor.execute("SELECT * FROM usuarios WHERE email = ?", ("admin@inov.com",))
    usuario = cursor.fetchone()

    if not usuario:
        cursor.execute("""
            INSERT INTO usuarios (nome, email, senha)
            VALUES (?, ?, ?)
        """, ("Administrador", "admin@inov.com", "1234"))

    conn.commit()
    conn.close()


def criar_pastas():
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    os.makedirs(EXPORT_FOLDER, exist_ok=True)
    os.makedirs("static/css", exist_ok=True)
    os.makedirs("static/js", exist_ok=True)
    os.makedirs("templates", exist_ok=True)


def usuario_logado():
    return "usuario_id" in session


def arquivo_permitido(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def limpar_texto(valor):
    if pd.isna(valor):
        return ""
    return str(valor).strip()


def limpar_numero(valor):
    if pd.isna(valor):
        return 0
    texto = str(valor).strip().replace("R$", "").replace(" ", "")
    texto = texto.replace(".", "").replace(",", ".")
    try:
        return float(texto)
    except ValueError:
        return 0


def buscar_ou_criar_centro(cursor, nome_centro, codigo_centro):
    cursor.execute("SELECT id FROM centros_custo WHERE codigo = ?", (codigo_centro,))
    centro = cursor.fetchone()

    if centro:
        return centro["id"]

    cursor.execute(
        "INSERT INTO centros_custo (nome, codigo) VALUES (?, ?)",
        (nome_centro, codigo_centro)
    )
    return cursor.lastrowid


def buscar_ou_criar_empresa(cursor, nome_empresa, cnpj, centro_custo_id):
    cursor.execute("SELECT id, centro_custo_id FROM empresas WHERE cnpj = ?", (cnpj,))
    empresa = cursor.fetchone()

    if empresa:
        if empresa["centro_custo_id"] != centro_custo_id:
            cursor.execute(
                "UPDATE empresas SET centro_custo_id = ? WHERE id = ?",
                (centro_custo_id, empresa["id"])
            )
        return empresa["id"]

    cursor.execute(
        "INSERT INTO empresas (nome, cnpj, centro_custo_id) VALUES (?, ?, ?)",
        (nome_empresa, cnpj, centro_custo_id)
    )
    return cursor.lastrowid


@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        senha = request.form.get("senha")

        conn = conectar()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM usuarios WHERE email = ? AND senha = ?", (email, senha))
        usuario = cursor.fetchone()
        conn.close()

        if usuario:
            session["usuario_id"] = usuario["id"]
            session["usuario_nome"] = usuario["nome"]
            return redirect(url_for("dashboard"))
        else:
            flash("E-mail ou senha inválidos.", "erro")

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/dashboard")
def dashboard():
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM empresas ORDER BY nome")
    empresas = cursor.fetchall()

    cursor.execute("""
        SELECT 
            SUM(CASE WHEN tipo_conta = 'Receita' THEN valor ELSE 0 END) AS receita_bruta,
            SUM(CASE WHEN tipo_conta = 'Custo' THEN valor ELSE 0 END) AS custos,
            SUM(CASE WHEN tipo_conta = 'Despesa' THEN valor ELSE 0 END) AS despesas
        FROM lancamentos
    """)
    resumo = cursor.fetchone()

    receita_bruta = resumo["receita_bruta"] if resumo["receita_bruta"] else 0
    custos = resumo["custos"] if resumo["custos"] else 0
    despesas = resumo["despesas"] if resumo["despesas"] else 0

    lucro_bruto = receita_bruta - custos
    resultado_liquido = lucro_bruto - despesas

    cursor.execute("SELECT * FROM centros_custo ORDER BY nome")
    centros = cursor.fetchall()

    cursor.execute("""
        SELECT 
            ano,
            mes,
            SUM(CASE WHEN tipo_conta = 'Receita' THEN valor ELSE 0 END) AS receita,
            SUM(CASE WHEN tipo_conta = 'Custo' THEN valor ELSE 0 END) AS custo,
            SUM(CASE WHEN tipo_conta = 'Despesa' THEN valor ELSE 0 END) AS despesa
        FROM lancamentos
        GROUP BY ano, mes
        ORDER BY ano, mes
    """)
    grafico = cursor.fetchall()

    labels = []
    valores = []

    for item in grafico:
        labels.append(f"{item['mes']:02d}/{item['ano']}")
        receita = item["receita"] if item["receita"] else 0
        custo = item["custo"] if item["custo"] else 0
        despesa = item["despesa"] if item["despesa"] else 0
        valores.append(receita - custo - despesa)

    conn.close()

    return render_template(
        "dashboard.html",
        empresas=empresas,
        centros=centros,
        receita_bruta=receita_bruta,
        custos=custos,
        lucro_bruto=lucro_bruto,
        resultado_liquido=resultado_liquido,
        labels=labels,
        valores=valores
    )


@app.route("/centros-custo", methods=["GET", "POST"])
def centros_custo():
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        nome = request.form.get("nome")
        codigo = request.form.get("codigo")

        if nome and codigo:
            try:
                cursor.execute("""
                    INSERT INTO centros_custo (nome, codigo)
                    VALUES (?, ?)
                """, (nome, codigo))
                conn.commit()
                flash("Centro de custo cadastrado com sucesso.", "sucesso")
            except sqlite3.IntegrityError:
                flash("Código já cadastrado.", "erro")

    cursor.execute("""
        SELECT 
            c.*,
            COUNT(e.id) AS total_empresas
        FROM centros_custo c
        LEFT JOIN empresas e ON e.centro_custo_id = c.id
        GROUP BY c.id
        ORDER BY c.id DESC
    """)
    centros = cursor.fetchall()

    conn.close()
    return render_template("centros_custo.html", centros=centros)


@app.route("/centro/<int:centro_id>", methods=["GET", "POST"])
def centro_detalhes(centro_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        empresa_id = request.form.get("empresa_id")
        mes = request.form.get("mes")
        ano = request.form.get("ano")
        tipo_conta = request.form.get("tipo_conta")
        conta_nome = request.form.get("conta_nome")
        descricao = request.form.get("descricao")
        valor = request.form.get("valor")

        if empresa_id and mes and ano and tipo_conta and conta_nome and valor:
            cursor.execute("""
                INSERT INTO lancamentos 
                (empresa_id, centro_custo_id, mes, ano, tipo_conta, conta_nome, descricao, valor)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (empresa_id, centro_id, mes, ano, tipo_conta, conta_nome, descricao, valor))
            conn.commit()
            flash("Lançamento cadastrado com sucesso.", "sucesso")

    cursor.execute("SELECT * FROM centros_custo WHERE id = ?", (centro_id,))
    centro = cursor.fetchone()

    cursor.execute("SELECT * FROM empresas WHERE centro_custo_id = ? ORDER BY nome", (centro_id,))
    empresas = cursor.fetchall()

    cursor.execute("""
        SELECT 
            l.*,
            e.nome AS empresa_nome
        FROM lancamentos l
        JOIN empresas e ON l.empresa_id = e.id
        WHERE l.centro_custo_id = ?
        ORDER BY l.ano DESC, l.mes DESC, l.id DESC
    """, (centro_id,))
    lancamentos = cursor.fetchall()

    cursor.execute("""
        SELECT 
            SUM(CASE WHEN tipo_conta = 'Receita' THEN valor ELSE 0 END) AS receita_bruta,
            SUM(CASE WHEN tipo_conta = 'Custo' THEN valor ELSE 0 END) AS custos,
            SUM(CASE WHEN tipo_conta = 'Despesa' THEN valor ELSE 0 END) AS despesas
        FROM lancamentos
        WHERE centro_custo_id = ?
    """, (centro_id,))
    resumo = cursor.fetchone()

    receita_bruta = resumo["receita_bruta"] if resumo["receita_bruta"] else 0
    custos = resumo["custos"] if resumo["custos"] else 0
    despesas = resumo["despesas"] if resumo["despesas"] else 0
    lucro_bruto = receita_bruta - custos
    resultado_liquido = lucro_bruto - despesas

    conn.close()

    return render_template(
        "centro_detalhes.html",
        centro=centro,
        empresas=empresas,
        lancamentos=lancamentos,
        receita_bruta=receita_bruta,
        custos=custos,
        lucro_bruto=lucro_bruto,
        resultado_liquido=resultado_liquido
    )


@app.route("/centro/<int:centro_id>/exportar")
def exportar_centro_excel(centro_id):
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM centros_custo WHERE id = ?", (centro_id,))
    centro = cursor.fetchone()

    if not centro:
        conn.close()
        flash("Centro de custo não encontrado.", "erro")
        return redirect(url_for("centros_custo"))

    cursor.execute("""
        SELECT 
            l.id,
            e.nome AS empresa,
            e.cnpj AS cnpj,
            c.nome AS centro_custo,
            c.codigo AS codigo_centro,
            l.mes,
            l.ano,
            l.tipo_conta,
            l.conta_nome,
            l.descricao,
            l.valor
        FROM lancamentos l
        JOIN empresas e ON l.empresa_id = e.id
        JOIN centros_custo c ON l.centro_custo_id = c.id
        WHERE l.centro_custo_id = ?
        ORDER BY l.ano DESC, l.mes DESC, l.id DESC
    """, (centro_id,))
    lancamentos = cursor.fetchall()

    conn.close()

    if not lancamentos:
        flash("Esse centro de custo não possui lançamentos para exportar.", "erro")
        return redirect(url_for("centro_detalhes", centro_id=centro_id))

    dados = []
    for item in lancamentos:
        dados.append({
            "ID": item["id"],
            "Empresa": item["empresa"],
            "CNPJ": item["cnpj"],
            "Centro de Custo": item["centro_custo"],
            "Código do Centro": item["codigo_centro"],
            "Mês": item["mes"],
            "Ano": item["ano"],
            "Tipo de Conta": item["tipo_conta"],
            "Conta": item["conta_nome"],
            "Descrição": item["descricao"],
            "Valor": item["valor"]
        })

    df = pd.DataFrame(dados)

    nome_centro = centro["nome"].replace(" ", "_").lower()
    caminho_arquivo = os.path.join(
        app.config["EXPORT_FOLDER"],
        f"centro_{nome_centro}_{centro_id}.xlsx"
    )

    with pd.ExcelWriter(caminho_arquivo, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Lançamentos")

    return send_file(caminho_arquivo, as_attachment=True)


@app.route("/empresas", methods=["GET", "POST"])
def empresas():
    if not usuario_logado():
        return redirect(url_for("login"))

    conn = conectar()
    cursor = conn.cursor()

    if request.method == "POST":
        nome = request.form.get("nome")
        cnpj = request.form.get("cnpj")
        centro_custo_id = request.form.get("centro_custo_id")

        if nome and cnpj:
            try:
                if centro_custo_id == "":
                    centro_custo_id = None

                cursor.execute("""
                    INSERT INTO empresas (nome, cnpj, centro_custo_id)
                    VALUES (?, ?, ?)
                """, (nome, cnpj, centro_custo_id))
                conn.commit()
                flash("Empresa cadastrada com sucesso.", "sucesso")
            except sqlite3.IntegrityError:
                flash("CNPJ já cadastrado.", "erro")

    cursor.execute("""
        SELECT e.*, c.nome AS centro_nome
        FROM empresas e
        LEFT JOIN centros_custo c ON e.centro_custo_id = c.id
        ORDER BY e.id DESC
    """)
    lista_empresas = cursor.fetchall()

    cursor.execute("SELECT * FROM centros_custo ORDER BY nome")
    centros = cursor.fetchall()

    conn.close()

    return render_template("empresas.html", empresas=lista_empresas, centros=centros)


@app.route("/importar-dados", methods=["GET", "POST"])
def importar_dados():
    if not usuario_logado():
        return redirect(url_for("login"))

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

        try:
            df = pd.read_excel(caminho_arquivo)

            df.columns = [str(col).strip().lower() for col in df.columns]

            colunas_necessarias = [
                "empresa",
                "cnpj",
                "centro_custo",
                "codigo_centro",
                "mes",
                "ano",
                "tipo_conta",
                "conta_nome",
                "descricao",
                "valor"
            ]

            colunas_faltando = [col for col in colunas_necessarias if col not in df.columns]

            if colunas_faltando:
                flash(
                    "A planilha está faltando estas colunas: " + ", ".join(colunas_faltando),
                    "erro"
                )
                return redirect(url_for("importar_dados"))

            conn = conectar()
            cursor = conn.cursor()

            total_importado = 0

            for _, linha in df.iterrows():
                nome_empresa = limpar_texto(linha["empresa"])
                cnpj = limpar_texto(linha["cnpj"])
                nome_centro = limpar_texto(linha["centro_custo"])
                codigo_centro = limpar_texto(linha["codigo_centro"])
                tipo_conta = limpar_texto(linha["tipo_conta"])
                conta_nome = limpar_texto(linha["conta_nome"])
                descricao = limpar_texto(linha["descricao"])

                if not nome_empresa or not cnpj or not nome_centro or not codigo_centro:
                    continue

                try:
                    mes = int(float(linha["mes"]))
                    ano = int(float(linha["ano"]))
                except (ValueError, TypeError):
                    continue

                valor = limpar_numero(linha["valor"])

                if mes < 1 or mes > 12:
                    continue

                if tipo_conta not in ["Receita", "Custo", "Despesa"]:
                    continue

                centro_custo_id = buscar_ou_criar_centro(cursor, nome_centro, codigo_centro)
                empresa_id = buscar_ou_criar_empresa(cursor, nome_empresa, cnpj, centro_custo_id)

                cursor.execute("""
                    INSERT INTO lancamentos
                    (empresa_id, centro_custo_id, mes, ano, tipo_conta, conta_nome, descricao, valor)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    empresa_id,
                    centro_custo_id,
                    mes,
                    ano,
                    tipo_conta,
                    conta_nome,
                    descricao,
                    valor
                ))

                total_importado += 1

            conn.commit()
            conn.close()

            flash(f"Importação concluída com sucesso. {total_importado} lançamento(s) importado(s).", "sucesso")
            return redirect(url_for("importar_dados"))

        except Exception as e:
            flash(f"Erro ao processar a planilha: {str(e)}", "erro")
            return redirect(url_for("importar_dados"))

    return render_template("importar_dados.html")


if __name__ == "__main__":
    criar_pastas()
    criar_tabelas()
    app.run(debug=True)