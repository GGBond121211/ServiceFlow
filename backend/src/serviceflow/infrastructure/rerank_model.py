from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import httpx

QWEN_TEXT_RERANK_MODEL = "qwen3.7-text-rerank"
QWEN_TEXT_RERANK_ENDPOINT_SUFFIX = "/api/v1/services/rerank/text-rerank/text-rerank"
DEFAULT_RERANK_INSTRUCT = (
    "Given a web search query, retrieve relevant passages that answer the query."
)


class RerankCallError(RuntimeError):
    pass


class RerankResponseError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class RerankResult:
    index: int
    relevance_score: float


class QwenTextReranker:
    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        model: str = QWEN_TEXT_RERANK_MODEL,
        timeout_seconds: float = 30.0,
        max_documents: int = 500,
        max_item_characters: int = 30_000,
        recommended_request_characters: int = 120_000,
        instruct: str = DEFAULT_RERANK_INSTRUCT,
    ) -> None:
        self._api_key = api_key
        self._endpoint = endpoint
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_documents = max_documents
        self.max_item_characters = max_item_characters
        self.recommended_request_characters = recommended_request_characters
        self.instruct = instruct

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> QwenTextReranker:
        source = os.environ if environ is None else environ
        api_key = (
            source.get("SERVICEFLOW_RERANK_API_KEY")
            or source.get("SERVICEFLOW_EMBEDDING_API_KEY")
            or source.get("CODEINSIGHT_EMBEDDING_API_KEY")
            or source.get("DASHSCOPE_API_KEY")
        )
        if not api_key:
            raise ValueError(
                "重排启用时必须配置 SERVICEFLOW_RERANK_API_KEY 或复用 Embedding/DASHSCOPE API Key"
            )
        endpoint = source.get("SERVICEFLOW_RERANK_BASE_URL") or _endpoint_from_embedding_url(
            source.get("SERVICEFLOW_EMBEDDING_BASE_URL")
            or source.get("CODEINSIGHT_EMBEDDING_BASE_URL")
        )
        if not endpoint:
            raise ValueError(
                "重排启用时必须配置 SERVICEFLOW_RERANK_BASE_URL 或 Embedding base URL"
            )
        return cls(
            api_key=api_key,
            endpoint=endpoint,
            model=source.get("SERVICEFLOW_RERANK_MODEL") or QWEN_TEXT_RERANK_MODEL,
            timeout_seconds=float(source.get("SERVICEFLOW_RERANK_TIMEOUT_S", "30")),
        )

    def rerank(
        self,
        query: str,
        documents: Sequence[str],
        *,
        top_n: int,
    ) -> tuple[RerankResult, ...]:
        self._validate_input(query, documents, top_n)
        response = self._post(
            {
                "model": self.model,
                "input": {"query": query, "documents": list(documents)},
                "parameters": {"top_n": top_n, "instruct": self.instruct},
            }
        )
        return self._parse_response(response, document_count=len(documents))

    def _validate_input(self, query: str, documents: Sequence[str], top_n: int) -> None:
        if not query.strip() or not documents or any(not item.strip() for item in documents):
            raise ValueError("重排输入的 query 和 documents 都必须是非空文本")
        if len(documents) > self.max_documents:
            raise ValueError(f"重排候选文档不能超过 {self.max_documents} 条")
        if top_n <= 0 or top_n > len(documents):
            raise ValueError("top_n 必须在 1 和候选文档数之间")
        if len(query) > self.max_item_characters:
            raise ValueError("query 超过官方单条 30,000 Token 限制的保守字符预检")
        if any(len(item) > self.max_item_characters for item in documents):
            raise ValueError("document 超过官方单条 30,000 Token 限制的保守字符预检")
        request_characters = len(query) * len(documents) + sum(map(len, documents))
        if request_characters > self.recommended_request_characters:
            raise ValueError("重排请求超过官方建议的总输入 Token 限制的保守字符预检")

    def _post(self, payload: dict[str, object]) -> dict[str, object]:
        try:
            response = httpx.post(
                self._endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            if response.status_code >= 400:
                raise RerankCallError(f"重排请求失败（HTTP {response.status_code}）")
        except httpx.HTTPError as error:
            raise RerankCallError("重排请求失败") from error
        try:
            value = response.json()
        except ValueError as error:
            raise RerankResponseError("重排响应不是合法 JSON") from error
        if not isinstance(value, dict):
            raise RerankResponseError("重排响应必须是 JSON 对象")
        return value

    def _parse_response(
        self,
        response: dict[str, object],
        *,
        document_count: int,
    ) -> tuple[RerankResult, ...]:
        output = response.get("output")
        results = output.get("results") if isinstance(output, dict) else None
        if not isinstance(results, list) or not results:
            raise RerankResponseError("重排响应缺少 output.results")
        parsed = []
        seen: set[int] = set()
        for item in results:
            if not isinstance(item, dict):
                raise RerankResponseError("重排结果项必须是 JSON 对象")
            try:
                index = int(item["index"])
                score = float(item["relevance_score"])
            except (KeyError, TypeError, ValueError) as error:
                raise RerankResponseError("重排结果缺少合法 index 或 relevance_score") from error
            if index < 0 or index >= document_count or index in seen:
                raise RerankResponseError("重排结果 index 越界或重复")
            if not 0.0 <= score <= 1.0:
                raise RerankResponseError("重排 relevance_score 必须在 0 到 1 之间")
            seen.add(index)
            parsed.append(RerankResult(index, score))
        return tuple(parsed)


def _endpoint_from_embedding_url(base_url: str | None) -> str | None:
    if not base_url:
        return None
    base = base_url.rstrip("/")
    for suffix in ("/compatible-mode/v1", "/compatible-api/v1", "/api/v1"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"{base}{QWEN_TEXT_RERANK_ENDPOINT_SUFFIX}"
