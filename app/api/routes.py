import json
import os
from typing import Dict, Tuple

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.templating import Jinja2Templates

from app.config.settings import settings
from app.middleware.auth import admin_required, verify_admin
from app.models.api_models import ApiKeyUsage
from app.services.api_service import ApiService
from app.services.llm_service import LLMService
from app.utils.helpers import get_current_time, log_api_usage

router = APIRouter()

@router.get("/models")
@router.get("/v1/models")
async def list_models():
    """Get available models list"""
    try:
        with open(settings.LLM_SERVERS_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        
        models = []
        for server_url, server_info in config.items():
            device = server_info.get("device", "unknown")
            for model_id in server_info.get("model", {}).keys():
                models.append({
                    "id": model_id,
                    "object": "model",
                    "owned_by": device
                })
        
        return {
            "object": "list",
            "data": models
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error loading models: {str(e)}")

templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)


def get_services(request: Request) -> tuple[LLMService, ApiService]:
    """获取服务实例"""
    app = request.app.state.app
    return app.llm_service, app.api_service


@router.get("/get-models")
async def get_models():
    """获取可用的模型列表"""
    try:
        # 检查文件是否存在
        if not os.path.exists(settings.SERVE_MODELS_FILE):
            raise FileNotFoundError(
                f"Models configuration file not found at {settings.SERVE_MODELS_FILE}"
            )

        # 读取JSON文件
        with open(settings.SERVE_MODELS_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)

        # 验证JSON格式
        if not isinstance(config, dict) or "models" not in config:
            raise ValueError("Invalid models configuration format")

        return {"models": config["models"]}

    except FileNotFoundError as e:
        # 文件不存在时的错误处理
        raise HTTPException(status_code=500, detail=f"Configuration error: {str(e)}")
    except json.JSONDecodeError as e:
        # JSON解析错误的处理
        raise HTTPException(
            status_code=500,
            detail=f"Invalid JSON format in configuration file: {str(e)}",
        )
    except Exception as e:
        # 其他错误的处理
        raise HTTPException(status_code=500, detail=f"Error loading models: {str(e)}")


@router.get("/")
async def home():
    """首页"""
    return FileResponse(os.path.join(settings.STATIC_DIR, "index.html"))


@router.get("/login")
async def login_page(request: Request):
    """登录页面"""
    return templates.TemplateResponse("login.html", {"request": request})


@router.post("/login")
async def login(request: Request):
    """处理登录请求"""
    data = await request.json()
    username = data.get("username")
    password = data.get("password")

    if verify_admin(username, password):
        request.session["authenticated"] = True
        request.session["is_admin"] = True
        accept = request.headers.get("accept", "")
        if "application/json" in accept:
            return {"status": "success"}
        return RedirectResponse(url="/get-usage", status_code=303)

    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/logout")
async def logout(request: Request):
    """退出登录"""
    request.session.clear()
    return RedirectResponse(url="/")


@router.post("/generate-api-key")
async def generate_api_key(request: Request):
    """生成新的API密钥"""
    data = await request.json()
    phone = data.get("phone")
    if not phone:
        raise HTTPException(status_code=400, detail="Phone number is required")

    _, api_service = get_services(request)

    # 检查手机号是否已存在
    for key, info in api_service.api_usage.items():
        if info.phone == phone:
            return {"error": "该手机号已生成过API密钥"}

    new_key = api_service.generate_api_key()

    # 更新API密钥信息
    api_service.api_usage[new_key] = ApiKeyUsage(
        usage=0,
        limit=1000000,  # 100万token限额
        reqs=0,
        created_at=get_current_time(),
        phone=phone,
    )

    return {"api_key": new_key}


@router.post("/update-api-key-limit")
@admin_required
async def update_api_key_limit(request: Request):
    """更新API密钥的使用限额"""
    data = await request.json()
    api_key = data.get("api_key")
    new_limit = data.get("new_limit")

    if not api_key or new_limit is None:
        raise HTTPException(
            status_code=400, detail="API key and new limit are required"
        )

    _, api_service = get_services(request)
    if api_key in api_service.api_usage:
        api_service.api_usage[api_key].limit = new_limit
        return {"status": "success"}

    raise HTTPException(status_code=404, detail="API key not found")


@router.post("/reset-api-key-usage")
@admin_required
async def reset_api_key_usage(request: Request):
    """重置API密钥使用量"""
    data = await request.json()
    api_key = data.get("api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    _, api_service = get_services(request)
    if api_key in api_service.api_usage:
        api_service.api_usage[api_key].usage = 0
        api_service.api_usage[api_key].reqs = 0
        return {"status": "success"}

    raise HTTPException(status_code=404, detail="API key not found")


@router.post("/revoke-api-key")
@admin_required
async def revoke_api_key(request: Request):
    """撤销API密钥"""
    data = await request.json()
    api_key = data.get("api_key")
    if not api_key:
        raise HTTPException(status_code=400, detail="API key is required")

    _, api_service = get_services(request)
    if api_key in api_service.api_usage:
        del api_service.api_usage[api_key]
        return {"status": "success"}

    raise HTTPException(status_code=404, detail="API key not found")


@router.get("/get-usage", response_class=HTMLResponse)
@admin_required
async def usage_dashboard(request: Request):
    """用量统计和管理仪表盘"""
    _, api_service = get_services(request)
    stats = api_service.get_usage_stats()
    api_keys = [
        {
            "key": key,
            "phone": info.phone,
            "usage": info.usage,
            "limit": info.limit,
            "reqs": info.reqs,
            "created_at": info.created_at,
            "last_used": info.last_used if hasattr(info, "last_used") else "N/A"
        }
        for key, info in api_service.api_usage.items()
    ]
    return templates.TemplateResponse(
        "dashboard_manage.html", 
        {
            "request": request,
            **stats.dict(),
            "api_keys": api_keys,
            "current_time": get_current_time()
        }
    )


@router.options("/v1/chat/completions")
@router.options("/chat/completions")
@router.options("/v1/completions")
@router.options("/completions")
async def options_handler():
    """处理 OPTIONS 请求"""
    return Response(status_code=200)


@router.post("/v1/chat/completions")
@router.post("/chat/completions")
async def proxy_handler_chat(request: Request):
    """请求转发处理"""
    llm_service, api_service = get_services(request)

    # 身份验证
    auth_header = request.headers.get("Authorization", "")
    _, _, api_key = auth_header.partition(" ")
    api_service.validate_api_key(api_key)
    api_service.check_usage_limit(api_key)

    # 请求处理
    req_data = await request.json()
    model = req_data.get("model")

    # 获取目标服务器
    target_server = llm_service.get_target_server(model)
    target = f"{target_server}{request.url.path.replace('/v1', '', 1)}"

    # 更新初始用量
    api_service.update_usage(api_key, req_data)

    # 构造请求头
    headers = llm_service.get_auth_header(model, api_key)

    try:
        # 流式响应处理
        if req_data.get("stream", False):
            num_tokens = 0

            async def stream_wrapper():
                nonlocal num_tokens
                client_stream = await llm_service.forward_request(
                    target, req_data, headers, stream=True
                )

                async with client_stream as response:
                    async for chunk in response.aiter_text():
                        num_tokens += chunk.count(
                            'data: {"choices":[{"delta":{"content":'
                        )
                        yield chunk

                api_service.api_usage[api_key].usage += num_tokens
                log_api_usage(api_key, api_service.api_usage[api_key].dict())

            return StreamingResponse(
                stream_wrapper(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        # 普通响应处理
        response_text = await llm_service.forward_request(target, req_data, headers)

        try:
            response = json.loads(response_text)

            # 更新最终用量
            if "usage" in response:
                tokens = (
                    response["usage"]["prompt_tokens"]
                    + response["usage"]["completion_tokens"]
                )
                api_service.api_usage[api_key].usage += tokens

            log_api_usage(api_key, api_service.api_usage[api_key].dict())

            return JSONResponse(response)
        except json.JSONDecodeError as e:
            return JSONResponse(
                {"error": "Invalid response from upstream server", "message": str(e)},
                status_code=500,
            )

    except HTTPException as e:
        return JSONResponse({"error": str(e.detail)}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"error": "Internal server error"}, status_code=500)


@router.post("/v1/completions")
@router.post("/completions")
async def proxy_handler_completions(request: Request):
    """请求转发处理"""
    llm_service, api_service = get_services(request)

    # 身份验证
    auth_header = request.headers.get("Authorization", "")
    _, _, api_key = auth_header.partition(" ")
    api_service.validate_api_key(api_key)

    # 请求处理
    req_data = await request.json()
    model = req_data.get("model")

    # 获取目标服务器
    target_server = llm_service.get_target_server(model)
    target = f"{target_server}{request.url.path.replace('/v1', '', 1)}"

    # 构造请求头
    headers = llm_service.get_auth_header(model, api_key)

    try:
        # 流式响应处理
        if req_data.get("stream", False):

            async def stream_wrapper():
                client_stream = await llm_service.forward_request(
                    target, req_data, headers, stream=True
                )

                async with client_stream as response:
                    async for chunk in response.aiter_text():
                        yield chunk

            return StreamingResponse(
                stream_wrapper(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )

        # 普通响应处理
        response_text = await llm_service.forward_request(target, req_data, headers)

        try:
            response = json.loads(response_text)
            return JSONResponse(response)
        except json.JSONDecodeError as e:
            return JSONResponse(
                {"error": "Invalid response from upstream server", "message": str(e)},
                status_code=500,
            )

    except HTTPException as e:
        return JSONResponse({"error": str(e.detail)}, status_code=e.status_code)
    except Exception as e:
        return JSONResponse({"error": "Internal server error"}, status_code=500)
