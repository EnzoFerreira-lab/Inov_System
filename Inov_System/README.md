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
contas e as taxas padrão cadastrados.

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
- Períodos históricos agregados da planilha original (ex: "Out a Dez/2025") são importados e
  mostrados numa seção própria em cada obra, sem se misturar aos meses individuais

## Próximos passos sugeridos

- Deixar a interface mais polida visualmente (hoje é funcional, mas simples)
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
app.py        -> rotas Flask
db.py         -> schema do banco + seed do plano de contas e taxas
dre.py        -> motor de cálculo do DRE
templates/    -> telas (Jinja2)
static/       -> CSS e JS
app_v1_backup.py, templates_v1_backup/ -> versão anterior do protótipo, mantida como referência
```
