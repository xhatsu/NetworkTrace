"""Isolated alert tests; no database or notification service is contacted."""
import json
import unittest
from contextlib import contextmanager
from unittest.mock import Mock, patch

from backend.app.services import alerting


class AlertMessageTests(unittest.TestCase):
    def payload(self):
        return {
            'rule': {'name': 'Latency rule', 'severity': 'warning'},
            'change': {'id': 'anm-test', 'summary': 'Latency increased',
                       'state': 'watch', 'status': 'open', 'started_at': 0,
                       'last_seen_at': 60000, 'signal_count': 2,
                       'highlights': [{'label': 'Latency', 'before': 0, 'after': 500,
                                       'unit': 'ms', 'delta': 0}],
                       'evidence': [{'detector': 'latency', 'detail': 'Measured impact'}],
                       'abnormality': {'reasons': ['Persistence insufficient']}},
            'scope': {'service': 'checkout', 'caller': 'gateway', 'principal': 'svc-user'},
            'links': {'change': 'https://example.test/changes/anm-test'},
        }

    def test_details_and_zero_values(self):
        message = alerting.format_alert_message(self.payload())
        for expected in ('Latency rule', 'Evaluation: watch', 'Workflow: open',
                         'checkout', 'gateway', 'svc-user', '1970-01-01 00:00:00 UTC',
                         'reference 0 → observed 500 ms; change 0%',
                         'Evidence [latency]: Measured impact', 'Persistence insufficient',
                         'https://example.test/changes/anm-test'):
            self.assertIn(expected, message)

    def test_legacy_missing_fields(self):
        message = alerting.format_alert_message({'change': {'summary': 'Legacy summary'}})
        self.assertIn('Legacy summary', message)
        self.assertIn('Started: —', message)

    def test_unicode_limit_preserves_link(self):
        payload = self.payload()
        payload['change']['evidence'] *= 100
        payload['change']['summary'] = '🚨' * 5000
        message = alerting.format_alert_message(payload)
        self.assertLessEqual(len(message.encode('utf-16-le')) // 2, 4000)
        self.assertTrue(message.endswith(payload['links']['change']))
        self.assertIn('…', message)

    def test_enqueue_and_delivery_use_rich_payload(self):
        db = Mock()
        db.execute.return_value.fetchone.return_value = None
        @contextmanager
        def transaction(*args):
            yield db
        episode = {**self.payload()['change'], 'subject': {'type': 'user', 'name': 'svc-user'},
                   'context': {'target': 'checkout', 'caller': 'gateway', 'operation': '/buy', 'source_ip': '192.0.2.1'}}
        rule = {'id': 'r1', 'name': 'Latency rule', 'severity': 'warning',
                'condition': {}, 'destinations': [{'type': 'telegram', 'chat_id': 'test-chat'}]}
        with patch.object(alerting, 'db_transaction', transaction), patch.object(alerting, 'load_rules', return_value=[rule]):
            self.assertEqual(alerting.enqueue_matching([episode], base_url='https://example.test'), 1)
        insert = next(c for c in db.execute.call_args_list if 'INSERT INTO alert_events' in c.args[0])
        payload = json.loads(insert.args[1][4])
        self.assertEqual(payload['scope']['service'], 'checkout')
        self.assertEqual(payload['scope']['principal'], 'svc-user')
        self.assertEqual(payload['change']['evidence'], episode['evidence'])
        row = {'delivery_id': 'd1', 'event_id': 'e1', 'rule_id': 'r1', 'destination_type': 'telegram',
               'destination_target': 'test-chat', 'attempts': 0}
        db.execute.return_value.fetchall.return_value = [row]
        db.execute.return_value.fetchone.return_value = {'payload_json': json.dumps(payload)}
        with patch.object(alerting, 'db_transaction', transaction), patch.object(alerting.httpx, 'post', return_value=Mock(status_code=200)) as post:
            self.assertEqual(alerting.deliver_pending(), 1)
        sent = json.loads(post.call_args.kwargs['content'])
        self.assertEqual(sent['chat_id'], 'test-chat')
        self.assertIn('Evidence [latency]', sent['text'])
        self.assertNotIn('parse_mode', sent)


if __name__ == '__main__':
    unittest.main()
