"""Grounded search, network budgets, robots, cache and no-paid-call routing. No real network or audio."""
import ast
import copy
import json
import socket
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import requests
from commands import web_search as ws
from tests.test_unmatched_turn import Harness

ROWS = [
    {'title': 'Lima', 'url': 'https://example.org/lima',
     'snippet': 'Lima is the capital city of Peru. The city sits on the Pacific coast of South America.', 'page': ''},
    {'title': 'Lima beans', 'url': 'https://example.net/beans',
     'snippet': 'Lima beans are a variety of edible bean. They are also known as butter beans in some places.', 'page': ''},
]
HTML = '''<div><a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Flima">Lima &amp; Peru</a>
<a class="result__snippet">Lima is the <b>capital city</b> of Peru. The city sits on the Pacific coast of South America.</a></div>'''


def model(sentences=None, alternate=None, answerable=True):
    if not answerable:
        content = 'INSUFFICIENT'
    else:
        if sentences is None:
            sentences = [{'text': "Peru's capital is Lima.", 'source': 1}]
        content = ' '.join('{text} [{source}]'.format(**sentence) for sentence in sentences)
        if alternate:
            content += '\nAlternative: ' + str(alternate)
    return {'choices': [{'message': {'content': content}}]}


class Clock:
    def __init__(self):
        self.now = 1000
    def __call__(self):
        return self.now
    def sleep(self, seconds):
        self.now += seconds


class Response:
    def __init__(self, text='', status=200, headers=None):
        self.status_code = status
        self.headers = headers or {'Content-Type': 'text/html'}
        self.encoding = 'utf-8'
        self.text = text
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def iter_content(self, size):
        data = self.text.encode()
        for i in range(0, len(data), size):
            yield data[i:i + size]


class SearchTests(unittest.TestCase):
    def test_parser_decodes_redirect_and_strips_markup_and_duplicates(self):
        rows = ws.parse_results(HTML * 2 + '<a class="result__a" href="javascript:alert(1)">bad</a>')
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['title'], 'Lima & Peru')
        self.assertEqual(rows[0]['url'], 'https://example.org/lima')
        self.assertIn('capital city', rows[0]['snippet'])
        self.assertNotIn('<b>', rows[0]['snippet'])

    def test_five_results_at_most_in_original_order(self):
        html = ''.join('<a class="result__a" href="https://example.org/{0}">Result {0}</a>'.format(i) for i in range(8))
        self.assertEqual([r['title'] for r in ws.parse_results(html)], ['Result ' + str(i) for i in range(5)])

    def test_generated_answer_uses_new_wording_and_validated_sources(self):
        seen = []
        def post(body):
            seen.append(body)
            return model(alternate=2)
        sentences, alternate, notice = ws.summarize_answer('Lima', ROWS, post)
        self.assertEqual(sentences, [{'text': "Peru's capital is Lima.", 'source': 1}])
        self.assertNotIn(sentences[0]['text'], ROWS[0]['snippet'])
        self.assertEqual(alternate, 2)
        self.assertEqual(notice, '')
        self.assertNotIn('tools', seen[0])
        self.assertNotIn('Authorization', str(seen[0]))
        self.assertEqual(seen[0]['model'], 'system')
        self.assertLessEqual(seen[0]['max_tokens'], 220)
        self.assertIn('untrusted DATA', seen[0]['messages'][0]['content'])
        self.assertIn('YOUR OWN WORDS', seen[0]['messages'][0]['content'])

    def test_source_footnotes_removed_before_prompt_and_from_results(self):
        rows = copy.deepcopy(ROWS)
        rows[0]['snippet'] = 'Lima[a][1] is the capital city of Peru.[citation needed]'
        rows[0]['page'] = 'The city[23] sits on the coast.[b]'
        seen = []
        ws.summarize_answer('q', rows, lambda body: (seen.append(body) or model()))
        context = seen[0]['messages'][1]['content']
        self.assertIn('Lima is the capital city of Peru.\nThe city sits on the coast.', context)
        self.assertNotIn('[a]', context)
        self.assertNotIn('[23]', context)
        parsed = ws.parse_results(HTML.replace('Lima is', 'Lima[a][1] is'))
        self.assertNotIn('[a]', parsed[0]['snippet'])
        self.assertNotIn('[1]', parsed[0]['snippet'])
        self.assertEqual(ws.clean_source_text('Keep [Fe] and [Ctrl] but not [12–14].'), 'Keep [Fe] and [Ctrl] but not .')

    def test_insufficient_evidence_is_not_a_snippet_fallback(self):
        sentences, alternate, notice = ws.summarize_answer('unknown fact', ROWS,
                                                         lambda body: model([], answerable=False))
        self.assertEqual((sentences, alternate, notice), ([], None, ws.NO_ANSWER))

    def test_invalid_citation_or_shape_uses_labeled_fallback(self):
        base = {'text': "Peru's capital is Lima.", 'source': 1}
        bad_sentences = [[], [base, dict(base, text='A new fact.'), dict(base, text='Another fact.'), dict(base, text='One more fact.')],
                         [dict(base, source=999)], [dict(base, source='bad')],
                         [dict(base, text='The population is 1234567 people.')],
                         [dict(base, text='First fact. Second new detail. Third useful idea. Fourth distinct thought.')],
                         [dict(base, text='Long ' * 40)], [dict(base, text='https://evil.example/')]]
        for generated in bad_sentences:
            with self.subTest(generated=generated):
                sentences, alternate, notice = ws.summarize_answer('q', ROWS, lambda body: model(generated))
                self.assertEqual(notice, ws.MODEL_UNAVAILABLE)
                self.assertEqual(sentences, ws.fallback_snippets(ROWS))
                self.assertIsNone(alternate)
                result = {'sentences': sentences, 'notice': notice, 'fallback': True}
                self.assertTrue(ws.answer_text(result).startswith('From the web: '))
                self.assertIn('[1]', ws.answer_text(result))

    def test_repeated_or_rephrased_facts_are_dropped(self):
        base = {'text': "Peru's capital is Lima.", 'source': 1}
        repeat = dict(base, text='Lima is the capital of Peru.')
        extra = {'text': 'It lies on South America’s Pacific coast.', 'source': 1}
        generated = [base, repeat, extra]
        sentences, _, notice = ws.summarize_answer('q', ROWS, lambda body: model(generated))
        self.assertEqual([s['text'] for s in sentences], [base['text'], extra['text']])
        self.assertEqual(notice, '')

    def test_paragraph_citation_applies_to_each_generated_sentence(self):
        response = {'choices': [{'message': {'content': "Peru's capital is Lima. It lies along the Pacific coast. [1]"}}]}
        sentences, _, notice = ws.summarize_answer('q', ROWS, lambda body: response)
        self.assertEqual(sentences, [{'text': "Peru's capital is Lima.", 'source': 1},
                                     {'text': 'It lies along the Pacific coast.', 'source': 1}])
        self.assertEqual(notice, '')

    def test_citation_before_terminal_punctuation_is_valid(self):
        response = {'choices': [{'message': {'content': "Peru's capital is Lima [1]."}}]}
        self.assertEqual(ws.summarize_answer('q', ROWS, lambda body: response),
                         ([{'text': "Peru's capital is Lima.", 'source': 1}], None, ''))

    def test_empty_alternative_metadata_does_not_discard_a_valid_answer(self):
        for empty in ('N.', 'none', 'null', '0'):
            response = {'choices': [{'message': {'content': "Peru's capital is Lima [1].\nAlternative: " + empty}}]}
            self.assertEqual(ws.summarize_answer('q', ROWS, lambda body: response),
                             ([{'text': "Peru's capital is Lima.", 'source': 1}], None, ''))

    def test_copied_long_sentence_is_a_labeled_model_failure(self):
        rows = copy.deepcopy(ROWS)
        copied = 'The city sits on the Pacific coast of South America.'
        self.assertEqual(ws.summarize_answer('q', rows, lambda body: model([{'text': copied, 'source': 1}]))[2],
                         ws.MODEL_UNAVAILABLE)

    def test_three_generated_sentences_and_no_snippet_when_fm_succeeds(self):
        generated = [dict(text="Peru's capital is Lima.", source=1),
                     dict(text='It lies on South America’s Pacific coast.', source=1),
                     dict(text='The other meaning is an edible bean.', source=2)]
        with patch.object(ws, 'fallback_snippets', side_effect=AssertionError('must not copy snippets')):
            sentences, _, notice = ws.summarize_answer('Lima', ROWS, lambda body: model(generated))
        self.assertEqual(len(sentences), 3)
        self.assertEqual(notice, '')

    def test_model_down_or_uncited_output_uses_clean_snippet_fallback(self):
        def down(body):
            raise requests.Timeout()
        for post in (down, lambda body: {}, lambda body: {'choices': [{'message': {'content': 'uncited answer'}}]}):
            sentences, alternate, notice = ws.summarize_answer('q', ROWS, post)
            self.assertEqual((sentences, alternate, notice), (ws.fallback_snippets(ROWS), None, ws.MODEL_UNAVAILABLE))
        rows = copy.deepcopy(ROWS)
        rows[0]['snippet'] = 'Lima[a][1] is the capital city of Peru. A repeat is not needed.'
        self.assertEqual(ws.summarize_answer('q', rows, down)[0], [{'text': 'Lima is the capital city of Peru.', 'source': 1}])

    def test_no_evidence_does_not_call_model(self):
        post = Mock()
        self.assertEqual(ws.summarize_answer('q', [], post)[2], ws.NO_ANSWER)
        post.assert_not_called()

    def test_model_endpoint_fixed_local_no_redirects(self):
        response = Mock()
        response.json.return_value = model()
        session = Mock()
        session.post.return_value = response
        with patch.object(ws.requests, 'Session', return_value=session):
            ws.summarize_answer('q', ROWS)
        self.assertEqual(session.post.call_args.args[0], 'http://127.0.0.1:1976/v1/chat/completions')
        self.assertEqual(session.post.call_args.kwargs['allow_redirects'], False)
        self.assertNotIn('headers', session.post.call_args.kwargs)
        self.assertFalse(session.trust_env)
        session.close.assert_called_once()

    def test_cache_ten_minutes_and_no_more_than_three_page_fetches(self):
        clock, fetcher = Clock(), Mock()
        fetcher.get.return_value = '<p>Lima is located on the Pacific coast.</p>'
        engine = ws.SearchEngine(fetcher, lambda body: model(), clock)
        rows = ROWS + [dict(ROWS[0], url='https://example.org/' + str(i)) for i in range(3)]
        with patch.object(ws, 'parse_results', side_effect=lambda html: copy.deepcopy(rows)):
            first = engine.search('search Lima')
            self.assertEqual(fetcher.get.call_count, 4)  # one SERP plus three pages
            first['results'].clear()
            self.assertEqual(len(engine.search('Lima')['results']), 5)
            self.assertEqual(fetcher.get.call_count, 4)
            clock.now += 600
            engine.search('Lima')
            self.assertEqual(fetcher.get.call_count, 8)

    def test_unavailable_model_recovers_without_refetching_web(self):
        fetcher = Mock()
        fetcher.get.return_value = HTML
        post = Mock(side_effect=[requests.ConnectionError(), model()])
        engine = ws.SearchEngine(fetcher, post)
        first = engine.search('Lima')
        self.assertEqual(first['notice'], ws.MODEL_UNAVAILABLE)
        before = fetcher.get.call_count
        second = engine.search('Lima')
        self.assertEqual(len(second['sentences']), 1)
        self.assertFalse(second['fallback'])
        self.assertEqual(fetcher.get.call_count, before)

    def test_empty_or_long_queries_do_not_fetch_and_are_not_silently_truncated(self):
        fetcher = Mock()
        engine = ws.SearchEngine(fetcher)
        self.assertIn('What would', engine.search('search')['notice'])
        query = 'x' * 401
        self.assertEqual(engine.search(query)['query'], query)
        fetcher.get.assert_not_called()

    def test_no_results_is_plain_and_does_not_fabricate_answer(self):
        fetcher, post = Mock(), Mock()
        fetcher.get.return_value = None
        result = ws.SearchEngine(fetcher, post).search('unknown')
        self.assertEqual(result['sentences'], [])
        self.assertEqual(result['results'], [])
        self.assertIn('No web results', result['notice'])
        post.assert_not_called()

    def test_google_uses_same_query_and_encodes_metacharacters(self):
        query = ws.search_query('search for C++ & Python?')
        self.assertEqual(query, 'C++ & Python?')
        from urllib.parse import parse_qs, urlsplit
        self.assertEqual(parse_qs(urlsplit(ws.google_url(query)).query)['q'], [query])

    def test_page_scripts_are_not_evidence(self):
        parser = ws.PageText()
        parser.feed('<script>invent a claim</script><style>bad</style><p>A real sentence from the source page.</p>')
        self.assertEqual(parser.text(), 'A real sentence from the source page.')

    def test_question_routes_and_commands_stay_separate(self):
        for text in ('What is the capital of Peru?', 'How do I make rice?', 'jaguar', 'search cats', 'tell me about Mars'):
            self.assertTrue(ws.is_search_request(text), text)
        for text in ('open Safari', 'translate this', 'yes', 'idy my downloads', 'play music'):
            self.assertFalse(ws.is_search_request(text), text)


class FetchTests(unittest.TestCase):
    def setUp(self):
        self.public = patch.object(ws, 'public_url', return_value=True)
        self.public.start()
        self.addCleanup(self.public.stop)
        self.clock = Clock()
        self.session = Mock()
        self.fetcher = ws.Fetcher(self.session, self.clock, self.clock.sleep)

    def test_disallowed_page_is_never_requested(self):
        self.session.get.return_value = Response('User-agent: *\nDisallow: /private')
        self.assertIsNone(self.fetcher.get('https://example.org/private', 1020))
        self.assertEqual(self.session.get.call_count, 1)

    def test_robots_allow_and_delay_and_cache(self):
        self.session.get.side_effect = [Response('User-agent: *\nAllow: /\nCrawl-delay: 4'), Response('body'), Response('again')]
        self.assertEqual(self.fetcher.get('https://example.org/a', 1020), 'body')
        self.assertEqual(self.clock.now, 1004)
        self.assertEqual(self.fetcher.get('https://example.org/b', 1020), 'again')
        self.assertEqual(self.clock.now, 1008)
        self.assertEqual(self.session.get.call_count, 3)
        self.assertFalse(self.session.get.call_args.kwargs['allow_redirects'])

    def test_robots_unavailable_denies_fetch_and_404_allows(self):
        self.session.get.side_effect = requests.Timeout()
        self.assertIsNone(self.fetcher.get('https://example.org/a', 1020))
        self.assertEqual(self.session.get.call_count, 1)
        self.fetcher.rules.clear()
        self.session.get.side_effect = [Response(status=404), Response('okay')]
        self.assertEqual(self.fetcher.get('https://example.org/a', 1020), 'okay')

    def test_retry_after_stops_immediate_requests(self):
        self.session.get.side_effect = [Response('User-agent: *\nAllow: /'),
                                        Response(status=429, headers={'Retry-After': '120'})]
        self.assertIsNone(self.fetcher.get('https://example.org/a', 1020))
        self.assertIsNone(self.fetcher.get('https://example.org/b', 1020))
        self.assertEqual(self.session.get.call_count, 2)

    def test_cross_origin_redirect_checks_destination_robots(self):
        self.session.get.side_effect = [Response('User-agent: *\nAllow: /'),
                                        Response(status=302, headers={'Location': 'https://other.org/blocked'}),
                                        Response('User-agent: *\nDisallow: /')]
        self.assertIsNone(self.fetcher.get('https://example.org/a', 1020))
        self.assertEqual(self.session.get.call_count, 3)
        self.assertEqual(self.session.get.call_args.args[0], 'https://other.org/robots.txt')

    def test_published_request_rate_is_respected(self):
        self.session.get.side_effect = [Response('User-agent: *\nAllow: /\nRequest-rate: 1/8'), Response('body')]
        self.assertEqual(self.fetcher.get('https://example.org/a', 1020), 'body')
        self.assertEqual(self.clock.now, 1008)

    def test_private_redirect_is_not_followed(self):
        self.session.get.side_effect = [Response('User-agent: *\nAllow: /'),
                                        Response(status=302, headers={'Location': 'http://127.0.0.1:1976/'})]
        with patch.object(ws, 'public_url', side_effect=lambda u: '127.0.0.1' not in u):
            self.assertIsNone(self.fetcher.get('https://example.org/a', 1020))
        self.assertEqual(self.session.get.call_count, 2)

    def test_byte_budget_and_deadline(self):
        self.session.get.side_effect = [Response('User-agent: *\nAllow: /'), Response('x' * (ws.MAX_BYTES * 2))]
        text = self.fetcher.get('https://example.org/a', 1020)
        self.assertLessEqual(len(text.encode()), ws.MAX_BYTES)
        before = self.session.get.call_count
        self.assertIsNone(self.fetcher.get('https://example.org/a', self.clock.now))
        self.assertEqual(self.session.get.call_count, before)

    def test_real_url_validation_rejects_private_dns_credentials_and_ports(self):
        self.public.stop()
        for url in ('http://127.0.0.1/', 'http://[::1]/', 'http://10.0.0.1/', 'file:///a', 'https://user:pass@example.org/',
                    'https://example.org:1976/', 'http://foo.local/'):
            self.assertFalse(ws.public_url(url), url)
        with patch.object(socket, 'getaddrinfo', return_value=[(0, 0, 0, '', ('192.168.1.1', 0))]):
            self.assertFalse(ws.public_url('https://example.org/'))


class RoutingTests(unittest.TestCase):
    def test_typed_and_spoken_question_bypasses_paid_classifier_and_deliver(self):
        for question in ('What is the capital of Peru?', 'How do I make rice?', 'jaguar'):
            harness = Harness(('llm', None))
            search = Mock()
            harness.ns['_search_turn'] = search
            harness.ns['jev'] = Mock(side_effect=AssertionError('paid classifier'))
            harness.ns['ask_llm'] = Mock(side_effect=AssertionError('paid answer'))
            harness.handle(question)
            search.assert_called_once_with(question, None, None)
            self.assertEqual(harness.delivered, [])

    def test_local_command_keeps_priority_over_search(self):
        harness = Harness(('llm', None))
        harness.ns['decide'] = lambda ans, text: ('actions', [('local',)])
        local, search = Mock(), Mock()
        harness.ns['_run_local'], harness.ns['_search_turn'] = local, search
        harness.handle('what time is it')
        local.assert_called_once()
        search.assert_not_called()

    def test_search_delivery_never_prefetches_or_autoplays(self):
        source = (Path(__file__).resolve().parents[1] / 'siri.py').read_text()
        node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_search_turn')
        result = {'query': 'q', 'results': copy.deepcopy(ROWS), 'sentences': [{'text': "Peru's capital is Lima.", 'source': 1}],
                  'alternative': None, 'notice': ''}
        events = []
        namespace = {'json': json, 'emit': lambda notify, state, detail: events.append((state, detail)), '_remember_reply': Mock()}
        exec(compile(ast.Module(body=[node], type_ignores=[]), '<search>', 'exec'), namespace)
        with patch.object(ws.ENGINE, 'search', return_value=result), patch.object(ws, 'LAST_ANSWER', None):
            namespace['_search_turn']('q', None)
        self.assertEqual([e[0] for e in events], ['Thinking', 'Web Search', 'Ready'])
        self.assertEqual(json.loads(events[1][1]), result)
        self.assertIn('[1]', events[2][1])
        self.assertNotIn('BRIEF_AUDIO', ast.get_source_segment(source, node))


if __name__ == '__main__':
    unittest.main()
