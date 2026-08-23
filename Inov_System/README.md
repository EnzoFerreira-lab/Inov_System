# INOV System — Sistema Contábil por Centro de Custo

Sistema desenvolvido para automatizar o DRE (Demonstração do Resultado) por obra/centro
de custo, replicando fielmente a lógica usada hoje na planilha Excel da contabilidade.

## Modelo de dados

- **Empresas**: clientes da contabilidade (ex: BELA NOVA CONSTRUTORA LTDA)
- **Obras**: centros de custo de cada empresa (ex: OBRA 251 - ESTHER TOWERS)
- **Plano de Contas**: categorias fixas de receita/custo (mesmas da planilha)
- **Lançamentos**: 1 valor por obra + categoria + mês/ano (equivale a uma célula da planilha)
- **Taxas**: percentuais configuráveis (Impostos, IRPJ/CSLL, Adm., Financeiras),
  com vigência — mudar uma taxa não altera meses já fechados

## Cálculo do DRE (dre.py)

```
Receita Bruta Total   = soma das categorias de receita
Custos Total          = soma das categorias de custo
Lucro Bruto            = Receita Bruta Total - Custos Total
(-) Impostos s/Serviço = Receita Bruta Total * taxa vigente
(-) IRPJ e CSLL         = Receita Bruta Total * taxa vigente
(-) Desp. Administrativa = Custos Total * taxa vigente
(-) Desp. Financeira     = Custos Total * taxa vigente
Lucro/Prejuízo Líquido  = Lucro Bruto - as 4 deduções acima
```

Essa lógica foi **validada com dados reais** da planilha `06-2026__DRE_-_CENTRO_DE_CUSTO.xlsx`
(OBRA 251, Jan a Jun/2026) — os valores calculados pelo sistema batem exatamente com os da planilha.

## Como rodar localmente

```bash
pip install -r requirements.txt
python app.py
```

Acesse http://localhost:5000 — login padrão: `admin@inov.com` / `1234` (troque depois).

O banco `database.db` é criado automaticamente na primeira execução, já com o plano de
contas e as taxas padrão cadastrados. O schema é aplicado ao importar o módulo, então
funciona igual servido por WSGI (gunicorn/waitress), não só por `python app.py`.

### Configuração

| Variável | Para que serve |
|---|---|
| `INOV_SECRET_KEY` | Assina o cookie de sessão. **Obrigatória em produção** — sem ela, o sistema sorteia uma chave nova a cada inicialização e todo mundo é deslogado no restart. |
| `INOV_DEBUG=1` | Liga o modo debug do Flask. Só em desenvolvimento: expõe um console Python a quem alcançar a porta. |

### Testes

```bash
python -m unittest discover -s tests -t .
```

51 testes, sem dependência externa (usam `unittest` da biblioteca padrão):

- **`test_calculo_dre.py`** — a matemática do DRE com números conferíveis de cabeça,
  incluindo a vigência das taxas (reajustar hoje não pode alterar mês já fechado).
- **`test_importacao.py`** — preservação de lançamento manual e o desfazer.
- **`test_web.py`** — login, CSRF, todas as telas, exportações e formatação BR.
- **`test_regressao_dados_reais.py`** — trava os números validados de 2026 contra o
  `database.db`. É pulado automaticamente onde o banco não existe. Se uma importação
  mudar legitimamente os dados, confira contra a planilha e regenere os valores com
  `python -m tests.gerar_valores_travados`.

### Backup

O `database.db` **não** é versionado no git — ele guarda a contabilidade real do cliente,
e o histórico do git manteria uma cópia para sempre, mesmo depois de apagada. Para backup,
copie o arquivo (com o sistema parado) ou use `sqlite3 database.db ".backup copia.db"`,
que funciona com o sistema no ar.

## O que já existe nesta versão

- Login (senha com hash, não mais texto puro)
- Empresas e Obras (cadastro)
- Plano de Contas (ativar/desativar categoria)
- Taxas configuráveis com vigência
- Lançamento manual por obra/mês (grade de categorias)
- **Importação direta do arquivo real de DRE da contabilidade** (multi-abas, uma por obra) —
  o sistema identifica sozinho cada obra, cada categoria e os valores de cada mês, sem precisar
  reformatar nada (`dre_import.py`). Testado com o arquivo real de Jun/2026: 53 abas lidas
  (52 obras + Depto Técnico), 17.360 lançamentos importados, apenas a aba "TOTAIS" fica de
  fora por escolha (é redundante com o `/totais` do sistema, que calcula isso ao vivo).
- Importação alternativa via planilha simples (formato: codigo_obra, categoria, mes, ano, valor)
- DRE por obra (mês a mês + acumulado, igual à planilha)
- Totais consolidados (todas as obras)
- **Editar e excluir** empresas e obras (com proteção: não deixa excluir empresa com obras vinculadas)
- **Exportar o DRE para Excel** — por obra ou consolidado, formatado, pronto pra enviar por e-mail
- Períodos agregados da planilha original (ex: "Out a Dez/2025") entram como **colunas do
  próprio DRE**, na mesma ordem da planilha (ver "Anos antigos" abaixo)

## Anos antigos: como a planilha guarda e como o sistema mostra

Na planilha de origem, **cada obra tem detalhe mês a mês de um ano só** — os anos
anteriores vêm num bloco agregado por coluna: `Março a Dez/23 | Jan a Dez/24 |
Jan a Dez/2025 | Janeiro/2026 | ... | Dezembro/2026 | Acumulado`.

Isso tem três consequências que o sistema precisa tratar:

1. **O ano de detalhe varia por obra.** A obra 265 tem 2024; a 277 tem 2025; a 305 tem
   2026. Treze obras não têm nenhum mês — só blocos anuais. Por isso o seletor de ano é
   **por obra**, e a tela abre no ano mais recente em que aquela obra tem lançamento.
2. **Os blocos agregados são colunas do DRE**, à esquerda dos meses, e recebem as mesmas
   quatro deduções, com a alíquota vigente no fim do período (`dre.fim_do_periodo`
   converte `"Março a Dez/23"` em `(2023, 12)`).
3. **Há dois totais**, porque significam coisas diferentes:
   - `Acum. <ano>` — só o ano selecionado.
   - `Total geral` — blocos agregados + ano, que é o que a coluna "Acumulado" da
     planilha mostra. Para a OBRA 251: `Acum. 2026` = R$ 441.557,27 de custo, enquanto
     `Total geral` = R$ 1.468.419,61 — os dois conferidos contra a planilha.

## Interface

Visual sóbrio/contábil: densidade alta, paleta neutra com azul institucional, cantos discretos
e **números tabulares** (todo dígito com a mesma largura, para as colunas de valor alinharem).

- **`templates/base.html`** — layout único de todas as telas internas. Uma tela filha só declara
  `{% extends 'base.html' %}`, o item de menu ativo e os blocos `cabecalho` / `descricao` /
  `acoes` / `conteudo`. Antes, cada template repetia `<head>`, sidebar e bloco de mensagens.
- **Formatação brasileira** — filtros Jinja registrados em `app.py`: `moeda` (`1.234,56`),
  `moeda_curta` (`1,48 mi`), `pct`, `data_br` e `competencia_br` (`2026-06` → `Jun/2026`).
- **Tabela do DRE** — cabeçalho fixo na rolagem vertical, coluna de conta fixa na horizontal,
  coluna de acumulado destacada, grupos/subtotais/deduções com peso visual distinto, zeros em
  cinza claro e um botão para esconder as contas sem movimento no ano.
- **Busca e filtros** no navegador (sem recarregar a página) nas listas de obras, empresas,
  plano de contas e na grade de lançamentos. A busca ignora acento e caixa.
- **Dashboard** com receita/custo em barras e resultado líquido em linha, margens, e ranking
  das melhores e piores obras por resultado do ano.
- `static/css/style.css` é a única folha de estilo — nenhum `<style>` solto nos templates.
- Impressão: `Ctrl+P` em qualquer DRE sai limpo (sem menu nem botões), pronto para PDF.

## Importação do Contimatic (em andamento)

O objetivo é que o DRE passe a ser alimentado e mantido pelos relatórios do Contimatic:
joga o relatório analítico no sistema e cada obra se atualiza sozinha.

`contimatic.py` está partido em duas camadas de propósito:

| Camada | O que faz | Situação |
|---|---|---|
| `ler_relatorio_analitico(caminho)` | Conhece o layout do arquivo e devolve lançamentos normalizados | **Falta o arquivo de exemplo** |
| `importar_lancamentos(...)` | Resolve conta e centro de custo, soma por competência, atualiza o DRE e guarda o detalhe | Pronto, 19 testes |

Um lançamento normalizado é `{obra_codigo, conta_codigo, conta_nome, data, documento,
historico, valor}` — o adaptador só precisa produzir isso.

Decisões já embutidas no miolo:

- **O detalhe é guardado** (tabela `partidas`). No DRE, todo valor mensal é clicável e abre
  os lançamentos que o formaram, com data, documento e histórico, e uma conferência entre a
  soma dos lançamentos e o valor do DRE.
- **A conta nunca é adivinhada.** Casa pelo de-para explícito (`contas_map`), depois pelo
  código do plano de contas, depois pelo nome. O que não casar volta como pendência com
  quantidade e valor — chutar a conta deslocaria valor entre linhas do DRE em silêncio.
- **Reimportar o mês substitui**, não soma: o relatório do mês é a verdade, então cada
  competência tocada é reconstruída do zero. Reimportar sem um lançamento o remove.
- **As proteções valem igual**: passa pelo mesmo `RegistroImportacao`, então lançamento
  manual continua protegido e a importação continua podendo ser desfeita.

## Segurança e integridade dos dados

- **CSRF em todo POST.** Cada formulário carrega um token ligado à sessão e o servidor
  recusa qualquer alteração sem ele. Sem isso, uma página em outro site conseguiria
  disparar ações destrutivas usando a sessão de quem estivesse logado — e excluir uma
  obra apaga todos os lançamentos dela.
- **Nada altera dado por GET.** Ativar/desativar categoria era um link; virou formulário
  com POST. Links que alteram estado são disparados por pré-carregamento do navegador.
- **Chave de sessão fora do código** (`INOV_SECRET_KEY`) e debug desligado por padrão.
- **Importação não sobrescreve correção manual.** Um valor ajustado na tela de Lançar
  Dados fica com `origem='manual'`; a importação preserva esse valor e lista o conflito,
  mostrando os dois lados. Quem importa pode optar explicitamente por deixar a planilha
  prevalecer, marcando uma caixa na tela de envio.
- **Toda importação pode ser desfeita.** Cada valor alterado guarda o estado anterior em
  `importacao_itens`; desfazer devolve tudo ao que era, inclusive a origem `manual`.
  Só a importação mais recente pode ser revertida — desfazer uma antiga por cima de outra
  mais nova ressuscitaria valores já superados.
- **Consolidado por empresa.** `/totais` e `/dashboard` aceitam `empresa_id`. Antes somavam
  as obras de todas as empresas juntas: com um cliente só ninguém percebia, mas o segundo
  cliente tornaria o número errado sem gerar erro nenhum.
- **Erros reais vão para o log.** Antes, qualquer falha ao salvar virava a mesma mensagem
  sobre CNPJ duplicado, escondendo o problema de verdade.

## Próximos passos sugeridos

- Login com permissão por usuário (ex: um usuário só vê certas obras)
- Comparação automática com o ano anterior (como a planilha já mostra)
- Tela para revisar/corrigir categorias criadas automaticamente na importação
  (hoje elas entram como "custo" ou "receita" conforme a seção da planilha, mas
  o código/nome pode precisar de ajuste manual ocasional)
- Nota sobre o Departamento Técnico: hoje ele é importado como se fosse uma "obra" pra não
  perder o dado, mas as 4 taxas (impostos, IRPJ/CSLL etc.) não fazem sentido pra despesa
  administrativa da empresa — vale revisar esse cálculo quando essa aba começar a ter dados
  reais preenchidos (hoje está toda zerada no arquivo de exemplo)

## Estrutura

```
app.py        -> rotas Flask, CSRF e filtros de formatação (moeda, pct, data_br...)
db.py         -> schema do banco + seed do plano de contas e taxas
dre.py        -> motor de cálculo do DRE
dre_import.py -> leitura do arquivo real multi-abas + RegistroImportacao (preserva
                 lançamento manual, guarda estado anterior) e desfazer_importacao
dre_export.py -> geração do Excel do DRE
tests/        -> suíte de testes (unittest, sem dependência externa)
templates/
  base.html     -> layout de todas as telas internas
  _sidebar.html -> menu lateral
  _icons.html   -> macro icon(), ícones em SVG
  _flash.html   -> bloco de mensagens
  <demais>      -> uma tela cada, estendendo base.html
static/       -> style.css (único) e script.js
app_v1_backup.py, templates_v1_backup/ -> versão anterior do protótipo, mantida como referência
```
