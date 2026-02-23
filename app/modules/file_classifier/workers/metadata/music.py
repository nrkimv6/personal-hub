"""음악 파일 메타데이터 추출 (mutagen)"""
import re
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import text


def detect_artist_lang(artist: str) -> str:
    if not artist:
        return "unknown"
    if re.search(r'[\uAC00-\uD7A3]', artist):
        return "ko"
    if re.search(r'[\u3040-\u30FF\u4E00-\u9FFF]', artist):
        return "ja"
    if re.search(r'[A-Za-z]', artist):
        return "en"
    return "unknown"


def extract(file_id: int, file_path: str, db: Session) -> dict:
    try:
        from mutagen import File as MutagenFile
        audio = MutagenFile(file_path, easy=True)
        if audio is None:
            return {"has_tags": False, "artist_lang": "unknown"}

        title = str(audio.get("title", [""])[0]) if audio.get("title") else None
        artist = str(audio.get("artist", [""])[0]) if audio.get("artist") else None
        album = str(audio.get("album", [""])[0]) if audio.get("album") else None
        genre = str(audio.get("genre", [""])[0]) if audio.get("genre") else None
        year_raw = audio.get("date", [""])[0] if audio.get("date") else None
        year = int(str(year_raw)[:4]) if year_raw and str(year_raw)[:4].isdigit() else None

        duration = int(audio.info.length) if hasattr(audio, 'info') and hasattr(audio.info, 'length') else None
        bitrate = int(audio.info.bitrate) if hasattr(audio, 'info') and hasattr(audio.info, 'bitrate') else None
        artist_lang = detect_artist_lang(artist or "")
        has_tags = bool(title or artist or album)

        db.execute(text("""
            INSERT OR REPLACE INTO fc_music_meta
                (file_id, title, artist, album, genre, year, duration_seconds, bitrate, artist_lang, has_tags)
            VALUES
                (:file_id, :title, :artist, :album, :genre, :year, :duration_seconds, :bitrate, :artist_lang, :has_tags)
        """), {
            "file_id": file_id, "title": title, "artist": artist, "album": album,
            "genre": genre, "year": year, "duration_seconds": duration,
            "bitrate": bitrate, "artist_lang": artist_lang, "has_tags": has_tags
        })
        return {"has_tags": has_tags, "artist_lang": artist_lang}
    except Exception as e:
        return {"has_tags": False, "artist_lang": "unknown", "error": str(e)}
