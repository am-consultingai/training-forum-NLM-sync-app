import os
from pydantic import Field
from pydantic_settings import BaseSettings

from backend import paths


class Settings(BaseSettings):
    source_drive_folder_id: str = ""
    output_drive_folder_id: str = ""
    extracted_text_drive_folder_id: str = ""
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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

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
