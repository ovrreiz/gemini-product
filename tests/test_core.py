"""Тести ядра без мережі та без Streamlit: python -m unittest -v"""
import dataclasses
import json
import unittest

from copygen import llm
from copygen.checks import run_checks
from copygen.config import PLATFORMS, LANGUAGES, Settings, settings_from_env
from copygen.errors import (ApiKeyInvalid, ApiKeyMissing, BackendError, BadResponse, EmptyResponse, InvalidRequest,
                            ModelUnavailable, QuotaExceeded, ServiceUnavailable)
from copygen.llm import BackendResponse
from copygen.models import ProductRequest
from copygen.prompts import build_prompt
from copygen.schema import normalize_hashtags, parse_copy

REAL = Settings(api_key="test-key", models=("m1", "m2"), mock=False)


def req(**kw):
    base = dict(name="Термокружка Nord", features=("Об'єм 450 мл", "Тримає тепло 8 годин"),
                audience="студенти", platform="instagram", language="uk", tone="Дружній", emoji=False)
    base.update(kw)
    return ProductRequest(**base)


def good_json(**over):
    d = {"title": "Термокружка Nord 450 мл", "short_description": "Тримає тепло 8 годин.",
         "long_description": "Зручна кружка на кожен день. Об'єм 450 мл.",
         "hashtags": ["#кружка", "#тепло", "#nord", "#офіс", "#студенти"],
         "call_to_action": "Замовляйте!", "keywords": ["термокружка", "nord"]}
    d.update(over)
    return json.dumps(d, ensure_ascii=False)


class FakeBackend:
    """Віддає заздалегідь підготовлені відповіді/помилки по черзі й запам'ятовує виклики."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []

    def generate_json(self, model, system, prompt, temperature, max_tokens):
        self.calls.append({"model": model, "prompt": prompt, "max_tokens": max_tokens})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, str):
            return BackendResponse(text=item, prompt_tokens=10, output_tokens=20, total_tokens=30)
        return item


def run(r, backend, settings=REAL, **kw):
    llm.clear_cache()
    return llm.generate(r, settings, backend=backend, sleep=lambda s: None, **kw)


class RequestTests(unittest.TestCase):
    def test_from_form_cleans_and_splits(self):
        r = ProductRequest.from_form("  Nord \x00", "a\n\n b \n", "", "telegram", "en", "Діловий", True)
        self.assertEqual(r.name, "Nord")
        self.assertEqual(r.features, ("a", "b"))
        r.validate()

    def test_validation_errors(self):
        for bad in (req(name="x"), req(features=()), req(features=("x" * 201,)), req(platform="tiktok"),
                    req(language="fr"), req(tone="Злий"), req(audience="a" * 201)):
            with self.assertRaises(InvalidRequest):
                bad.validate()

    def test_cache_key_depends_on_inputs(self):
        self.assertEqual(req().cache_key("m", 0.8), req().cache_key("m", 0.8))
        self.assertNotEqual(req().cache_key("m", 0.8), req(tone="Преміум").cache_key("m", 0.8))
        self.assertNotEqual(req().cache_key("m", 0.8), req().cache_key("m2", 0.8))


class SchemaTests(unittest.TestCase):
    def test_hashtags_normalized(self):
        self.assertEqual(normalize_hashtags(["# My tag!", "#my tag", "#", "кава", "Кава", "a_b"], 10),
                         ["#Mytag", "#кава", "#a_b"])
        self.assertEqual(len(normalize_hashtags([f"t{i}" for i in range(20)], 5)), 5)

    def test_parse_ok_and_code_fence(self):
        c = parse_copy("```json\n" + good_json() + "\n```", 5)
        self.assertEqual(c.title, "Термокружка Nord 450 мл")
        self.assertEqual(len(c.hashtags), 5)

    def test_parse_errors(self):
        for bad in ("not json", "[]", good_json(title=""), json.dumps({"title": "x"})):
            with self.assertRaises(BadResponse):
                parse_copy(bad, 5)


class PromptTests(unittest.TestCase):
    def test_prompt_contains_limits_language_and_data_tags(self):
        p = build_prompt(req(platform="telegram", language="pl"))
        spec = PLATFORMS["telegram"]
        for s in (str(spec.title_max), "Polish", "<product>", "</product>", "Термокружка Nord", "do not use emoji"):
            self.assertIn(s, p)

    def test_feedback_appended(self):
        self.assertIn("Fix them", build_prompt(req(), ["Довжина заголовка: 99 з 60"]))


class ChecksTests(unittest.TestCase):
    def _copy(self, **over):
        return parse_copy(good_json(**over), 12)

    def test_all_good(self):
        res = run_checks(self._copy(), req())
        self.assertTrue(all(c.ok for c in res), [c for c in res if not c.ok])

    def test_title_too_long_and_hashtag_count(self):
        res = {c.name: c for c in run_checks(self._copy(title="я" * 80, hashtags=["#a"]), req())}
        self.assertFalse(res["Довжина заголовка"].ok)
        self.assertFalse(res["Кількість хештегів"].ok)

    def test_invented_number_is_warning(self):
        res = {c.name: c for c in run_checks(self._copy(short_description="Знижка 50% лише сьогодні."), req())}
        c = res["Відсутність вигаданих чисел"]
        self.assertFalse(c.ok)
        self.assertEqual(c.severity, "warn")
        self.assertIn("50", c.detail)

    def test_language_mismatch_warns(self):
        res = {c.name: c for c in run_checks(
            self._copy(short_description="Keeps drinks hot.", long_description="A nice cup for every day."), req())}
        self.assertFalse(res["Відповідність мові"].ok)


class GenerateTests(unittest.TestCase):
    def test_success(self):
        b = FakeBackend(good_json())
        res = run(req(), b)
        self.assertEqual(res.model, "m1")
        self.assertEqual(res.attempts, 1)
        self.assertEqual((res.prompt_tokens, res.output_tokens, res.total_tokens), (10, 20, 30))
        self.assertFalse(res.hard_errors)
        self.assertFalse(res.mock)

    def test_retry_on_503_then_success(self):
        b = FakeBackend(BackendError(503, "busy"), BackendError(503, "busy"), good_json())
        res = run(req(), b)
        self.assertEqual(res.attempts, 3)
        self.assertEqual([c["model"] for c in b.calls], ["m1", "m1", "m1"])

    def test_503_exhausted_falls_back_to_next_model(self):
        b = FakeBackend(*[BackendError(503, "busy")] * 3, good_json())
        res = run(req(), b)
        self.assertEqual(res.model, "m2")

    def test_404_falls_back_without_retry(self):
        b = FakeBackend(BackendError(404, "model not found"), good_json())
        res = run(req(), b)
        self.assertEqual((res.model, res.attempts), ("m2", 2))

    def test_all_models_missing(self):
        with self.assertRaises(ModelUnavailable):
            run(req(), FakeBackend(BackendError(404, "x"), BackendError(404, "x")))

    def test_quota_on_all_models(self):
        b = FakeBackend(*[BackendError(429, "quota")] * 4)
        with self.assertRaises(QuotaExceeded):
            run(req(), b)

    def test_only_one_retry_for_429(self):
        b = FakeBackend(BackendError(429, "q"), BackendError(429, "q"), BackendError(429, "q"), BackendError(429, "q"))
        with self.assertRaises(QuotaExceeded):
            run(req(), b)
        self.assertEqual(len(b.calls), 4)      # по 2 виклики (1 повтор) на кожну з двох моделей

    def test_invalid_key_stops_immediately(self):
        for err in (BackendError(403, "denied"), BackendError(400, "API key not valid. Please pass a valid API key.")):
            b = FakeBackend(err, good_json())
            with self.assertRaises(ApiKeyInvalid):
                run(req(), b)
            self.assertEqual(len(b.calls), 1)

    def test_empty_response_retries_with_bigger_budget(self):
        b = FakeBackend(BackendResponse(text=None, finish_reason="MAX_TOKENS"), good_json())
        res = run(req(), b)
        self.assertEqual(b.calls[1]["max_tokens"], REAL.max_tokens * 2)
        self.assertEqual(res.attempts, 2)

    def test_empty_everywhere_raises(self):
        b = FakeBackend(*[BackendResponse(text="")] * 4)
        with self.assertRaises(EmptyResponse):
            run(req(), b)

    def test_bad_json_retried_once(self):
        b = FakeBackend("oops", good_json())
        self.assertEqual(run(req(), b).attempts, 2)

    def test_self_repair_when_title_too_long(self):
        b = FakeBackend(good_json(title="я" * 90), good_json())
        res = run(req(), b)
        self.assertTrue(res.repaired)
        self.assertFalse(res.hard_errors)
        self.assertIn("Довжина заголовка", b.calls[1]["prompt"])      # зворотний зв'язок дійшов до моделі

    def test_repair_not_accepted_if_worse(self):
        b = FakeBackend(good_json(title="я" * 90), good_json(title="я" * 90, hashtags=["#a"]))
        res = run(req(), b)
        self.assertFalse(res.repaired)

    def test_cache_hit_skips_backend(self):
        b = FakeBackend(good_json(), good_json())
        llm.clear_cache()
        r1 = llm.generate(req(), REAL, backend=b, sleep=lambda s: None)
        r2 = llm.generate(req(), REAL, backend=b, sleep=lambda s: None)
        self.assertFalse(r1.from_cache)
        self.assertTrue(r2.from_cache)
        self.assertEqual(len(b.calls), 1)
        r3 = llm.generate(req(), REAL, backend=b, sleep=lambda s: None, use_cache=False)
        self.assertFalse(r3.from_cache)

    def test_preferred_model_goes_first(self):
        b = FakeBackend(good_json())
        run(req(), b, model="m2")
        self.assertEqual(b.calls[0]["model"], "m2")

    def test_missing_key(self):
        with self.assertRaises(ApiKeyMissing):
            llm.generate(req(), Settings(api_key="", mock=False))


class MockTests(unittest.TestCase):
    def test_mock_passes_all_checks_for_every_combination(self):
        mock = dataclasses.replace(REAL, mock=True)
        for plat in PLATFORMS:
            for lang in LANGUAGES:
                for r in (req(platform=plat, language=lang),
                          req(platform=plat, language=lang, audience="",
                              features=tuple(f"Дуже довга характеристика номер {i} " * 3 for i in range(15)))):
                    res = llm.generate(r, mock)
                    self.assertTrue(res.mock)
                    self.assertFalse(res.hard_errors, (plat, lang, [c for c in res.checks if not c.ok]))


class SettingsTests(unittest.TestCase):
    def test_env(self):
        import os
        old = dict(os.environ)
        try:
            for k in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "MOCK", "GEMINI_MODELS"):
                os.environ.pop(k, None)
            s = settings_from_env()
            self.assertTrue(s.mock)                     # без ключа — демо-режим
            os.environ["GEMINI_API_KEY"] = "abc"
            os.environ["GEMINI_MODELS"] = "x, y"
            s = settings_from_env()
            self.assertFalse(s.mock)
            self.assertEqual(s.models, ("x", "y"))
            os.environ["MOCK"] = "1"
            self.assertTrue(settings_from_env().mock)
        finally:
            os.environ.clear()
            os.environ.update(old)


if __name__ == "__main__":
    unittest.main()
