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

148 testes, sem dependência externa (usam `unittest` da biblioteca padrão):

- **`test_calculo_dre.py`** — a matemática do DRE com números conferíveis de cabeça,
  incluindo a vigência das taxas (reajustar hoje não pode alterar mês já fechado) e os
  períodos agregados.
- **`test_importacao.py`** — preservação de lançamento manual e o desfazer.
- **`test_contimatic.py`** — leitura do relatório do Contimatic (monta o arquivo de
  exemplo linha a linha), conferência de totais, pendências e sugestões.
- **`test_permissoes.py`** — o que o funcionário pode e o que é da administradora.
- **`test_ajustes.py`** — Depto Técnico sem taxas, comparativo anual, mesclagem de
  categorias e backup.
- **`test_web.py`** — login, CSRF, todas as telas, exportações e formatação BR.
- **`test_regressao_dados_reais.py`** — trava os números validados de 2026 contra o
  `database.db`. É pulado automaticamente onde o banco não existe. Se uma importação
  mudar legitimamente os dados, confira contra a planilha e regenere os valores com
  `python -m tests.gerar_valores_travados`.

### Backup

O `database.db` **não** é versionado no git — ele guarda a contabilidade real do cliente,
e o histórico do git manteria uma cópia para sempre, mesmo depois de apagada.

O sistema gera **uma cópia por dia**, automaticamente, no primeiro acesso do dia
(`backup.backup_diario`, chamado na inicialização). As 20 mais recentes ficam em
`backups/`; as anteriores saem sozinhas. A administradora vê a lista em **Backup**, gera
uma cópia na hora e baixa qualquer uma.

A cópia usa a API de backup do SQLite, não `shutil.copy`: ela sai consistente mesmo se
alguém estiver gravando no meio.

```bash
python -m backup            # gera uma cópia agora
python -m backup --listar   # mostra as cópias existentes
```

**As cópias ficam na mesma máquina que o banco.** Isso protege contra erro de operação e
corrupção do arquivo, não contra perda do computador — baixe uma cópia de tempos em tempos
e guarde fora dali. Para restaurar: pare o sistema, troque o `database.db` pela cópia e suba.

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

## Importação do Contimatic

O DRE passa a ser alimentado pelo **DRE por centro de custo** exportado do Contimatic.
O relatório vem como um bloco em cascata, uma seção por obra:

```
OBRA: 318 VISTA BROOKLIN - ADOLPHO
  Receitas Brutas
    Servicos prestados - mercado interno - 25      217.704,60
  Receitas Brutas Total...                         217.704,60
  Deduções
    INSS S/ FATURAMENTO - 544                       (5.878,02)
  = Receita Líquida                                211.826,58
  Custos
    Salarios e Ordenados - 311                     (28.270,19)
  Custos Total...                                  (95.526,97)
  = Lucro Bruto                                    116.299,61
```

`contimatic.py` está partido em duas camadas: `ler_relatorio()` conhece o layout,
`importar_linhas()` grava. Só a primeira depende do formato do arquivo.

### O relatório não traz a competência

Não há nada no arquivo que diga a que mês os valores pertencem. **O mês e o ano são
escolhidos na tela de envio**, e é isso que decide onde os valores são gravados. Sem eles
a importação é recusada.

### Conferência antes de gravar

O relatório declara os próprios totais (`Custos Total...`). O sistema soma as contas que
leu e compara. Se divergir em qualquer seção, **nada é gravado** — a leitura errou em
algum lugar, e é melhor saber disso antes do número errado entrar no DRE.

### A conta nunca é adivinhada

Uma conta no lugar errado desloca dinheiro entre linhas do DRE sem gerar erro nenhum.
A resolução vai por de-para explícito (`contas_map`), código do plano de contas e nome
exato. O que não casar **não entra** e vira pendência em **Contas do Contimatic**, com o
valor envolvido e uma sugestão para conferir. Decidido uma vez, o sistema lembra.

Duas travas no sugeridor, vindas de casos reais do relatório:

- **Prefixo** — o Contimatic detalha o que o plano resume (`Servicos prestados - mercado
  interno` contra `Serviços prestados`) e a coluna estreita corta o nome no fim
  (`Locação de Maqs, Ferramentas e Equipamen`). Nos dois casos um nome começa o outro.
- **Nunca de despesa para receita** — `Serviços prestados por terceiros` é despesa e quase
  casa por prefixo com a receita `Serviços prestados`. Sugerir isso viraria gasto em
  faturamento.

Contas **sem código** (a coluna corta o código junto) recebem o nome normalizado como
chave. Sem isso elas não virariam nem pendência e ficariam fora do DRE para sempre.

### Deduções e Despesas Administrativas ficam de fora por padrão

O relatório traz `INSS S/ FATURAMENTO` e `Serviços prestados por terceiros` como valores
já contabilizados. O DRE do sistema **calcula** imposto (13,15%) e despesa administrativa
(5,56%) por alíquota. Importar os dois cobraria a mesma despesa duas vezes.

Por isso essas seções não entram sozinhas: aparecem como pendência, e quem importa decide
uma vez — apontar uma categoria (o de-para vale para qualquer seção) ou marcar para ignorar.

### Reimportar substitui

O relatório do mês é a verdade: cada competência tocada é reconstruída do zero, detalhe
incluído. Reimportar sem uma conta a remove daquele mês. As proteções de sempre continuam
valendo — lançamento manual preservado e importação reversível.

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

## Usuários e permissões

O corte é **por ação, não por obra**: todo funcionário enxerga e opera todas as obras.
O que fica reservado à administradora são as ações que apagam dado ou mudam a regra do
jogo para todo mundo.

| Ação | Funcionário | Administradora |
|---|:---:|:---:|
| Ver DRE, totais e dashboard | ✓ | ✓ |
| Lançar valores | ✓ | ✓ |
| Importar planilha e desfazer importação | ✓ | ✓ |
| Exportar para Excel | ✓ | ✓ |
| Cadastrar e editar empresa e obra | ✓ | ✓ |
| Criar, editar, ativar e desativar categoria | ✓ | ✓ |
| Consultar as taxas | ✓ | ✓ |
| **Excluir empresa ou obra** | — | ✓ |
| **Criar vigência de taxa** | — | ✓ |
| **Mesclar duas categorias** | — | ✓ |
| **Trocar receita/custo de conta já usada** | — | ✓ |
| **Administrar usuários e backup** | — | ✓ |

Cada um troca a própria senha em "Minha conta". A administradora cria usuários, redefine
senha, promove e desativa acesso — desativar preserva o histórico. O sistema não permite
ficar sem nenhuma administradora ativa, nem que alguém desative o próprio acesso.

A tabela `usuarios` ganhou `papel`, `ativo` e `criado_em` por migração (`_migrar_usuarios`),
que também promove o usuário mais antigo se o banco não tiver nenhum admin — sem isso, um
banco antigo subiria com todo mundo trancado do lado de fora.

## Departamento Técnico

Obras têm o campo `aplica_taxas`. As 4 taxas do DRE foram pensadas para uma obra que
fatura; o Departamento Técnico é despesa administrativa da própria empresa, e cobrar dele
uma taxa administrativa calculada sobre o próprio custo administrativo não faz sentido.
Ele entra com `aplica_taxas = 0` — na importação e por migração — e o DRE dele sai com as
quatro deduções zeradas. A tela de editar obra permite marcar outros centros de custo assim.

## Revisão do plano de contas

A tela de Plano de Contas destaca as categorias **criadas automaticamente na importação**
(coluna `origem`), mostra quantos lançamentos cada conta tem e permite editar nome, código
e tipo.

Ela também aponta **contas com nomes muito parecidos**. A importação reconhece diferença de
acento e caixa, mas não de abreviação: "Seguro Riscos Execução de Serv. Trab." e "Seguro
Riscos Execução de Serviços" entram como duas contas e dividem o valor em duas linhas do
DRE. Mesclar move lançamentos, períodos históricos, partidas e o de-para para a conta
mantida, somando onde a competência coincide — sem isso a restrição de unicidade barraria
a operação e o valor se perderia em silêncio. Não tem desfazer, por isso é da administradora.

## Próximos passos sugeridos

- Limpeza da pasta `uploads/`, que hoje guarda todo arquivo importado para sempre

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
