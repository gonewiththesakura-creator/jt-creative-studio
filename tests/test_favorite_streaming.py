import http.client

import pytest

from test_server_review_regressions import (
    SESSION_ID,
    json_request,
    panel,
    running_server,
    session_cookie,
)


def favorite_request(httpd, cookie, byte_range=None):
    connection = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=5)
    headers = {"Cookie": cookie}
    if byte_range is not None:
        headers["Range"] = byte_range
    try:
        connection.request("GET", "/api/favorite-image/video-favorite", headers=headers)
        response = connection.getresponse()
        return response.status, response.read(), dict(response.getheaders())
    finally:
        connection.close()


@pytest.fixture
def stored_video(panel):
    data = b"\x00\x00\x00\x18ftypmp42" + bytes(range(256)) * 2048
    path = panel.FAVORITES_DIR / "video-favorite.mp4"
    path.write_bytes(data)
    panel._favorites["video-favorite"] = {
        "id": "video-favorite",
        "image_path": str(path),
        "favorite_media_type": "video/mp4",
        "owner_session_hash": panel._session_hash(SESSION_ID),
    }
    return data


@pytest.mark.parametrize(
    "byte_range,start,end,status",
    [
        (None, 0, None, 200),
        ("bytes=0-31", 0, 31, 206),
        ("bytes=500000-", 500000, None, 206),
        ("bytes=-32", -32, None, 206),
    ],
)
def test_video_favorite_streams_full_and_single_byte_ranges(
    panel, stored_video, byte_range, start, end, status
):
    with running_server(panel) as httpd:
        code, body, headers = favorite_request(httpd, session_cookie(panel), byte_range)

    end = len(stored_video) - 1 if end is None else end
    start = len(stored_video) + start if start < 0 else start
    assert code == status
    assert body == stored_video[start:end + 1]
    assert headers["Content-Type"] == "video/mp4"
    assert headers["Accept-Ranges"] == "bytes"
    assert int(headers["Content-Length"]) == len(body)
    assert "private" in headers["Cache-Control"]
    if status == 206:
        assert headers["Content-Range"] == f"bytes {start}-{end}/{len(stored_video)}"
    else:
        assert "Content-Range" not in headers


@pytest.mark.parametrize(
    "byte_range",
    ["bytes=999999-", "bytes=10-9", "bytes=-0", "bytes=0-1,4-5", "bytes=bad"],
)
def test_video_favorite_rejects_invalid_or_unsatisfiable_ranges(
    panel, stored_video, byte_range
):
    with running_server(panel) as httpd:
        code, body, headers = favorite_request(httpd, session_cookie(panel), byte_range)

    assert code == 416
    assert headers["Content-Range"] == f"bytes */{len(stored_video)}"
    assert body != stored_video


def test_video_favorite_ranges_preserve_owner_isolation(panel, stored_video):
    with running_server(panel) as httpd:
        code, body, headers = favorite_request(
            httpd, session_cookie(panel, "different-owner-session-1234567890"), "bytes=0-31"
        )

    assert code == 404
    assert body != stored_video[:32]
    assert "Content-Range" not in headers


def test_video_history_exposes_owned_thumbnail_links_without_file_bodies(panel):
    jid, digest = "abcdef123456", "a" * 32
    panel._jobs[jid] = {
        "id": jid,
        "workflow": "h3_edit_n",
        "style_id": "video",
        "created": 100,
        "status": "done",
        "request_session_hash": panel._session_hash(SESSION_ID),
        "input_thumbnails": {"source_video": digest},
        "media": {"source_video": "clip.mp4"},
    }
    panel._jobs["fedcba654321"] = {
        **panel._jobs[jid],
        "id": "fedcba654321",
        "request_session_hash": panel._session_hash("different-owner-session-1234567890"),
    }
    with running_server(panel) as httpd:
        code, rows, _ = json_request(
            httpd, "GET", "/api/jobs?scope=video&limit=20", cookie=session_cookie(panel)
        )

    assert code == 200
    assert len(rows) == 1
    assert rows[0]["id"] == jid
    assert rows[0]["thumbnails"] == {
        "source_video": f"/api/video-thumbnail/{jid}/{digest}.jpg"
    }
    assert "input_thumbnails" not in rows[0]
    assert "data" not in rows[0]
    assert len(str(rows)) < 4000
