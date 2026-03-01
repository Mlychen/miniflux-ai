import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from adapters.llm_gateway import LLMGateway
from adapters.miniflux_gateway import MinifluxGateway


class TestMinifluxGateway(unittest.TestCase):
    def test_delegates_calls_to_underlying_client(self):
        fake_client = Mock()

        with patch('adapters.miniflux_gateway.miniflux.Client', return_value=fake_client) as ctor:
            gateway = MinifluxGateway('http://miniflux.local', 'api-key')

        ctor.assert_called_once_with('http://miniflux.local', api_key='api-key')

        gateway.me()
        fake_client.me.assert_called_once_with()

        gateway.get_entries(status=['unread'], limit=20)
        fake_client.get_entries.assert_called_once_with(status=['unread'], limit=20)

        gateway.update_entry(10, content='x')
        fake_client.update_entry.assert_called_once_with(10, content='x')

        gateway.get_feeds()
        fake_client.get_feeds.assert_called_once_with()

        gateway.create_feed(category_id=1, feed_url='http://x/rss')
        fake_client.create_feed.assert_called_once_with(category_id=1, feed_url='http://x/rss')

        gateway.refresh_feed(99)
        fake_client.refresh_feed.assert_called_once_with(99)


class TestLLMGateway(unittest.TestCase):
    def test_openai_provider_builds_messages_and_respects_max_length(self):
        cfg = SimpleNamespace(
            llm_provider='openai',
            llm_base_url='http://llm.local/v1',
            llm_api_key='k',
            llm_model='m',
            llm_timeout=33,
            llm_max_length=4,
        )
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='ok'))]
        )
        create = Mock(return_value=completion)
        fake_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(create=create)
            )
        )

        with patch('adapters.llm_gateway.OpenAI', return_value=fake_client):
            gateway = LLMGateway(cfg)
            out = gateway.get_result('system prompt', '123456', logger=None)

        self.assertEqual(out, 'ok')
        create.assert_called_once()
        kwargs = create.call_args.kwargs
        self.assertEqual(kwargs['model'], 'm')
        self.assertEqual(kwargs['timeout'], 33)
        self.assertEqual(kwargs['messages'][0]['content'], 'system prompt')
        self.assertIn('1234', kwargs['messages'][1]['content'])

    def test_gemini_provider_uses_generate_content(self):
        cfg = SimpleNamespace(
            llm_provider='gemini',
            llm_base_url='http://gemini.local',
            llm_api_key='k',
            llm_model='gemini-test',
            llm_timeout=30,
            llm_max_length=None,
        )
        response = SimpleNamespace(text='gemini-ok')
        generate_content = Mock(return_value=response)
        fake_client = SimpleNamespace(
            models=SimpleNamespace(generate_content=generate_content)
        )

        with patch(
            'adapters.llm_gateway.types.HttpOptions',
            side_effect=lambda base_url: {'base_url': base_url},
        ), patch(
            'adapters.llm_gateway.types.GenerateContentConfig',
            side_effect=lambda system_instruction: {'system_instruction': system_instruction},
        ), patch(
            'adapters.llm_gateway.genai.Client',
            return_value=fake_client,
        ):
            gateway = LLMGateway(cfg)
            out = gateway.get_result('${content}', 'hello', logger=None)

        self.assertEqual(out, 'gemini-ok')
        generate_content.assert_called_once()
        kwargs = generate_content.call_args.kwargs
        self.assertEqual(kwargs['model'], 'gemini-test')
        self.assertEqual(kwargs['contents'], 'hello')
        self.assertEqual(
            kwargs['config'],
            {'system_instruction': ['You are a helpful assistant.']},
        )


if __name__ == '__main__':
    unittest.main()
