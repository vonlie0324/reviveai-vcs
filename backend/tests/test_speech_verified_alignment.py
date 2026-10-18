import unittest
from app.services.speech_verified_alignment import validate_recognized_words


class TestSpeechAlignment(unittest.TestCase):
    def test_valid_transcript(self):
        self.assertTrue(validate_recognized_words('The tiny tailor fits the coat.', [
            ('The', 0.1, 0.3), ('tiny', 0.3, 0.6), ('tailor', 0.6, 1.0),
            ('fits', 1.0, 1.3), ('the', 1.3, 1.5), ('coat', 1.5, 2.0),
        ], duration=3))

    def test_wrong_transcript_rejected(self):
        self.assertFalse(validate_recognized_words('The tiny tailor fits the coat.', [
            ('the', 0, 0.2), ('dog', 0.2, 0.5), ('barks', 0.5, 0.9),
        ], duration=3))

    def test_overlapping_word_offsets_rejected(self):
        self.assertFalse(validate_recognized_words('hello world', [
            ('hello', 0.2, 0.8), ('world', 0.7, 1.2),
        ], duration=2))

    def test_out_of_bounds_rejected(self):
        self.assertFalse(validate_recognized_words('hello world', [
            ('hello', 0.2, 0.8), ('world', 0.8, 3.2),
        ], duration=2))

if __name__ == '__main__':
    unittest.main()
