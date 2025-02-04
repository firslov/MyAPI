from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import (
    StreamingResponse,
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.templating import Jinja2Templates
import os
from typing import Dict, Optional
from datetime import datetime

from app.config.settings import settings
from app.services.llm_service import LLMService
from app.services.api_service import ApiService
from app.middleware.auth import login_required, admin_required, verify_admin
from app.models.api_models import ApiKeyUsage
from app.utils.helpers import get_current_time

router = APIRouter()
templates = Jinja2Templates(directory=settings.TEMPLATES_DIR)


def get_services(request: Request) -> tuple[LLMService, ApiService]:
    """获取服务实例"""
    app = request.app.state.app
    return app.llm_service, app.api_service


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
        return {"status": "success"}

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
        code_reqs=0,
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
        api_service.api_usage[api_key].code_reqs = 0
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
    """用量统计仪表盘"""
    _, api_service = get_services(request)
    stats = api_service.get_usage_stats()
    return templates.TemplateResponse(
        "dashboard.html", {"request": request, **stats.dict()}
    )


@router.get("/manage-keys", response_class=HTMLResponse)
@admin_required
async def manage_keys(request: Request):
    """API密钥管理页面"""
    _, api_service = get_services(request)
    api_keys = [
        {
            "key": key,
            "phone": info.phone,
            "usage": info.usage,
            "limit": info.limit,
            "created_at": info.created_at,
        }
        for key, info in api_service.api_usage.items()
    ]
    return templates.TemplateResponse(
        "apikey_manage.html", {"request": request, "api_keys": api_keys}
    )


@router.post("/v1/chat/completions")
@router.post("/v1/completions")
async def proxy_handler(request: Request):
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
    is_chat = "chat" in request.url.path
    api_service.update_usage(api_key, req_data, is_chat)

    # 构造请求头
    headers = llm_service.get_auth_header(model, api_key)

    # 流式响应处理
    if req_data.get("stream", False):

        async def stream_wrapper():
            try:
                response = await llm_service.forward_request(
                    target, req_data, headers, stream=True
                )
                async for chunk in response.aiter_text():
                    yield chunk
            except Exception as e:
                yield str(e)
            finally:
                await response.aclose()

        return StreamingResponse(stream_wrapper(), media_type="application/json")

    # 普通响应处理
    try:
        response = await llm_service.forward_request(target, req_data, headers)
        response_data = await response.json()
        await response.aclose()

        # 更新最终用量
        if is_chat:
            api_service.update_final_usage(api_key, response_data)

        return JSONResponse(response_data)
    except HTTPException as e:
        return JSONResponse({"error": str(e.detail)}, status_code=e.status_code)
