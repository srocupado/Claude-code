# Monitor de Medidas Provisórias

Monitora automaticamente as Medidas Provisórias publicadas no Diário Oficial da União, gera uma **Nota Informativa** em DOCX e PDF com análise de impacto produzida por IA, e envia os documentos por e-mail.

---

## Como funciona

```
Planalto.gov.br ──► Busca MPs do dia
       │ (fallback)
Inlabs / DOU XML ──► Extrai texto integral
                          │
                    Claude Sonnet 4.6
                    (análise legislativa)
                          │
                  Gera DOCX + converte PDF
                          │
                   Envia por e-mail (Gmail)
```

1. **Busca** — consulta o índice do Planalto. Se indisponível, usa a API Inlabs (Diário Oficial XML via Imprensa Nacional) como fonte alternativa.
2. **Geração** — envia ementa e texto integral ao Claude Sonnet 4.6, que redige a Nota Informativa com rigor técnico-legislativo.
3. **Documento** — monta o DOCX com cabeçalho institucional (logo, prazos, caixa de atenção) e converte para PDF via LibreOffice.
4. **Envio** — anexa DOCX e PDF ao e-mail e dispara via Gmail SMTP.

---

## Pré-requisitos

| Requisito | Obter em |
|---|---|
| Python 3.12+ | python.org |
| LibreOffice | `sudo apt install libreoffice` |
| Chave Anthropic API | console.anthropic.com |
| Conta Gmail + App Password | myaccount.google.com/apppasswords |
| Conta Inlabs (gratuita) | inlabs.in.gov.br/acessar.php |

---

## Instalação local

```bash
git clone https://github.com/srocupado/Monitor-de-MP.git
cd Monitor-de-MP
pip install -r requirements.txt
cp .env.example .env   # preencha as variáveis abaixo
```

### Variáveis de ambiente (`.env`)

```env
# ── Obrigatórias ──────────────────────────────────────────────
ANTHROPIC_API_KEY=sk-ant-...
GMAIL_USER=seu@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
RECIPIENT_EMAIL=destinatario@email.com

# ── Inlabs / DOU (fallback quando Planalto está fora) ─────────
INLABS_EMAIL=seu@email.com
INLABS_PASSWORD=sua_senha_inlabs

# ── Opcionais ─────────────────────────────────────────────────
NOTIFY_IF_EMPTY=false   # envia e-mail mesmo quando não há MP
SCHEDULE_TIME=08:00     # horário de execução no modo --schedule
```

---

## Uso

```bash
# MPs publicadas hoje
python main.py

# MPs de uma data específica
python main.py --date 2026-04-15

# Modo agendado (roda todos os dias no SCHEDULE_TIME)
python main.py --schedule
```

---

## GitHub Actions

O workflow roda automaticamente **todo dia às 19h BRT (22h UTC)** e pode ser disparado manualmente com uma data específica na aba *Actions* do repositório.

### Configurar secrets

Em **Settings → Secrets and variables → Actions**, adicione:

| Secret | Descrição |
|---|---|
| `ANTHROPIC_API_KEY` | Chave da API Anthropic |
| `GMAIL_USER` | Conta Gmail remetente |
| `GMAIL_APP_PASSWORD` | App Password do Gmail |
| `RECIPIENT_EMAIL` | E-mail destinatário |
| `INLABS_EMAIL` | E-mail cadastrado no Inlabs |
| `INLABS_PASSWORD` | Senha do Inlabs |

> **Opcional:** Em *Variables*, defina `NOTIFY_IF_EMPTY=true` para receber notificação quando não houver MP publicada.

---

## Estrutura do projeto

```
Monitor-de-MP/
├── main.py            # Orquestrador principal
├── fetcher.py         # Busca MPs no Planalto e Inlabs/DOU
├── generator.py       # Chama Claude API e gera o texto da nota
├── docx_writer.py     # Monta o documento Word (.docx)
├── pdf_converter.py   # Converte DOCX → PDF via LibreOffice
├── mailer.py          # Envia e-mail com anexos via Gmail SMTP
├── config.py          # Lê variáveis de ambiente
├── podemos_logo.png   # Logo institucional (cabeçalho do documento)
├── template.docx      # Template base do documento Word
├── requirements.txt
└── .github/
    └── workflows/
        └── mp_monitor.yml
```

---

## Documento gerado

Cada Nota Informativa contém:

- **Cabeçalho** — nome oficial da MP, ementa, "Nota Informativa" e logo do Podemos
- **Quadro de prazos** — Eficácia, Sobrestamento e prazo de Emendas (calculados automaticamente)
- **Caixa de atenção** — lembrete de envio de emendas pelo Infoleg
- **Objetivos da MP** — barra roxa com título da seção
- **Análise** — resumo e detalhamento das alterações legais gerados pela IA
- **Rodapé** — vigência e assinatura da Assessoria da Liderança do Podemos

---

## Fontes de dados

| Fonte | Uso |
|---|---|
| **Planalto** (planalto.gov.br) | Fonte primária — índice diário de MPs |
| **Inlabs / DOU XML** (inlabs.in.gov.br) | Fallback automático quando Planalto está inacessível |

---

## Dependências principais

| Pacote | Função |
|---|---|
| `anthropic` | Claude API (geração de texto) |
| `python-docx` | Criação do documento Word |
| `requests` + `beautifulsoup4` | Scraping do Planalto e parsing HTML |
| `python-dotenv` | Leitura do `.env` |
| `schedule` | Agendamento local (`--schedule`) |
| LibreOffice (sistema) | Conversão DOCX → PDF |
