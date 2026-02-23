"""설치 파일 메타데이터 추출 (pefile)"""
import json
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text


def extract(file_id: int, file_path: str, db: Session) -> dict:
    ext = Path(file_path).suffix.lower()

    # bat/ps1 스킵
    if ext in ('.bat', '.ps1', '.cmd', '.sh'):
        return {"skipped": True, "reason": "script file"}

    # PE 분석 (.exe, .msi, .dll 등)
    if ext in ('.exe', '.dll', '.sys', '.msi'):
        return _extract_pe(file_id, file_path, db)

    return {"skipped": True, "reason": "unsupported format"}


def _extract_pe(file_id: int, file_path: str, db: Session) -> dict:
    try:
        import pefile
        pe = pefile.PE(file_path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_RESOURCE']])

        product_name = None
        company_name = None
        file_version = None

        if hasattr(pe, 'VS_VERSIONINFO'):
            for fileinfo in pe.FileInfo[0]:
                if fileinfo.Key == b'StringFileInfo':
                    for st in fileinfo.StringTable:
                        for entry in st.entries.items():
                            key = entry[0].decode('utf-8', errors='ignore').lower()
                            val = entry[1].decode('utf-8', errors='ignore').strip()
                            if key == 'productname':
                                product_name = val
                            elif key == 'companyname':
                                company_name = val
                            elif key == 'fileversion':
                                file_version = val

        pe.close()

        db.execute(text("""
            INSERT OR REPLACE INTO fc_installer_meta
                (file_id, product_name, company_name, file_version)
            VALUES (:file_id, :product_name, :company_name, :file_version)
        """), {
            "file_id": file_id,
            "product_name": product_name,
            "company_name": company_name,
            "file_version": file_version
        })

        meta = {}
        if product_name:
            meta["product_name"] = product_name
        if company_name:
            meta["company_name"] = company_name
        if file_version:
            meta["file_version"] = file_version

        if meta:
            db.execute(text(
                "UPDATE fc_files SET metadata_json = :meta WHERE id = :id"
            ), {"meta": json.dumps(meta), "id": file_id})

        return {"product_name": product_name, "company_name": company_name, "file_version": file_version}
    except Exception as e:
        return {"error": str(e)}
