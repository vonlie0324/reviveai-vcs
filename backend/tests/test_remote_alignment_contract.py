import unittest
from app.services.speech_verified_alignment import _words, inspect_word_offsets
class TestContract(unittest.TestCase):
    def test_number_normalization(self):
        self.assertEqual(_words('one last adjustment'),_words('1 last adjustment'))
    def test_zero_length_rejected(self):
        _,issues=inspect_word_offsets([('the',3.3,3.3)],6)
        self.assertEqual(issues[0]['reason'],'OUT_OF_RANGE_OR_NONPOSITIVE_DURATION')
    def test_positive_offsets(self):
        _,issues=inspect_word_offsets([('the',3.25,3.4)],6)
        self.assertFalse(issues)
