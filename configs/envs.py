from pathlib import Path

from tclogger import OSEnver

configs_root = Path(__file__).parents[1] / "configs"
envs_path = configs_root / "envs.json"

PROXY_APP_ENVS = OSEnver(envs_path)["proxy_app"]
SCHEDULER_APP_ENVS = OSEnver(envs_path)["scheduler_app"]
VIDEO_PAGE_API_MOCKER_ENVS = OSEnver(envs_path)["video_page_api_mocker"]
WORKER_APP_ENVS = OSEnver(envs_path)["worker_app"]

secrets_path = configs_root / "secrets.json"
SECRETS = OSEnver(secrets_path)
