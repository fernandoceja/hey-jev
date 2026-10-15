from commands import typesafe_vision as tv
from commands import vision


def test_flag_off_by_default(tmp_path):
    assert tv.enabled(str(tmp_path / "missing.txt")) is False
    f = tmp_path / "flag.txt"
    tv.set_enabled(True, str(f))
    assert tv.enabled(str(f)) is True
    tv.set_enabled(False, str(f))
    assert tv.enabled(str(f)) is False


def test_classify():
    assert tv.classify("where is the Save button?") == ("box", "Save button")
    assert tv.classify("find my cursor") == ("box", "cursor")
    assert tv.classify("is there an error dialog") == ("noul", "is there an error dialog?")
    assert tv.classify("Describe what's on screen") is None
    assert tv.classify("") is None


def test_body_has_image_box_and_model():
    body = tv.request_body("box", "Save button", "QUJD", ref="r1")
    assert body["model"] == "jev-1.14.0"
    assert body["assets"]["r1"] == {"type": "image", "format": "jpg", "data_base64": "QUJD"}
    assert body["state"]["screen"] == "r1"
    assert body["questions"]["where"]["type"] == "box"
    assert "criteria" not in body["questions"]["where"]
    assert tv.headers("k")[tv.DANGER_HEADER] == "true"


def test_size_limits():
    assert tv.size_ok(1568, 980)
    assert not tv.size_ok(2880, 1864)
    assert not tv.size_ok(255, 600)


def test_region_and_spoken():
    box = {"top": 0.0, "bottom": 0.1, "left": 0.0, "right": 0.1}
    ans = {"present": {"type": "noul", "noul": 0.95},
           "where": {"type": "box", "box": box, "confidence": 0.9}}
    assert tv.spoken("box", "save button", ans) == "Save button is in the top left of the screenshot."
    ans["present"]["noul"] = 0.05
    assert tv.spoken("box", "save button", ans).startswith("I don't see")
    ans["present"]["noul"] = 0.55
    assert tv.spoken("box", "x", ans) is None
    assert tv.spoken("noul", "q", {"answer": {"noul": 0.9}}) == "Yes."
    assert tv.spoken("noul", "q", {"answer": {"noul": 0.1}}) == "No."


def _run(cmd):
    if cmd[0] == "sips" and "-g" in cmd:
        return "pixelWidth: 1568\npixelHeight: 1015\n"
    return ""


def test_try_answer_off_never_posts():
    def post(*a):
        raise AssertionError("posted")
    assert tv.try_answer("where is x", "/tmp/a.jpg", _run, lambda p: b"x", post=post, key="k", flag=False) is None


def test_try_answer_on():
    seen = {}

    def post(body, key):
        seen["body"] = body
        return {"answers": {"answer": {"type": "noul", "noul": 0.9}}, "usage": {"input_tokens": 1000}}
    out = tv.try_answer("is there a dialog", "/tmp/a.jpg", _run, lambda p: b"x", post=post, key="k", flag=True)
    assert out == "Yes."
    assert seen["body"]["model"] == "jev-1.14.0"


def test_try_answer_errors_fall_back():
    def post(body, key):
        raise RuntimeError("400")
    assert tv.try_answer("is there a dialog", "/tmp/a.jpg", _run, lambda p: b"x", post=post, key="k", flag=True) is None
    assert tv.try_answer("is there a dialog", "/tmp/a.jpg", _run, lambda p: b"x", key="", flag=True) is None


def test_cost():
    assert abs(tv.cost({"usage": {"input_tokens": 1000000}}) - 0.042) < 1e-9


def _vision_post(body, key):
    return {"content": [{"type": "text", "text": "A Finder window."}], "usage": {}}


def test_ask_about_capture_uses_typesafe_when_it_answers():
    out = vision.ask_about_capture("/x.png", "is there a dialog", post=_vision_post, key="k",
                                   prepare=lambda p: ("/x.jpg", "image/jpeg"), read=lambda p: b"img",
                                   typesafe=lambda q, p, r: "Yes.")
    assert out == "Yes."


def test_ask_about_capture_falls_back():
    out = vision.ask_about_capture("/x.png", "is there a dialog", post=_vision_post, key="k",
                                   prepare=lambda p: ("/x.jpg", "image/jpeg"), read=lambda p: b"img",
                                   typesafe=lambda q, p, r: None)
    assert out == "A Finder window."
