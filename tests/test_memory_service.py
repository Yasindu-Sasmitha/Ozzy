import os
import tempfile
import unittest
from pathlib import Path

import memory_service


class MemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ['OZZY_DATA_DIR'] = self.temp.name
        memory_service.initialize()

    def tearDown(self):
        self.temp.cleanup()
        os.environ.pop('OZZY_DATA_DIR', None)

    def test_save_and_list_memory(self):
        result = memory_service.save_memory('I am building a robotics project.', 'project')
        self.assertTrue(result['ok'])
        memories = memory_service.list_memories()
        self.assertEqual(len(memories), 1)
        self.assertEqual(memories[0]['content'], 'I am building a robotics project.')
        self.assertEqual(memories[0]['category'], 'project')

    def test_duplicate_memory_is_not_duplicated(self):
        first = memory_service.save_memory('I prefer short answers.', 'preference')
        second = memory_service.save_memory('I prefer short answers.', 'preference')
        self.assertTrue(first['ok'])
        self.assertTrue(second['ok'])
        self.assertTrue(second['duplicate'])
        self.assertEqual(len(memory_service.list_memories()), 1)

    def test_search_finds_matching_memory(self):
        memory_service.save_memory('My robot project is called Ozzy.', 'project')
        memory_service.save_memory('I prefer a calm speaking voice.', 'preference')
        results = memory_service.search_memories('robot Ozzy')
        self.assertEqual(len(results), 1)
        self.assertIn('Ozzy', results[0]['content'])

    def test_secret_is_refused(self):
        result = memory_service.save_memory('My API key is AIzaABCDEFGHIJKLMNOPQRSTUVWXY123456', 'fact')
        self.assertFalse(result['ok'])
        self.assertEqual(memory_service.list_memories(), [])

    def test_delete_memory(self):
        saved = memory_service.save_memory('Project: desktop Ozzy.', 'project')
        memory_id = saved['memory']['id']
        self.assertEqual(memory_service.delete_memories([memory_id]), 1)
        self.assertEqual(memory_service.list_memories(), [])


if __name__ == '__main__':
    unittest.main()
