"""The local frontend serves only packaged public assets, never the repo root."""
import unittest
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
        for asset in ['app.js', 'style.css', 'studio.css', 'viewer.js', 'showcase.js']:
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
