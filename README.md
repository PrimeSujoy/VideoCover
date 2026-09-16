# Don't Remove Credit Tg - @NexonBots
# Subscribe YouTube Channel For Amazing Bot [https://youtube.com/@NexonBots](https://youtube.com/@NexonBots)
# Ask Doubt on telegram @NexonContactBot

<div align="center">

<img src="https://img.shields.io/badge/Python-3.8%2B-blue?style=flat-square&logo=python" alt="Python">
<img src="https://img.shields.io/badge/Telegram-Bot-0088cc?style=flat-square&logo=telegram" alt="Telegram">
<img src="https://img.shields.io/badge/MongoDB-Latest-13aa52?style=flat-square&logo=mongodb" alt="MongoDB">
<img src="https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker" alt="Docker">
<img src="https://img.shields.io/badge/License-MIT-green?style=flat-square" alt="License">

# 🎬 Instant Video Cover Bot

### ✨ Professional Telegram Bot for Adding Custom Covers to Videos ✨

<br>

[🚀 Quick Start](#quick-start) • [✨ Features](#features) • [⚙️ Setup](#setup) • [🌐 Deployment](#-deployment)

</div>

---

---

## 📋 About

<table align="center">
  <tr>
    <td><b>Instant Video Cover Bot</b> helps you apply custom thumbnail covers to videos instantly.</td>
  </tr>
  <tr>
    <td>Perfect for content creators who want professional-looking videos with custom covers.</td>
  </tr>
</table>

### 🎯 Key Features

| Feature | Benefit |
|---------|---------|
| 📸 **Upload Photo** | Save custom covers for your videos |
| 🎥 **Instant Apply** | Add covers to any video in seconds |
| 🔒 **Secure Access** | Force subscribe verification |
| 👥 **Admin Tools** | Full user management & controls |
| 📊 **Analytics** | Track users & system metrics |
| 💾 **Persistent** | MongoDB database integration |
| 🐳 **Containerized** | Docker deployment ready |

---

## ✨ Features

<details open>
<summary><b>📸 Core Features</b></summary>

| Feature | Description |
|---------|-------------|
| 📸 **Set Cover** | Upload photo as video thumbnail |
| 🎬 **Apply Cover** | Add cover to videos instantly |
| ✏️ **Change Cover** | Update cover anytime |
| 🗑️ **Remove Cover** | Delete saved cover |

</details>

<details open>
<summary><b>🔐 Security & Control</b></summary>

| Feature | Description |
|---------|-------------|
| 🔒 **Force Subscribe** | Require channel membership |
| ✅ **Verification** | Auto-verify users |
| 🚫 **Ban System** | Manage banned users |
| 👨‍💼 **Admin Panel** | Full control dashboard |

</details>

<details open>
<summary><b>📊 Admin Features</b></summary>

| Feature | Description |
|---------|-------------|
| 👥 **Users Stats** | Total, active, banned count |
| 📈 **Ban Rate** | Monitor ban statistics |
| 💻 **System Monitor** | CPU & RAM usage |
| 📢 **Broadcast** | Send messages to all users |
| ⏱️ **Uptime** | Bot status & performance |

</details>

---

## 🚀 Quick Start

### 📋 Prerequisites

| Requirement | Details |
|------------|---------|
| 🐍 **Python** | 3.8 or higher |
| 🤖 **Bot Token** | From [@BotFather](https://t.me/BotFather) |
| 🗄️ **MongoDB** | Local or [Atlas Cloud](https://mongodb.com/cloud/atlas) |
| 📚 **Git** | For cloning repository |

### ⚡ Quick Installation

```bash
# 1️⃣ Clone repository
git clone https://github.com/PrimeSujoy/VideoCover.git
cd video-cover-bot

# 2️⃣ Create virtual environment
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

# 3️⃣ Install dependencies
pip install -r requirements.txt

# 4️⃣ Setup configuration
cp ,env.example config.env
nano config.env  # Edit with your details

# 5️⃣ Run bot
python bot.py
```

✅ **Bot is running!**

---

## ⚙️ Setup

### 1️⃣ Get Bot Token

```
🤖 Open @BotFather in Telegram
📤 Send: /newbot
📝 Follow prompts to create bot
🔑 Copy your token
```

### 2️⃣ Configure Environment

```ini
# 🔓 Edit config.env

BOT_TOKEN=your_token_from_botfather
OWNER_ID=your_telegram_user_id
FORCE_SUB_CHANNEL_ID=-1002659719637
# Optional: receives first-time verified user registrations only
LOG_CHANNEL_ID=-1002659719637
MONGODB_URI=mongodb://localhost:27017
MONGODB_DATABASE=video_cover_bot
```

### 3️⃣ Setup MongoDB

<div align="left">

**☁️ Cloud Option (Recommended):**
1. Go to [MongoDB Atlas](https://www.mongodb.com/cloud/atlas)
2. Create free account
3. Create M0 free cluster
4. Copy connection string
5. Add to config.env

**💻 Local Option:**
```bash
# Ubuntu/Debian
sudo apt-get install mongodb

# macOS
brew install mongodb-community
```

</div>

### 4️⃣ Create Telegram Channels

```
📌 Create 2 private channels:
   1. Force Subscribe Channel
   2. Log Channel

🤖 Add your bot as ADMIN in both

📨 Forward any message from channel → check bot logs for ID
🔧 Update config.env with IDs
```

### 5️⃣ Run Bot

```bash
python bot.py
```

🎉 **Done! Your bot is live!**

---

## 🎮 Commands

<div align="center">

### 👤 User Commands

| Command | Purpose |
|---------|---------|
| `/start` | 🏠 Open main menu |
| `/help` | ❓ Show how to use |
| `/settings` | ⚙️ Configure preferences |
| `/remove` | 🗑️ Delete cover |

### 👮 Admin Commands

| Command | Purpose |
|---------|---------|
| `/admin` | 🛡️ Open admin panel |
| `/ban userid reason` | 🚫 Ban user |
| `/unban userid` | ✅ Unban user |
| `/stats` | 📊 User statistics |
| `/status` | ⏱️ System status |
| `/speedtest` | 🚀 Server download/upload speed test |
| `/broadcast message` | 📢 Send to all users |

</div>

---

## 🌐 Deployment

This repository supports Docker and standard Python deployment. It can run on
Railway, Koyeb, Northflank, Heroku, Linux VPS servers, Windows RDP servers, and
other platforms that can run a Dockerfile or `python bot.py`.

> [!IMPORTANT]
> Run exactly **one replica, instance, container, or dyno**. Telegram long
> polling does not allow multiple copies of the same bot token to poll at once.

### Required environment variables

| Variable | Required | Description |
|---|---:|---|
| `BOT_TOKEN` | Yes | Token from [@BotFather](https://t.me/BotFather) |
| `OWNER_ID` | Yes | Owner's numeric Telegram user ID |
| `MONGODB_URI` | Yes | Externally reachable MongoDB connection string |
| `MONGODB_DATABASE` | No | Database name; defaults to `video_cover_bot` |
| `OWNER_USERNAME` | No | Owner username without `@` |
| `FORCE_SUB_CHANNEL_ID` | No | Force-subscribe channel ID |
| `LOG_CHANNEL_ID` | No | Optional channel for first-time verified user registration logs only |
| `FORCE_SUB_BANNER_URL` | No | Public force-subscribe banner URL |
| `HOME_MENU_BANNER_URL` | No | Public home-menu banner URL |
| `PORT` | Platform | Health server port; cloud platforms usually inject it |

Use MongoDB Atlas or another hosted MongoDB service for cloud deployments.
Localhost MongoDB URLs do not work unless MongoDB runs inside the same server or
private network. Never commit `config.env` or expose `BOT_TOKEN` publicly.

### Health check

When `PORT` is set, the bot starts a small HTTP server alongside Telegram
polling:

- `GET /health` returns HTTP `200`.
- `GET /` returns HTTP `200`.

Use `/health` as the platform health-check path. The health server does not
replace the Telegram polling process.

### 🐳 Docker / Docker Compose

Copy the example configuration and fill in your secrets:

```bash
cp ,env.example config.env
docker compose up -d --build
docker compose logs -f bot
```

Without Compose:

```bash
docker build -t video-cover-bot .
docker run -d --name video-cover-bot --restart unless-stopped \
  --env-file config.env -p 8000:8000 video-cover-bot
```

Test the container health endpoint:

```bash
curl http://localhost:8000/health
```

### 🚂 Railway

1. Push this folder to a GitHub repository.
2. In Railway, choose **New Project → Deploy from GitHub Repo**.
3. Railway automatically detects the root `Dockerfile`.
4. Add the required variables from the table above.
5. In service settings, set **Healthcheck Path** to `/health`.
6. Keep **Replicas** set to `1`, then deploy.

Reference: [Railway Dockerfile deployments](https://docs.railway.com/builds/dockerfiles)
and [Railway health checks](https://docs.railway.com/deployments/healthchecks).

### 🟣 Koyeb

1. Create an app and a **Web Service** from your GitHub repository.
2. Select the **Dockerfile** builder.
3. Add the required environment variables.
4. Expose port `8000` using HTTP and route `/` to it. Set `PORT=8000` if Koyeb
   does not inject it automatically.
5. Configure an HTTP health check on `/health`.
6. Keep the service at exactly `1` instance and deploy.

Reference: [Koyeb services](https://www.koyeb.com/docs/reference/services) and
[Koyeb health checks](https://www.koyeb.com/docs/run-and-scale/health-checks).

### 🔷 Northflank

1. Create a project and add a **Combined Service** from your Git repository.
2. Select **Dockerfile** as the build type and use `Dockerfile` at the repository
   root.
3. Add the required runtime variables/secrets.
4. Add public port `8000`, set `PORT=8000`, and use `/health` for the HTTP health
   check.
5. Set the deployment to `1` instance and create the service.

Reference: [Northflank build and deploy guide](https://northflank.com/docs/v1/application/getting-started/build-and-deploy-your-code).

### 🟪 Heroku

The included `Procfile` starts a web process so Heroku can reach `/health`.
The included `.python-version` selects Python 3.12.

```bash
heroku login
heroku create your-video-cover-bot
heroku config:set BOT_TOKEN=your_token OWNER_ID=your_id \
  MONGODB_URI='your_mongodb_uri' MONGODB_DATABASE=video_cover_bot
git push heroku main
heroku ps:scale web=1
heroku logs --tail
```

Optional settings can be added with more `heroku config:set KEY=value` commands.
The included `app.json` also supports Heroku's app-setup flow after its
`repository` value is changed to your public repository URL.

Reference: [Heroku Procfile](https://devcenter.heroku.com/articles/procfile) and
[Heroku Python runtimes](https://devcenter.heroku.com/articles/python-runtimes).

### 🖥️ Linux VPS

#### Option A: Docker Compose

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
git clone https://github.com/PrimeSujoy/VideoCover.git video-cover-bot
cd video-cover-bot
cp ,env.example config.env
nano config.env
sudo docker compose up -d --build
sudo docker compose logs -f bot
```

#### Option B: Python and systemd

```bash
sudo useradd --system --create-home videobot
sudo mkdir -p /opt/video-cover-bot
sudo cp -a . /opt/video-cover-bot/
sudo chown -R videobot:videobot /opt/video-cover-bot
sudo -u videobot python3 -m venv /opt/video-cover-bot/.venv
sudo -u videobot /opt/video-cover-bot/.venv/bin/pip install -r /opt/video-cover-bot/requirements.txt
sudo cp video-cover-bot.service.example /etc/systemd/system/video-cover-bot.service
sudo systemctl daemon-reload
sudo systemctl enable --now video-cover-bot
sudo journalctl -u video-cover-bot -f
```

Before starting systemd, create `/opt/video-cover-bot/config.env` and secure it:

```bash
sudo chmod 600 /opt/video-cover-bot/config.env
sudo chown videobot:videobot /opt/video-cover-bot/config.env
```

### 🪟 Windows VPS / RDP

1. Install Python 3.12 and select **Add Python to PATH** during installation.
2. Copy `,env.example` to `config.env` and fill in the values.
3. Double-click `start-windows.bat`. It creates `.venv`, installs dependencies,
   and starts the bot.
4. For automatic startup, create a Windows Task Scheduler task that runs
   `start-windows.bat` at system startup with **Start in** set to this folder.

PowerShell alternative:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python bot.py
```

### ☁️ Other platforms

For Render, Fly.io, DigitalOcean App Platform, Google Cloud Run, AWS, Azure, or
any similar provider:

1. Deploy the root `Dockerfile`.
2. Add the required environment variables.
3. Expose the value of `PORT` (default `8000` in Docker).
4. Set the health check to `/health`.
5. Set the start command to `python bot.py` only when the platform does not use
   the Dockerfile command.
6. Keep the instance count at `1` and disable horizontal autoscaling.

### 🔴 Streamlit Community Cloud (experimental)

Streamlit deployment is supported through `streamlit_app.py`, but Community
Cloud hibernates apps that receive no web traffic for 12 hours. Use this option
for testing or personal use, not guaranteed 24/7 bot uptime.

1. Open Streamlit Community Cloud and select `PrimeSujoy/VideoCover`.
2. Select branch `main`.
3. Set **Main file path** to `streamlit_app.py`.
4. Open **Advanced settings** and select Python `3.12`.
5. In **Secrets**, paste TOML values using the format shown in
   `.streamlit/secrets.toml.example`.
6. Click **Save**, then **Deploy**.

Do not add `PORT` to Streamlit secrets. Streamlit manages its own HTTP port.
Run only one deployment of the same `BOT_TOKEN` at a time.

References: [Streamlit deployment](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/deploy),
[secrets management](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app/secrets-management),
and [app hibernation](https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app).

---

## 🆘 Troubleshooting

<table align="center" width="100%">
  <tr>
    <th align="left" width="30%">❌ Issue</th>
    <th align="left">✅ Solution</th>
  </tr>
  <tr>
    <td>🤐 Bot not responding</td>
    <td>Check BOT_TOKEN in config.env, restart: `python bot.py`</td>
  </tr>
  <tr>
    <td>🚫 MongoDB error</td>
    <td>Verify MONGODB_URI, ensure MongoDB is running</td>
  </tr>
  <tr>
    <td>🔒 Force-sub fails</td>
    <td>Check channel ID format, bot must be admin in channel</td>
  </tr>
  <tr>
    <td>📝 Logs not sending</td>
    <td>Verify LOG_CHANNEL_ID, bot must have admin rights</td>
  </tr>
</table>

### 📋 Check Logs

```bash
# Local run
python bot.py

# Docker
docker logs -f video-bot

# VPS (Systemd)
sudo journalctl -u video-bot -f
```

---

## 📄 License

<div align="center">

**MIT License** - See [LICENSE](LICENSE) for details

You are free to use, modify, and distribute this bot.

</div>

---

## 💬 Support & Community

<div align="center">

| Support Channel | Action |
|---|---|
| 🐛 **Found a Bug?** | [Create GitHub Issue](../../issues) |
| 💡 **Feature Request?** | [Open Discussion](../../discussions) |
| 📧 **Direct Contact** | Message bot owner on Telegram |

### Show Your Support ⭐

<a href="../../stargazers">
  <img src="https://img.shields.io/github/stars/PrimeSujoy/VideoCover?style=social" alt="GitHub Stars">
</a>

If this bot helped you:
- ⭐ Star this repository
- 🔄 Share with friends
- 📢 Tell others about it

</div>

---

<div align="center">

### 🎉 Ready to Deploy?

| Step | Action |
|------|--------|
| 1️⃣ | Follow [Quick Start](#quick-start) |
| 2️⃣ | Setup Telegram channels |
| 3️⃣ | Choose a platform from the [Deployment](#-deployment) guide |
| 4️⃣ | Launch your bot 🚀 |

---

<b>Made with ❤️ for the Telegram Community</b>

[⬆ Back to Top](#-instant-video-cover-bot)

</div>
