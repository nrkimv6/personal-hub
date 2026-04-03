from __future__ import annotations

from sqlalchemy import text


def _insert_slide(db, *, file_name: str, file_path: str, status: str = "PENDING", tag: str | None = None) -> int:
    db.execute(
        text(
            """
            INSERT INTO slides (
                file_name,
                file_path,
                status,
                tag,
                thumbnail,
                is_archived
            ) VALUES (
                :file_name,
                :file_path,
                :status,
                :tag,
                :thumbnail,
                0
            )
            """
        ),
        {
            "file_name": file_name,
            "file_path": file_path,
            "status": status,
            "tag": tag,
            "thumbnail": b"thumb",
        },
    )
    slide_id = int(db.execute(text("SELECT last_insert_rowid()")).scalar_one())
    db.commit()
    return slide_id


def test_put_slide_updates_tag_and_trims_value(slide_scanner_client, slide_scanner_session):
    slide_id = _insert_slide(
        slide_scanner_session,
        file_name="tag-target.jpg",
        file_path=r"D:\tmp\tag-target.jpg",
    )

    response = slide_scanner_client.put(f"/api/v1/ss/slides/{slide_id}", json={"tag": "  발표 1부  "})
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == slide_id
    assert payload["tag"] == "발표 1부"

    row = slide_scanner_session.execute(
        text("SELECT tag FROM slides WHERE id = :id"),
        {"id": slide_id},
    ).fetchone()
    assert row.tag == "발표 1부"

    clear_response = slide_scanner_client.put(f"/api/v1/ss/slides/{slide_id}", json={"tag": "   "})
    assert clear_response.status_code == 200
    assert clear_response.json()["tag"] is None


def test_get_slides_filters_by_tag(slide_scanner_client, slide_scanner_session):
    tagged_id = _insert_slide(
        slide_scanner_session,
        file_name="tagged.jpg",
        file_path=r"D:\tmp\tagged.jpg",
        tag="Q&A",
    )
    _insert_slide(
        slide_scanner_session,
        file_name="untagged.jpg",
        file_path=r"D:\tmp\untagged.jpg",
        tag=None,
    )

    response = slide_scanner_client.get("/api/v1/ss/slides?tag=Q%26A")
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert [item["id"] for item in payload["slides"]] == [tagged_id]
    assert payload["slides"][0]["tag"] == "Q&A"


def test_get_tags_returns_distinct_sorted_tags(slide_scanner_client, slide_scanner_session):
    _insert_slide(
        slide_scanner_session,
        file_name="deck-a.jpg",
        file_path=r"D:\tmp\deck-a.jpg",
        tag="발표 2부",
    )
    _insert_slide(
        slide_scanner_session,
        file_name="deck-b.jpg",
        file_path=r"D:\tmp\deck-b.jpg",
        tag="Q&A",
    )
    _insert_slide(
        slide_scanner_session,
        file_name="deck-c.jpg",
        file_path=r"D:\tmp\deck-c.jpg",
        tag="발표 2부",
    )
    _insert_slide(
        slide_scanner_session,
        file_name="deck-d.jpg",
        file_path=r"D:\tmp\deck-d.jpg",
        tag=" ",
    )

    response = slide_scanner_client.get("/api/v1/ss/tags")
    assert response.status_code == 200
    payload = response.json()
    assert payload["tags"] == ["Q&A", "발표 2부"]
