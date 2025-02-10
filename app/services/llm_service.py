import json
from typing import Dict, Optional, Union

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

    async def forward_request(
        self, target: str, data: Dict, headers: Dict, stream: bool = False
    ) -> Union[httpx.Response, str]:
        """转发请求到目标服务器，如果model有映射关系，则使用映射后的模型名"""
        if "model" in data and data["model"] in self.app_state.model_name_mapping:
            data = data.copy()
            data["model"] = self.app_state.model_name_mapping[data["model"]]
        try:
            if stream:
                # 直接返回 Response 对象，不要 await
                return self.http_client.stream(
                    "POST", target, json=data, headers=headers, timeout=300.0
                )

            # 非流式请求
            response = await self.http_client.post(
                target, json=data, headers=headers, timeout=None
            )
            response.raise_for_status()

            return response.text

        except httpx.HTTPStatusError as exc:
            logger.error(f"Upstream error: {exc.response.status_code}")
            if stream:
                return exc.response
            error_detail = {
                "error": f"LLM_SERVER 响应状态码 {exc.response.status_code}",
                "message": str(exc),
            }
            return json.dumps(error_detail)
        except Exception as exc:
            logger.error(f"Request failed: {str(exc)}")
            if stream:
                return httpx.Response(status_code=500, text=str(exc))
            error_detail = {
                "error": "与 LLM_SERVER 通信时出现网络错误",
                "message": str(exc),
            }
            return json.dumps(error_detail)

    def get_target_server(self, model: str) -> str:
        """获取目标服务器

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
        return servers[0]  # 可以实现负载均衡策略

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
