"""The local frontend serves only packaged public assets, never the repo root."""
import unittest
from html.parser import HTMLParser
from fastapi.testclient import TestClient
from roboforge.main import app


class FrontendTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_page_and_assets_are_served_with_no_inline_scripts(self):
        page = self.client.get('/')
        self.assertEqual(page.status_code, 200)
        self.assertIn('Run guided E2E demo', page.text)
        self.assertIn("script-src 'self'", page.headers['content-security-policy'])
        self.assertIn('camera=()', page.headers['permissions-policy'])
        self.assertNotIn('<script>', page.text)
        for asset in ['app.js', 'style.css', 'studio.css', 'viewer.js', 'showcase.js', 'motion.js', 'sections.js']:
            response = self.client.get('/ui/assets/' + asset)
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.content)

    def test_robot_studio_preserves_build_flows_and_has_real_exploration_controls(self):
        page = self.client.get('/').text
        for control in ['showcase-stage', 'sc-spin', 'sc-reset', 'explode', 'explode-value',
                        'robot-viewport', 'assembly-viewport', 'inspect-internals', 'to-assemble', 'asm-prints']:
            self.assertIn(f'id="{control}"', page)
        self.assertIn('studio.css', page)
        self.assertIn('Visual inspection only', page)
        source = self.client.get('/ui/assets/app.js').text
        self.assertIn('setExploded', source)
        self.assertIn('requestFullscreen', source)
        self.assertIn('setAngle', source)

    def test_private_files_are_not_served_and_api_routes_still_work(self):
        for path in ['/.env', '/ui/assets/.env', '/ui/assets/%2e%2e/%2e%2e/.env', '/ui/assets/../../pyproject.toml']:
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok'})
        project = self.client.post('/projects', json={'name': 'Frontend contract test'})
        self.assertEqual(project.status_code, 201)
        self.assertEqual(self.client.get('/projects/' + project.json()['id']).status_code, 200)

    def test_workspace_sections_have_unique_ids_and_contain_the_correct_controls(self):
        class Structure(HTMLParser):
            def __init__(self):
                super().__init__()
                self.sections = []
                self.parents = {}
                self.tabs = {}
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'section':
                    self.sections.append(attrs.get('id'))
                if attrs.get('id'):
                    self.assert_unique(attrs['id'])
                    self.parents[attrs['id']] = list(self.sections)
                if attrs.get('role') == 'tab':
                    self.tabs[attrs['id']] = attrs['aria-controls']
            def assert_unique(self, key):
                if key in self.parents:
                    raise AssertionError(f'Duplicate ID: {key}')
            def handle_endtag(self, tag):
                if tag == 'section':
                    self.sections.pop()
        structure = Structure()
        structure.feed(self.client.get('/').text)
        self.assertEqual(structure.sections, [], 'All section wrappers must close')
        expected = {'stage': 'panel-review', 'bom-lines': 'panel-review', 'budget-slider': 'panel-review',
                    'requirements-form': 'panel-edit', 'cad-form': 'panel-edit', 'research-form': 'panel-finance',
                    'downloads': 'panel-files', 'asm-stage': 'panel-steps', 'asm-prints': 'panel-prints',
                    'wiring-rows': 'panel-wiring', 'asm-tools': 'panel-checklist'}
        for control, panel in expected.items():
            self.assertIn(panel, structure.parents[control], control)
        for tab, panel in structure.tabs.items():
            self.assertIn(panel, structure.parents)
        self.assertEqual(len(structure.tabs), 8)

    def test_browser_source_keeps_secrets_and_capture_out_of_auto_demo(self):
        source = self.client.get('/ui/assets/app.js').text
        self.assertNotIn('localStorage', source)
        self.assertNotIn('innerHTML', source)
        self.assertNotIn('GLM_API_KEY', source)
        self.assertNotIn('SMARTSPECTRA_API_KEY', source)
        demo = source.split('async function runDemo()')[1].split('async function integrations()')[0]
        self.assertNotIn('getUserMedia', demo)
        self.assertIn('/voice/transcribe?consent=true', demo)


if __name__ == '__main__':
    unittest.main()
