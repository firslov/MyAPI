from typing import Dict, List, Optional
import httpx
from fastapi import HTTPException
from app.models.api_models import AppState
from app.utils.helpers import logger
from app.config.settings import settings


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
            servers_data: 服务器配置数据
        """
        self.app_state.llm_servers = servers_data
        self.app_state.cloud_models.clear()
        self.app_state.model_mapping.clear()

        for server, config in servers_data.items():
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
    ) -> httpx.Response:
        """转发请求到目标服务器

        Args:
            target: 目标URL
            data: 请求数据
            headers: 请求头
            stream: 是否使用流式响应

        Returns:
            httpx.Response: 响应对象

        Raises:
            HTTPException: 请求失败时抛出
        """
        try:
            if stream:
                response = await self.http_client.post(
                    target, json=data, headers=headers, timeout=300.0
                )
                response.raise_for_status()
                return response
            else:
                response = await self.http_client.post(
                    target, json=data, headers=headers
                )
                response.raise_for_status()
                return response
        except httpx.HTTPStatusError as e:
            logger.error(f"Upstream error: {e.response.status_code}")
            raise HTTPException(
                status_code=e.response.status_code, detail=f"Upstream error: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Request failed: {str(e)}")
            raise HTTPException(
                status_code=500, detail=f"Internal server error: {str(e)}"
            )

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
