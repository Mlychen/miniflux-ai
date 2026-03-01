import json
from typing import Any, Dict, List, Optional, Tuple

import urllib3
from markdownify import markdownify as md


class LLMGateway:
    def __init__(self, config):
        self._config = config
        self._provider = config.llm_provider or 'openai'
        self._http = urllib3.PoolManager()

    def _join_url(self, base_url: str, path: str) -> str:
        if not base_url:
            return path
        return f"{base_url.rstrip('/')}/{path.lstrip('/')}"

    def _timeout(self) -> urllib3.Timeout:
        timeout = getattr(self._config, "llm_timeout", 60)
        return urllib3.Timeout(total=timeout)

    def _post_json(
        self,
        url: str,
        headers: Dict[str, str],
        payload: Dict[str, Any],
    ) -> Tuple[int, Optional[Dict[str, Any]], str]:
        response = self._http.request(
            "POST",
            url,
            headers=headers,
            body=json.dumps(payload).encode("utf-8"),
            timeout=self._timeout(),
        )
        body_text = response.data.decode("utf-8", errors="replace")
        try:
            return response.status, json.loads(body_text), body_text
        except Exception:
            return response.status, None, body_text

    def _build_openai_messages(self, prompt: str, request: str) -> List[Dict[str, str]]:
        if "${content}" in prompt:
            return [
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": prompt.replace("${content}", md(request)),
                },
            ]
        return [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "The following is the input content:\n---\n " + md(request),
            },
        ]

    def _extract_openai_text(self, data: Dict[str, Any]) -> str:
        try:
            content = data["choices"][0]["message"]["content"]
        except Exception as e:
            raise RuntimeError(f"OpenAI response parse error: {e}") from e

        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    text = item.get("text")
                    if isinstance(text, str):
                        parts.append(text)
            if parts:
                return "".join(parts)
        raise RuntimeError("OpenAI response parse error: missing text content")

    def _extract_gemini_text(self, data: Dict[str, Any]) -> str:
        try:
            parts = data["candidates"][0]["content"]["parts"]
        except Exception as e:
            raise RuntimeError(f"Gemini response parse error: {e}") from e
        if not isinstance(parts, list):
            raise RuntimeError("Gemini response parse error: parts is not a list")
        text_parts = []
        for item in parts:
            if isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str):
                    text_parts.append(text)
        if not text_parts:
            raise RuntimeError("Gemini response parse error: missing text content")
        return "".join(text_parts)

    def _openai_call(self, messages: List[Dict[str, str]]) -> str:
        base = self._config.llm_base_url or ""
        api_key = self._config.llm_api_key or ""
        model = self._config.llm_model
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
        }
        candidates = [
            self._join_url(base, "/chat/completions"),
            self._join_url(base, "/v1/chat/completions"),
        ]
        last_error = None
        for url in candidates:
            status, data, body_text = self._post_json(url, headers, payload)
            if 200 <= status < 300:
                if not isinstance(data, dict):
                    raise RuntimeError("OpenAI response parse error: invalid JSON body")
                return self._extract_openai_text(data)
            last_error = RuntimeError(
                f"OpenAI HTTP error status={status} url={url} body={body_text[:500]}"
            )
        raise last_error or RuntimeError("OpenAI HTTP error: no endpoint candidates")

    def _gemini_call(self, prompt: str, request: str) -> str:
        base = self._config.llm_base_url or ""
        api_key = self._config.llm_api_key or ""
        model = self._config.llm_model
        if "${content}" in prompt:
            system_instruction = "You are a helpful assistant."
            user_text = prompt.replace("${content}", md(request))
        else:
            system_instruction = prompt
            user_text = "The following is the input content:\n---\n " + md(request)
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
        }
        candidates = [
            self._join_url(base, f"/v1beta/models/{model}:generateContent"),
            self._join_url(base, f"/v1/models/{model}:generateContent"),
        ]
        last_error = None
        for url in candidates:
            status, data, body_text = self._post_json(url, headers, payload)
            if 200 <= status < 300:
                if not isinstance(data, dict):
                    raise RuntimeError("Gemini response parse error: invalid JSON body")
                return self._extract_gemini_text(data)
            last_error = RuntimeError(
                f"Gemini HTTP error status={status} url={url} body={body_text[:500]}"
            )
        raise last_error or RuntimeError("Gemini HTTP error: no endpoint candidates")

    def get_result(self, prompt: str, request: str, logger=None):
        if self._config.llm_max_length and len(request) > self._config.llm_max_length:
            request = request[: self._config.llm_max_length]

        if self._provider == "gemini":
            try:
                return self._gemini_call(prompt, request)
            except Exception as e:
                if logger:
                    logger.error(f"Error in get_result (Gemini): {e}")
                raise

        try:
            messages = self._build_openai_messages(prompt, request)
            return self._openai_call(messages)
        except Exception as e:
            if logger:
                logger.error(f"Error in get_result (OpenAI): {e}")
            raise
