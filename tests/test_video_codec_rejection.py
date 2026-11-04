import struct, threading, time
import pytest
from video_uploads import UploadStaging
from test_server_review_regressions import panel

MSG = "该视频是 AV1 编码，云端视频节点无法读取。请先转成 H.264（MP4）再上传，例如：ffmpeg -i 原视频.mp4 -c:v libx264 -pix_fmt yuv420p -c:a aac 新视频.mp4"
WF = {"rh_media": {"v": {"type": "video"}}}


def box(kind, payload=b"", big=False):
    if big:
        return struct.pack(">I4sQ", 1, kind, 16 + len(payload)) + payload
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def moov(fourcc, big=False):
    entry = struct.pack(">I4s", 16, fourcc) + b"\0" * 8
    stsd = box(b"stsd", b"\0" * 4 + struct.pack(">I", 1) + entry, big)
    tree = stsd
    for kind in (b"stbl", b"minf"):
        tree = box(kind, tree, big)
    hdlr = box(b"hdlr", b"\0" * 8 + b"vide" + b"\0" * 12)
    tree = box(b"mdia", hdlr + tree, big)
    return box(b"moov", box(b"trak", tree, big), big)


def mp4(fourcc, big=False):
    return box(b"ftyp", b"isom\0\0\0\0isomav01") + moov(fourcc, big)


def check(panel, data, name="a.mp4", tmp_path=None):
    r1 = panel.validate_workflow_upload(WF, "v", name, data)
    p = tmp_path / name
    p.write_bytes(data)
    r2 = panel.validate_workflow_upload_file(WF, "v", name, p)
    assert r1 == r2
    return r1[1]


def test_avc1_allowed(panel, tmp_path):
    assert check(panel, mp4(b"avc1"), tmp_path=tmp_path) == "video/mp4"


def test_hvc1_allowed(panel, tmp_path):
    assert check(panel, mp4(b"hvc1"), tmp_path=tmp_path) == "video/mp4"


def test_av01_rejected(panel, tmp_path):
    data = mp4(b"av01")
    with pytest.raises(panel.UnsupportedVideoCodec) as e:
        panel.validate_workflow_upload(WF, "v", "a.mp4", data)
    assert str(e.value) == MSG and e.value.public_message == MSG
    p = tmp_path / "a.mp4"
    p.write_bytes(data)
    with pytest.raises(panel.UnsupportedVideoCodec) as e:
        panel.validate_workflow_upload_file(WF, "v", "a.mp4", p)
    assert str(e.value) == MSG and e.value.public_message == MSG


def test_moov_after_large_mdat(panel, tmp_path):
    p = tmp_path / "a.mp4"
    size = 5 * 1024 * 1024
    with p.open("wb") as f:
        f.write(box(b"ftyp", b"isom\0\0\0\0isom"))
        f.write(struct.pack(">I4s", size, b"mdat"))
        f.truncate(f.tell() + size - 8)
        f.seek(0, 2)
        f.write(moov(b"av01"))
    with pytest.raises(panel.UnsupportedVideoCodec):
        panel.validate_workflow_upload_file(WF, "v", "a.mp4", p)


def test_size_zero_mdat_then_nothing_and_64bit(panel, tmp_path):
    with pytest.raises(panel.UnsupportedVideoCodec):
        panel.validate_workflow_upload(WF, "v", "a.mp4", mp4(b"av01", big=True))
    assert check(panel, mp4(b"avc1", big=True), tmp_path=tmp_path) == "video/mp4"
    data = box(b"ftyp", b"isom\0\0\0\0isom") + struct.pack(">I4s", 0, b"mdat") + b"x" * 100
    assert check(panel, data, tmp_path=tmp_path) == "video/mp4"


@pytest.mark.parametrize("junk", [
    lambda: mp4(b"av01")[:-10],
    lambda: box(b"ftyp", b"isom\0\0\0\0") + b"\0\0\0\x20moov" + b"\xff" * 40,
    lambda: box(b"ftyp", b"isom\0\0\0\0") + box(b"moov", b"\xff" * 64),
    lambda: box(b"ftyp", b"isom\0\0\0\0") + struct.pack(">I4sQ", 1, b"moov", 3),
])
def test_garbage_allowed(panel, tmp_path, junk):
    assert check(panel, junk(), tmp_path=tmp_path) == "video/mp4"


def test_webm_codecs(panel, tmp_path):
    head = b"\x1aE\xdf\xa3" + b"\x00" * 40
    with pytest.raises(panel.UnsupportedVideoCodec):
        panel.validate_workflow_upload(WF, "v", "a.webm", head + b"\x86\x85V_AV1" + b"\0" * 50)
    assert check(panel, head + b"\x86\x85V_VP9" + b"\0" * 50, "a.webm", tmp_path) == "video/webm"


def test_finish_reports_public_message(tmp_path, panel):
    for exc, expected in ((panel.UnsupportedVideoCodec("av01"), MSG),
                          (RuntimeError("boom"), "云端接收失败，请重新选择文件重试")):
        up = UploadStaging()
        uid = up.start(tmp_path, "o", ("w", "video", "a.mp4"), 3)
        up.chunk(uid, "o", 0, b"abc")

        def process(row, exc=exc):
            raise exc
        up.finish(uid, "o", process)
        for _ in range(200):
            r = up.finish(uid, "o", process)
            if r["status"] != "processing":
                break
            time.sleep(.01)
        assert r["status"] == "error" and r["error"] == expected
