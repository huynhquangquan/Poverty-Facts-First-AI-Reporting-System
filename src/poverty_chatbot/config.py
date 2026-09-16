from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "db" / "poverty.db"
OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL_NAME = "qwen2.5:3b-instruct"
LLM_TIMEOUT = 120
REPORT_LLM_MAX_ATTEMPTS = 10