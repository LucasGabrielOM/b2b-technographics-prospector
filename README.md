# B2B Technographics Prospector

## Painel de leads

Abra `/dashboard` na URL da API para visualizar todos os leads persistidos pelo n8n. O painel permite filtrar por temperatura e status, pesquisar, editar os contatos, abrir o site da empresa, preparar WhatsApp/e-mail e marcar ou reabrir leads enviados. Painel, API e n8n usam a mesma tabela PostgreSQL; as alterações são sincronizadas imediatamente.

O acesso ao painel é protegido por login. O portal demo fica em `/login` e redireciona para o dashboard após autenticação. No ambiente local, o padrão é `admin / demo1234`; no Render, ajuste `PORTAL_USERNAME`, `PORTAL_PASSWORD` e `PORTAL_SECRET`.

## Prospecção automática completa

O workflow **B2B 03 - Prospecção automática completa** não recebe uma lista de domínios. Ele recebe apenas cidade, estado, segmentos e limite, descobre empresas com site na região, visita os sites, encontra CRM e canais de contato, pesquisa sinais públicos de reclamações e vagas, pontua os leads e prepara mensagens de WhatsApp ou e-mail.

```text
Agenda diária -> região/segmentos -> descobrir empresas e sites -> analisar CRM e contato
              -> pesquisar reclamações -> pontuar -> preparar mensagem
```

Para testar gratuitamente, importe `n8n/workflows/03_hot_leads.json` e execute **Testar agora**. O padrão agora pesquisa Santa Catarina inteira em lotes pequenos por cidade. Esse fluxo prioriza estabilidade: busca empresas com site, detecta CRM, encontra contato público, remove duplicados e retorna leads quentes ou mornos qualificados com score mínimo 45. A busca pública profunda de reclamações e vagas fica opcional por API, porque rodar isso dentro da chamada principal do n8n pode causar timeout. Para uso comercial estável com pesquisa profunda, configure `SERPER_API_KEY` no Render.

Se quiser aprofundar a qualificação com IA, configure `DEEPSEEK_API_KEY`. Nesse modo, o backend usa a DeepSeek como camada de leitura dos sinais públicos para resumir a oportunidade e reforçar o score.

O sistema não precisa de OpenAI para descobrir leads. O disparo automático, porém, exige uma conta real de WhatsApp Business Cloud API/provedor ou SMTP. Sem essa credencial, o último nó deixa a mensagem e o link prontos, mas não finge que enviou.

Por padrão, `POST /api/v1/prospect/run` usa `only_new=true`: consulta um conjunto até cinco vezes maior que o lote solicitado, compara os domínios com o PostgreSQL e devolve apenas empresas ainda não cadastradas. A restrição única da coluna `domain` também impede duplicação física no banco. Use `only_new=false` somente para reprocessar ou atualizar leads existentes.

MVP de prospecção B2B com **n8n + Python**, detecção multipágina de CRM por sinais públicos, enriquecimento opcional, score transparente de oportunidade, geração de abordagem e aprovação humana obrigatória antes do envio.

## Arquitetura

```text
n8n (orquestração) -> FastAPI (regras e integrações) -> PostgreSQL
                              |-> sites públicos / technographics
                              |-> Hunter (opcional)
                              |-> OpenAI (opcional; modo demo sem chave)
                              `-> webhook de outreach (bloqueado por padrão)
```

## Subir o projeto

Pré-requisitos: Docker Desktop e Docker Compose.

1. Copie `.env.example` para `.env`.
2. Troque senhas e `N8N_ENCRYPTION_KEY`.
3. Execute:

```bash
docker compose up -d --build
docker compose exec n8n n8n import:workflow --separate --input=/workflows
```

- n8n: http://localhost:5678
- API/Swagger: http://localhost:8000/docs
- Saúde: http://localhost:8000/health

Sem `OPENAI_API_KEY`, os rascunhos usam um gerador determinístico para permitir o teste completo. Sem `DEEPSEEK_API_KEY`, a qualificação profunda usa heurística local. Sem `HUNTER_API_KEY`, o contato pode ser preenchido manualmente pela API. O envio só funciona quando o lead está `approved`, `OUTREACH_ENABLED=true` e `OUTREACH_WEBHOOK_URL` está configurado.

Para habilitar o portal de login em produção, configure:

- `PORTAL_USERNAME`
- `PORTAL_PASSWORD`
- `PORTAL_SECRET`
- `PORTAL_SESSION_DAYS`
- `PORTAL_COOKIE_SECURE`

O runtime Python está fixado na série 3.12 por `python-api/.python-version`, inclusive para deploys nativos no Render.

## Primeiro teste

1. Abra o workflow **B2B 01 - Descoberta de technographics**.
2. Edite o nó **Definir domínios** com domínios que você tem permissão para pesquisar.
3. Execute o workflow.
4. Consulte `GET /api/v1/leads` no Swagger.
5. Enriqueça (`POST /{id}/enrich`) ou preencha o contato (`PATCH /{id}`).
6. Gere (`POST /{id}/generate`), revise e aprove (`POST /{id}/approve`).
7. Configure um provedor somente depois de validar a lista de supressão e os textos.

## Estados do pipeline

`discovered -> enriched -> drafted -> approved -> sent`

Qualquer lead pode ir para `suppressed`; nesse estado a geração e o envio ficam impedidos. Aprovação exige rascunho e e-mail. Envio exige aprovação e duas configurações explícitas.

## Priorização de leads

O detector visita a página inicial e até quatro páginas públicas relacionadas a contato, orçamento, atendimento ou sobre. Ele procura assinaturas de CRM e e-mails publicados pela própria empresa. O score é explicável e vai de 0 a 100:

- CRM detectado: 35 ou 50 pontos, conforme a confiança;
- evidência em páginas adicionais: até 20 pontos;
- e-mail profissional público: 20 pontos;
- empresa e setor identificados: 5 pontos cada;
- dor pública e tipo de oportunidade: reforço adicional de score quando há reclamações, vagas ou sinais de suporte/CRM.

Temperaturas: `hot` a partir de 65, `warm` a partir de 40 e `cold` abaixo disso. O workflow **B2B 03 - Descobrir e priorizar leads quentes** reúne todo o teste inicial: recebe os domínios, executa a descoberta, calcula o score e mostra somente os leads quentes. Para testar no n8n, basta importar esse único workflow. O score prioriza revisão; ele não autoriza envio automático.

O último nó do workflow 03 prepara uma abordagem e cria links de WhatsApp ou e-mail. O envio é manual e permanece com status `aguardando revisão manual`, evitando disparos acidentais durante os testes.

## Integrações e extensões

- `app/services.py`: assinaturas de Bitrix24, HubSpot, Salesforce, RD Station e Pipedrive.
- Hunter: adaptador de busca de e-mail corporativo.
- OpenAI: geração factual pelo endpoint Responses; padrão configurável em `OPENAI_MODEL`.
- Outreach: webhook genérico compatível com um segundo workflow n8n, Smartlead, Instantly ou serviço próprio.
- BuiltWith/Wappalyzer: próximos adaptadores recomendados para aumentar cobertura e confiança.

## LGPD e entregabilidade

Use apenas dados profissionais necessários e com finalidade documentada. Registre fonte e evidência, ofereça opt-out simples, mantenha lista de supressão, aplique limites de volume e não raspe áreas autenticadas ou que proíbam automação. Antes de produção, valide base legal, política de privacidade, retenção e atendimento aos direitos do titular com assessoria jurídica. Não automatize LinkedIn/Indeed diretamente; use APIs ou fontes autorizadas.

## Desenvolvimento e testes

```bash
cd python-api
python -m venv .venv
# Windows: .venv\\Scripts\\activate
pip install -r requirements-dev.txt
pytest -q
```

## Próximos passos para produção

1. Migrações com Alembic e autenticação na API.
2. Rate limiting, retry com backoff e fila (Redis/Celery).
3. Adaptadores BuiltWith/Wappalyzer, verificação de e-mail e deduplicação por empresa.
4. Painel de revisão ou notificações Slack/Teams/Telegram.
5. Métricas de origem, confiança, aprovação, resposta e opt-out.
6. Testes de prompts com amostra real antes de habilitar envio.
