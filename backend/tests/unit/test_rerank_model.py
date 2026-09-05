import httpx
import pytest

from serviceflow.infrastructure.rerank_model import (
    QwenTextReranker,
    RerankResponseError,
    _endpoint_from_embedding_url,
)


def test_endpoint_is_derived_from_dashscope_embedding_url() -> None:
    assert (
        _endpoint_from_embedding_url(
            "https://workspace.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
        )
        == "https://workspace.cn-beijing.maas.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )


def test_reranker_sends_nested_qwen37_request(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_post(url: str, **kwargs: object) -> httpx.Response:
        captured["url"] = url
        captured.update(kwargs)
        return httpx.Response(
            200,
            json={
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.8},
                        {"index": 0, "relevance_score": 0.2},
                    ]
                }
            },
        )

    monkeypatch.setattr("serviceflow.infrastructure.rerank_model.httpx.post", fake_post)
    reranker = QwenTextReranker(api_key="secret", endpoint="https://example.test/rerank")

    result = reranker.rerank("质量问题怎么处理", ["普通退货", "质量维修"], top_n=2)

    assert [(item.index, item.relevance_score) for item in result] == [(1, 0.8), (0, 0.2)]
    assert captured["url"] == "https://example.test/rerank"
    payload = captured["json"]
    assert isinstance(payload, dict)
    assert payload["model"] == "qwen3.7-text-rerank"
    assert payload["input"]["query"] == "质量问题怎么处理"
    assert payload["parameters"]["top_n"] == 2


def test_reranker_rejects_more_than_provider_document_limit() -> None:
    reranker = QwenTextReranker(
        api_key="secret",
        endpoint="https://example.test/rerank",
    )

    with pytest.raises(ValueError, match="500"):
        reranker.rerank("query", ["document"] * 501, top_n=1)


def test_reranker_rejects_malformed_provider_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "serviceflow.infrastructure.rerank_model.httpx.post",
        lambda *args, **kwargs: httpx.Response(200, json={"output": {"results": []}}),
    )
    reranker = QwenTextReranker(api_key="secret", endpoint="https://example.test/rerank")

    with pytest.raises(RerankResponseError, match="output.results"):
        reranker.rerank("query", ["document"], top_n=1)
