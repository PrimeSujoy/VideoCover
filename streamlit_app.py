# Don't Remove Credit Tg - @NexonBots
# Subscribe YouTube Channel For Amazing Bot https://youtube.com/@NexonBots
# Ask Doubt on telegram @NexonContactBot

"""Streamlit Community Cloud entrypoint for the Telegram polling bot."""

import os
import subprocess
import sys
from pathlib import Path

import streamlit as st


PROJECT_DIR = Path(__file__).resolve().parent


def load_streamlit_secrets() -> None:
    """Expose flat Streamlit secrets to bot.py as environment variables."""
    for key, value in st.secrets.items():
        if isinstance(value, (str, int, float, bool)):
            os.environ[str(key)] = str(value)


@st.cache_resource
def start_bot_process() -> subprocess.Popen:
    """Start exactly one Telegram polling process per Streamlit app process."""
    load_streamlit_secrets()
    child_environment = os.environ.copy()

    # Streamlit owns its HTTP port. The Telegram child must not bind to it.
    child_environment.pop("PORT", None)

    return subprocess.Popen(
        [sys.executable, str(PROJECT_DIR / "bot.py")],
        cwd=str(PROJECT_DIR),
        env=child_environment
    )


st.set_page_config(
    page_title="Video Cover Bot",
    page_icon="🎬",
    layout="centered"
)

st.title("🎬 Video Cover Bot")
st.caption("Telegram thumbnail automation service")

required_secrets = ("BOT_TOKEN", "OWNER_ID", "MONGODB_URI")
missing_secrets = [key for key in required_secrets if not st.secrets.get(key)]

if missing_secrets:
    st.error(
        "Missing required Streamlit secrets: " + ", ".join(missing_secrets)
    )
    st.info("Open App settings → Secrets and add the required values.")
    st.stop()

bot_process = start_bot_process()

if bot_process.poll() is not None:
    # A cached child may have exited. Clear it so the next rerun can recover.
    start_bot_process.clear()
    st.error("The Telegram bot process stopped. Reload this page to restart it.")
else:
    st.success("Telegram bot is running")
    st.write(f"Process ID: `{bot_process.pid}`")

st.warning(
    "Streamlit Community Cloud may hibernate inactive apps. "
    "Use Railway, Koyeb, Northflank, Heroku, or a VPS for reliable 24/7 uptime."
)

st.divider()
st.markdown("Telegram: **@NexonBots**")
st.markdown("YouTube: **https://youtube.com/@NexonBots**")
st.markdown("Support: **@NexonContactBot**")
