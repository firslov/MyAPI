import json
from typing import Dict, Optional, Union, List
from collections import defaultdict
import time

import httpx
from fastapi import HTTPException

from app.config.settings import settings
from app.models.api_models import AppState
from app.utils.helpers import logger


class LLMService:
    """LLM服务管理类"""

    def __init__(self):
        self.http_client: Optional[httpx.AsyncClient] = None
        self.app_state = AppState()
        self._server_health = defaultdict(lambda: {"healthy": True, "last_check": 0})
        self._server_counters = defaultdict(int)

    async def initialize(self) -> None:
        """初始化HTTP客户端"""
        self.http_client = httpx.AsyncClient(**settings.HTTP_CLIENT_CONFIG)

    async def cleanup(self) -> None:
        """清理资源"""
        if self.http_client:
            await self.http_client.aclose()

    def init_llm_resources(self, servers_data: Dict) -> None:
        """初始化LLM资源

        Args:
            servers_data: 服务器配置数据，model字段为key-value形式，key为客户使用的模型名，value为实际转发的模型名
        """
        self.app_state.llm_servers = servers_data
        self.app_state.cloud_models.clear()
        self.app_state.model_mapping.clear()
        self.app_state.model_name_mapping = {}  # 存储模型名称映射关系

        for server, config in servers_data.items():
            if isinstance(config["model"], dict):
                for client_model, target_model in config["model"].items():
                    self.app_state.model_mapping[client_model].append(server)
                    self.app_state.model_name_mapping[client_model] = target_model
                    if "apikey" in config:
                        self.app_state.cloud_models[client_model] = config["apikey"]
            else:
                # 兼容旧格式
                models = (
                    [config["model"]]
                    if isinstance(config["model"], str)
                    else config["model"]
                )
                for model in models:
                    self.app_state.model_mapping[model].append(server)
                    if "apikey" in config:
                        self.app_state.cloud_models[model] = config["apikey"]

    def _update_server_health(self, server: str, is_healthy: bool) -> None:
        """更新服务器健康状态"""
        self._server_health[server].update(
            {"healthy": is_healthy, "last_check": time.time()}
        )

    def _get_healthy_servers(self, servers: List[str]) -> List[str]:
        """获取健康的服务器列表"""
        current_time = time.time()
        health_check_interval = 60  # 1分钟检查间隔

        healthy_servers = []
        for server in servers:
            health_info = self._server_health[server]
            if (current_time - health_info["last_check"]) > health_check_interval:
                health_info["healthy"] = True  # 重置状态，给机会重试
            if health_info["healthy"]:
                healthy_servers.append(server)

        return healthy_servers or servers  # 如果没有健康服务器，返回所有服务器

    def get_target_server(self, model: str) -> str:
        """获取目标服务器，使用轮询负载均衡

        Args:
            model: 模型名称

        Returns:
            str: 目标服务器URL

        Raises:
            HTTPException: 不支持的模型
        """
        servers = self.app_state.model_mapping.get(model, [])
        if not servers:
            raise HTTPException(400, f"Unsupported model: {model}")

        healthy_servers = self._get_healthy_servers(servers)

        # 使用轮询策略选择服务器
        server_index = self._server_counters[model] % len(healthy_servers)
        self._server_counters[model] += 1

        # 如果计数太大，重置以避免溢出
        if self._server_counters[model] > 10000:
            self._server_counters[model] = 0

        return healthy_servers[server_index]

    async def forward_request(
        self, target: str, data: Dict, headers: Dict, stream: bool = False
    ) -> Union[httpx.Response, str]:
        """转发请求到目标服务器，如果model有映射关系，则使用映射后的模型名"""
        if "model" in data and data["model"] in self.app_state.model_name_mapping:
            data = data.copy()
            data["model"] = self.app_state.model_name_mapping[data["model"]]

        try:
            # 设置重试策略
            retries = 2
            last_error = None

            while retries >= 0:
                try:
                    if stream:
                        return self.http_client.stream(
                            "POST", target, json=data, headers=headers
                        )

                    response = await self.http_client.post(
                        target, json=data, headers=headers
                    )
                    response.raise_for_status()
                    self._update_server_health(target, True)  # 标记服务器为健康
                    return response.text

                except httpx.HTTPStatusError as exc:
                    last_error = exc
                    logger.error(f"HTTP error for {target}: {exc.response.status_code}")
                    self._update_server_health(target, False)  # 标记服务器为不健康
                    if exc.response.status_code >= 500:  # 只有服务器错误才重试
                        retries -= 1
                        if retries >= 0:
                            await self.http_client.aclose()  # 关闭连接以确保重新建立
                            self.http_client = httpx.AsyncClient(
                                **settings.HTTP_CLIENT_CONFIG
                            )
                            continue
                    break

                except Exception as exc:
                    last_error = exc
                    logger.error(f"Network error for {target}: {str(exc)}")
                    self._update_server_health(target, False)
                    retries -= 1
                    if retries >= 0:
                        await self.http_client.aclose()
                        self.http_client = httpx.AsyncClient(
                            **settings.HTTP_CLIENT_CONFIG
                        )
                        continue
                    break

            # 处理最终错误
            if isinstance(last_error, httpx.HTTPStatusError):
                if stream:
                    return last_error.response
                error_detail = {
                    "error": f"LLM_SERVER 响应状态码 {last_error.response.status_code}",
                    "message": str(last_error),
                }
            else:
                if stream:
                    return httpx.Response(status_code=500, text=str(last_error))
                error_detail = {
                    "error": "与 LLM_SERVER 通信时出现网络错误",
                    "message": str(last_error),
                }
            return json.dumps(error_detail)

        except Exception as exc:
            logger.error(f"Unexpected error: {str(exc)}")
            if stream:
                return httpx.Response(status_code=500, text=str(exc))
            return json.dumps(
                {
                    "error": "处理请求时发生意外错误",
                    "message": str(exc),
                }
            )

    def get_auth_header(self, model: str, api_key: str) -> Dict[str, str]:
        """生成认证头

        Args:
            model: 模型名称
            api_key: API密钥

        Returns:
            Dict[str, str]: 认证头
        """
        return {
            "Authorization": f"Bearer {self.app_state.cloud_models.get(model, api_key)}",
            "Content-Type": "application/json",
        }
