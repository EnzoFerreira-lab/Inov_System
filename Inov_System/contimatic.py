"""
Importação dos lançamentos contábeis vindos do Contimatic.

O módulo está partido em duas camadas de propósito:

  * **ler_relatorio_analitico(caminho)** — o adaptador que conhece o layout do
    arquivo do Contimatic e devolve uma lista de lançamentos normalizados.
    É a única parte que depende do formato do relatório.

  * **importar_lancamentos(...)** — o miolo: resolve obra e conta, soma os
    lançamentos por competência, atualiza o DRE e guarda o detalhe. Não sabe
    nada sobre Excel nem sobre o Contimatic, e por isso é testável sem arquivo.

Um lançamento normalizado é um dicionário:

    {
        "obra_codigo":  "251",              # centro de custo
        "conta_codigo": "311",              # conta contábil
        "conta_nome":   "Salarios e Ordenados",
        "data":         datetime.date(2026, 6, 15),
        "documento":    "NF 1234",          # opcional
        "historico":    "Folha de junho",   # opcional
        "valor":        24143.11,           # positivo; o sinal vem do tipo da conta
    }
"""

import datetime
import unicodedata


def _normalizar(texto):
    if texto is None:
        return ""
    nfkd = unicodedata.normalize("NFKD", str(texto))
    sem_acento = "".join(c for c in nfkd if not unicodedata.combining(c))
    return " ".join(sem_acento.lower().split())


def _codigo_limpo(codigo):
    """'0000311' e '311' são a mesma conta; '3.1.1' também aparece."""
    if codigo is None:
        return ""
    texto = str(codigo).strip()
    if texto.endswith(".0"):          # o Excel entrega número como float
        texto = texto[:-2]
    somente_digitos = "".join(c for c in texto if c.isdigit())
    return somente_digitos.lstrip("0") or somente_digitos


class ResolvedorDeContas:
    """
    Descobre a que categoria do plano de contas pertence cada conta contábil.

    Ordem de tentativa: o de-para explícito (contas_map), depois o código que já
    está em categorias_conta, e por fim o nome da conta. O que não casar é
    devolvido em 'nao_resolvidas' para a tela de revisão — nunca é adivinhado,
    porque uma conta no lugar errado desloca valor entre linhas do DRE.
    """

    def __init__(self, cur):
        self.cur = cur

        cur.execute("SELECT id, codigo, nome FROM categorias_conta")
        categorias = cur.fetchall()
        self.por_codigo = {_codigo_limpo(r["codigo"]): r["id"] for r in categorias if r["codigo"]}
        self.por_nome = {_normalizar(r["nome"]): r["id"] for r in categorias}

        cur.execute("SELECT conta_codigo, categoria_id, ignorar FROM contas_map")
        self.mapa = {
            _codigo_limpo(r["conta_codigo"]): (r["categoria_id"], r["ignorar"])
            for r in cur.fetchall()
        }

        self.nao_resolvidas = {}

    def resolver(self, conta_codigo, conta_nome):
        """Devolve (categoria_id, motivo). categoria_id None = não resolvida."""
        codigo = _codigo_limpo(conta_codigo)

        if codigo in self.mapa:
            categoria_id, ignorar = self.mapa[codigo]
            if ignorar:
                return None, "ignorada"
            if categoria_id:
                return categoria_id, "de-para"

        if codigo and codigo in self.por_codigo:
            return self.por_codigo[codigo], "codigo"

        nome = _normalizar(conta_nome)
        if nome and nome in self.por_nome:
            return self.por_nome[nome], "nome"

        self.nao_resolvidas.setdefault(codigo or nome, {
            "conta_codigo": conta_codigo,
            "conta_nome": conta_nome,
            "ocorrencias": 0,
            "valor_total": 0.0,
        })
        return None, "nao_resolvida"

    def registrar_pendencia(self, conta_codigo, conta_nome, valor):
        chave = _codigo_limpo(conta_codigo) or _normalizar(conta_nome)
        pendencia = self.nao_resolvidas.get(chave)
        if pendencia:
            pendencia["ocorrencias"] += 1
            pendencia["valor_total"] += abs(valor or 0)


def resolver_obras(cur):
    """Código do centro de custo -> id da obra."""
    cur.execute("SELECT id, codigo FROM obras")
    return {_codigo_limpo(r["codigo"]) or str(r["codigo"]).strip().upper(): r["id"]
            for r in cur.fetchall()}


def importar_lancamentos(cur, linhas, registro, importacao_id=None, substituir_competencias=True):
    """
    Grava os lançamentos normalizados: soma por competência para atualizar o
    DRE e guarda cada lançamento individual em 'partidas'.

    Com substituir_competencias=True (padrão), cada competência tocada pelo
    arquivo é reconstruída do zero — o relatório do mês é a verdade, e reimportar
    corrige um valor que tinha sido lançado a mais. Sem isso, reimportar o mesmo
    mês duplicaria o detalhe.

    Devolve um resumo com o que entrou e o que ficou pendente de mapeamento.
    """
    resolvedor = ResolvedorDeContas(cur)
    obras_por_codigo = resolver_obras(cur)

    agora = datetime.datetime.now().isoformat()

    celulas = {}          # (obra_id, categoria_id, ano, mes) -> soma
    detalhes = []         # partidas a inserir
    obras_desconhecidas = {}
    ignoradas_sem_data = 0

    for linha in linhas:
        valor = linha.get("valor") or 0.0
        data = linha.get("data")

        if not data:
            ignoradas_sem_data += 1
            continue

        obra_id = obras_por_codigo.get(_codigo_limpo(linha.get("obra_codigo"))
                                       or str(linha.get("obra_codigo") or "").strip().upper())
        if not obra_id:
            chave = str(linha.get("obra_codigo") or "(sem centro de custo)")
            registro_obra = obras_desconhecidas.setdefault(chave, {"ocorrencias": 0, "valor_total": 0.0})
            registro_obra["ocorrencias"] += 1
            registro_obra["valor_total"] += abs(valor)
            continue

        categoria_id, _motivo = resolvedor.resolver(linha.get("conta_codigo"), linha.get("conta_nome"))
        if not categoria_id:
            resolvedor.registrar_pendencia(linha.get("conta_codigo"), linha.get("conta_nome"), valor)
            continue

        chave = (obra_id, categoria_id, data.year, data.month)
        celulas[chave] = celulas.get(chave, 0.0) + abs(valor)

        detalhes.append({
            "obra_id": obra_id,
            "categoria_id": categoria_id,
            "mes": data.month,
            "ano": data.year,
            "data": data.isoformat(),
            "documento": linha.get("documento"),
            "historico": linha.get("historico"),
            "conta_codigo": linha.get("conta_codigo"),
            "conta_nome": linha.get("conta_nome"),
            "valor": abs(valor),
        })

    # O detalhe antigo das competências tocadas sai antes de entrar o novo.
    if substituir_competencias and detalhes:
        competencias = {(d["obra_id"], d["ano"], d["mes"]) for d in detalhes}
        for obra_id, ano, mes in competencias:
            cur.execute(
                "DELETE FROM partidas WHERE obra_id = ? AND ano = ? AND mes = ?",
                (obra_id, ano, mes),
            )

    for d in detalhes:
        cur.execute(
            """
            INSERT INTO partidas
                (obra_id, categoria_id, mes, ano, data, documento, historico,
                 conta_codigo, conta_nome, valor, importacao_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (d["obra_id"], d["categoria_id"], d["mes"], d["ano"], d["data"],
             d["documento"], d["historico"], d["conta_codigo"], d["conta_nome"],
             d["valor"], importacao_id),
        )

    # O total de cada célula passa pelo RegistroImportacao, então continua
    # valendo a proteção do lançamento manual e o desfazer.
    gravados = 0
    for (obra_id, categoria_id, ano, mes), total in celulas.items():
        if registro.gravar_lancamento(obra_id, categoria_id, mes, ano, total, agora):
            gravados += 1

    return {
        "lancamentos_lidos": len(linhas),
        "partidas_gravadas": len(detalhes),
        "celulas_atualizadas": gravados,
        "competencias": sorted({(d["ano"], d["mes"]) for d in detalhes}),
        "obras_tocadas": sorted({d["obra_id"] for d in detalhes}),
        "contas_nao_resolvidas": sorted(
            resolvedor.nao_resolvidas.values(),
            key=lambda p: -p["valor_total"],
        ),
        "obras_desconhecidas": obras_desconhecidas,
        "ignoradas_sem_data": ignoradas_sem_data,
    }


def buscar_partidas(cur, obra_id, categoria_id, ano, mes):
    """O detalhe por trás de uma célula do DRE, para a tela de conferência."""
    cur.execute(
        """
        SELECT data, documento, historico, conta_codigo, conta_nome, valor
        FROM partidas
        WHERE obra_id = ? AND categoria_id = ? AND ano = ? AND mes = ?
        ORDER BY data, id
        """,
        (obra_id, categoria_id, ano, mes),
    )
    return [dict(r) for r in cur.fetchall()]


# ---------------------------------------------------------------------------
# Adaptador do arquivo do Contimatic
# ---------------------------------------------------------------------------

def ler_relatorio_analitico(caminho_arquivo):
    """
    Lê o relatório analítico exportado do Contimatic e devolve os lançamentos
    normalizados (ver o formato no topo do módulo).

    AINDA NÃO IMPLEMENTADO: falta um arquivo de exemplo real para saber em que
    linha começa o cabeçalho, como as colunas se chamam, se o centro de custo
    vem numa coluna ou como um agrupamento acima dos lançamentos, e como o
    débito/crédito aparece. Todo o resto do caminho (resolver conta, somar por
    competência, atualizar o DRE, guardar o detalhe) já está pronto e testado
    em importar_lancamentos.
    """
    raise NotImplementedError(
        "O leitor do relatório do Contimatic depende de um arquivo de exemplo. "
        "Envie um relatório analítico real (.xlsx) de um mês completo."
    )
