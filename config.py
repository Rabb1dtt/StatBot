import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# Model routing: different models for different tasks
MODEL_ORCHESTRATOR = os.environ.get("MODEL_ORCHESTRATOR", "anthropic/claude-sonnet-4-6")  # query parsing
MODEL_TRANSLATE = os.environ.get("MODEL_TRANSLATE", "google/gemini-3-flash-preview")  # name transliteration
MODEL_ANALYSIS = os.environ.get("MODEL_ANALYSIS", "xiaomi/mimo-v2-pro")  # heavy analysis
