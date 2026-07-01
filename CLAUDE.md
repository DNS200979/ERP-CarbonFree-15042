# CarbonFree ERP — Guia para o Claude Code

> Arquivo de contexto do projeto. O agente lê isto no início de cada sessão.
> Mantenha enxuto e atualizado.

## Visão geral

CarbonFree é um **ERP de conformidade com a Lei 15.042/2024** (SBCE — Sistema
Brasileiro de Comércio de Emissões), desenvolvido pelo **Movimento Brasil Verde
(MBV)**. Atende gestores ESG: controle de passivos **CBE**, geração de créditos
**CRVE**, inventários **GEE**, certificados rurais e conformidade do
agronegócio.

O projeto sustenta a **acreditação OVV junto ao Inmetro** (ISO/IEC 17029, ISO
14064-3, ISO 14065, ISO 14066) — isso impõe rigor técnico nas calculadoras e
trilhas de auditoria (memória de cálculo, quebra por gás, Tier, incerteza).

Repositório: `github.com/DNS200979/ERP-CarbonFree-15042`

## Stack

- **Backend:** FastAPI (Python)
- **Banco/Auth:** Supabase (Postgres + Auth)
- **Frontend:** SPA única em `index.html` — Tailwind (via CDN), Lucide Icons, Chart.js
- **Fontes:** Plus Jakarta Sans, Fraunces, JetBrains Mono

## Estrutura / arquivos-chave

- `app/services/motor_ia.py` — motor de cálculo de emissões (funções puras:
  combustível, eletricidade, refrigerante, cadeia, transporte). Fatores
  IPCC / GHG Protocol Brasil.
- `app/api/routes/calculadoras.py` — endpoints atômicos das calculadoras + histórico.
  Quando `salvar=true`, a resposta traz `historico_id` (id da linha gravada em
  `historico_calculos`), usado pelo frontend para anexar evidências ao cálculo.
- `app/api/routes/mrv_mensal.py` — endpoints do MRV mensal
  (`/mrv/setores`, `/mrv/calcular`, `/mrv/fechamentos`, `/mrv/consolidado/{ano}`).
- `app/api/routes/documentos.py` — anexo de evidências (upload/listar/URL
  assinada/remover), vinculado a um cálculo (`historico`) ou fechamento MRV
  (`fechamento`), com escopo opcional a um insumo. Ver seção "Evidências" abaixo.
- `app/services/motor_verificacao.py` — motor de verificação/pré-auditoria
  ISO 14064-3 (materialidade, risco, amostragem, parecer). *(pendente — ver roadmap)*
- `app/api/routes/verificacao.py` — endpoints da verificação
  (`/verificacao/analisar`, `/verificacao/metodologia`). *(pendente — ver roadmap)*
- `app/api/routes/certificados.py` — certificados rurais.
- `app/services/orgaos_ambientais.py` — adapter de dados abertos do IBAMA.
- `app/api/auth.py` — `usuario_autenticado` (valida JWT do Supabase).
- `app/database/client.py` — `get_db_client()` (Supabase com service key) e
  `get_storage_client()` (mesmo cliente, para o Storage de evidências).
- `index.html` — SPA completa.  `mrv_mensal.html` — MRV mensal.

## Evidências / documentos anexados

Upload de documentos de referência (NF-e, laudos, faturas, MTR, certificados de
calibração) como evidência de um cálculo ou fechamento MRV — base da trilha de
evidências para o dossiê de verificação (OVV).

- **Endpoints** (`app/api/routes/documentos.py`, prefix `/api/v1/documentos`):
  `POST /upload` (multipart), `GET /` (listar por alvo), `GET /{id}/url` (URL
  assinada de 5 min para download), `DELETE /{id}` (soft-delete).
- **Storage:** bucket **privado** `evidencias-compliance` (Supabase Storage).
  Todo acesso passa pelo backend com a service key — o browser nunca fala direto
  com o Storage. Chave do objeto: `{usuario_id}/{tipo_alvo}/{alvo_id}/{uuid}_{nome}`.
- **Tabela:** `documentos_evidencia` (linkagem polimórfica: `historico_id` **ou**
  `fechamento_id`, + `insumo_chave` opcional; `removido_em` para soft-delete).
- **Limites:** 10 MB/arquivo; allow-list de mime (PDF, imagem, DOCX/XLSX/XLS, XML,
  TXT); checagem de magic bytes (`_ASSINATURAS_POR_MIME` em `documentos.py` — o
  conteúdo deve bater com o mime declarado). Constantes em `app/config.py`.
- **Autorização:** o dono do alvo é validado na camada FastAPI (a service key
  ignora RLS), mesmo padrão de `historico_calculos`/`fechamentos_mensais`.
- **Infra manual:** bucket + tabela são criados por SQL rodado à mão no Supabase
  (não há tooling de migração) — o script vive no plano de implementação.
- **Frontend:** modal `#doc-modal` + funções `abrirDocumentos`/`enviarDocumento`/
  `carregarDocumentos`/`abrirUrlDocumento`/`removerDocumento` em `index.html`
  (espelham o padrão de upload multipart do import de ECF, `lerECFInventario`).
  Botão de anexo na aba Histórico das calculadoras, no card de resultado e na
  tabela de fechamentos MRV.

## Validação (rodar SEMPRE após editar — não há suite de testes ainda)

- **Python:** `python -m py_compile <arquivo.py>`
- **JS dentro do HTML:** extrair os blocos `<script>` inline (sem `src`) e rodar
  `node --check`. Exemplo de extrator rápido:

  ```bash
  python3 -c "import re;open('_x.js','w').write('\n;\n'.join(re.findall(r'<script(?![^>]*src=)[^>]*>(.*?)</script>',open('index.html').read(),re.S|re.I)))" && node --check _x.js && rm _x.js
  ```

## Convenções

- **Edite arquivos no lugar** e valide cada alteração antes de concluir.
- Idioma de código e UX: **pt-BR** (comentários e mensagens ao usuário).
- **Respostas REST:** nunca remover campos existentes; adicionar campos novos
  sem quebrar os antigos (compatibilidade com SAP/TOTVS e com a SPA).
- Falhas ao salvar histórico **não devem bloquear o cálculo** (falha silenciosa
  com log).

## Paleta de marca (MBV) — usar nos novos componentes

Definida no `tailwind.config` do `index.html`:

- `mbv-dark` #152417 · `mbv-deep` #0c170e · `mbv-surface` #1e3321 · `mbv-border` #2c4630
- `mbv-green` #8cbd41 · `mbv-olive` #b0a94e · `mbv-cream` #f7f6ee · `mbv-lime` #d4e9a8
- `sbce-warn` #d97706 · `sbce-danger` #b91c1c · `sbce-ok` #15803d

## Regras de domínio (críticas — acreditação OVV)

- **Rastreabilidade ISO 14064:** todo resultado de calculadora traz quebra por
  gás (CO₂/CH₄/N₂O), separação do CO₂ **biogênico**, conjunto de **GWP** (AR6
  padrão / AR5), nível **Tier**, incerteza indicativa e `memoria_calculo` passo
  a passo.
- **Verificação em DOIS níveis (não misturar):**
  - *Por fonte* → classificação de **risco** (inerente × controle → distorção
    material). É o bloco `verificacao_fonte` de cada cálculo.
  - *Por inventário* → **parecer** com materialidade (5% padrão) e amostragem.
    Só existe no nível do portfólio, via `/verificacao/analisar`.
    **Nunca emitir parecer sobre fonte isolada** — seria erro metodológico numa
    auditoria OVV.
  - *Imparcialidade (ISO/IEC 17029):* a verificação é asseguramento interno /
    prontidão para auditoria; não substitui o OVV independente, e um OVV não
    verifica inventário que ele mesmo elaborou.
- **Unidades:** fatores de combustão são por **kg** (não tonelada). Atenção a
  conversões — esse é o ponto onde já houve superestimativa de ~1000×.
- **Fatores de eletricidade:** SIN médio por ano (MCTI/SIRENE). Confirmar sempre
  na edição vigente do SIRENE e da Ferramenta do GHG Protocol Brasil.

## Dados públicos brasileiros — limitações conhecidas

- Nenhuma API aceita CPF/CNPJ e devolve todos os campos ambientais.
- CPF é restrito por **LGPD**; CAR/SICAR exige número do CAR ou localização (não
  documento pessoal); **FATMA não existe mais** (IMA-SC desde 2017).
- Automatizável: razão social via **BrasilAPI** (CNPJ), sugestão de atividade
  via **CNAE**, checagem de embargos **IBAMA** via dados abertos por documento.

## Supabase / RLS (gotcha importante)

- O cliente com **anon key** faz `auth.uid()` retornar **NULL** em INSERTs do
  backend. Por isso o backend escreve com **service key**, com o JWT validado na
  camada FastAPI (`usuario_autenticado`) **antes** das operações de banco.
- **Nunca** expor a service key no frontend nem commitar segredos no repositório.

## Pendências / roadmap

Melhorias MRV/Calculadora derivadas do estudo da Lei 15.042 (4 fases):

- ✅ **Fase 1 — Evidências/documentos** (feita): ver seção "Evidências" acima.
- **Fase 2 — Fatores de emissão versionados**: mover os dicts hardcoded
  (`FATORES_*`/`GWP_SETS` em `motor_ia.py`, `SETORES_ETAPA1` em `mrv_mensal.py`)
  para uma tabela `fatores_emissao` no Supabase com `vigencia_inicio/fim` —
  atualizar fator sem deploy e reproduzir cálculo histórico pelo fator da época.
- **Fase 3 — Trilha de auditoria + aprovação**: colunas `status`
  (`rascunho`/`validado`/`aprovado`), `validado_por/em`, `aprovado_por/em` em
  `historico_calculos` e `fechamentos_mensais`, + tabela `eventos_auditoria`.
- **Fase 4 — Motor de verificação + dossiê**: implementar `motor_verificacao.py`
  e `verificacao.py` (parecer com materialidade 5% + amostragem) e exportar um
  dossiê (cálculo + evidências da Fase 1 + trilha da Fase 3) para o OVV.

Outras pendências:

- Visualizador de PDF de inventários (`GET /api/v1/emissoes/{id}/pdf`).
- Login: OAuth Google/Microsoft, convite por e-mail, tela "Sessão encerrada".
- Parecer de inventário na UI (botão no Histórico ou no detalhe da emissão).
  Requer persistir `nivel_tier` e `incerteza_pct` por fonte para alimentar o
  `/verificacao/analisar`.
- Limpeza de objetos órfãos no Storage: apagar um cálculo/fechamento faz
  cascade na linha de `documentos_evidencia`, mas não remove o arquivo do bucket.
