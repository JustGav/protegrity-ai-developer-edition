# Banking Portal Chatbot — Protegrity Dual-Gate Demo

> **Project v1.3** · Protegrity Developer Edition v1.1.1  
> Guardrail · Discover · Protect · Unprotect

A secure AI-powered banking demo that processes sensitive customer data through
Protegrity's **dual-gate architecture** — ensuring PII is **never exposed** to an
LLM in clear text. The project ships two complementary applications:

| App | Port | Audience | Purpose |
|---|---|---|---|
| **TechnicalApp** | 5002 | Engineers / Demos | Configurable orchestrator explorer — switch LLM, orchestrator, data sources, Protegrity roles live |
| **BusinessCustomerApp** | 5003 | End Customers | Self-service banking portal — dashboard, account data, AI chat assistant |
| **Kuzu Explorer** | 8000 | Engineers / Demos | Graph database browser GUI — explore the Kuzu knowledge graph visually |
| **pgweb** | 8081 | Engineers / Demos | PostgreSQL browser GUI — view all 4 banking tables (customers, accounts, credit\_cards, transactions) |
| **ChromaDB Viewer** | 8501 | Engineers / Demos | Streamlit browser — inspect ChromaDB documents and run semantic search queries (auto-started by `start.sh`) |
| **PostgreSQL** | 5432 | Internal (Docker) | Relational banking data store — customer records, accounts, transactions |

Both apps share the same orchestration layer, Protegrity services, and protected
customer dataset (`customers_protected.json`).

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Prerequisites](#prerequisites)
3. [Installation](#installation)
4. [Configuration](#configuration)
5. [Running the Apps](#running-the-apps)
   - [Docker (recommended)](#docker-recommended)
   - [Local Python](#local-python)
6. [Docker Deployment](#docker-deployment)
7. [Running Tests](#running-tests)
8. [Architecture](#architecture)
9. [Project Structure](#project-structure)
10. [Orchestrators & Data Sources](#orchestrators--data-sources)
11. [Users & Roles](#users--roles)
12. [Developer Edition — Limitations & Constraints](#developer-edition--limitations--constraints)
13. [Further Reading](#further-reading)

---

## Quick Start

### Docker (recommended)

```bash
# 0. Ensure Docker is installed (see Prerequisites below)
docker --version          # must show Docker ≥ 20.x
docker compose version    # must show ≥ 2.30

# 1. Clone and enter the project
git clone https://github.com/calexcham/protegrity-developer-edition.git
cd protegrity-developer-edition/community-solutions/Orchestrators-BankingPortalChatbot

# 2. Install Protegrity Developer Edition containers (first time only)
bash scripts/setup_protegrity.sh

# 3. Configure environment
cp .env.example .env   # edit with your API keys

# 4. Start everything — checks Protegrity, builds images, starts both apps
./start.sh
```

Both apps are available immediately:
- **TechnicalApp** → http://localhost:5002/tech/login
- **BusinessCustomerApp** → http://localhost:5003/bank/login
- **Kuzu Explorer** → http://localhost:8000
- **pgweb (PostgreSQL)** → http://localhost:8081
- **ChromaDB Viewer** → http://localhost:8501 (auto-started by `start.sh`)

### Local Python (no Docker for apps)

```bash
# 1. Install Protegrity containers + Python SDK
bash scripts/setup_protegrity.sh

# 2. Build the Python environment (creates .venv/, installs deps, bootstraps .env)
bash scripts/setup_env.sh          # venv
# — or —
bash scripts/setup_env.sh --conda banking-portal  # conda

# 3. Fill in your API keys
#    (setup_env.sh already created .env from .env.example)
#    edit .env

# 4. Activate and start both apps
source .venv/bin/activate          # or: conda activate banking-portal
bash scripts/start_apps.sh
```

---

## Prerequisites

- **Docker** + **Docker Compose ≥ 2.30** — **required** for both Protegrity services and the app containers
  > `start.sh` will fail with *"Docker is not installed"* if `docker` is not on `PATH`.
  >
  > **Install Docker Engine (Linux):**
  > ```bash
  > # Ubuntu/Debian — official convenience script
  > curl -fsSL https://get.docker.com | sudo sh
  >
  > # Add your user to the docker group (avoids permission errors)
  > sudo usermod -aG docker $USER && newgrp docker
  >
  > # Verify
  > docker --version && docker compose version
  > ```
  >
  > **macOS / Windows:** Install [Docker Desktop](https://docs.docker.com/get-docker/).

- **Python 3.12.11+ or 3.13** (required by `protegrity-developer-python >= 1.1.0`)
  > **Ubuntu 24.04 (noble):** The system Python 3.12.3 is too old and deadsnakes
  > does not ship a newer 3.12.x for noble. Install **Python 3.13** instead:
  > ```bash
  > sudo add-apt-repository ppa:deadsnakes/ppa
  > sudo apt-get update && sudo apt-get install -y python3.13 python3.13-venv
  > bash scripts/setup_env.sh --python python3.13
  > ```
  > `setup_protegrity.sh` will attempt this automatically.
- **Git**
- **LLM API keys** — at least one of:
  - [OpenAI](https://platform.openai.com/) (`OPENAI_API_KEY`)
  - [Anthropic](https://console.anthropic.com/) (`ANTHROPIC_API_KEY`)
  - [Groq](https://console.groq.com/) (`GROQ_API_KEY`)

### Protegrity Developer Edition

Sign up for a free account at [protegrity.com/developers/dev-edition-api](https://www.protegrity.com/developers/dev-edition-api).
You will receive credentials by email:

| Credential | Environment Variable |
|---|---|
| Email | `DEV_EDITION_EMAIL` |
| Password | `DEV_EDITION_PASSWORD` |
| API Key | `DEV_EDITION_API_KEY` |

> **Note:** See [Developer Edition — Limitations & Constraints](#developer-edition--limitations--constraints)
> for rate limits, session expiry, and functional scope.

---

## Installation

### Step 1 — Install Protegrity Developer Edition

The setup script checks for and installs both the **Docker containers** (Data Discovery + Semantic Guardrail) and the **Python SDK** (`protegrity-developer-python`):

```bash
# Check what's installed
bash scripts/setup_protegrity.sh --check

# Install missing components automatically
bash scripts/setup_protegrity.sh
```

**What it does:**

| Component | How it's installed |
|---|---|
| Protegrity Docker containers | Clones [protegrity-developer-edition](https://github.com/Protegrity-Developer-Edition/protegrity-developer-edition), runs `docker compose up -d` |
| Python SDK | `pip install protegrity-developer-python` (falls back to cloning [protegrity-developer-python](https://github.com/Protegrity-Developer-Edition/protegrity-developer-python) and building from source) |

**Manual installation** (if you prefer):

```bash
# 1. Docker containers
git clone https://github.com/Protegrity-Developer-Edition/protegrity-developer-edition.git
cd protegrity-developer-edition
docker compose up -d
cd ..

# 2. Python SDK
pip install protegrity-developer-python
```

After installation, the following services should be running:

| Service | Container | Port | Purpose |
|---|---|---|---|
| Data Discovery | `classification_service` | 8580 | PII classification & tokenization |
| Semantic Guardrail | `semantic_guardrail` | 8581 | Malicious prompt detection & risk scoring |
| Pattern Provider | `pattern_provider` | — | Classification patterns |
| Context Provider | `context_provider` | — | Classification context |

### Step 2 — Build the Python environment

Use the setup script — it creates an isolated environment, validates the Python
version (≥ 3.12.11, required by the Protegrity SDK), installs all dependencies,
and bootstraps `.env` if it does not yet exist.

**venv** (recommended for most users):

```bash
bash scripts/setup_env.sh                 # creates .venv/ in the project root
```

**conda** (if you use Anaconda / Miniconda):

```bash
bash scripts/setup_env.sh --conda banking-portal
```

**Custom Python interpreter or venv path:**

```bash
bash scripts/setup_env.sh --python /usr/local/bin/python3.13
bash scripts/setup_env.sh --venv ~/envs/banking-portal
```

**Check an existing environment without modifying it:**

```bash
bash scripts/setup_env.sh --check
```

After the script finishes, activate the environment and start the apps:

```bash
# venv
source .venv/bin/activate
bash scripts/start_apps.sh

# conda
conda activate banking-portal
bash scripts/start_apps.sh
```

> **Manual install** (if you prefer not to use the script):
> ```bash
> python3 -m venv .venv && source .venv/bin/activate
> pip install -r config/requirements.txt
> ```

### Protegrity Python SDK

Included in `config/requirements.txt` (`protegrity-developer-python>=1.1.1`):
- `find_and_protect()` — PII discovery + tokenization (Gate 1)
- `find_and_unprotect()` — detokenization (Gate 2)

---

## Configuration

### Environment Variables (`.env`)

```env
# Protegrity Developer Edition
DEV_EDITION_EMAIL=your-email@company.com
DEV_EDITION_PASSWORD=your-password
DEV_EDITION_API_KEY=your-api-key

# LLM API Keys (at least one required)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
GROQ_API_KEY=gsk_...

# Protegrity feature toggles (both enabled by default)
GUARDRAIL_ENABLED=true
DISCOVERY_ENABLED=true

# Protegrity service URLs (defaults)
CLASSIFY_URL=http://localhost:8580/pty/data-discovery/v1.1/classify
SGR_URL=http://localhost:8581/pty/semantic-guardrail/v1.1/conversations/messages/scan
SGR_PROCESSOR=financial

# App ports (defaults)
TECH_PORT=5002
BUSINESS_PORT=5003
```

### TechnicalApp Runtime Settings (UI)

| Setting | Options | Default |
|---|---|---|
| Orchestrator | direct, langgraph, crewai, llamaindex | direct |
| LLM Provider | openai, anthropic, groq | openai |
| Data Sources | Postgres, RAG, Knowledge Graph | Postgres only |
| Semantic Guardrail | on / off | on |
| Data Discovery | on / off | on |
| Protegrity User | superuser, Marketing, Finance, Support | superuser |
| Show Trace | on / off | on |

---

## Running the Apps

### Docker (recommended)

```bash
./start.sh              # start everything (checks Protegrity first)
./start.sh --status     # show running containers and health
./start.sh --logs       # stream live logs from both apps
./start.sh --stop       # stop app containers (leaves Protegrity running)
./start.sh --restart    # rebuild and restart app containers
```

### Local Python

```bash
# Start both apps (cross-platform, macOS + Linux)
bash scripts/start_apps.sh

# Or start individually
python3 TechnicalApp/run.py        # → http://localhost:5002
python3 BusinessCustomerApp/run.py # → http://localhost:5003
```

**Full URLs:**

| App | URL |
|---|---|
| **TechnicalApp** | `http://localhost:5002/tech/login` → `http://localhost:5002/tech/dashboard` |
| **BusinessCustomerApp** | `http://localhost:5003/bank/login` → `http://localhost:5003/bank/dashboard` |
| **Kuzu Explorer** | `http://localhost:8000` (Docker only — read-only graph browser) |
| **pgweb** | `http://localhost:8081` (Docker only — PostgreSQL browser, all 4 tables) |
| **ChromaDB Viewer** | `http://localhost:8501` (auto-started by `start.sh` — overview, browse, search) |

> **Tip:** If ports are already in use from a previous run, the `start_apps.sh` script
> cleans them automatically. To do it manually: `lsof -ti tcp:5002,5003 | xargs kill -9`

---

## Docker Deployment

Both apps run as Docker containers inside Protegrity's own `protegrity-network`,
so they reach the Protegrity services via internal Docker hostnames — no `localhost`
references needed inside the containers.

### Architecture

```
protegrity-network (external — created by Protegrity Developer Edition)
 │
 ├── classification_service:8050   (Protegrity Data Discovery)
 ├── semantic_guardrail:8001        (Protegrity Semantic Guardrail)
 ├── pattern_provider               (Protegrity Pattern Provider)
 ├── context_provider               (Protegrity Context Provider)
 │
 ├── banking_postgres → host:5432   (PostgreSQL — banking data store)
 ├── banking_pgweb   → host:8081   (pgweb — PostgreSQL browser GUI)
 ├── technical_app   → host:5002   (TechnicalApp — admin/demo portal)
 ├── business_app    → host:5003   (BusinessCustomerApp — customer portal)
 └── kuzu_explorer   → host:8000   (Kuzu Explorer — graph browser GUI, read-only)
```

### How it works

| Step | What happens |
|---|---|
| `./start.sh` | Checks Docker is running |
| | Checks if Protegrity containers are active (≥ 3 of 4 services) |
| | If not active, starts them from `.protegrity-install/` |
| | Builds the shared `banking-portal-app` image (single `Dockerfile`) |
| | Starts all containers, joined to `protegrity-network` |
| Container startup | `docker/entrypoint.sh` polls `classification_service:8050` for up to 120s |
| | `technical-app` seeds PostgreSQL and KuzuDB if empty or incomplete |
| | `business-app` and `kuzu-explorer` wait for `technical-app` to be healthy |
| | If Protegrity is not reachable after 120s, apps start in degraded mode |

### URL overrides inside Docker

The `.env` file uses `localhost` addresses for local development. When running in
Docker, these are automatically overridden with internal hostnames:

| Variable | `.env` (local) | Docker (compose override) |
|---|---|---|
| `PROTEGRITY_HOST` | `http://localhost:8580` | `http://classification_service:8050` |
| `CLASSIFY_URL` | `http://localhost:8580/...` | `http://classification_service:8050/...` |
| `DETOKENIZE_URL` | `http://localhost:8580/...` | `http://classification_service:8050/...` |
| `SGR_URL` | `http://localhost:8581/...` | `http://semantic_guardrail:8001/...` |

### Persistent volumes

| Volume / bind mount | Container path | Purpose |
|---|---|---|
| `./TechnicalApp/chat_history_tech` | `/app/TechnicalApp/chat_history_tech` | Chat history (survives restarts) |
| `./BusinessCustomerApp/chat_history` | `/app/BusinessCustomerApp/chat_history` | Chat history (survives restarts) |
| `kuzu_data` (named volume) | `/app/kuzu_data` / `/database` | Kuzu graph DB — seeded by `technical-app`; read-only for `business-app` and `kuzu-explorer` |
| `postgres_data` (named volume) | `/var/lib/postgresql/data` | PostgreSQL data directory (survives restarts) |

### Environment variables for Docker

All variables from `.env` are passed through. Additional Docker-specific variables:

| Variable | Default | Purpose |
|---|---|---|
| `FLASK_DEBUG` | `false` | Enable Flask debug mode (set `true` for development only) |
| `PTY_WAIT_TIMEOUT` | `120` | Seconds to wait for Protegrity before starting in degraded mode |
| `KUZU_READ_ONLY` | `true` | Opens KuzuDB in read-only mode for Flask (seeding runs in write mode before Flask starts) |
| `FLASK_SECRET_KEY` | (built-in default) | Override Flask session secret per app |

---

## Running Tests

### Unit Tests (pytest)

```bash
# Run all 68 unit tests
python3 -m pytest tests/ -v

# Individual test files
python3 -m pytest tests/test_orchestration.py -v   # orchestration layer
python3 -m pytest tests/test_orchestrators.py -v   # config & gates
python3 -m pytest tests/test_banking_service.py -v # data service
python3 -m pytest tests/test_pii_tags.py -v        # PII tag format
python3 -m pytest tests/test_conversation_history.py -v
```

**68 unit tests** across 5 files — all run without live Protegrity services or LLM APIs.

### TechnicalApp Integration Tests

```bash
# App must be running on port 5002
python3 tests/test_app_integration.py --suite quick       # smoke (1 customer)
python3 tests/test_app_integration.py --suite prompts     # all 7 pre-prompts
python3 tests/test_app_integration.py --suite matrix      # all orchestrator×LLM combos
python3 tests/test_app_integration.py --suite customers   # all 15 customers
python3 tests/test_app_integration.py --suite datasources # data source variations
python3 tests/test_app_integration.py --suite roles       # Protegrity user roles
python3 tests/test_app_integration.py --suite full        # 252 tests (7×3×12)
python3 tests/test_app_integration.py --suite all         # all except full
```

### BusinessCustomerApp Integration Tests

```bash
# App must be running on port 5003
python3 tests/test_business_app_integration.py --suite quick   # smoke (auth, summary, chat)
python3 tests/test_business_app_integration.py --suite login   # all 15 customers login+PII check
python3 tests/test_business_app_integration.py --suite chat    # pre-prompts × 3 customers
python3 tests/test_business_app_integration.py --suite full    # all of the above
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Shared Orchestration Layer                       │
│                                                                     │
│   User Query ──▶ GATE 1 ──▶ Orchestrator ──▶ GATE 2 ──▶ Response   │
│                    │              │              │                   │
│                    ├─ Guardrail   ├─ PostgreSQL   └─ Unprotect /     │
│                    ├─ Discover    ├─ RAG search      Redact         │
│                    └─ Protect     ├─ KG query                       │
│                                  └─ LLM call                       │
├─────────────────────────────────────────────────────────────────────┤
│  TechnicalApp (5002)          │  BusinessCustomerApp (5003)         │
│  Engineers / Demos            │  End Customers                      │
│  Configurable orchestrators   │  LangGraph + Protegrity fixed        │
│  All Protegrity roles         │  Dashboard + protected data          │
└─────────────────────────────────────────────────────────────────────┘

Protegrity Services:
  ├─ Data Discovery     (port 8580) — PII classification
  ├─ Semantic Guardrail (port 8581) — malicious prompt detection
  └─ Developer Edition  (cloud)     — tokenize / detokenize PII
```

### Dual-Gate Data Flow

```
customers_protected.json  ──▶  PostgreSQL (pre-tokenized rows)
         │                              │
         ▼                              ▼
    [PERSON]Xk9[/PERSON]    ┌─────────────────────┐
    [EMAIL]abc@x[/EMAIL]    │   Gate 1 (Input)     │  user query → protect PII
    [CREDIT_CARD]...[/]     │   Gate 2 (Output)    │  LLM answer → unprotect
                            └─────────────────────┘
                                       │
                        LLM never sees real PII — only tokens
```

1. **Data at rest**: `customers_protected.json` + PostgreSQL store all PII as Protegrity tokens
2. **Gate 1**: Guardrail scan + tokenize any PII in the user’s message
3. **Orchestrator**: Works entirely with tokens — PostgreSQL, RAG, Knowledge Graph, and LLM all see only tokens
4. **Gate 2**: Final response detokenized by the Protegrity SDK before reaching the user

---

## Project Structure

```
Orchestrators_v1.3/
├── TechnicalApp/
│   ├── app.py                  # Flask app — configurable orchestrator demo
│   └── run.py                  # Launcher (port 5002)
├── BusinessCustomerApp/
│   ├── app.py                  # Flask app — customer portal + AI chat
│   ├── run.py                  # Launcher (port 5003)
│   ├── templates/              # Jinja2 HTML templates
│   └── static/                 # CSS, JS, assets
├── orchestrators/
│   ├── base.py                 # BaseOrchestrator + PipelineResult
│   ├── factory.py              # Orchestrator factory
│   ├── direct_orch.py          # Direct LLM call
│   ├── langgraph_orch.py       # LangGraph state machine
│   ├── crewai_orch.py          # CrewAI multi-agent
│   └── llamaindex_orch.py      # LlamaIndex query engine
├── services/
│   ├── protegrity_guard.py     # Gate 1 & Gate 2 implementation
│   ├── banking_service.py      # Customer data access (protected data)
│   ├── conversation_history.py # Chat history persistence
│   └── protegrity_dev_edition_helper.py  # SDK session management
├── config/
│   ├── orchestration_config.py # LLM, orchestrator, gate settings
│   ├── protegrity_config.py    # Entity mappings, API URLs
│   ├── requirements.txt        # Python dependencies
│   ├── users.json              # TechnicalApp engineer accounts
│   └── customer_users.json     # BusinessCustomerApp customer accounts
├── common/
│   ├── protegrity_gates.py     # Gate 1 / Gate 2 wrappers
│   ├── knowledge_graph.py      # KuzuDB graph queries (read-only in Flask; seeded by entrypoint)
│   └── rag_retriever.py        # ChromaDB vector search
├── llm_providers/
│   └── factory.py              # OpenAI / Anthropic / Groq factory
├── db/
│   ├── connection.py           # PostgreSQL + Kuzu DB connections
│   ├── seed.py                 # Seed script (PostgreSQL banking data)
│   ├── seed_kuzu.py            # Seed script (Kuzu graph DB)
│   └── migrations/             # PostgreSQL migration scripts (01_schema.sql, ...)
├── banking_data/
│   ├── customers.json          # Raw (unprotected) customer data
│   ├── customers_protected.json # Protegrity-tokenized data (used at runtime)
│   ├── knowledge_base/         # Pre-tokenized per-customer KB files
│   └── knowledge_prep/         # Data protection pipeline scripts
├── chroma_db/                  # ChromaDB vector store (auto-generated)
├── kuzu_data/
│   └── banking.kuzu            # Kuzu graph database (auto-generated)
├── tests/
│   ├── smoke_test.py                        # Quick offline smoke test
│   ├── test_orchestration.py               # Orchestration layer unit tests
│   ├── test_orchestrators.py               # Config & gate unit tests
│   ├── test_banking_service.py             # Banking service unit tests
│   ├── test_pii_tags.py                    # PII token format tests
│   ├── test_conversation_history.py        # History persistence tests
│   ├── test_app_integration.py             # TechnicalApp integration (252 tests)
│   └── test_business_app_integration.py    # BusinessCustomerApp integration
├── readme/
│   ├── README.md                    # This file
│   ├── readme_TechnicalApp.md       # TechnicalApp deep-dive
│   ├── readme_BusinessCustomerApp.md # BusinessCustomerApp deep-dive
│   ├── readme_for_Orchestrators.md  # Orchestrator architecture
│   ├── readme_for_Protegrity.md     # Protegrity SDK integration
│   ├── readme_for_Claude.md         # AI assistant reference
│   ├── readme_Direct.md             # Direct orchestrator
│   ├── readme_LangGraph.md          # LangGraph orchestrator
│   ├── readme_CrewAI.md             # CrewAI orchestrator
│   └── readme_LlamaIndex.md         # LlamaIndex orchestrator
├── scripts/
│   ├── setup_env.sh               # Build Python venv or conda env, install deps, bootstrap .env
│   ├── setup_protegrity.sh        # Auto-install Protegrity containers + SDK
│   ├── start_apps.sh              # Local (non-Docker) launcher for both apps
│   ├── browse_chromadb.py         # CLI inspector for ChromaDB (list, show, search, rebuild)
│   ├── chromadb_viewer.py         # Streamlit GUI browser for ChromaDB (local)
│   └── bump_version.sh            # Version bump helper
├── docker/
│   └── entrypoint.sh              # Container entrypoint — waits for Protegrity, launches app
├── Dockerfile                  # Shared image for TechnicalApp + BusinessCustomerApp
├── docker-compose.yml          # Runs both apps on protegrity-network
├── start.sh                    # Master launcher — Protegrity check + docker compose up
├── .dockerignore               # Files excluded from the Docker build context
├── .env                        # Environment variables (not in git)
├── pyproject.toml              # Pytest configuration
└── VERSION                     # 1.3
```

---

## Orchestrators & Data Sources

| Orchestrator | Postgres | RAG | KG | Description |
|---|---|---|---|---|
| **direct** | ✅ | ❌ | ❌ | Single LLM call with PostgreSQL context |
| **langgraph** | ✅ | ✅ | ✅ | State machine — all data sources |
| **crewai** | ✅ | ❌ | ✅ | Multi-agent: Retriever + Responder |
| **llamaindex** | ✅ | ✅ | ❌ | Query engine with vector search |

All orchestrators receive and return **tokenized data only** — PII protection is
handled exclusively by the two gates, not inside the orchestrator.

---

## Users & Roles

### TechnicalApp (`config/users.json`)

| Username | Password | Role |
|---|---|---|
| `admin` | `Adm!n@S3cure2026` | Technical Administrator |
| `engineer` | `Eng#Pr0tegrity!` | Integration Engineer |
| `langgraph` | `LangGraph#2026` | LangGraph Engineer |
| `crewai` | `CrewAI#2026` | CrewAI Engineer |
| `llamaindex` | `LlamaIndex#2026` | LlamaIndex Engineer |

### BusinessCustomerApp (`config/customer_users.json`)

15 demo customers: `allison100`/`pass100` through `tanya114`/`pass114`.  
A clickable credentials panel is shown on the login page.

---

## Developer Edition — Limitations & Constraints

The Protegrity Developer Edition is **free for development and demonstration**.
The following constraints apply to the public cloud endpoints; self-hosted
(enterprise) deployments do not have these restrictions.

### API Rate Limits

| Limit | Value |
|---|---|
| Request Rate | 50 requests / second |
| Burst | up to 100 requests |
| Quota | 10,000 requests per user |
| Max Payload Size | 1 MB |

The application includes built-in retry logic with exponential backoff in
`services/protegrity_guard.py` to handle transient `429` errors.

### Session Expiry

Developer Edition sessions expire after approximately **30 minutes** of
inactivity. The helper in `services/protegrity_dev_edition_helper.py`
detects expired sessions and re-authenticates automatically; no user
intervention is required.

### Functional Scope

| Capability | Available in Dev Edition |
|---|---|
| PII classification (`classify`) | Yes |
| Tokenization / detokenization (`protect` / `unprotect`) | Yes |
| Semantic Guardrail (`scan`) | Yes |
| Synthetic data generation | Yes (v1.1+) |
| Role-based access (multiple `protegrity_user` roles) | Yes |
| Enterprise policy management | No — enterprise only |
| Custom data-element definitions | No — enterprise only |
| High-availability / clustering | No — enterprise only |

### Other Constraints

- **Python SDK version**: requires Python **3.12.11+** (`protegrity-developer-python >= 1.1.0`; 3.13 also supported).
- **Not for production**: the Developer Edition is intended for prototyping,
  demos, and evaluation. Production workloads require a licensed Protegrity
  deployment.
- **Network dependency**: tokenize / detokenize calls go to Protegrity's
  cloud; an internet connection is required (local containers handle
  classification and guardrail only).

> For full terms see
> [protegrity.com/developer-edition](https://www.protegrity.com/developer-edition).

---

## Further Reading

| File | Description |
|---|---|
| [readme_TechnicalApp.md](readme_TechnicalApp.md) | Goals, architecture, and features of the TechnicalApp |
| [readme_BusinessCustomerApp.md](readme_BusinessCustomerApp.md) | Goals, architecture, and features of the BusinessCustomerApp |
| [readme_for_Orchestrators.md](readme_for_Orchestrators.md) | Orchestrator internals and data flow |
| [readme_for_Protegrity.md](readme_for_Protegrity.md) | Protegrity SDK integration and entity mappings |
| [readme_for_Claude.md](readme_for_Claude.md) | Comprehensive technical reference for AI assistants |
| [readme_Direct.md](readme_Direct.md) | Direct orchestrator |
| [readme_LangGraph.md](readme_LangGraph.md) | LangGraph orchestrator |
| [readme_CrewAI.md](readme_CrewAI.md) | CrewAI orchestrator |
| [readme_LlamaIndex.md](readme_LlamaIndex.md) | LlamaIndex orchestrator |

---

*Protegrity Developer Edition is free for development and demonstration purposes.*  
*See [protegrity.com/developer-edition](https://www.protegrity.com/developer-edition) for terms.*
