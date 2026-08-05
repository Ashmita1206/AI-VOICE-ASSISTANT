"""
AI Voice Assistant — Central Configuration & Logging
===================================================

All configurable settings, environment variables, paths, and system parameters live here.
Configured via Pydantic models with defaults populated from environment variables (.env).
"""

import os
import sys
import logging
from typing import Tuple, Optional
from pathlib import Path
from pydantic import BaseModel, Field
from dotenv import load_dotenv

# Load variables from .env file
load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def _detect_device() -> Tuple[str, str]:
    """Auto-detect the best available compute device and matching type."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda", "float16"
    except ImportError:
        pass
    return "cpu", "int8"


class PathsConfig(BaseModel):
    base_dir: str = Field(default_factory=lambda: BASE_DIR)
    audio_dir: str = Field(default_factory=lambda: os.path.join(BASE_DIR, "audio_recordings"))
    data_dir: str = Field(default_factory=lambda: os.path.join(BASE_DIR, "data"))
    cache_dir: str = Field(default_factory=lambda: os.path.join(BASE_DIR, "cache"))
    log_dir: str = Field(default_factory=lambda: os.path.join(BASE_DIR, "logs"))
    notepad_session_cache_file: str = Field(
        default_factory=lambda: os.path.join(
            os.path.expanduser("~"), ".gemini", "antigravity-ide", "notepad_session.json"
        )
    )
    whatsapp_user_data_dir: str = Field(
        default_factory=lambda: os.path.expanduser("~/.whatsapp_automation_profile")
    )


class AudioConfig(BaseModel):
    sample_rate: int = Field(default=16_000)
    channels: int = Field(default=1)
    default_duration: int = Field(default=5)
    silence_threshold: float = Field(
        default_factory=lambda: float(os.getenv("SILENCE_THRESHOLD", "0.01"))
    )
    silence_duration: float = Field(
        default_factory=lambda: float(os.getenv("SILENCE_DURATION", "2.0"))
    )


class STTConfig(BaseModel):
    model_id: str = Field(
        default_factory=lambda: os.getenv("STT_MODEL_ID", "deepdml/faster-whisper-large-v3-turbo-ct2")
    )
    beam_size: int = Field(
        default_factory=lambda: int(os.getenv("STT_BEAM_SIZE", "5"))
    )
    vad_filter: bool = Field(
        default_factory=lambda: os.getenv("STT_VAD_FILTER", "True").lower() == "true"
    )
    use_remote: bool = Field(
        default_factory=lambda: os.getenv("STT_USE_REMOTE", "false").lower() == "true"
    )
    api_url: str = Field(
        default_factory=lambda: os.getenv("STT_API_URL", "https://common-sketch-cornmeal.ngrok-free.dev/transcribe")
    )
    api_timeout: int = Field(
        default_factory=lambda: int(os.getenv("STT_API_TIMEOUT", "60"))
    )


class RAGConfig(BaseModel):
    use_remote: bool = Field(
        default_factory=lambda: os.getenv("RAG_USE_REMOTE", "true").lower() == "true"
    )
    api_url: str = Field(
        default_factory=lambda: os.getenv("RAG_API_URL", os.getenv("COLAB_API_URL", "https://evaluator-agreeing-plenty.ngrok-free.dev"))
    )
    api_timeout: int = Field(
        default_factory=lambda: int(os.getenv("RAG_API_TIMEOUT", "30"))
    )


class ColabConfig(BaseModel):
    api_url: str = Field(
        default_factory=lambda: os.getenv("COLAB_API_URL", "https://evaluator-agreeing-plenty.ngrok-free.dev")
    )
    timeout: int = Field(
        default_factory=lambda: int(os.getenv("COLAB_TIMEOUT", "120"))
    )


class ServerConfig(BaseModel):
    flask_port: int = Field(
        default_factory=lambda: int(os.getenv("FLASK_PORT", "5000"))
    )
    log_level: str = Field(
        default_factory=lambda: os.getenv("LOG_LEVEL", "INFO")
    )


class AutomationConfig(BaseModel):
    pyautogui_failsafe: bool = Field(default=True)
    
    # Notepad Automation
    notepad_exe: str = Field(default="notepad.exe")
    notepad_proc_name: str = Field(default="notepad")
    notepad_title_fragment: str = Field(default="notepad")
    window_poll_interval: float = Field(default=0.35)
    window_launch_timeout: float = Field(default=12.0)
    focus_settle_ms: int = Field(default=350)
    save_dialog_timeout: float = Field(default=5.0)
    typing_interval: float = Field(default=0.04)

    # WhatsApp Automation
    whatsapp_url: str = Field(default="https://web.whatsapp.com")
    whatsapp_login_timeout: int = Field(default=60000)
    whatsapp_element_timeout: int = Field(default=5000)


class AppConfig(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    stt: STTConfig = Field(default_factory=STTConfig)
    rag: RAGConfig = Field(default_factory=RAGConfig)
    colab: ColabConfig = Field(default_factory=ColabConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)
    automation: AutomationConfig = Field(default_factory=AutomationConfig)


# Global configuration instance
config = AppConfig()

# ---------------------------------------------------------------------------
# Centralized Logging Setup
# ---------------------------------------------------------------------------
def setup_logging(log_level: Optional[str] = None) -> logging.Logger:
    """Configure root logger format and level."""
    level_str = log_level or config.server.log_level
    numeric_level = getattr(logging, level_str.upper(), logging.INFO)
    
    os.makedirs(config.paths.log_dir, exist_ok=True)
    
    formatter = logging.Formatter(
        "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)
    
    # Avoid adding duplicate handlers if setup_logging is called multiple times
    if not root_logger.handlers:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        root_logger.addHandler(console_handler)
        
        log_file = os.path.join(config.paths.log_dir, "assistant.log")
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        root_logger.addHandler(file_handler)
        
    return root_logger


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance for a given module name."""
    return logging.getLogger(name)


# Centralized logger instance
logger = get_logger("ai_voice_assistant")

# Ensure default directories exist
os.makedirs(config.paths.audio_dir, exist_ok=True)
os.makedirs(config.paths.data_dir, exist_ok=True)
os.makedirs(config.paths.cache_dir, exist_ok=True)
os.makedirs(config.paths.log_dir, exist_ok=True)


# ---------------------------------------------------------------------------
# Backward Compatibility Module-Level Constants
# ---------------------------------------------------------------------------
DEVICE, COMPUTE_TYPE = _detect_device()

AUDIO_DIR = config.paths.audio_dir
DATA_DIR = config.paths.data_dir
CACHE_DIR = config.paths.cache_dir
LOG_DIR = config.paths.log_dir

STT_MODEL_ID = config.stt.model_id
STT_BEAM_SIZE = config.stt.beam_size
STT_VAD_FILTER = config.stt.vad_filter
STT_USE_REMOTE = config.stt.use_remote
STT_API_URL = config.stt.api_url
STT_API_TIMEOUT = config.stt.api_timeout

AUDIO_SAMPLE_RATE = config.audio.sample_rate
AUDIO_CHANNELS = config.audio.channels
AUDIO_DEFAULT_DURATION = config.audio.default_duration
SILENCE_THRESHOLD = config.audio.silence_threshold
SILENCE_DURATION = config.audio.silence_duration

LOG_LEVEL = config.server.log_level
FLASK_PORT = config.server.flask_port

COLAB_API_URL = config.colab.api_url
COLAB_TIMEOUT = config.colab.timeout

RAG_USE_REMOTE = config.rag.use_remote
RAG_API_URL = config.rag.api_url
RAG_API_TIMEOUT = config.rag.api_timeout

# Automation Constants
SESSION_CACHE_FILE = config.paths.notepad_session_cache_file
WHATSAPP_USER_DATA_DIR = config.paths.whatsapp_user_data_dir
NOTEPAD_EXE = config.automation.notepad_exe
NOTEPAD_PROC_NAME = config.automation.notepad_proc_name
NOTEPAD_TITLE_FRAGMENT = config.automation.notepad_title_fragment
WINDOW_POLL_INTERVAL = config.automation.window_poll_interval
WINDOW_LAUNCH_TIMEOUT = config.automation.window_launch_timeout
FOCUS_SETTLE_MS = config.automation.focus_settle_ms
SAVE_DIALOG_TIMEOUT = config.automation.save_dialog_timeout
TYPING_INTERVAL = config.automation.typing_interval
WHATSAPP_URL = config.automation.whatsapp_url
WHATSAPP_LOGIN_TIMEOUT = config.automation.whatsapp_login_timeout
WHATSAPP_ELEMENT_TIMEOUT = config.automation.whatsapp_element_timeout
PYAUTOGUI_FAILSAFE = config.automation.pyautogui_failsafe
