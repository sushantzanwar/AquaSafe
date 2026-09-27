# 🚀 Deploying AquaSafe to Render (Free Tier)

AquaSafe is packaged as a unified service hosting both the **FastAPI Intelligence Backend** and the **HTML5 / GIS Frontend** through a single container on Render.

---

## 📋 Prerequisites
- A free [Render.com](https://render.com) account.
- Your Google Gemini API Key.
- Repository: [https://github.com/sushantzanwar/AquaSafe](https://github.com/sushantzanwar/AquaSafe) (Branch: `new-main-branch`).

---

## ⚡ Option 1: 1-Click Blueprint Deploy (Recommended)

1. Log in to your [Render Dashboard](https://dashboard.render.com).
2. Click **New +** in the top right corner and select **Blueprint**.
3. Connect your GitHub account and select repository: `sushantzanwar/AquaSafe`.
4. Choose Branch: **`new-main-branch`**.
5. Render will automatically detect [`render.yaml`](render.yaml).
6. Fill in the Secret Environment Variables when prompted:
   - `GEMINI_API_KEY`: `<your_gemini_api_key>`
   - `LLM_API_KEY`: `<your_gemini_api_key>`
7. Click **Apply**. Render will create the PostgreSQL database (`aquasafe-db`), build the Docker container, run the migrations on start and deploy the app!

---

## 🛠 Option 2: Manual Web Service Setup

If you prefer setting up the Web Service manually:

1. In Render Dashboard, click **New +** → **Web Service**.
2. Select **Build and deploy from a Git repository**.
3. Choose `sushantzanwar/AquaSafe` and branch **`new-main-branch`**.
4. Configure the settings:
   - **Name**: `aquasafe` (or any name you like)
   - **Region**: Oregon (US West) or closest to your users
   - **Language / Runtime**: **Docker**
   - **Dockerfile Path**: `Dockerfile`
   - **Instance Type**: **Free**
5. Under **Environment Variables**, add:
   | Key | Value | Description |
   | :--- | :--- | :--- |
   | `PORT` | `8000` | Port uvicorn binds to |
   | `DATABASE_URL` | Internal URL of a Render PostgreSQL | Needed for credits/field verification; without it those endpoints return 503 and everything else works |
   | `LLM_PROVIDER` | `gemini` | AI Model Provider |
   | `GEMINI_API_KEY` | `your_gemini_api_key` | Gemini API access key |
   | `LLM_API_KEY` | `your_gemini_api_key` | Fallback RAG key |
6. Click **Create Web Service**.

---

## 🌐 Deployed Access URLs

Once Render completes the build, your application will be live at `https://aquasafe-xxxx.onrender.com`:

| View | Path | Description |
| :--- | :--- | :--- |
| **All-in-One Home** | `/` or `/dashboard.html` | Real-time map, 11-band spectral profile |
| **Analysis Workspace** | `/assistant.html` | Sentinel-2 lake radiometry analysis |
| **AI Assistant** | `/ai-assistant.html` | Gemini RAG chat & hydrological safety |
| **Proof Gallery** | `/satellite-proof.html` | Spectral verification & ground surveys |
| **Architecture Flowchart** | `/architecture.html` | Interactive system blueprint |
| **Interactive API Docs** | `/docs` | Swagger REST documentation |

---

## 🗄 Database and persistence

- The blueprint provisions a free Render PostgreSQL and passes it in as `DATABASE_URL`; migrations run automatically when the container starts. (Render's free databases expire after a period, so upgrade the plan for anything long-lived.)
- Uploaded field photos and the legacy analysis history are written under `/data` in the container. Render's free web tier has an ephemeral disk, so they are lost on redeploy; attach a Render Disk mounted at `/data` if you need them to persist.

---

## 🐳 Local Docker (app + PostgreSQL)

```bash
cp .env.example .env          # set POSTGRES_PASSWORD and your LLM key
docker compose up -d --build  # app on http://localhost:8000, PostgreSQL as the `db` service
```

Single container without a database (credits disabled):

```bash
docker build -t aquasafe .
docker run -p 8000:8000 --env-file .env aquasafe
```
