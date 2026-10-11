import os
import unittest
from unittest import mock

from roboforge import shopping
from roboforge.models import Component, Requirements, RobotProject


def result(url, title, content=''):
    return {'url': url, 'title': title, 'content': content}


class ShoppingTests(unittest.TestCase):
    def setUp(self):
        shopping._offers.clear()
        self.env = mock.patch.dict(os.environ, {'TAVILY_API_KEY': 'test'})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        shopping._offers.clear()

    def test_only_product_pages_for_the_same_model_are_kept(self):
        shopping._offers['Slamtec RPLIDAR S2'] = [
            result('https://www.amazon.com/Slamtec-A2M12-Lidar/dp/B0B44PQZN7', 'Slamtec RPLIDAR A2M12 Lidar', '$599.99'),
            result('https://files.seeedstudio.com/rplidar_S2.pdf', 'RPLIDAR S2 datasheet'),
            result('https://www.aliexpress.com/w/wholesale-rplidar-s2.html', 'Rplidar s2'),
            result('https://www.robotshop.com/es/products/rplidar-s2', 'RPlidar S2 escáner láser'),
            result('https://www.robotshop.com/products/rplidar-s2-360-laser-scanner', 'RPlidar S2 360° Laser Scanner',
                   'Now $371.86, was $413.18. Ships with a $5 cable.'),
        ]
        offers = shopping.find_offers('Slamtec RPLIDAR S2', 399)
        self.assertEqual([o.store for o in offers], ['RobotShop'])
        self.assertEqual(offers[0].price_usd, 371.86)  # the $5 cable is not this part's price

    def test_most_parts_stay_at_one_store_unless_another_is_clearly_cheaper(self):
        parts = [Component(name=n, category='electronics', kind='camera', unit_cost_usd=100) for n in ('Cam A1', 'Cam B2', 'Cam C3')]
        shopping._offers.update({
            'Cam A1': [result('https://www.robotshop.com/products/cam-a1', 'Cam A1', '$100.00')],
            'Cam B2': [result('https://www.robotshop.com/products/cam-b2', 'Cam B2', '$105.00'),
                       result('https://www.amazon.com/cam-b2/dp/X', 'Cam B2', '$100.00')],
            'Cam C3': [result('https://www.robotshop.com/products/cam-c3', 'Cam C3', '$150.00'),
                       result('https://www.amazon.com/cam-c3/dp/Y', 'Cam C3', '$90.00')],
        })
        out = shopping.where_to_buy(RobotProject(name='x', requirements=Requirements(description='x'), components=parts))
        self.assertEqual(out['main_store'], 'RobotShop')
        self.assertEqual([line['offer']['store'] for line in out['lines']], ['RobotShop', 'RobotShop', 'Amazon'])

    def test_no_match_gives_a_store_search_instead(self):
        part = Component(name='Wiring harness + connectors', category='electronics', kind='wiring', unit_cost_usd=90)
        shopping._offers['Wiring harness + connectors'] = [result('https://www.amazon.com/Car-Stereo/dp/Z', 'Car stereo adapter')]
        line = shopping.where_to_buy(RobotProject(name='x', requirements=Requirements(description='x'),
                                                  components=[part]))['lines'][0]
        self.assertIsNone(line['offer'])
        self.assertTrue(line['search_url'].startswith('https://www.amazon.com/s?k=Wiring'))


if __name__ == '__main__':
    unittest.main()
