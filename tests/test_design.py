"""Briefs become sensible, distinct robots; selected parts can be inspected and edited."""
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from roboforge.assembly import build_assembly
from roboforge.concept import Concept, buildable, design_concept
from roboforge.design import BriefError, configure
from roboforge.llm import LLMUnavailable
from roboforge.main import app
from roboforge.models import Requirements
from roboforge.research import Reference, ReferenceImage, Research

_offline = mock.patch('roboforge.api.design_concept', side_effect=LLMUnavailable('offline in tests'))
_no_search = mock.patch('roboforge.api.find_references', return_value=Research())


def setUpModule():
    _offline.start()  # keyword body plans unless a test supplies a concept
    _no_search.start()


def tearDownModule():
    _offline.stop()
    _no_search.stop()


def design(text, budget=2000):
    return configure(Requirements(description=text, budget_usd=budget))


class BriefTests(unittest.TestCase):
    def test_nonsense_and_unsupported_briefs_are_refused(self):
        for text in ('asdf', 'A drone that flies around the house', 'A pool cleaning robot',
                     'A window cleaning robot'):
            with self.subTest(text=text), self.assertRaises(BriefError):
                design(text)
        client = TestClient(app)
        response = client.post('/projects', json={'name': 'x', 'requirements': {'description': 'qwer zxcv'}})
        self.assertEqual(response.status_code, 422)
        self.assertIn('robot job', response.json()['detail'])

    def test_jobs_get_their_own_body_plan(self):
        cases = {
            'A security patrol robot for my office at night': 'security_patrol',
            'A robot that reads stories to my kids': 'telepresence',
            'A robot that cooks dinner': 'stationary_arm',
            'A robot that brings me a beer from the fridge': 'mobile_manipulator',
            'A lawn mower robot': 'tracked_explorer',
            'A vacuum robot for my household': 'cleaning_robot',
            'A robot that follows me in the airport carrying my suitcase 20 kg': 'delivery_rover',
            'Move shelves of boxes in a fulfilment center autonomously': 'warehouse_amr',
            'Inspect pipes in a factory and read gauges': 'security_patrol',
            'Carry tools for construction workers on a job site': 'delivery_rover',
            'Restock grocery store shelves at night': 'mobile_manipulator',
        }
        for text, archetype in cases.items():
            with self.subTest(text=text):
                self.assertEqual(design(text).archetype, archetype)

    def test_whole_words_only(self):
        # "household" is not "hold", "towels" is not "tow", "farmhouse" is not "arm".
        self.assertEqual(design('A vacuum robot for my household').archetype, 'cleaning_robot')
        self.assertNotEqual(design('A robot that carries towels around the house').archetype, 'warehouse_amr')

    def test_tracked_robot_has_motors_strong_enough_and_missing_tools_are_flagged(self):
        result = design('Outdoor garden inspection on rough terrain', 1500)
        self.assertFalse([w for w in result.warnings if 'under-sized' in w])
        self.assertNotIn('hub-motor-250w', [c.catalog_id for c in result.components])
        mower = design('A lawn mower robot')
        self.assertTrue(any('cutting deck' in w for w in mower.warnings))
        self.assertTrue(any('water tank' in w for w in design('Water my garden plants').warnings))

    def test_indoor_robots_get_solid_wheels_and_sidewalk_robots_pneumatic(self):
        def wheel(text):
            return next(c.catalog_id for c in design(text, 3000).components if c.kind == 'wheel')
        self.assertNotIn('pneumatic', wheel('Deliver medicine between hospital rooms'))
        self.assertIn('pneumatic', wheel('Deliver packages on the sidewalk to houses in my neighbourhood'))


class PartEditTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        project = self.client.post('/projects', json={'name': 'Explorer', 'requirements': {
            'description': 'Outdoor garden inspection on rough terrain', 'budget_usd': 1500}}).json()
        self.base = f"/projects/{project['id']}"
        built = self.client.post(self.base + '/design/auto', json={}).json()['project']
        self.parts = {c['kind']: c for c in built['components']}

    def edit(self, kind, **body):
        return self.client.post(f"{self.base}/components/{self.parts[kind]['id']}/edit", json=body).json()

    def test_info_reports_what_the_part_holds_and_its_load(self):
        info = self.client.get(f"{self.base}/components/{self.parts['drive_motor']['id']}/info").json()
        self.assertEqual(info['holds_verb'], 'Drives')
        self.assertEqual([h['name'] for h in info['holds']], [self.parts['track']['name']])
        self.assertEqual(info['mounted_on']['name'], self.parts['frame']['name'])
        self.assertEqual(info['load']['status'], 'ok')
        self.assertTrue(any(a['meets'] is False for a in info['alternatives']))
        frame = self.client.get(f"{self.base}/components/{self.parts['frame']['id']}/info").json()
        self.assertGreater(len(frame['holds']), 5)
        self.assertFalse(frame['removable'])

    def test_info_explains_what_the_part_does_and_why_it_was_picked(self):
        def explain(kind):
            return self.client.get(f"{self.base}/components/{self.parts[kind]['id']}/info").json()['explain']
        battery = explain('battery')
        self.assertIn('how long the robot runs', battery['does'])
        self.assertIn('Wh', battery['why'])  # the sizing reason from the design
        self.edit('battery', instruction='use the 40Ah one')
        self.assertEqual(explain('battery')['why'], 'You chose this part.')

    def test_cheaper_keeps_sizing_unless_forced(self):
        refused = self.edit('drive_motor', instruction='make it cheaper')
        self.assertFalse(refused['changed'])
        self.assertIn('too weak', refused['reply'])
        forced = self.edit('drive_motor', instruction='make it cheaper anyway')
        self.assertTrue(forced['changed'])
        self.assertTrue(forced['warnings'])
        self.assertTrue(forced['project']['architecture']['edited'])

    def test_named_swap_keeps_the_selection_and_frame_cannot_be_removed(self):
        swapped = self.edit('battery', instruction='use the 40Ah one')
        self.assertTrue(swapped['changed'])
        self.assertEqual(swapped['component_id'], self.parts['battery']['id'])
        battery = next(c for c in swapped['project']['components'] if c['id'] == self.parts['battery']['id'])
        self.assertEqual(battery['catalog_id'], 'lifepo4-12v-40ah')
        self.assertFalse(self.edit('frame', remove=True)['changed'])
        removed = self.edit('lights', instruction='remove it')
        self.assertTrue(removed['changed'])
        self.assertNotIn(self.parts['lights']['id'], [c['id'] for c in removed['project']['components']])

    def test_unclear_request_without_a_model_gives_guidance(self):
        with mock.patch('roboforge.parts._ask_model', side_effect=RuntimeError('offline')):
            outcome = self.edit('compute', instruction='paint it purple')
        self.assertFalse(outcome['changed'])
        self.assertIn('cheaper', outcome['reply'])


PHOTOGRAPHER = Concept(
    name='Follow-me camera robot', summary='Follows you and takes a photo when you say click.',
    reference='Temi, Segway Loomo', chassis='mobile_robot', arm=False,
    modules=['pan_tilt', 'lights', 'lift', 'vacuum'], voice=True, lidar=True, mast_m=1.0, camera_mount='mast',
    payload_kg=0, runtime_h=4)


class ConceptTests(unittest.TestCase):
    def test_concept_is_made_buildable(self):
        concept = buildable(PHOTOGRAPHER)
        self.assertEqual(concept.modules, ['pan_tilt', 'lights'])  # no lift or vacuum on a 2-wheel base
        arm_job = buildable(PHOTOGRAPHER.model_copy(update={'arm': True, 'chassis': 'telepresence'}))
        self.assertEqual(arm_job.chassis, 'mobile_manipulator')

    def test_ai_concept_becomes_its_own_robot(self):
        client = TestClient(app)
        project = client.post('/projects', json={'name': 'cam', 'requirements': {
            'description': 'a robot that follows me everywhere and takes a picture when I say click',
            'budget_usd': 2500}}).json()
        with mock.patch('roboforge.api.design_concept', return_value=buildable(PHOTOGRAPHER)) as ask:
            built = client.post(f"/projects/{project['id']}/design/auto", json={}).json()['project']
            # Budget slider after the requirements agent restated the brief as tasks: same robot, no new call.
            slider = {**built['requirements'], 'tasks': ['Follow the user', 'Take photos'], 'budget_usd': 6000}
            client.post(f"/projects/{project['id']}/design/auto", json={'requirements': slider})
        self.assertEqual(ask.call_count, 1)
        kinds = {c['kind'] for c in built['components']}
        self.assertTrue({'pan_tilt', 'lights', 'microphone', 'lidar'} <= kinds)
        self.assertFalse({'cargo_bin', 'arm_servo', 'lift'} & kinds)
        self.assertEqual(built['architecture']['type'], 'Follow-me camera robot')
        from roboforge.store import store
        layout = build_assembly(store.get(project['id']))
        mast = next(n for n in layout.nodes if n.role == 'mast')
        self.assertGreater(mast.size[1], 0.9)
        self.assertIn('pan_tilt', {n.role for n in layout.nodes})
        self.assertFalse([n for n in layout.nodes if n.role == 'other'])

    def test_forced_robot_type_keeps_the_ai_concept(self):
        client = TestClient(app)
        project = client.post('/projects', json={'name': 'cam', 'requirements': {
            'description': 'a robot that follows me everywhere and takes a picture when I say click',
            'budget_usd': 2500}}).json()
        path = f"/projects/{project['id']}/design/auto"
        with mock.patch('roboforge.api.design_concept', return_value=buildable(PHOTOGRAPHER)) as ask:
            req = client.post(path, json={}).json()['project']['requirements']
            forced = client.post(path, json={'requirements': {**req, 'robot_type': 'tracked_explorer'}}).json()
            back = client.post(path, json={'requirements': {**req, 'robot_type': None}}).json()
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(forced['project']['architecture']['archetype'], 'tracked_explorer')
        self.assertEqual(back['project']['architecture']['type'], 'Follow-me camera robot')

    def test_architect_does_not_undo_changes_made_while_it_thinks(self):
        from roboforge.agents import AGENTS
        from roboforge.store import store
        client = TestClient(app)
        project = client.post('/projects', json={'name': 'cam', 'requirements': {
            'description': 'a robot that follows me everywhere', 'budget_usd': 2500}}).json()

        def slow_turn(snapshot, message):
            latest = store.get(project['id'])  # the user moves the budget slider mid-call
            latest.requirements = latest.requirements.model_copy(update={'budget_usd': 6000, 'robot_type': 'telepresence'})
            store.save_revision(latest)
            turn = mock.Mock(reply='ok', next_question=None, ready_for_design=True)
            return {'turn': turn, 'requirements': snapshot.requirements.model_copy(update={'tasks': ['Follow me']}),
                    'feasibility_concerns': [], 'robot_category': 'follow-me robot'}

        with mock.patch.object(AGENTS['architect'], 'run', side_effect=slow_turn):
            client.post(f"/projects/{project['id']}/architect/chat", json={'message': 'hi'})
        req = store.get(project['id']).requirements
        self.assertEqual((req.budget_usd, req.robot_type, req.tasks), (6000, 'telepresence', ['Follow me']))

    def test_web_research_reaches_the_concept_prompt(self):
        research = Research(references=[Reference(title='LeKiwi', url='https://example.com', snippet='3-wheel base')],
                            images=[ReferenceImage(url='https://example.com/a.jpg', description='a wheeled arm robot')])
        req = Requirements(description='a robot that picks up toys')
        for photo, expected in ((0, 0), (7, None)):
            with mock.patch('roboforge.llm.generate_structured',
                            return_value=PHOTOGRAPHER.model_copy(update={'photo': photo})) as ask:
                concept = design_concept(req, research)
            self.assertIn('LeKiwi: 3-wheel base', ask.call_args.args[1])
            self.assertIn('Photo 0: a wheeled arm robot', ask.call_args.args[1])
            self.assertEqual(concept.photo, expected)  # a photo number the search didn't return is dropped

    def test_research_is_stored_with_the_concept(self):
        client = TestClient(app)
        project = client.post('/projects', json={'name': 'cam', 'requirements': {
            'description': 'a robot that follows me and takes photos', 'budget_usd': 2500}}).json()
        research = Research(images=[ReferenceImage(url='https://example.com/a.jpg')])
        with mock.patch('roboforge.api.design_concept', return_value=buildable(PHOTOGRAPHER)), \
                mock.patch('roboforge.api.find_references', return_value=research):
            built = client.post(f"/projects/{project['id']}/design/auto", json={}).json()['project']
        self.assertEqual(built['architecture']['research']['images'][0]['url'], 'https://example.com/a.jpg')

    def test_model_can_refuse_an_impossible_job(self):
        client = TestClient(app)
        project = client.post('/projects', json={'name': 'x', 'requirements': {
            'description': 'a robot that cleans the outside of skyscrapers', 'budget_usd': 2500}}).json()
        refusal = PHOTOGRAPHER.model_copy(update={'unsupported': 'Needs to hang off a building.'})
        with mock.patch('roboforge.llm.generate_structured', return_value=refusal), \
                mock.patch('roboforge.api.design_concept', new=design_concept):
            response = client.post(f"/projects/{project['id']}/design/auto", json={})
        self.assertEqual(response.status_code, 422)
        self.assertIn('building', response.json()['detail'])


if __name__ == '__main__':
    unittest.main()
