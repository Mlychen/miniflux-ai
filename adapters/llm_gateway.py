from markdownify import markdownify as md

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

try:
    from google import genai
    from google.genai import types
except Exception:
    genai = None
    types = None


class LLMGateway:
    def __init__(self, config):
        self._config = config
        self._provider = config.llm_provider or 'openai'
        if self._provider == 'gemini':
            if genai is None or types is None:
                raise RuntimeError(
                    "Gemini provider requires package `google-genai` to be installed correctly."
                )
            self._client = genai.Client(
                http_options=types.HttpOptions(base_url=config.llm_base_url),
                api_key=config.llm_api_key,
            )
        else:
            if OpenAI is None:
                raise RuntimeError(
                    "OpenAI provider requires package `openai` with `OpenAI` client export."
                )
            self._client = OpenAI(base_url=config.llm_base_url, api_key=config.llm_api_key)

    def get_result(self, prompt: str, request: str, logger=None):
        if self._config.llm_max_length and len(request) > self._config.llm_max_length:
            request = request[: self._config.llm_max_length]

        if self._provider == "gemini":
            try:
                if "${content}" in prompt:
                    instruction = ["You are a helpful assistant."]
                    contents = prompt.replace("${content}", md(request))
                else:
                    instruction = [prompt]
                    contents = "The following is the input content:\n---\n " + md(request)

                response = self._client.models.generate_content(
                    model=self._config.llm_model,
                    contents=contents,
                    config=types.GenerateContentConfig(
                        system_instruction=instruction,
                    ),
                )
                return response.text
            except Exception as e:
                if logger:
                    logger.error(f"Error in get_result (Gemini): {e}")
                raise

        if "${content}" in prompt:
            messages = [
                {"role": "system", "content": "You are a helpful assistant."},
                {
                    "role": "user",
                    "content": prompt.replace("${content}", md(request)),
                },
            ]
        else:
            messages = [
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": "The following is the input content:\n---\n " + md(request),
                },
            ]

        try:
            completion = self._client.chat.completions.create(
                model=self._config.llm_model,
                messages=messages,
                timeout=self._config.llm_timeout,
            )
            return completion.choices[0].message.content
        except Exception as e:
            if logger:
                logger.error(f"Error in get_result (OpenAI): {e}")
            raise
