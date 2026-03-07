from pathlib import Path

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# ── 顯式載入 .env ──────────────────────────────────────────────────────────────
# 以 config.py 所在位置為基準（soul/core/），往上兩層抵達專案根目錄
# 這樣無論從哪個工作目錄啟動，都能正確載入 .env
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
_DOTENV_PATH: Path = _PROJECT_ROOT / ".env"

load_dotenv(_DOTENV_PATH, override=False)   # override=False：不覆蓋已有的系統環境變數


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(_DOTENV_PATH),         # 傳入絕對路徑，pydantic-settings 二次讀取
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Provider 選擇：「anthropic」直連 Claude，「openrouter」透過 OpenRouter 路由
    soul_llm_provider: str = Field("anthropic", alias="SOUL_LLM_PROVIDER")

    # Anthropic
    anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")

    # OpenRouter
    openrouter_api_key: str = Field("", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = Field("https://openrouter.ai/api/v1", alias="OPENROUTER_BASE_URL")
    openrouter_app_name: str = Field("openSOUL", alias="OPENROUTER_APP_NAME")

    # OpenAI（用於 Embedding）
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    soul_llm_model: str = Field("claude-sonnet-4-6", alias="SOUL_LLM_MODEL")
    soul_llm_temperature: float = Field(0.3, alias="SOUL_LLM_TEMPERATURE")
    soul_embedding_model: str = Field("text-embedding-3-small", alias="SOUL_EMBEDDING_MODEL")
    soul_embedding_dim: int = Field(1536, alias="SOUL_EMBEDDING_DIM")

    # FalkorDB
    falkordb_host: str = Field("localhost", alias="FALKORDB_HOST")
    falkordb_port: int = Field(6379, alias="FALKORDB_PORT")
    falkordb_password: str = Field("", alias="FALKORDB_PASSWORD")

    # Project root (for skill execution)
    soul_project_root: Path = Field(default_factory=lambda: _PROJECT_ROOT, description="Project root directory")

    # Workspace
    soul_workspace_path: Path = Field(Path("./workspace"), alias="SOUL_WORKSPACE_PATH")

    # Graph names
    soul_semantic_graph: str = Field("soul_semantic", alias="SOUL_SEMANTIC_GRAPH")
    soul_episodic_graph: str = Field("soul_episodic", alias="SOUL_EPISODIC_GRAPH")
    soul_procedural_graph: str = Field("soul_procedural", alias="SOUL_PROCEDURAL_GRAPH")

    # Edge weight params
    soul_weight_alpha: float = Field(0.3, alias="SOUL_WEIGHT_ALPHA")
    soul_weight_beta: float = Field(0.4, alias="SOUL_WEIGHT_BETA")
    soul_weight_gamma: float = Field(0.3, alias="SOUL_WEIGHT_GAMMA")
    soul_decay_lambda: float = Field(0.01, alias="SOUL_DECAY_LAMBDA")
    soul_prune_threshold: float = Field(0.05, alias="SOUL_PRUNE_THRESHOLD")

    # Gating
    soul_verify_max_retries: int = Field(3, alias="SOUL_VERIFY_MAX_RETRIES")
    soul_verify_threshold: float = Field(0.6, alias="SOUL_VERIFY_THRESHOLD")

    # Dream Engine
    soul_dream_idle_minutes: int = Field(5, alias="SOUL_DREAM_IDLE_MINUTES")
    soul_dream_cron: str = Field("0 3 * * *", alias="SOUL_DREAM_CRON")
    soul_dream_replay_da_threshold: float = Field(0.7, alias="SOUL_DREAM_REPLAY_DA_THRESHOLD")

    # FastAPI
    soul_api_host: str = Field("0.0.0.0", alias="SOUL_API_HOST")
    soul_api_port: int = Field(8000, alias="SOUL_API_PORT")
    soul_api_reload: bool = Field(True, alias="SOUL_API_RELOAD")

    # Gmail IMAP
    gmail_address: str = Field("", alias="GMAIL_ADDRESS")
    gmail_app_password: str = Field("", alias="GMAIL_APP_PASSWORD")
    gmail_check_interval_minutes: int = Field(5, alias="GMAIL_CHECK_INTERVAL_MINUTES")

    @property
    def workspace_path(self) -> Path:
        return Path(self.soul_workspace_path)

    @property
    def soul_md_path(self) -> Path:
        return self.workspace_path / "SOUL.md"

    @property
    def memory_md_path(self) -> Path:
        return self.workspace_path / "MEMORY.md"

    @property
    def daily_log_dir(self) -> Path:
        return self.workspace_path / "memory"


settings = Settings()

import logging
logger = logging.getLogger("soul")
