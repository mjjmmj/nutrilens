import os
import sys
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests
from PIL import Image
import modules.cloud_ocr as cloud_ocr
from modules.cloud_ocr import (
    CloudOCRError,
    run_baidu_unlimited_ocr,
    run_mistral_ocr,
    baidu_ocr_available,
    _image_to_data_uri,
    _extract_text_from_gradio_result,
    _extract_text_from_mistral_response,
    _model_rejected,
    MISTRAL_OCR_URL,
)


def _test_image():
    return Image.new("RGB", (100, 100), color="white")


def setup_function(_fn):
    """Reset module-level fallback caches between tests so one test's
    discovered/failed strategy doesn't leak into the next."""
    cloud_ocr._baidu_working_strategy = None
    cloud_ocr._mistral_working_model = None


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
# _extract_text_from_gradio_result: defensive multi-shape parsing
# --------------------------------------------------------------------------- #

def test_extract_gradio_result_dict_text_key():
    assert _extract_text_from_gradio_result({"text": "hello", "done": True}) == "hello"


def test_extract_gradio_result_dict_alternate_keys():
    # Simulates a future response-schema change to a different key name
    assert _extract_text_from_gradio_result({"output": "hello"}) == "hello"
    assert _extract_text_from_gradio_result({"result": "hello"}) == "hello"
    assert _extract_text_from_gradio_result({"markdown": "hello"}) == "hello"
    assert _extract_text_from_gradio_result({"content": "hello"}) == "hello"


def test_extract_gradio_result_plain_string():
    assert _extract_text_from_gradio_result("plain text") == "plain text"


def test_extract_gradio_result_tuple_multiple_outputs():
    # Simulates an endpoint that returns multiple outputs (tuple), where
    # the useful text isn't necessarily in the first position
    assert _extract_text_from_gradio_result((None, {"text": "found it"})) == "found it"
    assert _extract_text_from_gradio_result(("first output", "")) == "first output"


def test_extract_gradio_result_empty_dict_returns_empty():
    assert _extract_text_from_gradio_result({}) == ""


def test_extract_gradio_result_none_returns_empty():
    assert _extract_text_from_gradio_result(None) == ""


def test_extract_gradio_result_unrelated_type_returns_empty():
    assert _extract_text_from_gradio_result(12345) == ""


# --------------------------------------------------------------------------- #
# baidu/Unlimited-OCR: known-good path
# --------------------------------------------------------------------------- #

def test_baidu_ocr_available_reflects_import():
    assert isinstance(baidu_ocr_available(), bool)


def test_run_baidu_ocr_known_api_success():
    mock_client = MagicMock()
    mock_client.predict.return_value = {"text": "Calories 180\nProtein 6g", "done": True}
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        text = run_baidu_unlimited_ocr(_test_image())
    assert text == "Calories 180\nProtein 6g"
    # Confirm the known call shape was used (api_name + expected kwargs)
    _, kwargs = mock_client.predict.call_args
    assert kwargs["api_name"] == "/run_ocr"
    assert kwargs["mode"] == "gundam"


def test_run_baidu_ocr_passes_correct_mode():
    mock_client = MagicMock()
    mock_client.predict.return_value = {"text": "some text", "done": True}
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        run_baidu_unlimited_ocr(_test_image(), mode="base")
    _, kwargs = mock_client.predict.call_args
    assert kwargs["mode"] == "base"


def test_run_baidu_ocr_missing_dependency_raises_clear_error():
    with patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", False):
        try:
            run_baidu_unlimited_ocr(_test_image())
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "gradio_client" in str(e)


def test_run_baidu_ocr_client_construction_failure_raises_clear_error():
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
    # Discovery fallback would also be tried and should fail cleanly too
    mock_client.view_api.return_value = {"named_endpoints": {}}
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        try:
            run_baidu_unlimited_ocr(_test_image())
            assert False, "should have raised"
        except CloudOCRError:
            pass


# --------------------------------------------------------------------------- #
# baidu/Unlimited-OCR: fallback / future-proofing mechanisms
# --------------------------------------------------------------------------- #

def test_run_baidu_ocr_falls_back_to_discovery_when_known_api_fails():
    """The core future-proofing test: if the known api_name/params raise
    (simulating the Space's API having changed), the code should
    automatically discover and call whatever OCR-like endpoint currently
    exists instead of just failing."""
    mock_client = MagicMock()
    # Known call raises (as if /run_ocr no longer exists)
    # Discovery finds a renamed endpoint "/extract_text" instead
    mock_client.predict.side_effect = [
        Exception("no endpoint named /run_ocr"),  # known-api attempt fails
        {"text": "recovered via discovery", "done": True},  # discovery attempt succeeds
    ]
    mock_client.view_api.return_value = {
        "named_endpoints": {
            "/extract_text_ocr": {
                "parameters": [
                    {"label": "Input Image", "parameter_name": "img"},
                    {"label": "Resolution Mode", "parameter_name": "res_mode"},
                    {"label": "Prompt text", "parameter_name": "instruction"},
                ]
            }
        }
    }
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        text = run_baidu_unlimited_ocr(_test_image())
    assert text == "recovered via discovery"
    # Second predict call should have used the discovered endpoint name
    second_call_kwargs = mock_client.predict.call_args_list[1][1]
    assert second_call_kwargs["api_name"] == "/extract_text_ocr"
    assert "img" in second_call_kwargs  # matched by "image" in label
    assert "res_mode" in second_call_kwargs  # matched by "mode" in label
    assert "instruction" in second_call_kwargs  # matched by "prompt" in label


def test_run_baidu_ocr_remembers_working_strategy_across_calls():
    """Once discovery is confirmed to work, subsequent calls should try
    discovery first rather than repeating the failed known-api attempt."""
    mock_client = MagicMock()
    mock_client.predict.side_effect = [
        Exception("known api broken"),
        {"text": "first call via discovery", "done": True},
    ]
    mock_client.view_api.return_value = {
        "named_endpoints": {"/new_ocr": {"parameters": [{"label": "image", "parameter_name": "image"}]}}
    }
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        run_baidu_unlimited_ocr(_test_image())
        assert cloud_ocr._baidu_working_strategy == "discovered"

        # Second call: discovery should be attempted FIRST this time
        mock_client.predict.side_effect = [{"text": "second call, discovery first", "done": True}]
        text2 = run_baidu_unlimited_ocr(_test_image())
    assert text2 == "second call, discovery first"


def test_run_baidu_ocr_both_strategies_fail_raises_clear_combined_error():
    mock_client = MagicMock()
    mock_client.predict.side_effect = Exception("totally broken")
    mock_client.view_api.return_value = {"named_endpoints": {}}
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        try:
            run_baidu_unlimited_ocr(_test_image())
            assert False, "should have raised"
        except CloudOCRError as e:
            # Should mention that the API may have changed, not just a
            # generic network error
            assert "api" in str(e).lower() or "changed" in str(e).lower() or "busy" in str(e).lower()


def test_run_baidu_ocr_discovery_skips_non_image_endpoints():
    """Discovery should skip endpoints that don't look like they accept
    an image at all, rather than calling something irrelevant."""
    mock_client = MagicMock()
    mock_client.predict.side_effect = [
        Exception("known api broken"),
        {"text": "found the right one", "done": True},
    ]
    mock_client.view_api.return_value = {
        "named_endpoints": {
            "/unrelated_endpoint": {"parameters": [{"label": "some_text_param", "parameter_name": "x"}]},
            "/actual_ocr": {"parameters": [{"label": "photo", "parameter_name": "photo"}]},
        }
    }
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True):
        text = run_baidu_unlimited_ocr(_test_image())
    assert text == "found the right one"


def test_temp_file_cleaned_up_after_call(tmp_path):
    """Resource-hygiene check: the temp image file created for the
    upload shouldn't linger on disk after the call completes."""
    created_paths = []
    real_named_temp_file = __import__("tempfile").NamedTemporaryFile

    def tracking_temp_file(*args, **kwargs):
        f = real_named_temp_file(*args, **kwargs)
        created_paths.append(f.name)
        return f

    mock_client = MagicMock()
    mock_client.predict.return_value = {"text": "some text", "done": True}
    with patch("modules.cloud_ocr.GradioClient", return_value=mock_client), \
         patch("modules.cloud_ocr.handle_file", return_value="handled_file_ref"), \
         patch("modules.cloud_ocr._HAS_GRADIO_CLIENT", True), \
         patch("modules.cloud_ocr.tempfile.NamedTemporaryFile", side_effect=tracking_temp_file):
        run_baidu_unlimited_ocr(_test_image())

    assert len(created_paths) == 1
    assert not os.path.exists(created_paths[0])


# --------------------------------------------------------------------------- #
# _extract_text_from_mistral_response: defensive multi-shape parsing
# --------------------------------------------------------------------------- #

def test_extract_mistral_response_documented_shape():
    data = {"pages": [{"markdown": "Page One"}, {"markdown": "Page Two"}]}
    assert _extract_text_from_mistral_response(data) == "Page One\n\nPage Two"


def test_extract_mistral_response_alternate_page_key():
    # Simulates Mistral renaming "markdown" to "text" in a future version
    data = {"pages": [{"text": "Page via alternate key"}]}
    assert _extract_text_from_mistral_response(data) == "Page via alternate key"


def test_extract_mistral_response_alternate_top_level_shape():
    # Simulates a hypothetical schema change with no "pages" key at all
    assert _extract_text_from_mistral_response({"text": "top level text"}) == "top level text"
    assert _extract_text_from_mistral_response({"content": "top level content"}) == "top level content"


def test_extract_mistral_response_empty_returns_empty_string():
    assert _extract_text_from_mistral_response({}) == ""
    assert _extract_text_from_mistral_response({"pages": []}) == ""


# --------------------------------------------------------------------------- #
# _model_rejected: distinguishing "bad model ID" from other errors
# --------------------------------------------------------------------------- #

def _response(status_code, json_body=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body or {}
    resp.text = str(json_body or {})
    return resp


def test_model_rejected_true_for_model_not_found_message():
    resp = _response(400, {"message": "Model 'foo' not found"})
    assert _model_rejected(resp) is True


def test_model_rejected_true_for_invalid_model_message():
    resp = _response(404, {"error": "invalid model specified"})
    assert _model_rejected(resp) is True


def test_model_rejected_false_for_unrelated_400_error():
    resp = _response(400, {"message": "Invalid image format"})
    assert _model_rejected(resp) is False


def test_model_rejected_false_for_non_4xx_status():
    resp = _response(500, {"message": "model not found"})
    assert _model_rejected(resp) is False


def test_model_rejected_false_for_unparseable_json():
    resp = MagicMock()
    resp.status_code = 400
    resp.json.side_effect = ValueError("not json")
    assert _model_rejected(resp) is False


# --------------------------------------------------------------------------- #
# Mistral OCR: known-good path
# --------------------------------------------------------------------------- #

def test_run_mistral_ocr_success():
    api_response = {
        "pages": [
            {"index": 0, "markdown": "Nutrition Facts\nCalories 180"},
            {"index": 1, "markdown": "Protein 6g"},
        ]
    }
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _response(200, api_response)
        text = run_mistral_ocr(_test_image(), api_key="fake-key-123")
    assert "Nutrition Facts" in text
    assert "Calories 180" in text
    assert "Protein 6g" in text


def test_run_mistral_ocr_sends_correct_payload():
    api_response = {"pages": [{"markdown": "some text"}]}
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _response(200, api_response)
        run_mistral_ocr(_test_image(), api_key="my-secret-key")

    args, kwargs = mock_post.call_args
    assert args[0] == MISTRAL_OCR_URL or kwargs.get("url") == MISTRAL_OCR_URL
    assert kwargs["headers"]["Authorization"] == "Bearer my-secret-key"
    assert kwargs["json"]["model"] == cloud_ocr._MISTRAL_MODEL_CANDIDATES[0]
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
        mock_post.return_value = _response(401, {"error": "unauthorized"})
        try:
            run_mistral_ocr(_test_image(), api_key="bad-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "401" in str(e) or "key" in str(e).lower()


def test_run_mistral_ocr_rate_limit_raises_specific_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _response(429, {})
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "429" in str(e) or "rate limit" in str(e).lower()


def test_run_mistral_ocr_server_error_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _response(500, {})
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "500" in str(e)


def test_run_mistral_ocr_timeout_raises_clear_error():
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.side_effect = requests.exceptions.Timeout("timed out")
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
        mock_post.return_value = _response(200, {"pages": []})
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError:
            pass


def test_run_mistral_ocr_result_feeds_into_existing_parser():
    """The whole point of returning plain text is that it flows through
    the same bilingual/extended-nutrient parser used for local OCR."""
    from modules.ocr_parser import parse_nutrition_text

    api_response = {
        "pages": [{"markdown": "Calories 210\nTotal Fat 9g\nProtein 7g\nSodium 140mg"}]
    }
    with patch("modules.cloud_ocr.requests.post") as mock_post:
        mock_post.return_value = _response(200, api_response)
        text = run_mistral_ocr(_test_image(), api_key="fake-key")

    parsed = parse_nutrition_text(text)
    assert parsed.calories == 210
    assert parsed.total_fat_g == 9
    assert parsed.protein_g == 7
    assert parsed.sodium_mg == 140


# --------------------------------------------------------------------------- #
# Mistral OCR: model-ID fallback chain (future-proofing)
# --------------------------------------------------------------------------- #

def test_run_mistral_ocr_falls_back_to_next_model_on_rejection():
    """Core future-proofing test: if the primary model ID is rejected as
    unknown/unavailable (simulating Mistral retiring/renaming it), the
    code should automatically retry with the next candidate rather than
    failing outright."""
    primary_model = cloud_ocr._MISTRAL_MODEL_CANDIDATES[0]
    fallback_model = cloud_ocr._MISTRAL_MODEL_CANDIDATES[1]

    responses = {
        primary_model: _response(400, {"message": f"Model '{primary_model}' not found"}),
        fallback_model: _response(200, {"pages": [{"markdown": "recovered text"}]}),
    }

    def fake_post(url, json, headers, timeout):
        return responses[json["model"]]

    with patch("modules.cloud_ocr.requests.post", side_effect=fake_post):
        text = run_mistral_ocr(_test_image(), api_key="fake-key")

    assert text == "recovered text"
    assert cloud_ocr._mistral_working_model == fallback_model


def test_run_mistral_ocr_remembers_working_model_across_calls():
    primary_model = cloud_ocr._MISTRAL_MODEL_CANDIDATES[0]
    fallback_model = cloud_ocr._MISTRAL_MODEL_CANDIDATES[1]
    responses = {
        primary_model: _response(400, {"message": f"Model '{primary_model}' not found"}),
        fallback_model: _response(200, {"pages": [{"markdown": "first call"}]}),
    }
    call_log = []

    def fake_post(url, json, headers, timeout):
        call_log.append(json["model"])
        return responses.get(json["model"], _response(200, {"pages": [{"markdown": "second call"}]}))

    with patch("modules.cloud_ocr.requests.post", side_effect=fake_post):
        run_mistral_ocr(_test_image(), api_key="fake-key")
        assert cloud_ocr._mistral_working_model == fallback_model

        call_log.clear()
        run_mistral_ocr(_test_image(), api_key="fake-key")

    # Second call should go straight to the remembered working model,
    # not repeat the failed primary-model attempt first.
    assert call_log == [fallback_model]


def test_run_mistral_ocr_all_models_rejected_raises_helpful_error():
    def fake_post(url, json, headers, timeout):
        return _response(400, {"message": f"Model '{json['model']}' not found"})

    with patch("modules.cloud_ocr.requests.post", side_effect=fake_post):
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            msg = str(e).lower()
            assert "model" in msg
            assert "_mistral_model_candidates" in msg.lower() or "retired" in msg or "renamed" in msg


def test_run_mistral_ocr_non_model_error_does_not_trigger_fallback():
    """A 400 error unrelated to the model (e.g. bad image data) shouldn't
    cause the code to burn through every model candidate -- it should
    fail immediately with the real error."""
    call_log = []

    def fake_post(url, json, headers, timeout):
        call_log.append(json["model"])
        return _response(400, {"message": "Invalid image encoding"})

    with patch("modules.cloud_ocr.requests.post", side_effect=fake_post):
        try:
            run_mistral_ocr(_test_image(), api_key="fake-key")
            assert False, "should have raised"
        except CloudOCRError as e:
            assert "400" in str(e)
    # Should have only tried the first model, not fallen through all of them
    assert len(call_log) == 1
