import pandas as pd
import requests
import uvicorn

from typing import Union, Optional

from fastapi import FastAPI, Body
from pydantic import BaseModel, Field
from tclogger import logger

from apps.arg_parser import ArgParser
from networks.constants import REGION_CODES
from networks.proxy_pool import ProxyPool, ProxyBenchmarker
from networks.video_page import VideoPageFetcher
from configs.envs import SCHEDULER_APP_ENVS, WORKER_APP_ENVS


class SchedulerApp:
    def __init__(self):
        self.app = FastAPI(
            docs_url="/",
            title=SCHEDULER_APP_ENVS["app_name"],
            swagger_ui_parameters={"defaultModelsExpandDepth": -1},
            version=SCHEDULER_APP_ENVS["version"],
        )
        self.init_tids()
        self.setup_routes()
        logger.success(
            f"> {SCHEDULER_APP_ENVS['app_name']} - v{SCHEDULER_APP_ENVS['version']}"
        )

    def init_tids(self):
        self.tid_idx = 0
        self.region_codes = ["game", "knowledge", "tech"]
        main_regions = [REGION_CODES[region_code] for region_code in self.region_codes]
        self.tids = [
            sub_region["tid"]
            for main_region in main_regions
            for sub_region in main_region["children"].values()
        ]
        logger.note(f"> Regions: {self.region_codes} => {len(self.tids)} sub-regions")

    def new_task(
        self,
        tid: int = Body(),
        pn: Optional[int] = Body(1),
        ps: Optional[int] = Body(50),
        mock: Optional[bool] = Body(True),
    ):
        logger.mesg(f"> GET: tid={tid}, pn={pn}, ps={ps}", end=" => ")

        # if tid == -1, then no more tasks
        if tid == -1:
            logger.success(f"[Finished]")
            res_json = {"code": 200, "message": "Tasks finished", "data": {}}
            return res_json

        # fetch video page info
        fetcher = VideoPageFetcher()
        res_json = fetcher.get(tid=tid, pn=pn, ps=ps, mock=mock)
        archives = res_json.get("data", {}).get("archives", [])
        res_code = res_json.get("code", -1)
        if res_code == 0 and len(archives) > 0:
            logger.success(f"[code={res_code}]")
        else:
            logger.warn(f"[code={res_code}]")
            logger.warn(f"{res_json.get('message', '')}")
        return res_json

    def next_task_params(self, tid: int, pn: int, archieve_len: int = 0):
        if archieve_len > 0:
            pn += 1
        else:
            self.tid_idx += 1
            if self.tid_idx < len(self.tids):
                tid = self.tids[self.tid_idx]
                pn = 1
            else:
                tid = -1
                pn = -1
        return tid, pn

    class VideoInfoPostItem(BaseModel):
        code: int = Field(default=0)
        message: str = Field(default="0")
        ttl: int = Field(default=1)
        data: dict = Field(default={})

    def save_video_info(self, item: VideoInfoPostItem):
        data = item.data
        logger.note(f"Video info:")
        logger.mesg(data)

    def setup_routes(self):
        self.app.post(
            "/new_task",
            summary="Create new task by: Region(tid), Page idx (pn), Page size (ps)",
        )(self.new_task)

        self.app.post(
            "/save_video_info",
            summary="Save video info to database",
        )(self.save_video_info)


app = SchedulerApp().app

if __name__ == "__main__":
    args = ArgParser(app_envs=SCHEDULER_APP_ENVS).args
    if args.reload:
        uvicorn.run("__main__:app", host=args.host, port=args.port, reload=True)
    else:
        uvicorn.run("__main__:app", host=args.host, port=args.port)

    # python -m apps.scheduler_app
