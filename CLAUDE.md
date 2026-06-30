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
- `app/services/motor_verificacao.py` — motor de verificação/pré-auditoria
  ISO 14064-3 (materialidade, risco, amostragem, parecer).
- `app/api/routes/verificacao.py` — endpoints da verificação
  (`/verificacao/analisar`, `/verificacao/metodologia`).
- `app/api/routes/certificados.py` — certificados rurais.
- `app/services/orgaos_ambientais.py` — adapter de dados abertos do IBAMA.
- `app/api/auth.py` — `usuario_autenticado` (valida JWT do Supabase).
- `app/database/client.py` — `get_db_client()` (cliente Supabase com service key).
- `index.html` — SPA completa.  `mrv_mensal.html` — MRV mensal.

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

- Visualizador de PDF de inventários (`GET /api/v1/emissoes/{id}/pdf`).
- Login: OAuth Google/Microsoft, convite por e-mail, tela "Sessão encerrada".
- Parecer de inventário na UI (botão no Histórico ou no detalhe da emissão).
  Requer persistir `nivel_tier` e `incerteza_pct` por fonte para alimentar o
  `/verificacao/analisar`.
