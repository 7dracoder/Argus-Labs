"""Covers on open-deck robots and the assembly guide (steps, wiring, prints). No CAD runtime needed."""
import re
import unittest

from fastapi.testclient import TestClient

from roboforge.api import SHOWCASE, _showcase_project
from roboforge.assembly import build_assembly
from roboforge.catalog import make_component
from roboforge.design import configure
from roboforge.models import Requirements, RobotProject
from roboforge.guide import AMPACITY, assembly_guide, pack_voltage
from roboforge.main import app


class Covers(unittest.TestCase):
    def test_open_deck_robots_get_a_cover_per_exposed_module(self):
        expected = {"mobile_manipulator": {"battery", "compute"}, "stationary_arm": {"compute"},
                    "tracked_explorer": {"compute"}, "mobile_robot": {"battery", "compute"},
                    "delivery_rover": set(), "warehouse_amr": set(), "cleaning_robot": set(),
                    "telepresence": set(), "security_patrol": set()}
        for key, modules in expected.items():
            with self.subTest(key=key):
                if key == 'mobile_robot':
                    result = configure(Requirements(robot_type=key, description='A small indoor mobile robot.'))
                    project = RobotProject(name=key, components=result.components,
                                           architecture={'archetype': key})
                else:
                    project = _showcase_project(key)
                covers = [n for n in build_assembly(project).nodes if n.role == "cover"]
                self.assertEqual(sum(c.quantity for c in project.components if c.kind == "cover"), len(modules))
                self.assertEqual({n.label.split()[0].lower().replace("computer", "compute") for n in covers}, modules)

    def test_cover_fits_over_its_module_and_sits_on_the_deck(self):
        nodes = build_assembly(_showcase_project("mobile_manipulator")).nodes
        for role in ("battery", "compute"):
            module = next(n for n in nodes if n.role == role)
            cover = next(n for n in nodes if n.role == "cover" and n.position[2] == module.position[2])
            inner_l = cover.spec["length_mm"] - 2 * cover.spec["thickness_mm"]
            inner_w = cover.spec["width_mm"] - 2 * cover.spec["thickness_mm"]
            self.assertGreater(inner_l, module.size[0] * 1000)
            self.assertGreater(inner_w, module.size[2] * 1000)
            self.assertGreater(cover.spec["height_mm"] - cover.spec["thickness_mm"], module.size[1] * 1000)
            deck = module.position[1] - module.size[1] / 2
            self.assertAlmostEqual(cover.position[1] - cover.size[1] / 2, deck, places=3)


class Guide(unittest.TestCase):
    def test_every_body_plan_explains_protection_and_nonprintable_purchases(self):
        for key, *_ in SHOWCASE:
            with self.subTest(key=key):
                project = _showcase_project(key)
                guide = assembly_guide(project)
                self.assertTrue(guide['protection'])
                self.assertTrue(any('pin' in n for n in guide['notes']))
                self.assertEqual(guide['revision'], project.revision)
                self.assertEqual(guide['project_id'], project.id)
                self.assertTrue(any(p['kind'] == 'compute' for p in guide['buy']))
                self.assertTrue(any(s['key'] == 'covers' for s in guide['steps']))
                self.assertTrue(all('not pre-split' in p['note'] for p in guide['prints']
                                    if p['printable'] and not p['fits_bed']))

    def test_guide_remains_on_requested_revision(self):
        client = TestClient(app)
        project = client.post('/projects/demo').json()
        path = f"/projects/{project['id']}"
        original = client.get(path + '/assembly-guide?revision=1').json()
        client.post(path + '/components', json={'catalog_id': 'raspberry-pi-5'})
        self.assertEqual(client.get(path + '/assembly-guide?revision=1').json(), original)
        self.assertGreater(client.get(path + '/assembly-guide').json()['revision'], original['revision'])
        self.assertEqual(client.get(path + '/prints/0/stl?revision=999').status_code, 404)

    def test_every_printable_export_matches_a_visible_node_spec(self):
        for key, *_ in SHOWCASE:
            with self.subTest(key=key):
                project = _showcase_project(key)
                assembly = build_assembly(project)
                specs = [n.spec for n in assembly.nodes if n.spec]
                guide = assembly_guide(project)
                for part in guide['prints']:
                    if part['printable']:
                        self.assertIn(part['spec'], specs)
                self.assertTrue(any(p['kind'] == 'frame' for p in guide['buy']))

    def test_pack_voltage_from_battery_name(self):
        self.assertEqual(pack_voltage(make_component("lifepo4-12v-20ah")), (12.8, 14.6))
        self.assertEqual(pack_voltage(make_component("liion-4s-12ah")), (14.8, 16.8))
        self.assertEqual(pack_voltage(make_component("lifepo4-24v-50ah")), (25.6, 29.2))

    def test_every_wire_is_rated_for_its_fuse_and_main_fuse_covers_branches(self):
        ampacity = dict(AMPACITY)
        for key, *_ in SHOWCASE:
            with self.subTest(key=key):
                rows = assembly_guide(_showcase_project(key))["wiring"]["rows"]
                for row in rows:
                    gauge = re.match(r"(\d+) AWG", row["wire"])
                    if row["fuse_a"] and gauge:
                        self.assertGreaterEqual(ampacity[int(gauge.group(1))], row["fuse_a"], row)
                main = rows[0]["fuse_a"]
                self.assertTrue(all(r["fuse_a"] is None or r["fuse_a"] <= main for r in rows))

    def test_servos_never_get_more_than_their_rated_voltage(self):
        project = _showcase_project("mobile_manipulator")
        project.components = [c for c in project.components if c.kind != "arm_servo"] + [
            make_component("feetech-sts3215", 3)]
        guide = assembly_guide(project)["wiring"]
        bus = next(r for r in guide["rows"] if "Feetech STS3215" in r["to"] and "power board" in r["to"])
        self.assertEqual(bus["voltage"], "7.4 V DC")
        self.assertTrue(any("buck" in e and "7.4 V" in e for e in guide["extras"]))

    def test_encoder_supply_and_servo_power_hub_are_not_assumed_safe(self):
        project = _showcase_project('mobile_manipulator')
        project.components = [c for c in project.components if c.kind != 'arm_servo'] + [
            make_component('dynamixel-xm540', 8)]
        guide = assembly_guide(project)['wiring']
        encoder = next(r for r in guide['rows'] if 'Motor encoders' in r['from'])
        self.assertIn('Do not assume', encoder['note'])
        self.assertTrue(any('Separately rated servo power distribution' in r['to'] for r in guide['rows']))
        self.assertTrue(any('10 A total' in n for n in guide['notes']))

    def test_guide_steps_show_every_part_once_and_list_covers_to_print(self):
        client = TestClient(app)
        project = client.post("/projects/demo").json()
        guide = client.get(f"/projects/{project['id']}/assembly-guide").json()
        keys = [s["key"] for s in guide["steps"]]
        self.assertEqual(keys[0], "print")
        self.assertLess(keys.index("wiring"), keys.index("covers"))
        self.assertEqual(keys[-1], "test")
        nodes = [n for s in guide["steps"] if s["key"] != "print" for n in s["nodes"]]
        layout = client.get(f"/projects/{project['id']}/assembly").json()["nodes"]
        self.assertEqual(sorted(nodes), list(range(len(layout))))
        covers = [p for p in guide["prints"] if p["kind"] == "cover"]
        self.assertEqual(len(covers), 2)
        self.assertTrue(all(p["printable"] and p["fits_bed"] and p["grams_each"] > 0 for p in covers))
        gripper = next(p for p in guide["prints"] if p["kind"] == "gripper")
        self.assertFalse(gripper["printable"])


if __name__ == "__main__":
    unittest.main()
