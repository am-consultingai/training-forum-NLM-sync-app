import os
import sys
from pydantic import Field
from pydantic_settings import BaseSettings

from backend import paths

# In the packaged (PyInstaller) app, do NOT read a stray ./.env from whatever
# directory the exe happens to be launched from — it can silently hijack the model
# path and the data_dir (i.e. which database the app uses) based on launch location.
# Frozen → real env vars + bundled defaults only. In dev (not frozen), .env is honored.
_ENV_FILE = None if getattr(sys, "frozen", False) else ".env"


class Settings(BaseSettings):
    # Shipped defaults — the Training Forum Drive folders. These travel with the
    # build (this module is bundled into the exe), so a fresh install syncs with no
    # folder setup required. A user can still override any of them via the Settings
    # UI (persisted to app_config.json, which wins) or an env var, but they don't
    # have to. Keep these in sync with the canonical folders:
    #   source   = original content   https://drive.google.com/drive/folders/1jl82g-J8vJfF6kzIW7CWpRJg9WMYOm-6
    #   output   = chunks             https://drive.google.com/drive/folders/1aDD62rFx8FYHsHIs_N3awduvolzu0YR1
    #   mirror   = extracted text     https://drive.google.com/drive/folders/1qsgaST-n_XBN0aDwUtcF4c-uBfoefXql
    source_drive_folder_id: str = "1jl82g-J8vJfF6kzIW7CWpRJg9WMYOm-6"
    output_drive_folder_id: str = "1aDD62rFx8FYHsHIs_N3awduvolzu0YR1"
    extracted_text_drive_folder_id: str = "1qsgaST-n_XBN0aDwUtcF4c-uBfoefXql"
    # Defaults resolve to per-user / bundled locations so the packaged app works
    # with no .env present. Env vars (GOOGLE_CREDENTIALS_PATH, etc.) still override
    # for development.
    google_credentials_path: str = Field(default_factory=paths.oauth_client_path)
    google_token_path: str = Field(default_factory=paths.token_path)
    whisper_model_path: str = Field(default_factory=paths.model_dir)
    whisper_device: str = "auto"
    whisper_compute_type: str = "auto"
    ffmpeg_path: str = Field(default_factory=paths.default_ffmpeg)
    data_dir: str = Field(default_factory=paths.default_data_root)
    sync_schedule_hour: int = 2
    sync_schedule_minute: int = 0
    max_upload_retries: int = 3
    # The daily cron is disabled by default (manual-sync only in the packaged app).
    # Set ENABLE_SCHEDULER=1 to run the background daily sync (e.g. for dev).
    enable_scheduler: bool = False

    model_config = {"env_file": _ENV_FILE, "env_file_encoding": "utf-8"}

    @property
    def downloads_dir(self) -> str:
        return os.path.join(self.data_dir, "downloads")

    @property
    def transcripts_dir(self) -> str:
        return os.path.join(self.data_dir, "transcripts")

    # The local extracted-text mirror (alias of transcripts_dir, kept for clarity:
    # this tree now mirrors the source structure and is synced to Drive).
    @property
    def extracted_text_dir(self) -> str:
        return self.transcripts_dir

    @property
    def chunks_dir(self) -> str:
        return os.path.join(self.data_dir, "chunks")

    @property
    def db_path(self) -> str:
        return os.path.join(self.data_dir, "sync.db")


settings = Settings()
