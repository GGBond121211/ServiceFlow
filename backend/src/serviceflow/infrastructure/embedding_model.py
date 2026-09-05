from __future__ import annotations

import os
from collections.abc import Mapping, Sequence

from openai import OpenAI, OpenAIError


class EmbeddingCallError(RuntimeError):
    pass


class EmbeddingResponseError(RuntimeError):
    pass


class OpenAICompatibleEmbedding:
    def __init__(self, *, client: OpenAI, model: str, batch_size: int = 16) -> None:
        self._client = client
        self.model = model
        self.batch_size = batch_size
        self.dimension: int | None = None

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str] | None = None,
    ) -> OpenAICompatibleEmbedding:
        source = os.environ if environ is None else environ
        api_key = source.get("SERVICEFLOW_EMBEDDING_API_KEY") or source.get(
            "CODEINSIGHT_EMBEDDING_API_KEY"
        )
        model = source.get("SERVICEFLOW_EMBEDDING_MODEL") or source.get(
            "CODEINSIGHT_EMBEDDING_MODEL"
        )
        base_url = source.get("SERVICEFLOW_EMBEDDING_BASE_URL") or source.get(
            "CODEINSIGHT_EMBEDDING_BASE_URL"
        )
        if not api_key:
            raise ValueError(
                "必须配置 SERVICEFLOW_EMBEDDING_API_KEY 或 CODEINSIGHT_EMBEDDING_API_KEY"
            )
        if not model:
            raise ValueError(
                "必须配置 SERVICEFLOW_EMBEDDING_MODEL 或 CODEINSIGHT_EMBEDDING_MODEL"
            )
        return cls(
            client=OpenAI(
                api_key=api_key,
                base_url=base_url or None,
                timeout=30.0,
                max_retries=0,
            ),
            model=model,
        )

    def embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts or any(not text.strip() for text in texts):
            raise ValueError("Embedding 输入必须包含非空文本")
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = list(texts[start : start + self.batch_size])
            try:
                response = self._client.embeddings.create(model=self.model, input=batch)
            except OpenAIError as error:
                code = getattr(error, "code", None) or type(error).__name__
                raise EmbeddingCallError(f"Embedding 请求失败（{code}）") from error
            data = sorted(response.data or (), key=lambda item: item.index)
            if len(data) != len(batch):
                raise EmbeddingResponseError("Embedding 返回数量与输入数量不一致")
            vectors.extend(tuple(float(value) for value in item.embedding) for item in data)
        if not vectors or any(not vector for vector in vectors):
            raise EmbeddingResponseError("Embedding 返回结果包含空向量")
        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise EmbeddingResponseError("Embedding 返回向量的维度不一致")
        self.dimension = dimension
        return tuple(vectors)
