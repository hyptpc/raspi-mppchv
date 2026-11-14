import json
from pathlib import Path
import unittest

try:
    import quickjs
except ImportError:
    quickjs = None


@unittest.skipIf(quickjs is None, 'Install requirements.txt to run JavaScript rendering tests')
class StatusUiTests(unittest.TestCase):
    def setUp(self):
        self.context = quickjs.Context()
        self.context.eval('''
            var window = {};
            var rendered = '';
            var heading = {textContent: '', className: 'port-on'};
            var content = {set outerHTML(value) {rendered = value;}};
            var panel = {querySelector(selector) {
                return selector === 'h2' ? heading : content;
            }};
            var document = {getElementById() {return panel;}};
        ''')
        self.context.eval(Path('static/script.js').read_text())
        self.context.eval('portLabels = {1: "HV1"};')

    def render(self, data):
        return json.loads(self.context.eval(
            f'updateStatusPanels({json.dumps(data)}); JSON.stringify({{html:rendered, heading:heading.className}});'))

    def test_error_sample_shows_unknown_instead_of_off_or_ok(self):
        result = self.render([{'port_id': 1, 'timestamp': '2026-11-13T12:00:00',
                              'is_hv_on': None, 'is_overcurrent': None, 'is_current_limit': None,
                              'is_temp_sensor_connected': None, 'is_temp_in_range': None,
                              'is_temp_correction_enabled': None}])
        self.assertEqual(result['html'].count('>UNKNOWN<'), 6)
        self.assertNotIn('>OFF<', result['html'])
        self.assertNotIn('>OK<', result['html'])
        self.assertEqual(result['heading'], 'port-unknown')

    def test_known_false_values_keep_their_actual_meaning(self):
        result = self.render([{'port_id': 1, 'timestamp': '2026-11-13T12:00:00',
                              'is_hv_on': False, 'is_overcurrent': False, 'is_current_limit': False,
                              'is_temp_sensor_connected': False, 'is_temp_in_range': False,
                              'is_temp_correction_enabled': False}])
        self.assertNotIn('UNKNOWN', result['html'])
        self.assertIn('>OFF<', result['html'])
        self.assertIn('>OK<', result['html'])
        self.assertEqual(result['heading'], 'port-off')

    def test_missing_or_non_boolean_values_are_unknown(self):
        result = self.render([{'port_id': 1, 'timestamp': '2026-11-13T12:00:00', 'is_hv_on': 0}])
        self.assertEqual(result['html'].count('>UNKNOWN<'), 6)
        self.assertEqual(result['heading'], 'port-unknown')

    def test_no_recent_data_clears_old_on_colour(self):
        result = self.render([])
        self.assertEqual(result['heading'], 'port-unknown')
        self.assertIn('No recent data', result['html'])


if __name__ == '__main__':
    unittest.main()
