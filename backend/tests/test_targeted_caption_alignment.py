import unittest
from app.services.speech_verified_alignment import validate_recognized_words

class CaptionValidationTests(unittest.TestCase):
    def test_exact_valid(self):
        self.assertTrue(validate_recognized_words('A good dog', [('A',0.0,.1),('good',.1,.3),('dog',.3,.5)],duration=1))
    def test_mismatched_text_rejected(self):
        self.assertFalse(validate_recognized_words('A good dog', [('a',0.0,.1),('bad',.1,.3),('cat',.3,.5)],duration=1))
    def test_overlapping_offsets_rejected(self):
        self.assertFalse(validate_recognized_words('A good dog', [('A',0.0,.4),('good',.3,.5),('dog',.5,.8)],duration=1))
if __name__=='__main__': unittest.main()
