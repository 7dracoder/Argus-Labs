"""Edits change the saved robot, BOM, CAD inputs and later rebuilds, not just replies."""
import json
import tempfile
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from roboforge.edits import EditPlan, parse_plan, EditRequest
from roboforge.llm import LLMUnavailable
from roboforge.main import app
from roboforge.models import RobotProject, Requirements
from roboforge.research import Research
from roboforge.store import store


@pytest.fixture
def robot():
    with patch('roboforge.api.design_concept', side_effect=LLMUnavailable('offline')), patch('roboforge.api.find_references', return_value=Research()):
        client = TestClient(app)
        p = client.post('/projects', json={'name': 'Editable robot', 'requirements': {
            'description': 'A household robot that picks up objects and carries 1 kg', 'budget_usd': 2500}}).json()
        path = f"/projects/{p['id']}"
        client.post(path + '/design/auto', json={}).raise_for_status()
        yield client, path


def edit(robot, message, **extra):
    client, path = robot
    return client.post(path + '/design/edit', json={'message': message, **extra})


def test_dimensions_change_nodes_summary_and_revision_not_old_revision(robot):
    client, path = robot
    old = client.get(path + '/assembly').json()
    before = client.get(path).json()['revision']
    response = edit(robot, 'Make the robot body 600 by 400 mm and mast height 70 cm')
    assert response.status_code == 200, response.text
    p = response.json()['project']
    assert p['revision'] == before + 1
    a = client.get(path + '/assembly').json()
    assert a['summary']['body_size_mm'] == [600, 400]
    assert a['summary']['body_area_m2'] == .24
    assert next(n for n in a['nodes'] if n['role'] == 'frame')['size'][::2] == [.6, .4]
    assert next(n for n in a['nodes'] if n['role'] == 'mast')['size'][1] == .7
    assert client.get(path + f'/assembly?revision={before}').json() == old
    rebuilt = client.post(path + '/design/auto', json={'requirements': {**p['requirements'], 'budget_usd': 5000}})
    assert rebuilt.status_code == 200
    assert client.get(path + '/assembly').json()['summary']['body_size_mm'] == [600, 400]


def test_named_part_and_remove_survive_budget_rebuild(robot):
    client, path = robot
    p = client.get(path).json()
    camera = next(c for c in p['components'] if c['kind'] == 'camera')
    response = edit(robot, 'Replace the battery with the 40Ah model and remove the camera')
    assert response.status_code == 200, response.text
    p = response.json()['project']
    assert next(c for c in p['components'] if c['kind'] == 'battery')['catalog_id'] == 'lifepo4-12v-40ah'
    assert not any(c['kind'] == 'camera' for c in p['components'])
    p = client.post(path + '/design/auto', json={'requirements': {**p['requirements'], 'budget_usd': 6000}}).json()['project']
    assert next(c for c in p['components'] if c['kind'] == 'battery')['catalog_id'] == 'lifepo4-12v-40ah'
    assert not any(c['id'] == camera['id'] or c['kind'] == 'camera' for c in p['components'])
    assert not any(n['role'] == 'camera' for n in client.get(path + '/assembly').json()['nodes'])


def test_direct_remove_and_swap_are_not_undone(robot):
    client, path = robot
    p = client.get(path).json()
    c = next(c for c in p['components'] if c['kind'] == 'camera')
    client.delete(path + '/components/' + c['id']).raise_for_status()
    client.post(path + '/design/auto', json={}).raise_for_status()
    assert not any(c['kind'] == 'camera' for c in client.get(path).json()['components'])


def test_relative_size_units_and_work_area_are_distinct(robot):
    client, path = robot
    before = client.get(path + '/assembly').json()['summary']['body_size_mm']
    response = edit(robot, 'Make the robot 25% wider and working area 120 m2')
    assert response.status_code == 200, response.text
    after = response.json()['dimensions']
    assert after['body_size_mm'] == [before[0], before[1] * 1.25]
    assert after['operating_area_m2'] == 120
    response = edit(robot, 'Set body length to 24 inches')
    assert response.status_code == 200, response.text
    assert response.json()['dimensions']['body_size_mm'][0] == 609.6
    response = edit(robot, 'Set footprint area to 0.3 m2')
    assert response.status_code == 200, response.text
    assert response.json()['dimensions']['body_area_m2'] == pytest.approx(.3, abs=.0001)


def test_exact_wheel_size_visible_and_preserved(robot):
    client, path = robot
    response = edit(robot, 'Set wheels to 150 mm')
    assert response.status_code == 200, response.text
    p = response.json()['project']
    assert next(c for c in p['components'] if c['kind'] == 'wheel')['specs']['diameter_mm'] == 150
    assert all(n['size'][0] == .075 for n in client.get(path + '/assembly').json()['nodes'] if n['role'] == 'wheel')


@pytest.mark.parametrize('message', ['Set the body width to 5 mm', 'Set wheels to 200 mm', 'Make the robot 100% smaller', "Don't remove the battery", 'What if I remove the camera?'])
def test_invalid_edits_are_atomic_and_honest(robot, message):
    client, path = robot
    before = client.get(path).json()
    response = edit(robot, message)
    assert response.status_code == 422, response.text
    assert client.get(path).json() == before


def test_model_plan_is_validated_and_part_ids_cannot_be_invented(robot):
    client, path = robot
    before = client.get(path).json()
    with patch('roboforge.edits.generate_structured', return_value=EditPlan(parts=[{'part_name': 'battery', 'catalog_id': 'made-up'}])):
        response = edit(robot, 'Something expressed differently')
    assert response.status_code == 422
    assert client.get(path).json() == before


def test_stale_edit_conflicts_without_overwrite(robot):
    client, path = robot
    before = client.get(path).json()
    response = edit(robot, 'Make body width 400 mm', expected_revision=before['revision'] - 1)
    assert response.status_code == 409
    assert client.get(path).json() == before
    def concurrent(project, request):
        p = store.get(before['id'])
        p.requirements.budget_usd = 9000
        store.save_revision(p)
        return EditPlan(requirements={'body_width_mm': 500})
    with patch('roboforge.api.parse_plan', side_effect=concurrent):
        response = edit(robot, 'Set body width 500 mm')
    assert response.status_code == 409
    assert client.get(path).json()['requirements']['budget_usd'] == 9000
    assert client.get(path).json()['requirements']['body_width_mm'] is None


def test_offline_common_edits_do_not_need_a_model(robot):
    with patch('roboforge.edits.generate_structured', side_effect=LLMUnavailable('offline')) as model:
        assert edit(robot, 'Make body width 400 mm').status_code == 200
        assert edit(robot, 'Use the 40Ah battery').status_code == 200
    model.assert_not_called()


def test_named_hardware_dimensions_never_resize_the_whole_robot(robot):
    client, path = robot
    before = client.get(path).json()
    response = edit(robot, 'Set battery width to 500 mm')
    assert response.status_code == 422
    assert client.get(path).json() == before


def test_custom_cad_resize_has_new_real_exports_without_duplicate_bom(robot):
    client, path = robot
    with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'ROBOFORGE_CAD_ROOT': directory}):
        first = client.post(path + '/agents/mechanical', json={'spec': {'kind': 'arm_link'}, 'estimated_unit_cost_usd': 8})
        assert first.status_code == 200, first.text
        first = first.json()
        response = edit(robot, 'Change the arm link length to 160 mm')
        assert response.status_code == 200, response.text
        p = response.json()['project']
        assert len(p['manufacturing']['cad_parts']) == 1
        latest = list(p['manufacturing']['cad_parts'].values())[0]
        assert latest['design_id'] != first['design_id']
        assert latest['component_id'] == first['component_id']
        assert latest['geometry']['bounds_mm'] == [160, 40, 6]
        assert len([c for c in p['components'] if c['id'] == first['component_id']]) == 1
        assert client.get(path + f"/cad/{latest['design_id']}/step?revision={p['revision']}").status_code == 200
        assert client.get(first['downloads']['step']).status_code == 200
        assert client.get(path + '/robot/report').status_code == 200
        response = edit(robot, 'Change this part width to 50 mm', component_id=first['component_id'])
        assert response.status_code == 200, response.text
        latest = list(response.json()['project']['manufacturing']['cad_parts'].values())[0]
        assert latest['geometry']['bounds_mm'] == [160, 50, 6]


def test_ui_exposes_real_edit_endpoint_and_no_extra_rebuild_click():
    client = TestClient(app)
    source = client.get('/ui/assets/app.js').text
    page = client.get('/').text
    assert 'design/edit' in source and 'applyDesignEdit(answer)' in source
    for field in ['design-edit-message', 'req-length', 'req-width', 'req-link', 'req-mast', 'req-wheel', 'req-area']:
        assert f'id="{field}"' in page
