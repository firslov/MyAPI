from functools import wraps
from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse


def login_required(func):
    """登录验证装饰器"""

    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        if not request.session.get("authenticated"):
            if request.headers.get("accept") == "application/json":
                raise HTTPException(status_code=401, detail="Authentication required")
            return RedirectResponse(url="/login")
        return await func(request, *args, **kwargs)

    return wrapper


def admin_required(func):
    """管理员验证装饰器"""

    @wraps(func)
    async def wrapper(request: Request, *args, **kwargs):
        if not request.session.get("is_admin"):
            if request.headers.get("accept") == "application/json":
                raise HTTPException(status_code=403, detail="Admin privileges required")
            return RedirectResponse(url="/login")
        return await func(request, *args, **kwargs)

    return wrapper


# 管理员凭据
ADMIN_CREDENTIALS = {"admin": "admin123"}  # 实际应用中应使用更安全的密码存储方式


def verify_admin(username: str, password: str) -> bool:
    """验证管理员凭据"""
    return ADMIN_CREDENTIALS.get(username) == password
