"""파이프라인 통합 워커 — scan→metadata→rule_classify→llm_classify→review_pending 순차 실행"""
import threading
from typing import Optional, Callable
from sqlalchemy.orm import Session
from .scanner import FileScanner
from .metadata_extractor import MetadataExtractor
from .rule_classifier import RuleClassifier
from .llm_classifier import LLMClassifier
from .task_progress import TaskProgressManager
from ..config import settings


PIPELINE_STAGES = ["scan", "metadata", "rule_classify", "llm_classify"]


class PipelineWorker:
    def __init__(self, db: Session):
        self.db = db
        self._stop_flag = False
        self.current_stage: Optional[str] = None
        self.stage_stats: dict = {}

    def stop(self):
        self._stop_flag = True

    def run(self, root_folders: Optional[list] = None,
            progress_callback: Optional[Callable] = None) -> dict:
        results = {}

        # 1. Scan
        if self._stop_flag:
            return results
        self.current_stage = "scan"
        if progress_callback:
            progress_callback("scan", 0, 0)
        folders = root_folders or settings.SCAN_ROOT_FOLDERS
        scanner = FileScanner(self.db)
        scan_stats = scanner.scan(folders)
        results["scan"] = scan_stats
        if progress_callback:
            progress_callback("scan", scan_stats.get("total", 0), scan_stats.get("total", 0))

        # 2. Metadata extraction
        if self._stop_flag:
            return results
        self.current_stage = "metadata"
        if progress_callback:
            progress_callback("metadata", 0, 0)
        extractor = MetadataExtractor(self.db)
        meta_stats = extractor.extract()
        results["metadata"] = meta_stats
        if progress_callback:
            progress_callback("metadata", meta_stats.get("total", 0), meta_stats.get("total", 0))

        # 3. Rule classification
        if self._stop_flag:
            return results
        self.current_stage = "rule_classify"
        if progress_callback:
            progress_callback("rule_classify", 0, 0)
        rule_clf = RuleClassifier(self.db)
        rule_stats = rule_clf.classify()
        results["rule_classify"] = rule_stats
        if progress_callback:
            progress_callback("rule_classify", rule_stats.get("total", 0), rule_stats.get("total", 0))

        # 4. LLM classification (미분류만)
        if self._stop_flag:
            return results
        self.current_stage = "llm_classify"
        if progress_callback:
            progress_callback("llm_classify", 0, 0)
        llm_clf = LLMClassifier(self.db)
        llm_stats = llm_clf.classify()
        results["llm_classify"] = llm_stats
        if progress_callback:
            progress_callback("llm_classify", llm_stats.get("total", 0), llm_stats.get("total", 0))

        self.current_stage = "done"
        return results
