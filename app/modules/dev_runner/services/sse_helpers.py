"""SSE pubsub 공통 헬퍼 — Redis Pub/Sub 정리 로직 일원화"""


async def safe_close_pubsub(pubsub) -> None:
    """Redis pubsub 안전 정리: punsubscribe → aclose, fallback close"""
    if pubsub is None:
        return
    try:
        await pubsub.unsubscribe()
        await pubsub.punsubscribe()
        await pubsub.aclose()
    except AttributeError:
        try:
            await pubsub.close()
        except Exception:
            pass
    except Exception:
        pass


__all__ = ["safe_close_pubsub"]
