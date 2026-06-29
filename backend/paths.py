"""Re-export the path helpers from win_app.app_core.paths so the backend package
imports them under a stable name. See win_app/app_core/paths.py for the impl."""
from win_app.app_core.paths import (  # noqa: F401
    APP_NAME,
    app_home,
    bundled_dir,
    creds_dir,
    cuda_dir,
    default_data_root,
    default_ffmpeg,
    frontend_dist_dir,
    is_frozen,
    long_path,
    model_dir,
    oauth_client_path,
    token_path,
)
