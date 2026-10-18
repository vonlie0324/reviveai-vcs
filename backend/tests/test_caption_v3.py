import unittest
from app.services.speech_verified_alignment import inspect_word_offsets, validate_recognized_words

class TestV3(unittest.TestCase):
    def test_zero_duration_rejected(self):
        _, issues = inspect_word_offsets([('the',3.3,3.3)],6)
        self.assertEqual(issues[0]['reason'], 'OUT_OF_RANGE_OR_NONPOSITIVE_DURATION')
    def test_valid_independent_offsets(self):
        self.assertTrue(validate_recognized_words('meet the tailor', [('meet',.2,.5),('the',.6,.72),('tailor',.8,1.2)],duration=6))
    def test_numbers_equivalent(self):
        self.assertTrue(validate_recognized_words('just one last adjustment', [('just',0,.2),('1',.3,.5),('last',.6,.8),('adjustment',.9,1.3)],duration=6))
if __name__=='__main__': unittest.main()
