import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PIL import Image
from modules.cloud_ocr import (
    CloudOCRError,
    run_baidu_unlimited_ocr,
    run_mistral_ocr,
    baidu_ocr_available,
    _image_to_data_uri,
    MISTRAL_OCR_URL,
    MISTRAL_OCR_MODEL,
)


def _test_image():
    return Image.new("RGB", (100, 100), color="white")


# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #

def test_image_to_data_uri_format():
    uri = _image_to_data_uri(_test_image())
    assert uri.startswith("data:image/png;base64,")


def test_image_to_data_uri_handles_rgba():
    img = Image.new("RGBA", (50, 50), color=(255, 255, 255, 255))
    uri = _image_to_data_uri(img)
    assert uri.startswith("data:image/png;base64,")


# --------------------------------------------------------------------------- #
# baidu/Unlimited-OCR backend
# --------------------------------------------------------------------------- #

def test_baidu_ocr_available_reflects_import():
    # In this test environment gradio_client is installed, so this should
    # be True; the function should never raise regardless.
    assert isinstance(baidu_ocr_available(), bool)


def test_run_baidu_ocr_success_dict_result():
    mock_client = MagicMock()
    mock_client.predict.return_value = {"text": "Calories 180\nProtein 6g", "done": True}
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        text = run_baidu_unlimited_ocr(_test_image())
    assert text == "Calories 180\nProtein 6g"


def test_run_baidu_ocr_success_string_result():
    mock_client = MagicMock()
    mock_client.predict.return_value = "Calories 180"
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        text = run_baidu_unlimited_ocr(_test_image())
    assert text == "Calories 180"


def test_run_baidu_ocr_passes_correct_api_name_and_mode():
    mock_client = MagicMock()
    mock_client.predict.return_value = {"text": "some text", "done": True}
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        run_baidu_unlimited_ocr(_test_image(), mode="base")
    _, kwargs = mock_client.predict.call_args
    assert kwargs["mode"] == "base"
    assert kwargs["api_name"] == "/run_ocr"


def test_run_baidu_ocr_missing_dependency_raises_clear_error():
    with patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", False):
        try:
            run_baidu_unlimited_ocr(_test_image())
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "gradio_client" in str(e)


def test_run_baidu_ocr_network_failure_raises_cloud_ocr_error():
    with patch("modules.cloud_ocr.GradioClient", side_effect=ConnectionError("no internet")), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        try:
            run_baidu_unlimited_ocr(_test_image())
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "baidu" in str(e).lower()


def test_run_baidu_ocr_empty_result_raises_cloud_ocr_error():
    mock_client = MagicMock()
    mock_client.predict.return_value = {"text": "", "done": True}
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        try:
            run_baidu_unlimited_ocr(_test_image())
            assert False, "should have raised"
        except CloudOCRError:
            pass


def test_run_baidu_ocr_unexpected_result_type_raises_cloud_ocr_error():
    mock_client = MagicMock()
    mock_client.predict.return_value = None
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        try:
            run_baidu_unlimited_ocr(_test_image())
            assert False, "should have raised"
        except CloudOCRError:
            pass


# --------------------------------------------------------------------------- #
# Mistral OCR backend
# --------------------------------------------------------------------------- #

def _mock_mistral_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.text = str(json_data)
    return resp


def test_run_mistral_ocr_success():
    api_response = {
        "pages": [
            {"index": 0, "markdown": "Nutrition Facts\nCalories 180"},
            {"index": 1, "markdown": "Protein 6g"},
        ]
    }
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response(api_response)
        text = run_mistral_ocr(_test_image(), api_key="fake-key-123")
    assert "Nutrition Facts" in text
    assert "Calories 180" in text
    assert "Protein 6g" in text


def test_run_mistral_ocr_sends_correct_payload():
    api_response = {"pages": [{"markdown": "some text"}]}
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response(api_response)
        run_mistral_ocr(_test_image(), api_key="my-secret-key")

    args, kwargs = mock_post.call_args
    assert args[0] == MISTRAL_OCR_URL or kwargs.get("url") == MISTRAL_OCR_URL
    assert kwargs["headers"]["Authorization"] == "Bearer my-secret-key"
    assert kwargs["json"]["model"] == MISTRAL_OCR_MODEL
    assert kwargs["json"]["document"]["type"] == "image_url"
    assert kwargs["json"]["document"]["image_url"].startswith("data:image/png;base64,")


def test_run_mistral_ocr_missing_api_key_raises_without_network_call():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        try:
            run_mistral_ocr(_test_image(), api_key="")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "api key" in str(e).lower()
    mock_post.assert_not_called()


def test_run_mistral_ocr_whitespace_only_api_key_raises():
    try:
        run_mistral_ocr(_test_image(), api_key="   ")
        assert False, "should have raised"
    except CloudOCRError:
        pass


def test_run_mistral_ocr_unauthorized_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response({"error": "unauthorized"}, status_code=401)
        try:
            run_mistral_ocr(_test_image(), api_key="bad-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "401" in str(e) or "key" in str(e).lower()


def test_run_mistral_ocr_rate_limit_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response({}, status_code=429)
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "429" in str(e) or "rate limit" in str(e).lower()


def test_run_mistral_ocr_server_error_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response({}, status_code=500)
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "500" in str(e)


def test_run_mistral_ocr_timeout_raises_clear_error():
    import requests as requests_module
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.side_effect = requests_module.exceptions.Timeout("timed out")
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "timed out" in str(e).lower()


def test_run_mistral_ocr_network_failure_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.side_effect = ConnectionError("no internet")
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError:
            pass


def test_run_mistral_ocr_malformed_json_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        resp = MagicMock()
        resp.status_code = 200
        resp.json.side_effect = ValueError("invalid json")
        mock_post.return_value = resp
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError:
            pass


def test_run_mistral_ocr_empty_pages_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response({"pages": []})
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError:
            pass


def test_run_mistral_ocr_missing_pages_key_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response({})
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError:
            pass


def test_run_mistral_ocr_combines_multiple_pages_with_blank_line():
    api_response = {"pages": [{"markdown": "Page One"}, {"markdown": "Page Two"}]}
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response(api_response)
        text = run_mistral_ocr(_test_image(), api_key="fake-key")
    assert text == "Page One\n\nPage Two"


def test_run_mistral_ocr_result_feeds_into_existing_parser():
    """The whole point of returning plain text is that it flows through
    the same bilingual/extended-nutrient parser used for local OCR."""
    from modules.ocr_parser import parse_nutrition_text

    api_response = {
        "pages": [{"markdown": "Calories 210\nTotal Fat 9g\nProtein 7g\nSodium 140mg"}]
    }
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _mock_mistral_response(api_response)
        text = run_mistral_ocr(_test_image(), api_key="fake-key")

    parsed = parse_nutrition_text(text)
    assert parsed.calories == 210
    assert parsed.total_fat_g == 9
    assert parsed.protein_g == 7
    assert parsed.sodium_mg == 140
