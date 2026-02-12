"""
파일 메타데이터 수집 워커

- 파일명에서 날짜 추출 (FILENAME_DATE_PATTERNS)
- EXIF 메타데이터 읽기 (Pillow)
- 메타데이터 신뢰 등급 결정
- 날짜 충돌 감지
"""

import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image
from PIL.ExifTags import TAGS
from sqlalchemy import text
from sqlalchemy.orm import Session


# 파일명 날짜 패턴 (계획서 Section 4.1)
FILENAME_DATE_PATTERNS = [
    # 표준 카메라 앱
    (r"IMG_(\d{8})_(\d{6})", "%Y%m%d_%H%M%S"),
    (r"IMG-(\d{8})-WA(\d+)", "%Y%m%d"),  # WhatsApp
    (r"(\d{8})_(\d{6})", "%Y%m%d_%H%M%S"),
    (r"SAVE_(\d{8})_(\d{6})", "%Y%m%d_%H%M%S"),

    # 삼성
    (r"(\d{4})(\d{2})(\d{2})_(\d{6})", "%Y%m%d_%H%M%S"),

    # 아이폰
    (r"IMG_(\d{4})", None),  # 순번만, 날짜 없음
    (r"Photo (\d{4}-\d{2}-\d{2})", "%Y-%m-%d"),

    # 스크린샷
    (r"Screenshot_(\d{4})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})", "%Y-%m-%d-%H-%M-%S"),
    (r"스크린샷 (\d{4})-(\d{2})-(\d{2})", "%Y-%m-%d"),

    # 카카오톡
    (r"KakaoTalk_(\d{8})_(\d{6})", "%Y%m%d_%H%M%S"),

    # 범용
    (r"(\d{4})-(\d{2})-(\d{2})", "%Y-%m-%d"),
    (r"(\d{4})\.(\d{2})\.(\d{2})", "%Y.%m.%d"),
]


class MetadataExtractor:
    """파일 메타데이터 추출 워커"""

    def __init__(self, db: Session):
        self.db = db

    def extract_and_save(self, file_id: int, file_path: Path):
        """
        파일 메타데이터 추출 및 DB 저장

        Args:
            file_id: file_classifications.id
            file_path: 파일 경로
        """
        # 1. 파일명에서 날짜 추출
        filename_date, filename_pattern = self._extract_date_from_filename(file_path.name)

        # 2. EXIF 메타데이터 읽기
        exif_original, exif_digitized = self._extract_exif_dates(file_path)

        # 3. 신뢰 등급 결정 및 충돌 감지
        final_date, date_source, trust_level = self._resolve_date_priority(
            filename_date, exif_original, exif_digitized
        )

        # 4. DB 업데이트
        self.db.execute(
            text("""
                UPDATE file_classifications
                SET
                    extracted_date = :final_date,
                    date_source = :date_source,
                    date_trust_level = :trust_level
                WHERE id = :file_id
            """),
            {
                "file_id": file_id,
                "final_date": final_date.isoformat() if final_date else None,
                "date_source": date_source,
                "trust_level": trust_level,
            }
        )
        self.db.commit()

        # 5. 충돌 감지 시 경고 로그
        if self._detect_date_conflict(filename_date, exif_original):
            print(f"[경고] 날짜 불일치: {file_path.name} — 파일명({filename_date}) vs EXIF({exif_original})")

    def _extract_date_from_filename(self, filename: str) -> Tuple[Optional[datetime], Optional[str]]:
        """
        파일명에서 날짜 추출

        Returns:
            (추출된 datetime, 매칭된 패턴) 또는 (None, None)
        """
        for pattern, date_format in FILENAME_DATE_PATTERNS:
            match = re.search(pattern, filename, re.IGNORECASE)
            if match:
                if date_format is None:
                    # 순번만 있고 날짜 없음 (예: IMG_0001.jpg)
                    return None, pattern

                # 매칭된 그룹을 조합하여 날짜 문자열 생성
                date_str = "".join(match.groups())
                try:
                    return datetime.strptime(date_str, date_format), pattern
                except ValueError:
                    continue  # 날짜 파싱 실패 시 다음 패턴 시도

        return None, None

    def _extract_exif_dates(self, file_path: Path) -> Tuple[Optional[datetime], Optional[datetime]]:
        """
        EXIF 메타데이터에서 날짜 추출

        Returns:
            (DateTimeOriginal, DateTimeDigitized) 또는 (None, None)
        """
        try:
            with Image.open(file_path) as img:
                exif_data = img._getexif()
                if not exif_data:
                    return None, None

                exif = {TAGS.get(k, k): v for k, v in exif_data.items()}

                original = exif.get("DateTimeOriginal")
                digitized = exif.get("DateTimeDigitized")

                # EXIF 날짜 형식: "2023:04:15 14:30:22"
                original_dt = self._parse_exif_datetime(original) if original else None
                digitized_dt = self._parse_exif_datetime(digitized) if digitized else None

                return original_dt, digitized_dt

        except Exception as e:
            # EXIF 읽기 실패 (EXIF 없음, 손상된 이미지 등)
            return None, None

    def _parse_exif_datetime(self, exif_str: str) -> Optional[datetime]:
        """
        EXIF 날짜 문자열을 datetime으로 변환

        Args:
            exif_str: "2023:04:15 14:30:22" 형식

        Returns:
            datetime 객체 또는 None
        """
        try:
            return datetime.strptime(exif_str, "%Y:%m:%d %H:%M:%S")
        except ValueError:
            return None

    def _resolve_date_priority(
        self,
        filename_date: Optional[datetime],
        exif_original: Optional[datetime],
        exif_digitized: Optional[datetime],
    ) -> Tuple[Optional[datetime], str, str]:
        """
        메타데이터 신뢰 등급에 따라 최종 날짜 결정

        신뢰 등급 (높음 → 낮음):
        1. user_input (사용자 직접 입력) — 이 함수에서는 처리 안 함
        2. filename (파일명 날짜)
        3. exif_original (EXIF DateTimeOriginal)
        4. exif_digitized (EXIF DateTimeDigitized)
        5. folder_name (폴더명) — 이 함수에서는 처리 안 함
        6. file_modified (파일 수정일) — 이 함수에서는 처리 안 함
        7. unknown (없음)

        Returns:
            (최종 날짜, 날짜 소스, 신뢰 등급)
        """
        if filename_date:
            return filename_date, "filename", "filename"
        elif exif_original:
            return exif_original, "exif_original", "exif_original"
        elif exif_digitized:
            return exif_digitized, "exif_digitized", "exif_digitized"
        else:
            return None, "unknown", "unknown"

    def _detect_date_conflict(
        self,
        filename_date: Optional[datetime],
        exif_date: Optional[datetime],
        threshold_days: int = 30
    ) -> bool:
        """
        파일명 날짜와 EXIF 날짜 간 충돌 감지

        Args:
            filename_date: 파일명 날짜
            exif_date: EXIF 날짜
            threshold_days: 허용 오차 (일)

        Returns:
            충돌 여부 (True = 불일치)
        """
        if not filename_date or not exif_date:
            return False  # 둘 중 하나라도 없으면 충돌 아님

        diff_days = abs((filename_date - exif_date).days)
        return diff_days > threshold_days


class MetadataWorker:
    """메타데이터 수집 백그라운드 워커"""

    def __init__(self, db: Session):
        self.db = db
        self.extractor = MetadataExtractor(db)

    async def process_pending_files(self, batch_size: int = 100):
        """
        pending 상태 파일의 메타데이터 수집

        Args:
            batch_size: 배치 크기
        """
        # pending 상태 파일 조회
        result = self.db.execute(
            text("""
                SELECT id, file_path
                FROM file_classifications
                WHERE extracted_date IS NULL
                LIMIT :batch_size
            """),
            {"batch_size": batch_size}
        ).fetchall()

        print(f"[메타데이터 수집] 처리 대상: {len(result)}개")

        for row in result:
            file_id = row.id
            file_path = Path(row.file_path)

            if not file_path.exists():
                print(f"[경고] 파일 없음: {file_path}")
                continue

            try:
                self.extractor.extract_and_save(file_id, file_path)
            except Exception as e:
                print(f"[오류] 메타데이터 추출 실패: {file_path} - {e}")

        print(f"[메타데이터 수집] 완료")
