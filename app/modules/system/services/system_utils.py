"""
System utility helpers — run_admin_command, send_redis_command
"""
import asyncio
import json
import uuid


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
    """Redis command를 enqueue하고 command id를 즉시 반환한다.

    Args:
        redis_client: async Redis client
        cmd_key: 명령 큐 키 (e.g. "infra:commands")
        result_key: 결과 큐 키 (e.g. "infra:command_results")
        command: JSON 직렬화된 명령 문자열
        timeout: legacy 인자. accepted/status 전환 후 request path에서 대기하지 않는다.
        timeout_msg: legacy 인자. accepted/status 전환 후 request path에서 대기하지 않는다.
    """
    try:
        payload = json.loads(command)
        command_id = payload.get("command_id") or uuid.uuid4().hex[:12]
        payload["command_id"] = command_id
        payload["result_key"] = f"{result_key}:{command_id}"
        await redis_client.delete(payload["result_key"])
        await redis_client.lpush(cmd_key, json.dumps(payload, ensure_ascii=False))
        return {
            "success": True,
            "status": "accepted",
            "command_id": command_id,
            "result_key": payload["result_key"],
            "message": "명령이 접수되었습니다.",
        }
    except Exception as e:
        return {"success": False, "message": f"Redis 명령 전송 실패: {str(e)}"}


async def get_redis_command_result(redis_client, result_key: str, command_id: str) -> dict:
    """command-specific result key에서 결과를 non-blocking 조회한다."""
    key = f"{result_key}:{command_id}"
    try:
        raw = await redis_client.lindex(key, 0)
        if raw is None:
            return {
                "success": True,
                "status": "pending",
                "command_id": command_id,
                "message": "명령 처리 대기 중입니다.",
            }
        data = json.loads(raw) if isinstance(raw, str) else json.loads(raw.decode())
        return {
            "success": bool(data.get("success", False)),
            "status": "completed" if data.get("success", False) else "failed",
            "command_id": command_id,
            "message": data.get("message", "완료"),
            "result": data,
        }
    except Exception as e:
        return {
            "success": False,
            "status": "failed",
            "command_id": command_id,
            "message": f"Redis 명령 결과 조회 실패: {str(e)}",
        }
