import unittest
import os
import sys
from app import app, get_char_outline, scale_to_distance, get_bicycling_route
from shapely.geometry import LineString

class TestRouteGeneration(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_char_outline_generation(self):
        # Test with Chinese character
        outline = get_char_outline('山')
        self.assertIsInstance(outline, LineString)
        self.assertTrue(len(outline.coords) > 0)

    def test_distance_scaling(self):
        # Create a simple line for testing
        line = LineString([(0, 0), (1, 1)])
        target_distance = 5  # 5km
        scaled_coords = scale_to_distance(line, target_distance)
        self.assertTrue(len(scaled_coords) > 0)

    def test_route_generation_api(self):
        test_data = {
            'text': '山',
            'distance': 5,
            'start_point': [116.397428, 39.90923]
        }
        response = self.app.post('/generate_route',
                                json=test_data,
                                content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn('path', data)
        self.assertTrue(len(data['path']) > 0)

    def test_invalid_input(self):
        # Test empty text
        response = self.app.post('/generate_route',
                                json={'text': '', 'distance': 5, 'start_point': [116.397428, 39.90923]},
                                content_type='application/json')
        self.assertEqual(response.status_code, 400)

        # Test invalid distance
        response = self.app.post('/generate_route',
                                json={'text': '山', 'distance': -1, 'start_point': [116.397428, 39.90923]},
                                content_type='application/json')
        self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    unittest.main()