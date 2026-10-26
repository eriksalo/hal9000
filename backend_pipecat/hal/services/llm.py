"""LLM factory: Claude for the conversation, a Hailo-hosted model when offline."""

from __future__ import annotations

from loguru import logger
from pipecat.services.anthropic.llm import AnthropicLLMService
from pipecat.services.llm_service import LLMService

from hal.config import HALConfig


def build_claude(config: HALConfig) -> AnthropicLLMService:
    llm_cfg = config.llm
    logger.info(f"LLM: {llm_cfg.model} (effort={llm_cfg.effort}, caching={llm_cfg.enable_prompt_caching})")
    return AnthropicLLMService(
        api_key=llm_cfg.api_key,
        settings=AnthropicLLMService.Settings(
            model=llm_cfg.model,
            max_tokens=llm_cfg.max_tokens,
            effort=llm_cfg.effort,
            enable_prompt_caching=llm_cfg.enable_prompt_caching,
            system_prompt_cache_ttl=llm_cfg.system_prompt_cache_ttl,
        ),
    )


def build_offline_llm(config: HALConfig) -> LLMService:
    """Small on-device model served by hailo-ollama (OpenAI-compatible API)."""
    from pipecat.services.ollama.llm import OLLamaLLMService

    base_url = config.hailo.ollama_url.rstrip("/")
    if not base_url.endswith("/v1"):
        base_url += "/v1"
    logger.info(f"Offline LLM: {config.hailo.offline_model} via {base_url}")
    return OLLamaLLMService(
        base_url=base_url,
        settings=OLLamaLLMService.Settings(model=config.hailo.offline_model, max_tokens=256),
    )
