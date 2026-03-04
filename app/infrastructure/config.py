from yaml import safe_load


class Config:
    def __init__(self, data=None):
        self.c = data or {}
        self.log_level = self.c.get('log_level', 'INFO')

        self.miniflux_base_url = self.get_config_value('miniflux', 'base_url', None)
        self.miniflux_api_key = self.get_config_value('miniflux', 'api_key', None)
        self.miniflux_webhook_secret = self.get_config_value('miniflux', 'webhook_secret', None)
        self.miniflux_schedule_interval = self.get_config_value('miniflux', 'schedule_interval', None)
        self.miniflux_entry_mode = self.get_config_value('miniflux', 'entry_mode', 'auto')
        self.miniflux_task_store_enabled = self.get_config_value('miniflux', 'task_store_enabled', True)
        self.miniflux_task_workers = self.get_config_value(
            'miniflux', 'task_workers', 2
        )
        self.miniflux_task_claim_batch_size = self.get_config_value(
            'miniflux', 'task_claim_batch_size', 20
        )
        self.miniflux_task_lease_seconds = self.get_config_value(
            'miniflux', 'task_lease_seconds', 60
        )
        self.miniflux_task_poll_interval = self.get_config_value(
            'miniflux', 'task_poll_interval', 1.0
        )
        self.miniflux_task_retry_delay_seconds = self.get_config_value(
            'miniflux', 'task_retry_delay_seconds', 30
        )
        self.miniflux_task_max_attempts = self.get_config_value(
            'miniflux', 'task_max_attempts', 5
        )
        self.miniflux_save_entry_enabled = self.get_config_value(
            'miniflux', 'save_entry_enabled', False
        )
        self.miniflux_save_entry_max_attempts = self.get_config_value(
            'miniflux', 'save_entry_max_attempts', self.miniflux_task_max_attempts
        )
        self.miniflux_dedup_marker = self.get_config_value('miniflux', 'dedup_marker', '<!-- miniflux-ai:processed -->')

        self.llm_provider = self.get_config_value('llm', 'provider', 'openai')
        self.llm_base_url = self.get_config_value('llm', 'base_url', None)
        self.llm_api_key = self.get_config_value('llm', 'api_key', None)
        self.llm_model = self.get_config_value('llm', 'model', None)
        self.llm_max_length = self.get_config_value('llm', 'max_length', None)
        self.llm_timeout = self.get_config_value('llm', 'timeout', 60)
        self.llm_max_workers = self.get_config_value('llm', 'max_workers', 4)
        self.llm_RPM = self.get_config_value('llm', 'RPM', 1000)
        self.llm_daily_limit = self.get_config_value('llm', 'daily_limit', None)
        self.llm_pool_capacity = self.get_config_value('llm', 'pool_capacity', None)
        self.llm_request_expected_retries = self.get_config_value('llm', 'request_expected_retries', 2)
        self.llm_request_ttl_seconds = self.get_config_value('llm', 'request_ttl_seconds', 600)

        self.ai_news_url = self.get_config_value('ai_news', 'url', None)
        self.ai_news_schedule = self.get_config_value('ai_news', 'schedule', None)
        self.ai_news_prompts = self.get_config_value('ai_news', 'prompts', None)
        self.preprocess_prompt = self.c.get('preprocess_prompt')

        self.agents = self.c.get('agents', {})

        # Debug config
        debug_config = self.c.get('debug', {})
        self.debug_enabled = debug_config.get('enabled', False)
        self.debug_host = debug_config.get('host', '0.0.0.0')
        self.debug_port = debug_config.get('port', 8081)

    @classmethod
    def from_file(cls, path='config.yml'):
        with open(path, encoding='utf8') as f:
            data = safe_load(f) or {}
        return cls(data)

    @classmethod
    def from_dict(cls, data):
        return cls(data or {})

    def get_config_value(self, section, key, default=None):
        return self.c.get(section, {}).get(key, default)
