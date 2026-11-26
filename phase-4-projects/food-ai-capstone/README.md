# Food AI Restaurant Assistant

An educational, fictional restaurant application based on the supplied capstone case study. It has a browser UI, FastAPI, MySQL, Gemini generation and embeddings, document retrieval, and one tool-using agent. Payments and deliveries are simulated.

## Run locally

Python 3.10+ and a running MySQL 8 server are required. If the `food_ai` database and user do not already exist, ask a MySQL administrator to create them. For a local Ubuntu installation using socket-authenticated root, run `sudo mysql` and enter the following in the MySQL prompt, replacing the placeholder with a unique strong password:

```sql
CREATE DATABASE food_ai CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'food_ai'@'localhost' IDENTIFIED BY 'REPLACE_WITH_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON food_ai.* TO 'food_ai'@'localhost';
```

If the database or user already exists, do not recreate or reset it; confirm the correct account, host, permissions and password with the administrator. Depending on your MySQL installation, use `mysql -u root -p` rather than `sudo mysql`. The SQL above is for a local user; remote connections need an appropriate MySQL user host and secure network configuration. Never commit passwords or real API keys.

If you already have access to a shared MySQL database, set its connection URL in `.env` instead; a separate database is not required. Food AI uses the `food_ai_` table prefix, so its user, order and other tables are distinct from existing tables such as `users`. It does not use or modify the shared database's existing users.

From this directory:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
# Edit .env: replace CHANGE_ME in DATABASE_URL with your MySQL password,
# and set GEMINI_API_KEY to your own Gemini API key.
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
```

For passwords containing URL-special characters such as `@`, `:`, `/`, `#`, `%`, or `?`, percent-encode the password in `DATABASE_URL`. Set the host, port or database name in `.env` if your MySQL installation differs. The application cannot create the database itself: it creates tables in the configured database on startup and seeds an empty installation. Startup fails visibly if the connection or credentials are incorrect.

Open <http://127.0.0.1:8000/> for the UI, <http://127.0.0.1:8000/docs> for the API, and <http://127.0.0.1:8000/health> for health. The key stays on the server. Without a key, manual ordering works but chat and document indexing return 503. Gemini usage may incur provider charges and sends chat text, recent conversation, tool results and indexed documents to Gemini; use fictional data only.

On the first startup against an empty database, the app creates tables and seeds ten menu items, three sample orders and these fictional **local-demo-only** accounts:

| Role | Username | Password |
|---|---|---|
| Admin | `admin` | `admin-demo` |
| Customer | `alice` | `alice-demo` |
| Customer | `bob` | `bob-demo` |

These are deliberately public demonstration credentials. Do not expose this app to the internet or use these accounts for real data. The frontend keeps the Basic credentials only in browser memory until sign-out or refresh. HTTP Basic requires HTTPS outside localhost.

To enable grounded policy answers, sign in as admin and use **Upload and index** to upload `knowledge_base/restaurant_policy.txt` (or another fictional UTF-8 TXT, PDF, or DOCX). Gemini generates embeddings during indexing. Uploading the same filename creates a new active version. Ask, for example, “What is the cancellation policy?” or “Does Masala Dosa contain allergens?” The assistant must not guarantee allergen safety.

## Using the application

* Browse all dishes or filter vegetarian, non-vegetarian, price and name. Sign in to order a portion or cancel a confirmed order in My Orders.
* Admins can create/update/disable menu items, advance order statuses and upload documents. For an update, enter the item's ID and all its fields; uncheck Active to disable it.
* Start a chat and ask “Show non-vegetarian food”, “Is item 6 available?”, “List my orders”, “What is the status of order 1?”, or “Order one chicken biryani.” The agent sees live data via the authenticated API.
* The assistant can prepare an order or cancellation, but it does not execute it until the owner uses the separate **Confirm** button. **Reject** makes no changes. The server rechecks ownership, price, capacity and status on confirmation. Confirmation is idempotent and expires after 15 minutes.
* Chats, tool results, pending actions, orders and indexed documents persist in MySQL across restarts. Session history is private to its owner.

The assistant can also answer general food questions and combine menu search with document retrieval in one response. It cannot provide actual payment processing, delivery tracking, real-time external restaurant data, or guaranteed allergen safety. Possible future agent tools include dietary preference profiles, personalized recommendations based on explicit preferences, and delivery tracking through an authorized provider; they are not implemented here.

## Architecture and responsibilities

```text
Browser (HTML/CSS/JavaScript)
    -> FastAPI routes, Pydantic validation, HTTP Basic/role checks
        -> Order service and chat orchestration
            -> repository interfaces / SQLAlchemy repositories -> MySQL
            -> Gemini agent -> allowlisted, validated tools -> local API (live reads)
            -> Gemini embeddings -> MySQL document chunks -> cosine retrieval
```

* **Frontend:** renders menu, orders, admin controls, chat history, citations and confirmation buttons. It uses `textContent` for untrusted text.
* **API:** validates requests, authenticates users, checks ownership/roles, and converts errors into a stable JSON shape.
* **Business service:** checks availability and transitions, snapshots server prices, and atomically updates orders and stock. MySQL transactions use row locks for inventory, orders, idempotency, actions and chat sequence numbers. Inventory rows are locked in item-ID order to reduce deadlocks.
* **Repositories:** encapsulate menu/order lookup. The service receives small repository protocols through a composition function: dependency inversion and interface segregation, with replaceable implementations. Routes, business services, persistence and AI each have distinct responsibilities (single responsibility); new implementations can extend these boundaries without changing existing consumers (open/closed and substitutability).
* **GenAI job:** Gemini generates conversational responses and embeddings; it does not determine authoritative inventory, prices or transaction results.
* **Agent job:** interpret intent, choose from an allowlist, validate tool arguments, obtain live facts, retrieve policy evidence and prepare actions. The tool loop is bounded to six rounds. Read tools call the same ASGI API with the authenticated user's credentials; the model cannot choose credentials or URLs.
* **Confirmation:** the confirmation endpoint applies the same order service used by the manual API, within the same database transaction as the action state. This is intentionally a direct service call rather than a second HTTP call: it makes the action state and mutation atomic and prevents duplicate orders after a retry.

Patterns illustrated include Repository, Dependency Injection, a tool-dispatch/command boundary, and human-in-the-loop confirmation. There is one agent with multiple tools, not multiple autonomous agents.

## API overview

The complete schemas are in Swagger. Public reads are `GET /api/menu_items` and `GET /api/menu_items/{id}`. Admins manage menu items and update order statuses. Customers use `POST /api/orders` with an `Idempotency-Key` header, `GET /api/orders`, `GET /api/orders/{id}`, and `POST /api/orders/{id}/cancel`. Admins index documents at `POST /api/documents`. Authenticated chat endpoints create/list sessions, send/list messages, and confirm/reject actions at `POST /api/chat/actions/{id}/confirm` with `{"confirm": true}` or `false`. Protected resources enforce owner or admin access as applicable.

## Tests

```bash
.venv/bin/python -m pytest -q
```

By default, tests use a separate temporary SQLite database and mocked Gemini responses/embeddings. They cover permissions, stock concurrency, idempotency, confirmation, expiry, price changes, agent tools, citations and persisted AI errors. A live Gemini request requires a valid key and is not part of the test suite.

To run the same suite against MySQL, create a **new, empty, dedicated test database**, grant a test account permissions on it, then set `TEST_DATABASE_URL` when running pytest:

```bash
TEST_DATABASE_URL='mysql+pymysql://test_user:TEST_PASSWORD@127.0.0.1:3306/food_ai_test?charset=utf8mb4' .venv/bin/python -m pytest -q
```

Tests create and modify data and should never point at your application database. Use a fresh test database for each run. Avoid putting real passwords in shell history; use environment management appropriate for your environment.

## Differences and limitations

* Existing SQLite data and earlier unprefixed Food AI tables are not automatically migrated. Switching `DATABASE_URL` or upgrading to prefixed tables selects a separate set of data; old orders, users and chats remain in their original tables. Back up existing data before migration.
* Embeddings are stored in MySQL and cosine-scanned rather than in ChromaDB. This is suitable only for a small demo; the similarity cutoff is heuristic and retrieval can miss relevant evidence.
* `create_all` initializes a new database; there is no versioned schema migration system. Back up the database before schema changes.
* The in-process per-client rate limiter is demo-grade, resets on restart and is not shared across workers. Basic authentication, demo credentials, document processing, logging, deletion/retention policies and deployment configuration need further hardening before production use.
* The document extractor limits uploads to 5 MiB and 200 chunks; policy documents are untrusted data and cannot authorize actions. No real external integrations are included.
