from app.infrastructure.llm_gateway import LLMGateway


def build_llm_client(config):
    return LLMGateway(config)


def get_ai_result(llm_client, config, prompt: str, request: str, logger=None):
    if hasattr(llm_client, 'get_result'):
        return llm_client.get_result(prompt, request, logger)

    # Backward-compatible fallback for callers that still pass a raw SDK client.
    return build_llm_client(config).get_result(prompt, request, logger)
