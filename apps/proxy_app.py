import pandas as pd
import threading
import uvicorn

from typing import Optional, List, Literal

from fastapi import FastAPI
from tclogger import logger

from apps.arg_parser import ArgParser
from configs.envs import PROXY_APP_ENVS
from networks.proxy_pool import ProxyPool, ProxyBenchmarker


class ProxiesDatabase:
    COLUMN_DTYPES = {
        "server": str,
        "latency": float,
        "last_checked": "datetime64[ns]",
    }
    COLUMNS = list(COLUMN_DTYPES.keys())
    INDEX_COLUMNS = ["server"]

    def __init__(self):
        self.init_df()
        self.lock = threading.Lock()

    def init_df(self):
        # create a pandas dataframe to store good proxies
        # columns: server(ip:port):str, latency:float, last_checked:datetime
        self.df_good = self.default_df()
        self.df_bad = self.default_df()
        self.df_using = self.default_df()

    def default_df(self):
        df = pd.DataFrame(columns=self.COLUMNS).astype(self.COLUMN_DTYPES)
        df = df.set_index(self.INDEX_COLUMNS)
        return df

    def add_proxy(
        self,
        server: str,
        latency: float,
        status: Literal["good", "bad", "using"] = "good",
    ):
        new_item = {
            "latency": latency,
            "last_checked": pd.Timestamp.now(),
        }
        new_row = pd.Series(new_item)

        with self.lock:
            if status == "good":
                logger.success(f"+ Add good proxy: [{latency:.2f}s] {server}")
                self.df_good.loc[server] = new_row
            elif status == "bad":
                logger.back(f"x Add bad proxy: {server}")
                self.df_bad.loc[server] = new_row
            elif status == "using":
                logger.note(f"= Add using proxy: {server}")
                self.df_using.loc[server] = new_row
            else:
                logger.warn(f"Unknown proxy status: {status}")

    def add_good_proxy(self, server: str, latency: float):
        self.add_proxy(server, latency, "good")

    def add_bad_proxy(self, server: str):
        self.add_proxy(server, -1, "bad")

    def add_using_proxy(self, server: str, latency: float):
        self.add_proxy(server, latency, "using")

    def get_good_proxies_list(self) -> List[str]:
        return self.df_good.index.tolist()

    def get_bad_proxies_list(self) -> List[str]:
        return self.df_bad.index.tolist()

    def get_using_proxies_list(self) -> List[str]:
        return self.df_using.index.tolist()

    def empty_good_proxies(self):
        old_good_proxies = self.get_good_proxies_list()
        self.df_good = self.default_df()
        logger.success(f"> Empty {len(old_good_proxies)} good proxies")
        return old_good_proxies

    def empty_bad_proxies(self):
        old_bad_proxies = self.get_bad_proxies_list()
        self.df_bad = self.default_df()
        logger.success(f"> Empty {len(old_bad_proxies)} bad proxies")
        return old_bad_proxies

    def empty_using_proxies(self):
        old_using_proxies = self.get_using_proxies_list()
        self.df_using = self.default_df()
        logger.success(f"> Empty {len(old_using_proxies)} using proxies")
        return old_using_proxies


class ProxyApp:
    def __init__(self):
        self.app = FastAPI(
            docs_url="/",
            title=PROXY_APP_ENVS["app_name"],
            swagger_ui_parameters={"defaultModelsExpandDepth": -1},
            version=PROXY_APP_ENVS["version"],
        )
        self.db = ProxiesDatabase()
        self.setup_routes()
        logger.success(f"> {PROXY_APP_ENVS['app_name']} - v{PROXY_APP_ENVS['version']}")

    def refresh_proxies(self):
        logger.note(f"> Refreshing proxies")
        proxies = ProxyPool().get_proxies_list()
        proxies = list(set(proxies))
        benchmarker = ProxyBenchmarker()
        old_good_proxies = self.db.get_good_proxies_list()
        old_bad_proxies = self.db.get_bad_proxies_list()
        self.db.empty_good_proxies()
        proxies_to_test = list(set(proxies + old_good_proxies) - set(old_bad_proxies))
        logger.mesg(
            f"  - Retest {len(old_good_proxies)} good proxies, and skip {len(old_bad_proxies)} bad proxies\n"
            f"  - Test {len(proxies_to_test)} new proxies"
        )
        benchmarker.batch_test_proxy(
            proxies_to_test,
            good_callback=self.db.add_good_proxy,
            bad_callback=self.db.add_bad_proxy,
        )
        res = {
            "total": len(proxies),
            "usable": len(self.db.df_good),
            "status": "refreshed",
        }
        return res

    def get_all_proxies(self):
        logger.note(f"> Return all proxies")

    # ANCHOR[id=get_proxy]
    def get_proxy(self, mock: Optional[bool] = False):
        if mock:
            res = {
                "server": "mock",
                "latency": 0.0,
                "status": "ok",
            }
        else:
            # get the proxy with lowest latency and not in using list
            good_rows = self.db.df_good.sort_values("latency")
            using_rows = self.db.df_using
            usable_rows = good_rows[~good_rows.index.isin(using_rows.index)]
            if usable_rows.empty:
                logger.warn(f"> No usable proxy")
                res = {
                    "server": "No usable proxy",
                    "latency": -1,
                    "status": "error",
                }
            else:
                res = {
                    "server": usable_rows.index[0],
                    "latency": usable_rows.iloc[0]["latency"],
                    "status": "ok",
                }
                self.db.add_using_proxy(res["server"], res["latency"])

        logger.success(
            f"> Get proxy: {res['server']}, latency={res['latency']:.2f}s, status={res['status']}"
        )

        return res

    def del_proxy(self, server: str):
        logger.warn(f"> Delete proxy: {server}")
        res = {
            "server": server,
            "status": "deleted",
        }
        return res

    # ANCHOR[id=reset_using_proxies]
    def reset_using_proxies(self):
        old_using_proxies = self.db.empty_using_proxies()
        message = f"Reset {len(old_using_proxies)} using proxies"
        logger.warn(f"> {message}")
        res = {
            "message": message,
            "status": "ok",
        }
        return res

    def setup_routes(self):
        self.app.get(
            "/all_proxies",
            summary="Get all proxies",
        )(self.get_all_proxies)

        self.app.get(
            "/get_proxy",
            summary="Get a usable proxy",
        )(self.get_proxy)

        self.app.delete(
            "/del_proxy",
            summary="Delete a proxy",
        )(self.del_proxy)

        self.app.post(
            "/reset_using_proxies",
            summary="Reset using proxies",
        )(self.reset_using_proxies)

        self.app.post(
            "/refresh_proxies",
            summary="Refresh IP Proxies with benchmarker",
        )(self.refresh_proxies)


app = ProxyApp().app

if __name__ == "__main__":
    args = ArgParser(app_envs=PROXY_APP_ENVS).args
    if args.reload:
        uvicorn.run("__main__:app", host=args.host, port=args.port, reload=True)
    else:
        uvicorn.run("__main__:app", host=args.host, port=args.port)

    # python -m apps.proxy_app
