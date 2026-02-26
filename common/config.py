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
        self.miniflux_webhook_queue_max_size = self.get_config_value('miniflux', 'webhook_queue_max_size', 1000)
        self.miniflux_webhook_queue_workers = self.get_config_value('miniflux', 'webhook_queue_workers', 2)
        self.miniflux_dedup_marker = self.get_config_value('miniflux', 'dedup_marker', '<!-- miniflux-ai:processed -->')

        self.llm_provider = self.get_config_value('llm', 'provider', 'openai')
        self.llm_base_url = self.get_config_value('llm', 'base_url', None)
        self.llm_api_key = self.get_config_value('llm', 'api_key', None)
        self.llm_model = self.get_config_value('llm', 'model', None)
        self.llm_max_length = self.get_config_value('llm', 'max_length', None)
        self.llm_timeout = self.get_config_value('llm', 'timeout', 60)
        self.llm_max_workers = self.get_config_value('llm', 'max_workers', 4)
        self.llm_RPM = self.get_config_value('llm', 'RPM', 1000)

        self.ai_news_url = self.get_config_value('ai_news', 'url', None)
        self.ai_news_schedule = self.get_config_value('ai_news', 'schedule', None)
        self.ai_news_prompts = self.get_config_value('ai_news', 'prompts', None)

        self.agents = self.c.get('agents', {})

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
