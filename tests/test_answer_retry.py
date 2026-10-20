"""Empty LLM answers: bigger cap, one no-thinking retry, then a spoken fallback. No network."""
import pathlib
import unittest

from commands.model import (
    HAIKU_EFFORT, MAX_TOKENS_ANSWER, MAX_TOKENS_ANSWER_RETRY, NO_ANSWER, REFUSAL,
    answer_with_retry, chat_body, no_reasoning_body,
)

SPANISH = "¿Cómo se dice 'good morning' en inglés y qué hora es?"


def reply(text, cost=0.0001, finish="stop"):
    return {"choices": [{"message": {"content": text}, "finish_reason": finish}], "usage": {"cost": cost}}


class Poster:
    def __init__(self, *payloads):
        self.payloads, self.bodies = list(payloads), []

    def __call__(self, body):
        self.bodies.append(body)
        return self.payloads.pop(0)


def question(text):
    return chat_body(MAX_TOKENS_ANSWER, [{"role": "system", "content": "short"},
                                         {"role": "user", "content": text}], usage=True)


class AnswerRetryTests(unittest.TestCase):
    def test_answer_cap_leaves_room_for_thinking_and_effort_stays_low(self):
        self.assertEqual(MAX_TOKENS_ANSWER, 768)
        self.assertEqual(HAIKU_EFFORT, "low")
        body = question("hi")
        self.assertEqual(body["max_tokens"], 768)
        self.assertEqual(body["reasoning"], {"effort": "low"})

    def test_answer_on_first_try_posts_once(self):
        post = Poster(reply("Canberra."))
        self.assertEqual(answer_with_retry(question("capital?"), post), ("Canberra.", 0.0001))
        self.assertEqual(len(post.bodies), 1)

    def test_spanish_question_with_empty_first_answer_gets_retried_answer(self):
        post = Poster(reply(None, finish="length"),
                      reply("'Buenos días' es 'good morning', y son las 4:07 PM."))
        line, cost = answer_with_retry(question(SPANISH), post)
        self.assertIn("good morning", line)
        self.assertAlmostEqual(cost, 0.0002)
        self.assertEqual(post.bodies[1]["messages"][-1]["content"], SPANISH)

    def test_empty_answer_retries_once_with_reasoning_off_and_small_cap(self):
        first = question("summary please")
        post = Poster(reply(""), reply("Here you go."))
        self.assertEqual(answer_with_retry(first, post)[0], "Here you go.")
        retry = post.bodies[1]
        self.assertEqual(retry["reasoning"], {"enabled": False})
        self.assertEqual(retry["max_tokens"], MAX_TOKENS_ANSWER_RETRY)
        self.assertLess(MAX_TOKENS_ANSWER_RETRY, MAX_TOKENS_ANSWER)
        self.assertEqual(retry["messages"], first["messages"])
        self.assertEqual(first["reasoning"], {"effort": "low"})  # original untouched

    def test_still_empty_after_retry_speaks_sorry_and_stops(self):
        post = Poster(reply(None), reply("  "))
        self.assertEqual(answer_with_retry(question("x"), post)[0], NO_ANSWER)
        self.assertEqual(NO_ANSWER, "Sorry, I didn't catch an answer, try again.")
        self.assertEqual(len(post.bodies), 2)

    def test_refusal_is_not_retried(self):
        post = Poster(reply(None, finish="refusal"))
        self.assertEqual(answer_with_retry(question("x"), post)[0], REFUSAL)
        self.assertEqual(len(post.bodies), 1)

    def test_no_reasoning_body_copies(self):
        body = question("x")
        self.assertIsNot(no_reasoning_body(body), body)

    def test_siri_ask_llm_uses_the_retry(self):
        src = (pathlib.Path(__file__).resolve().parents[1] / "siri.py").read_text()
        fn = src[src.index("def ask_llm("):src.index("# ----", src.index("def ask_llm("))]
        self.assertIn("answer_with_retry(body, post)", fn)


if __name__ == "__main__":
    unittest.main()
