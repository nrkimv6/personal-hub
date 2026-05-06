"""
AI 분류 라우터

LLMWorker 큐 방식으로 이미지 분류 수행.
API(Session 0)에서 enqueue → LLMWorker(Session 1)에서 CLI 실행 → 결과 폴링.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from sqlalchemy import text
from pydantic import BaseModel
from typing import Optional, List
import asyncio
import json
import logging
import time

from ..database import get_db
from ..config import settings as ic_settings

router = APIRouter(prefix="/classify", tags=["classify"])
logger = logging.getLogger(__name__)

# 전역 상태 (실제 프로덕션에서는 Redis 등 사용)
classification_status = {
    "running": False,
    "total": 0,
    "processed": 0,
    "failed": 0,
    "current_file": None,
    "model": None,
}


CLI_MAX_WORKERS = 2  # 동시 enqueue 수 (폴링 병렬 제어)

# 폴링 설정
POLL_INTERVAL_SECONDS = 2
POLL_TIMEOUT_SECONDS = 180  # 3분


class ClassifyRequest(BaseModel):
    """AI 분류 요청"""
    file_ids: Optional[List[int]] = None  # None이면 전체 미분류 파일
    model: str = "claude_cli"  # claude_cli, gemini_cli
    batch_size: int = 10
    gap_minutes: int = 60  # 시간 클러스터링 간격
    max_workers: int = CLI_MAX_WORKERS  # 동시 호출 수


class SmartClassifyRequest(BaseModel):
    """스마트 AI 분류 요청"""
    model: str = "claude_cli"
    batch_size: int = 10
    gap_minutes: int = 60
    max_workers: int = CLI_MAX_WORKERS
    similarity_threshold: float = 0.85  # CLIP 유사도 임계값


class ClassifyResponse(BaseModel):
    """분류 응답"""
    message: str
    total: int
    status: str


@router.post("/start", response_model=ClassifyResponse)
async def start_classification(
    background_tasks: BackgroundTasks,
    request: Optional[ClassifyRequest] = None,
    db: Session = Depends(get_db),
):
    """
    AI 분류 시작 (백그라운드 작업)
    """
    global classification_status
    if request is None:
        request = ClassifyRequest()

    if classification_status["running"]:
        raise HTTPException(status_code=400, detail="Classification already running")

    # 분류할 파일 조회 (이미 AI 분류 완료된 파일 제외 = resume 지원)
    if request.file_ids:
        placeholders = ",".join(str(int(fid)) for fid in request.file_ids)
        query = text(f"""
            SELECT id, file_path
            FROM file_classifications
            WHERE id IN ({placeholders})
              AND (status = 'pending' OR (status = 'folder_mapped' AND ai_category_id IS NULL))
        """)
        files = db.execute(query).fetchall()
    else:
        query = text("""
            SELECT id, file_path
            FROM file_classifications
            WHERE status = 'pending' OR (status = 'folder_mapped' AND ai_category_id IS NULL)
            ORDER BY id
        """)
        files = db.execute(query).fetchall()

    total = len(files)

    if total == 0:
        raise HTTPException(status_code=400, detail="No files to classify")

    # 상태 초기화
    classification_status = {
        "running": True,
        "total": total,
        "processed": 0,
        "failed": 0,
        "current_file": None,
        "model": request.model,
    }

    # 백그라운드 작업 시작
    background_tasks.add_task(
        run_classification,
        files,
        request.model,
        request.batch_size,
        request.gap_minutes,
        request.max_workers,
    )

    return ClassifyResponse(
        message=f"Classification started for {total} files",
        total=total,
        status="running",
    )


@router.get("/status")
async def get_status(db: Session = Depends(get_db)):
    """분류 진행 상태 조회 — 메모리 우선, DB fallback"""
    if classification_status["running"]:
        return classification_status

    # DB에서 최신 작업 조회
    from ..workers.task_progress import TaskProgressManager
    progress_mgr = TaskProgressManager(db)
    latest = progress_mgr.get_latest('ai_classify')

    if latest:
        total = latest["total_items"] or 0
        processed = latest["processed_items"] or 0
        # 완료된 작업이면 실패 건수 = total - processed
        failed = max(0, total - processed) if latest["status"] in ("completed", "failed") else 0
        return {
            "running": latest["status"] == "running",
            "total": total,
            "processed": processed,
            "failed": failed,
            "current_file": latest["current_item"],
            "model": None,
            "status": latest["status"],
            "error": latest["error_message"],
        }

    return classification_status


@router.post("/stop")
async def stop_classification():
    """분류 중지"""
    global classification_status

    if not classification_status["running"]:
        raise HTTPException(status_code=400, detail="No classification running")

    classification_status["running"] = False

    return {"message": "Classification stopped"}


@router.post("/smart-start", response_model=ClassifyResponse)
async def smart_start_classification(
    background_tasks: BackgroundTasks,
    request: Optional[SmartClassifyRequest] = None,
    db: Session = Depends(get_db),
):
    """
    스마트 AI 분류: 폴더 자동 매핑 → unclear 파일만 추출 → (향후) 유사도 그룹핑 → AI 분류.
    기존 start와 달리 전체가 아닌 unclear 폴더 파일만 AI 분류 대상으로 선별합니다.
    """
    global classification_status
    if request is None:
        request = SmartClassifyRequest()

    if classification_status["running"]:
        raise HTTPException(status_code=400, detail="Classification already running")

    # Phase 1: 폴더 자동 매핑
    from ..workers.folder_classifier import FolderClassifier
    classifier = FolderClassifier(db)
    auto_map_result = classifier.auto_map_folders()

    # Phase 2: unclear 폴더 파일만 추출 (pending이고 source_folder가 unclear인 파일)
    # + source_folder가 NULL인 파일 (폴더 미매핑)
    files = db.execute(text("""
        SELECT fc.id, fc.file_path
        FROM file_classifications fc
        LEFT JOIN folder_mappings fm ON fc.source_folder_id = fm.id
        WHERE fc.status = 'pending'
          AND fc.ai_category_id IS NULL
          AND (fm.folder_status IN ('unclear', 'flat', 'nested') OR fc.source_folder_id IS NULL)
        ORDER BY fc.id
    """)).fetchall()

    total = len(files)

    if total == 0:
        return ClassifyResponse(
            message=f"스마트 분류: 폴더 매핑 {auto_map_result['files_mapped']}건 완료, AI 분석 대상 없음",
            total=0,
            status="completed",
        )

    # 상태 초기화 (phase 추가)
    classification_status = {
        "running": True,
        "total": total,
        "processed": 0,
        "failed": 0,
        "current_file": None,
        "model": request.model,
        "phase": "ai_classifying",
        "smart": True,
        "auto_map_result": auto_map_result,
        "similarity_threshold": request.similarity_threshold,
    }

    # 백그라운드 작업 시작 (기존 run_classification 재활용)
    background_tasks.add_task(
        run_classification,
        files,
        request.model,
        request.batch_size,
        request.gap_minutes,
        request.max_workers,
    )

    return ClassifyResponse(
        message=f"스마트 분류: 폴더 매핑 {auto_map_result['files_mapped']}건, AI 분석 {total}건 시작",
        total=total,
        status="running",
    )


def _get_monitor_db_session():
    """monitor.db (메인 DB) 세션 생성."""
    from app.database import SessionLocal as MonitorSessionLocal
    return MonitorSessionLocal()


def _build_classify_prompt(categories: list[str], image_path: str, provider: str = "claude") -> str:
    """이미지 분류 프롬프트 생성.

    Args:
        categories: 분류 카테고리 목록
        image_path: 이미지 파일 경로 (claude: 프롬프트에 포함, gemini: cli_options["image_path"]로 별도 전달)
        provider: 'claude' 또는 'gemini'
    """
    cat_list = "\n".join(f"- {cat}" for cat in categories)

    if provider == "gemini":
        # Gemini CLI는 @경로 문법으로 이미지를 직접 첨부 — Read 도구 불필요
        return f"""다음 이미지를 아래 카테고리 중 하나로 분류하세요.

**컨텍스트:**
이미지의 내용을 분석하여 가장 적합한 카테고리로 분류하세요.

**가능한 카테고리:**
{cat_list}

첨부된 이미지를 분석하여 가장 적합한 카테고리를 선택하세요.
응답은 반드시 지정된 JSON 스키마 형식으로만 출력하세요.
"""
    else:
        # Claude CLI: Read 도구로 이미지 파일 읽기
        return f"""다음 이미지를 아래 카테고리 중 하나로 분류하세요.

**컨텍스트:**
이미지의 내용을 분석하여 가장 적합한 카테고리로 분류하세요.

**가능한 카테고리:**
{cat_list}

**이미지 파일:**
- {image_path}

각 이미지 파일을 Read 도구로 읽어서 분석하고, 가장 적합한 카테고리를 선택하세요.
응답은 반드시 지정된 JSON 스키마 형식으로만 출력하세요.
"""


def _build_cli_options() -> dict:
    """이미지 분류용 CLI 옵션.

    exec_mode=True: shell 경유 없이 subprocess 직접 실행.
    이미지 분류는 --allowedTools Read + --json-schema 등 복잡한 옵션이 필요하므로
    shell 이스케이프 문제를 피하기 위해 exec 모드 사용.
    """
    return {
        "exec_mode": True,
        "output_format": "json",
        "json_schema": {
            "type": "object",
            "properties": {
                "category": {"type": "string"},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"}
            },
            "required": ["category", "confidence"]
        },
        "allowed_tools": ["Read"],
    }


async def run_classification(
    files: List[tuple],
    model: str,
    batch_size: int,
    gap_minutes: int,
    max_workers: int = CLI_MAX_WORKERS,
):
    """
    실제 분류 실행 (백그라운드) — LLMWorker 큐 방식 + DB 진행 추적
    """
    global classification_status

    from ..database import SessionLocal
    from ..workers.task_progress import TaskProgressManager
    from ..workers.log_buffer import pipeline_logs
    from app.modules.claude_worker.services.llm_service import LLMService

    progress_db = SessionLocal()
    progress_mgr = TaskProgressManager(progress_db)
    task_id = progress_mgr.start_task('ai_classify', len(files))
    classification_status["task_id"] = task_id

    # 카테고리 목록 조회
    cat_db = SessionLocal()
    try:
        categories = [
            row[0] for row in cat_db.execute(
                text("SELECT full_path FROM categories ORDER BY full_path")
            ).fetchall()
        ]
    finally:
        cat_db.close()

    if not categories:
        logger.error("No categories found. Create categories first.")
        classification_status["running"] = False
        progress_mgr.fail_task(task_id, "카테고리가 없습니다.")
        progress_db.close()
        return

    # provider 결정
    if model == "gemini_cli":
        provider = "gemini"
    else:
        provider = "claude"

    # CLI 옵션 구성
    # - claude: exec_mode + json_schema 등 Claude CLI 전용 옵션
    # - gemini: image_path는 enqueue_and_poll 내부에서 classify_path 확정 후 설정
    if provider == "claude":
        cli_options = _build_cli_options()
    else:
        cli_options = {}  # gemini: enqueue_and_poll에서 image_path 주입

    # model명 변환: claude_cli → sonnet (LLMWorker에서 사용하는 모델명)
    llm_model = ic_settings.CLAUDE_MODEL if provider == "claude" else ""

    # pHash 중복 그룹 기반 최적화: 대표 1장만 분류 → 나머지 일괄 적용
    file_ids = [f.id for f in files]
    group_db = SessionLocal()
    try:
        placeholders = ",".join(str(fid) for fid in file_ids)
        group_rows = group_db.execute(text(f"""
            SELECT dm.file_id, dm.group_id, dm.quality_score
            FROM duplicate_members dm
            WHERE dm.file_id IN ({placeholders})
            ORDER BY dm.group_id, dm.quality_score DESC NULLS LAST
        """)).fetchall()
    finally:
        group_db.close()

    # 그룹별 대표 파일 선정 (quality_score 최고)
    group_map = {}  # group_id → [file_ids]
    representative_ids = set()  # 대표 파일 ID
    member_to_group = {}  # file_id → group_id
    for row in group_rows:
        fid, gid, _ = row
        member_to_group[fid] = gid
        if gid not in group_map:
            group_map[gid] = []
            representative_ids.add(fid)  # 첫 번째 (quality_score 최고) = 대표
        group_map[gid].append(fid)

    # 분류 대상 분리: 대표 파일 + 그룹 미소속 파일만 LLM 큐에 등록
    files_to_classify = []
    files_skip = []  # 대표가 아닌 그룹 멤버 (나중에 일괄 적용)
    for f in files:
        if f.id in member_to_group and f.id not in representative_ids:
            files_skip.append(f)
        else:
            files_to_classify.append(f)

    skip_count = len(files_skip)
    total_groups = len(group_map)

    # CLIP 유사도 기반 추가 그룹핑 (smart 모드일 때만)
    clip_group_map = {}  # clip_group_id → [file_ids]
    clip_representative_ids = set()
    clip_skip_count = 0

    if classification_status.get("smart"):
        try:
            clip_db = SessionLocal()
            clip_file_ids = [f.id for f in files_to_classify]
            if clip_file_ids:
                placeholders_clip = ",".join(str(fid) for fid in clip_file_ids)
                # CLIP 임베딩이 있는 파일 조회
                clip_rows = clip_db.execute(text(f"""
                    SELECT file_id, clip_embedding
                    FROM image_features
                    WHERE file_id IN ({placeholders_clip})
                      AND clip_embedding IS NOT NULL
                """)).fetchall()

                if len(clip_rows) >= 2:
                    import numpy as np
                    try:
                        import faiss
                        # 임베딩 로드
                        embeddings = []
                        embed_file_ids = []
                        for row in clip_rows:
                            emb = np.frombuffer(row.clip_embedding, dtype=np.float32)
                            if emb.shape[0] == 512:
                                embeddings.append(emb)
                                embed_file_ids.append(row.file_id)

                        if len(embeddings) >= 2:
                            emb_np = np.vstack(embeddings).astype("float32")
                            faiss.normalize_L2(emb_np)

                            # 유사도 매트릭스로 그룹핑 (threshold=0.85)
                            threshold = classification_status.get("similarity_threshold", 0.85)
                            index = faiss.IndexFlatIP(512)
                            index.add(emb_np)
                            k = min(20, len(embeddings))
                            distances, indices = index.search(emb_np, k)

                            # Union-Find로 그룹 구성
                            parent = list(range(len(embeddings)))

                            def find(x):
                                while parent[x] != x:
                                    parent[x] = parent[parent[x]]
                                    x = parent[x]
                                return x

                            def union(a, b):
                                ra, rb = find(a), find(b)
                                if ra != rb:
                                    parent[ra] = rb

                            for i in range(len(embeddings)):
                                for j_idx in range(k):
                                    j = indices[i][j_idx]
                                    if j == -1 or j == i:
                                        continue
                                    if distances[i][j_idx] >= threshold:
                                        union(i, j)

                            # 그룹 구성
                            groups = {}
                            for i in range(len(embeddings)):
                                root = find(i)
                                if root not in groups:
                                    groups[root] = []
                                groups[root].append(embed_file_ids[i])

                            # 2개 이상 멤버 그룹만 처리
                            clip_gid = 0
                            for root, members in groups.items():
                                if len(members) < 2:
                                    continue
                                clip_group_map[clip_gid] = members
                                clip_representative_ids.add(members[0])  # 첫 번째 = 대표
                                clip_gid += 1

                            # files_to_classify에서 CLIP 그룹 비대표 제거
                            clip_non_rep = set()
                            for members in clip_group_map.values():
                                for m in members[1:]:
                                    clip_non_rep.add(m)

                            new_files_to_classify = []
                            clip_files_skip = []
                            for f in files_to_classify:
                                if f.id in clip_non_rep:
                                    clip_files_skip.append(f)
                                else:
                                    new_files_to_classify.append(f)

                            clip_skip_count = len(clip_files_skip)
                            files_skip.extend(clip_files_skip)
                            files_to_classify = new_files_to_classify

                            pipeline_logs.add("classify", f"[CLIP] 유사 그룹 {len(clip_group_map)}개, {clip_skip_count}건 대표 결과 복사 예정")
                    except ImportError:
                        pipeline_logs.add("classify", "[CLIP] faiss-cpu 미설치, 유사도 그룹핑 건너뜀")
            clip_db.close()
        except Exception as e:
            pipeline_logs.add("classify", f"[CLIP] 그룹핑 오류: {e}")

    # 시작 로그
    if skip_count > 0 or clip_skip_count > 0:
        pipeline_logs.add("classify", f"[시작] {len(files)}건 중 {len(files_to_classify)}건 LLM 큐 분류 (pHash 그룹 {total_groups}개/{skip_count}건, CLIP 그룹 {len(clip_group_map)}개/{clip_skip_count}건 대표 결과 복사)")
    else:
        pipeline_logs.add("classify", f"[시작] {len(files)}건 분류 시작 (모델: {model}, 카테고리: {len(categories)}개, LLM 큐 방식)")

    semaphore = asyncio.Semaphore(max_workers)

    async def enqueue_and_poll(file_id: int, file_path: str):
        """단일 파일: enqueue → 폴링 → 결과 저장"""
        async with semaphore:
            if not classification_status["running"]:
                return

            classification_status["current_file"] = file_path
            filename = file_path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]

            try:
                # 썸네일 우선 전달
                thumb_path = ic_settings.THUMBNAIL_DIR / f"{file_id}.jpg"
                classify_path = str(thumb_path) if thumb_path.exists() else file_path

                # gemini: classify_path 확정 후 cli_options에 image_path 주입
                # (cli_options는 외부 클로저에서 참조하므로 새 dict 생성)
                effective_cli_options = cli_options
                if provider == "gemini":
                    effective_cli_options = {**(cli_options or {}), "image_path": classify_path}

                # 프롬프트 생성 (provider에 따라 분기)
                prompt = _build_classify_prompt(categories, classify_path, provider)

                # LLM 큐에 등록 (monitor.db 사용)
                monitor_db = _get_monitor_db_session()
                try:
                    llm_service = LLMService(monitor_db)
                    llm_request = llm_service.enqueue(
                        caller_type="image_classify",
                        caller_id=str(file_id),
                        prompt=prompt,
                        requested_by="api",
                        request_source="image_classifier",
                        provider=provider,
                        model=llm_model,
                        cli_options=effective_cli_options,
                    )
                    request_id = llm_request.id
                    logger.debug(f"Enqueued: file_id={file_id}, request_id={request_id}")
                finally:
                    monitor_db.close()

                # 폴링으로 결과 대기
                start_time = time.time()
                result_data = None

                while time.time() - start_time < POLL_TIMEOUT_SECONDS:
                    if not classification_status["running"]:
                        return

                    await asyncio.sleep(POLL_INTERVAL_SECONDS)

                    poll_db = _get_monitor_db_session()
                    try:
                        llm_service = LLMService(poll_db)
                        req = llm_service.get_request_by_id(request_id)
                        if req and req.status == "completed":
                            if req.result:
                                result_data = json.loads(req.result)
                            break
                        elif req and req.status == "failed":
                            classification_status["failed"] += 1
                            error_msg = req.error_message or "Unknown error"
                            pipeline_logs.add("classify", f"[FAIL] {filename} — {error_msg[:100]}")
                            return
                    finally:
                        poll_db.close()
                else:
                    # 타임아웃
                    classification_status["failed"] += 1
                    pipeline_logs.add("classify", f"[TIMEOUT] {filename} — {POLL_TIMEOUT_SECONDS}초 대기 초과")
                    return

                # 결과 저장 (image_classifier.db)
                if result_data:
                    category_path = result_data.get("category", "")
                    confidence = float(result_data.get("confidence", 0.5))
                    reasoning = result_data.get("reasoning", "")

                    if category_path and not category_path.startswith("error/"):
                        ic_db = SessionLocal()
                        try:
                            # category_path로 category_id 조회
                            cat_row = ic_db.execute(
                                text("SELECT id FROM categories WHERE full_path = :path"),
                                {"path": category_path}
                            ).fetchone()

                            if not cat_row:
                                # Bug #5 수정: LIKE 부분 매칭 — 정확히 끝나는 경로 우선, 그 다음 포함 경로
                                # ORDER BY: 정확 suffix 일치(0) 우선, 그 다음 길이 짧은 순
                                cat_row = ic_db.execute(
                                    text("""
                                        SELECT id FROM categories
                                        WHERE full_path LIKE :path
                                        ORDER BY
                                            CASE WHEN full_path = :exact THEN 0
                                                 WHEN full_path LIKE :suffix THEN 1
                                                 ELSE 2
                                            END,
                                            LENGTH(full_path)
                                        LIMIT 1
                                    """),
                                    {
                                        "path": f"%{category_path}%",
                                        "exact": category_path,
                                        "suffix": f"%/{category_path}",
                                    }
                                ).fetchone()

                            if cat_row:
                                category_id = cat_row[0]
                                ic_db.execute(text("""
                                    UPDATE file_classifications
                                    SET ai_category_id = :category_id,
                                        ai_confidence = :confidence,
                                        ai_reasoning = :reasoning,
                                        ai_model = :model,
                                        final_category_id = :category_id,
                                        status = 'ai_classified',
                                        classified_at = datetime('now')
                                    WHERE id = :file_id
                                """), {
                                    "file_id": file_id,
                                    "category_id": category_id,
                                    "confidence": confidence,
                                    "reasoning": reasoning,
                                    "model": model,
                                })
                                ic_db.commit()
                                classification_status["processed"] += 1
                                conf_pct = round(confidence * 100)
                                pipeline_logs.add("classify", f"[OK] {filename} → {category_path} ({conf_pct}%)")

                                # API 사용량 기록
                                try:
                                    from ..workers.cost_tracker import CostTracker
                                    cost_db = SessionLocal()
                                    try:
                                        tracker = CostTracker(cost_db)
                                        tracker.record_usage(model=model, image_count=1)
                                    finally:
                                        cost_db.close()
                                except Exception as cost_err:
                                    logger.warning(f"Cost tracking failed for file {file_id}: {cost_err}")
                            else:
                                logger.warning(f"Category not found: {category_path} for {file_path}")
                                classification_status["failed"] += 1
                                pipeline_logs.add("classify", f"[FAIL] {filename} — 카테고리 매칭 실패: {category_path}")
                        finally:
                            ic_db.close()
                    else:
                        classification_status["failed"] += 1
                        pipeline_logs.add("classify", f"[FAIL] {filename} — 분류 결과 없음")
                else:
                    classification_status["failed"] += 1
                    pipeline_logs.add("classify", f"[FAIL] {filename} — 결과 데이터 없음")

            except Exception as e:
                logger.error(f"Classification failed for {file_path}: {e}")
                classification_status["failed"] += 1
                pipeline_logs.add("classify", f"[ERROR] {filename} — {type(e).__name__}: {e}")

    try:
        # 배치 단위로 병렬 처리 (대표 파일 + 그룹 미소속 파일만)
        for i in range(0, len(files_to_classify), batch_size):
            if not classification_status["running"]:
                msg = "Classification stopped by user"
                logger.info(msg)
                pipeline_logs.add("classify", msg)
                progress_mgr.pause_task(task_id)
                break

            batch = files_to_classify[i:i + batch_size]
            tasks = [enqueue_and_poll(f.id, f.file_path) for f in batch]
            await asyncio.gather(*tasks)

            # DB 진행 업데이트
            try:
                succeeded = classification_status["processed"]
                failed = classification_status["failed"]
                batch_num = i // batch_size + 1
                total_batches = (len(files_to_classify) + batch_size - 1) // batch_size
                progress_mgr.update_progress(
                    task_id, succeeded,
                    f"배치 {batch_num}/{total_batches} (성공: {succeeded}, 실패: {failed})"
                )
                pipeline_logs.add("classify", f"[배치 {batch_num}/{total_batches}] 성공: {succeeded}, 실패: {failed}, 남은: {len(files_to_classify) - i - len(batch)}")
            except Exception:
                pass
        else:
            # pHash 그룹 멤버에 대표 결과 일괄 복사
            if files_skip and classification_status["running"]:
                copy_db = SessionLocal()
                copied = 0
                try:
                    for f in files_skip:
                        gid = member_to_group.get(f.id)
                        if not gid:
                            continue
                        # 대표 파일의 분류 결과 조회
                        reps = [fid for fid in group_map[gid] if fid in representative_ids]
                        if not reps:
                            # Bug #4 수정: 대표 파일이 group_map에 없으면(이미 분류됨 등) skip
                            continue
                        rep_id = reps[0]
                        rep_row = copy_db.execute(text("""
                            SELECT ai_category_id, ai_confidence, ai_reasoning, ai_model
                            FROM file_classifications WHERE id = :rep_id AND ai_category_id IS NOT NULL
                        """), {"rep_id": rep_id}).mappings().first()

                        if rep_row:
                            copy_db.execute(text("""
                                UPDATE file_classifications
                                SET ai_category_id = :cat_id, ai_confidence = :conf,
                                    ai_reasoning = :reason, ai_model = :model,
                                    final_category_id = :cat_id, status = 'ai_classified',
                                    classified_at = datetime('now')
                                WHERE id = :file_id
                            """), {
                                "file_id": f.id,
                                "cat_id": rep_row["ai_category_id"],
                                "conf": rep_row["ai_confidence"],
                                "reason": f"[그룹 복사] {rep_row['ai_reasoning'] or ''}",
                                "model": rep_row["ai_model"],
                            })
                            copied += 1
                            classification_status["processed"] += 1
                    copy_db.commit()
                    if copied > 0:
                        pipeline_logs.add("classify", f"[pHash 그룹 복사] {copied}건 대표 결과 일괄 적용")
                except Exception as e:
                    logger.error(f"Group copy failed: {e}")
                    copy_db.rollback()
                finally:
                    copy_db.close()

            # CLIP 유사도 그룹 멤버에 대표 결과 일괄 복사
            if clip_group_map and classification_status["running"]:
                clip_copy_db = SessionLocal()
                clip_copied = 0
                try:
                    for gid, members in clip_group_map.items():
                        rep_id = members[0]  # 대표
                        rep_row = clip_copy_db.execute(text("""
                            SELECT ai_category_id, ai_confidence, ai_reasoning, ai_model
                            FROM file_classifications WHERE id = :rep_id AND ai_category_id IS NOT NULL
                        """), {"rep_id": rep_id}).mappings().first()

                        if rep_row:
                            for member_id in members[1:]:
                                clip_copy_db.execute(text("""
                                    UPDATE file_classifications
                                    SET ai_category_id = :cat_id, ai_confidence = :conf,
                                        ai_reasoning = :reason, ai_model = :model,
                                        final_category_id = :cat_id, status = 'ai_classified',
                                        classified_at = datetime('now')
                                    WHERE id = :file_id
                                """), {
                                    "file_id": member_id,
                                    "cat_id": rep_row["ai_category_id"],
                                    "conf": rep_row["ai_confidence"],
                                    "reason": f"[CLIP 유사 복사] {rep_row['ai_reasoning'] or ''}",
                                    "model": rep_row["ai_model"],
                                })
                                clip_copied += 1
                                classification_status["processed"] += 1
                    clip_copy_db.commit()
                    if clip_copied > 0:
                        pipeline_logs.add("classify", f"[CLIP 그룹 복사] {clip_copied}건 대표 결과 일괄 적용")
                except Exception as e:
                    logger.error(f"CLIP group copy failed: {e}")
                    clip_copy_db.rollback()
                finally:
                    clip_copy_db.close()

            # 최종 결과 판정
            succeeded = classification_status["processed"]
            failed = classification_status["failed"]
            if succeeded == 0 and failed > 0:
                progress_mgr.fail_task(task_id, f"전체 실패: {failed}건 모두 분류 실패")
            elif failed > 0:
                progress_mgr.complete_task(task_id)
                logger.warning(f"Classification done with {failed} failures out of {succeeded + failed}")
            else:
                progress_mgr.complete_task(task_id)

    except Exception as e:
        progress_mgr.fail_task(task_id, str(e))
        raise
    finally:
        classification_status["running"] = False
        classification_status["current_file"] = None
        progress_db.close()

        succeeded = classification_status['processed']
        failed = classification_status['failed']
        total = classification_status['total']
        if failed > 0 and succeeded == 0:
            msg = f"Classification FAILED: {failed}/{total}건 전부 실패"
            logger.error(msg)
        elif failed > 0:
            msg = f"Classification done: 성공 {succeeded}/{total}, 실패 {failed}건"
            logger.warning(msg)
        else:
            msg = f"Classification completed: {succeeded}/{total}건 성공"
            logger.info(msg)
        pipeline_logs.add("classify", msg)
