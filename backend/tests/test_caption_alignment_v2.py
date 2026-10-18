import unittest
from app.services.speech_verified_alignment import _words, inspect_word_offsets, validate_recognized_words

class AlignmentV2Tests(unittest.TestCase):
    def test_numeric_equivalence(self):
        self.assertEqual(_words('Just one last adjustment'), _words('just 1 last adjustment'))
        self.assertTrue(validate_recognized_words('Just one last adjustment before the big debut', [('just',0,.25),('1',.25,.5),('last',.5,.7),('adjustment',.7,1.2),('before',1.2,1.6),('the',1.6,1.8),('big',1.8,2.0),('debut',2.0,2.6)], duration=7))
    def test_small_overlap_only(self):
        corrected, errors = inspect_word_offsets([('a',0,.5),('b',.49,.8)], 2)
        self.assertEqual(errors, [])
        self.assertEqual(corrected[1][1], .5)
    def test_large_overlap_rejected(self):
        _, issues = inspect_word_offsets([('a',0,.5),('b',.4,.8)], 2)
        self.assertEqual(issues[0]['reason'], 'WORD_OVERLAP')
    def test_nonpositive_rejected(self):
        _, issues = inspect_word_offsets([('a',0,0)], 2)
        self.assertEqual(issues[0]['reason'], 'OUT_OF_RANGE_OR_NONPOSITIVE_DURATION')
    def test_out_of_bounds_rejected(self):
        _, issues = inspect_word_offsets([('a',0,2.2)], 2)
        self.assertEqual(issues[0]['reason'], 'OUT_OF_RANGE_OR_NONPOSITIVE_DURATION')

if __name__ == '__main__': unittest.main()
