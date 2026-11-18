"""
config.py — AIZEN AI global configuration and shared state.

All constants are defined here. Mutable state is stored as module-level
variables so every module can import and update them directly.
"""

import os

# ------------------------------------------------------------------
# VERSION
# ------------------------------------------------------------------

AIZEN_VERSION = "1.0.0"

# ------------------------------------------------------------------
# API
# ------------------------------------------------------------------

API_BASE = "http://localhost:20128/v1"

# Native local Ollama endpoint. Local model IDs are namespaced as ollama:<name>.
OLLAMA_BASE_URL = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
OLLAMA_TIMEOUT = 8
OLLAMA_REQUEST_TIMEOUT = 300
OLLAMA_DEFAULT_CONTEXT = 8192
OLLAMA_NUM_CTX = 8192
# Output tokens reserved for Ollama completions (subtracted from context window
# to get the maximum safe *input* token budget for local models).
OLLAMA_NUM_PREDICT = 2048
# Maximum input tokens for local Ollama requests:
# OLLAMA_NUM_CTX - OLLAMA_NUM_PREDICT with an additional 5% safety margin.
OLLAMA_MAX_INPUT_TOKENS = int((OLLAMA_NUM_CTX - OLLAMA_NUM_PREDICT) * 0.95)  # 5,832

CHAT_URL = f"{API_BASE}/chat/completions"
MODELS_URL = f"{API_BASE}/models"

# API key: prefer environment variable, fall back to built-in OmniRoute local key.
# The local OmniRoute key is not a secret — it controls local server access only.
API_KEY = os.environ.get("OMNIROUTE_API_KEY", "sk-ff79cd28b94904a4-5eb82e-f0509e81")

# ------------------------------------------------------------------
# FILE PATHS
# ------------------------------------------------------------------

DATA_DIR = os.path.expanduser("~/.myai")

CHATS_FILE = os.path.join(DATA_DIR, "chats.json")
CONFIG_FILE = os.path.join(DATA_DIR, "config.json")
PROMPT_HISTORY_FILE = os.path.join(DATA_DIR, "prompt_history.txt")
PROVIDER_HEALTH_FILE = os.path.join(DATA_DIR, "provider_health.json")
ANALYTICS_DB = os.path.join(DATA_DIR, "aizen.db")
KB_DIR = os.path.join(DATA_DIR, "kb")
KB_INDEX_FILE = os.path.join(KB_DIR, "faiss.index")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
VOICE_TMP_DIR = os.path.join(DATA_DIR, "tmp")
FREE_REGISTRY_FILE = os.path.join(DATA_DIR, "free_model_registry.json")

# ------------------------------------------------------------------
# DEFAULTS
# ------------------------------------------------------------------

DEFAULT_MODEL = "auto"
DEFAULT_PROVIDER_MODE = "cloud"  # cloud | local | offline
DEFAULT_STREAMING = True
DEFAULT_RAG_ENABLED = True
DEFAULT_RAG_TOP_K = 5
DEFAULT_RAG_THRESHOLD = 0.40
DEFAULT_RAG_MAX_TOKENS = 2500
DEFAULT_PROJECT_MODE = False
DEFAULT_PROJECT_MAX_TOKENS = 2500
DEFAULT_AGENT_ENABLED = False
DEFAULT_COMMAND_TIMEOUT = 120
DEFAULT_ROUTER_MODE = "AUTO"
DEFAULT_MODEL_SELECTION_MODE = "ROUTER"
DEFAULT_ROUTER_VERBOSE = False
DEFAULT_DEBUG_MODE = False
DEFAULT_FREE_VERIFICATION_DAYS = 30

# Router scoring weights (Phase 14)
DEFAULT_ROUTER_ENABLED = True
DEFAULT_ROUTER_CAPABILITY_WEIGHT = 0.40
DEFAULT_ROUTER_CONTEXT_WEIGHT    = 0.20
DEFAULT_ROUTER_HEALTH_WEIGHT     = 0.20
DEFAULT_ROUTER_RELIABILITY_WEIGHT = 0.15
DEFAULT_ROUTER_LATENCY_WEIGHT    = 0.05
DEFAULT_ROUTER_MAX_FALLBACKS     = 2

# Voice defaults (Phase 13)
DEFAULT_VOICE_ENABLED = False
DEFAULT_VOICE_INPUT_ENABLED = True
DEFAULT_VOICE_OUTPUT_ENABLED = False
DEFAULT_VOICE_STT_BACKEND = "local"
DEFAULT_VOICE_TTS_BACKEND = "local"
DEFAULT_VOICE_LANGUAGE = "auto"
DEFAULT_VOICE_SPEED = 1.0
DEFAULT_VOICE_PUSH_TO_TALK = True
DEFAULT_VOICE_MAX_SPEECH_CHARS = 3000

# ------------------------------------------------------------------
# SYSTEM PROMPT
# ------------------------------------------------------------------

SYSTEM_PROMPT = """
You are AIZEN AI.

You are a multi-model AI assistant powered through OmniRoute.

You help with:

- Programming
- Java
- Python
- JavaScript
- React
- Spring Boot
- Databases
- Cybersecurity
- Data Structures and Algorithms
- Study questions
- General questions

Maintain conversation context.

When code is requested:

- Give clean and readable code.
- Explain it simply.
- Prefer Java or Python unless another language is explicitly requested.

Be clear and useful.
"""

# Compact system prompt for local Ollama models.
# Omits cloud-routing instructions, global skill files, and tool descriptions
# that are irrelevant to local inference and would waste the limited context window.
LOCAL_SYSTEM_PROMPT = """You are AIZEN AI, a local assistant running on Ollama.

Help with programming (Java, Python, JS, React, Spring Boot), databases, cybersecurity, algorithms, and general questions.

When writing code: be clean, readable, and explain simply. Prefer Java or Python unless another language is requested.

Maintain conversation context. Be clear and concise."""

# ------------------------------------------------------------------
# UI COPY
# ------------------------------------------------------------------

AIZEN_LOGO = r"""
     █████╗ ██╗███████╗███████╗███╗   ██╗
    ██╔══██╗██║╚══███╔╝██╔════╝████╗  ██║
    ███████║██║  ███╔╝ █████╗  ██╔██╗ ██║
    ██╔══██║██║ ███╔╝  ██╔══╝  ██║╚██╗██║
    ██║  ██║██║███████╗███████╗██║ ╚████║
    ╚═╝  ╚═╝╚═╝╚══════╝╚══════╝╚═╝  ╚═══╝
"""

EXIT_DIALOGUES = [
    "Every answer only reveals another layer.",
    "Knowledge changes the moment you understand it.",
    "Until our paths cross again.",
    "The session ends. The observation continues.",
    "You may leave the conversation, but not what you learned.",
    "A conclusion is only another beginning.",
    "For now, the curtain falls."
]

# ------------------------------------------------------------------
# MUTABLE RUNTIME STATE
# (modules mutate these via:  import config; config.chats = ...)
# ------------------------------------------------------------------

chats = []

current_chat_id = None

current_model = DEFAULT_MODEL
streaming_enabled = DEFAULT_STREAMING

model_catalog = []
model_map = {}
local_model_catalog = []
local_model_map = {}
provider_mode = DEFAULT_PROVIDER_MODE
raw_model_catalog = []
raw_model_map = {}

last_displayed_models = []

last_usage = {
    "prompt_tokens": 0,
    "completion_tokens": 0,
    "total_tokens": 0,
    "actual_model": None,
    "response_time": 0.0
}

rag_enabled = DEFAULT_RAG_ENABLED
rag_top_k = DEFAULT_RAG_TOP_K
rag_similarity_threshold = DEFAULT_RAG_THRESHOLD
rag_max_context_tokens = DEFAULT_RAG_MAX_TOKENS
last_rag_sources = []

project_mode = DEFAULT_PROJECT_MODE
active_project_path = None
last_project_sources = []

# -- Phase 9: Edit system runtime state --
pending_edit = None          # dict or None — one active proposal at a time

# -- Phase 10: Terminal execution state --
agent_enabled = DEFAULT_AGENT_ENABLED
command_timeout = DEFAULT_COMMAND_TIMEOUT
startup_cwd = os.getcwd()     # captured once at import time
last_command_result = None    # CommandResult | None

# -- Phase 11: Smart Router state --
router_mode = DEFAULT_ROUTER_MODE
model_selection_mode = DEFAULT_MODEL_SELECTION_MODE
router_verbose = DEFAULT_ROUTER_VERBOSE
last_routing_decision = None
routing_history = []

# -- Phase 14: Router config weights & on/off --
router_enabled = DEFAULT_ROUTER_ENABLED
router_capability_weight  = DEFAULT_ROUTER_CAPABILITY_WEIGHT
router_context_weight     = DEFAULT_ROUTER_CONTEXT_WEIGHT
router_health_weight      = DEFAULT_ROUTER_HEALTH_WEIGHT
router_reliability_weight = DEFAULT_ROUTER_RELIABILITY_WEIGHT
router_latency_weight     = DEFAULT_ROUTER_LATENCY_WEIGHT
router_max_fallbacks      = DEFAULT_ROUTER_MAX_FALLBACKS

# -- Phase 15: Debug mode --
debug_mode = DEFAULT_DEBUG_MODE

# -- Phase 13: Free model registry state --
free_verification_days = DEFAULT_FREE_VERIFICATION_DAYS

# -- Context Budgeting & TPM Protection State --
DEFAULT_CONTEXT_BUDGET_SAFETY_FACTOR = 0.80
DEFAULT_MAX_RETRY_AFTER_WAIT = 5.0
model_context_budgets = {}
model_tpm_limits = {}
context_budget_safety_factor = DEFAULT_CONTEXT_BUDGET_SAFETY_FACTOR
max_retry_after_wait = DEFAULT_MAX_RETRY_AFTER_WAIT


# -- Phase 13: Voice mode runtime state --
voice_enabled = DEFAULT_VOICE_ENABLED
voice_input_enabled = DEFAULT_VOICE_INPUT_ENABLED
voice_output_enabled = DEFAULT_VOICE_OUTPUT_ENABLED
voice_stt_backend = DEFAULT_VOICE_STT_BACKEND
voice_tts_backend = DEFAULT_VOICE_TTS_BACKEND
voice_language = DEFAULT_VOICE_LANGUAGE
voice_speed = DEFAULT_VOICE_SPEED
voice_push_to_talk = DEFAULT_VOICE_PUSH_TO_TALK
voice_max_speech_chars = DEFAULT_VOICE_MAX_SPEECH_CHARS
voice_input_device = None
voice_output_device = None
voice_is_listening = False
voice_is_speaking = False
