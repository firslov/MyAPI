import asyncio
import signal
import sys
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles

from app.config.settings import settings
from app.models.api_models import ApiKeyUsage
from app.services.api_service import ApiService
from app.services.llm_service import LLMService
from app.utils.helpers import load_json_file, save_json_file, logger


class Application:
    """应用程序核心类，负责管理应用的生命周期和核心服务"""

    def __init__(self):
        self.llm_service = LLMService()
        self.api_service = ApiService()
        self.background_tasks: Set[asyncio.Task] = set()

    async def startup(self) -> None:
        """应用启动初始化"""
        # 初始化服务
        await self.llm_service.initialize()
        
        # 使用ApiService缓存的配置初始化LLM资源
        self.llm_service.init_llm_resources(self.api_service.llm_servers_cache)
        
        # 加载API密钥使用情况
        api_usage_data = await load_json_file(settings.API_KEYS_FILE)
        self.api_service.api_usage = {
            key: ApiKeyUsage(**data) for key, data in api_usage_data.items()
        }

        # 启动后台任务
        self._start_background_tasks()

    async def shutdown(self) -> None:
        """应用关闭清理"""
        # 取消后台任务
        for task in self.background_tasks:
            task.cancel()

        # 等待任务完成
        if self.background_tasks:
            await asyncio.gather(*self.background_tasks, return_exceptions=True)

        # 清理资源
        await self.llm_service.cleanup()
        # 转换为可序列化的字典
        usage_data = {
            key: model.dict() for key, model in self.api_service.api_usage.items()
        }
        await save_json_file(usage_data, settings.API_KEYS_FILE)

    def _start_background_tasks(self) -> None:
        """启动后台任务"""
        task = self._periodic_save_task()
        bg_task = asyncio.create_task(task)
        self.background_tasks.add(bg_task)
        bg_task.add_done_callback(self.background_tasks.discard)

    async def _periodic_save_task(self) -> None:
        """定期保存任务"""
        while True:
            await asyncio.sleep(settings.CACHE_TTL)

            # 保存API使用情况
            usage_data = {
                key: model.dict() for key, model in self.api_service.api_usage.items()
            }
            await save_json_file(usage_data, settings.API_KEYS_FILE)

            # 更新LLM服务器列表（使用ApiService缓存）
            current_servers_data = self.api_service.llm_servers_cache
            if current_servers_data != self.llm_service.app_state.llm_servers:
                self.llm_service.init_llm_resources(current_servers_data)
                logger.info("LLM servers list updated")


def create_application() -> FastAPI:
    """创建FastAPI应用实例"""
    app = Application()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI):
        # 启动
        await app.startup()
        yield
        # 关闭
        await app.shutdown()

    # 创建FastAPI应用
    fastapi_app = FastAPI(lifespan=lifespan)

    # 配置中间件
    # 添加受信任主机中间件
    fastapi_app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=[
            "api.aihao.world",
            "localhost",
            "localhost:8087",
            "0.0.0.0:8087",
            "0.0.0.0",
        ],
    )

    # 配置CORS
    origins = [
        "http://localhost:8087",
        "https://api.aihao.world",
        "http://api.aihao.world",
        "http://0.0.0.0:8087",
    ]
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["set-cookie"],
    )

    # 配置静态文件和模板
    fastapi_app.mount(
        "/static", StaticFiles(directory=settings.STATIC_DIR), name="static"
    )

    # 注册信号处理
    signal.signal(signal.SIGINT, lambda s, f: sys.exit(0))

    # 保存应用实例
    fastapi_app.state.app = app

    return fastapi_app
