import random
import string
import json
import aiofiles
from typing import Dict
import logging
from datetime import datetime
from app.config.settings import settings

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s | %(asctime)s | %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)


async def load_json_file(filename: str) -> Dict:
    """异步加载JSON文件

    Args:
        filename: JSON文件路径

    Returns:
        Dict: 加载的JSON数据
    """
    try:
        async with aiofiles.open(filename, "r") as f:
            return json.loads(await f.read())
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading {filename}: {str(e)}")
        return {}


async def save_json_file(data: Dict, filename: str) -> None:
    """异步保存JSON文件

    Args:
        data: 要保存的数据
        filename: 保存的文件路径
    """
    try:
        async with aiofiles.open(filename, "w") as f:
            await f.write(json.dumps(data, indent=2))
    except Exception as e:
        logger.error(f"Error saving {filename}: {str(e)}")
        raise


def generate_token(prefix: str = "xh", length: int = 20) -> str:
    """生成随机API密钥

    Args:
        prefix: 密钥前缀
        length: 密钥长度

    Returns:
        str: 生成的API密钥
    """
    return f"{prefix}-" + "".join(
        random.choices(string.digits + string.ascii_letters, k=length)
    )


def get_current_time() -> str:
    """获取当前北京时间

    Returns:
        str: 格式化的时间字符串
    """
    return datetime.now(settings.TIMEZONE).strftime("%Y-%m-%d %H:%M:%S")


def log_api_usage(api_key: str, usage_info: Dict) -> None:
    """记录API使用情况

    Args:
        api_key: API密钥
        usage_info: 使用情况信息
    """
    logger.info(
        f"API_key: {api_key[-6:]} | "
        f"剩余Token: {usage_info['limit'] - usage_info['usage']} | "
        f"请求次数: {usage_info['reqs']} | "
    )
