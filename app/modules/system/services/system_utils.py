"""
System utility helpers — run_admin_command, send_redis_command
"""
import asyncio
import json


async def run_admin_command(ps_cmd: str, success_msg: str) -> dict:
    """Execute a PowerShell command (may require admin privileges)"""
    try:
        proc = await asyncio.create_subprocess_shell(
            f'powershell -Command "{ps_cmd}"',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15)

        if proc.returncode == 0:
            return {"success": True, "message": success_msg}
        else:
            error_msg = stderr.decode('utf-8', errors='replace') if stderr else "Unknown error"
            return {"success": False, "message": error_msg}
    except Exception as e:
        return {"success": False, "message": str(e)}


async def send_redis_command(
    redis_client,
    cmd_key: str,
    result_key: str,
    command: str,
    timeout: int = 30,
    timeout_msg: str | None = None,
) -> dict:
    """delete→lpush→brpop 패턴 공통 헬퍼.

    Args:
        redis_client: async Redis client
        cmd_key: 명령 큐 키 (e.g. "infra:commands")
        result_key: 결과 큐 키 (e.g. "infra:command_results")
        command: JSON 직렬화된 명령 문자열
        timeout: brpop 타임아웃 (초)
        timeout_msg: 타임아웃 시 반환 메시지 (None이면 기본 메시지)
    """
    try:
        await redis_client.delete(result_key)
        await redis_client.lpush(cmd_key, command)

        result = await redis_client.brpop(result_key, timeout=timeout)
        if result:
            _, result_data = result
            result_json = json.loads(result_data) if isinstance(result_data, str) else json.loads(result_data.decode())
            return {"success": result_json.get("success", False), "message": result_json.get("message", "완료")}
        else:
            msg = timeout_msg or f"응답 타임아웃 ({timeout}초)"
            return {"success": False, "message": msg}
    except Exception as e:
        return {"success": False, "message": f"Redis 명령 전송 실패: {str(e)}"}
