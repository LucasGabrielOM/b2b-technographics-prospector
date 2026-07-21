# B2B Technographics Prospector

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

Sem `OPENAI_API_KEY`, os rascunhos usam um gerador determinístico para permitir o teste completo. Sem `HUNTER_API_KEY`, o contato pode ser preenchido manualmente pela API. O envio só funciona quando o lead está `approved`, `OUTREACH_ENABLED=true` e `OUTREACH_WEBHOOK_URL` está configurado.

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
- empresa e setor identificados: 5 pontos cada.

Temperaturas: `hot` a partir de 70, `warm` a partir de 45 e `cold` abaixo disso. Consulte `GET /api/v1/leads/hot` ou importe o workflow **B2B 03 - Leads quentes priorizados**. O score prioriza revisão; ele não autoriza envio automático.

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
