"""Веб-інтерфейс (Streamlit): генератор описів товарів і хештегів на основі Gemini API."""
import dataclasses
import hmac
import json
import time

import streamlit as st

from copygen import llm
from copygen.config import LANGUAGES, PLATFORMS, TONES, settings_from_env
from copygen.errors import CopygenError
from copygen.models import ProductRequest

st.set_page_config(page_title="Генератор описів товарів (Gemini)", page_icon="🛍️", layout="wide")

BASE = settings_from_env()


# ---------- необов'язковий пароль на вхід (змінна APP_PASSWORD) ----------
def gate() -> None:
    if not BASE.app_password:
        return
    if st.session_state.get("authed"):
        return
    st.title("🔒 Вхід")
    pwd = st.text_input("Пароль", type="password")
    if pwd:
        if hmac.compare_digest(pwd.encode(), BASE.app_password.encode()):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("Невірний пароль.")
    st.stop()


gate()
st.session_state.setdefault("n_requests", 0)
st.session_state.setdefault("history", [])
st.session_state.setdefault("last", None)

# ---------- бічна панель: ключ, режим, модель ----------
with st.sidebar:
    st.header("⚙️ Налаштування")
    api_key = BASE.api_key
    if not BASE.has_key:
        api_key = st.text_input("Gemini API key", type="password",
                                help="Ключ береться в Google AI Studio. Зберігається лише в цій сесії.")
    demo = st.checkbox("Демо-режим (без звернення до API)", value=not (BASE.has_key or api_key),
                       help="Простий шаблонний генератор без ШІ — лише щоб показати інтерфейс.")
    model = st.selectbox("Модель Gemini", BASE.models, disabled=demo)
    temperature = st.slider("Креативність (temperature)", 0.0, 1.5, 0.8, 0.1, disabled=demo)
    use_cache = st.checkbox("Використовувати кеш", value=True,
                            help="Однакові запити не витрачають квоту API повторно.")
    left = BASE.max_requests_per_session - st.session_state["n_requests"]
    st.caption(f"Залишилось запитів у цій сесії: {max(left, 0)} з {BASE.max_requests_per_session}")
    st.caption("Платформа: Gemini API · Google AI Studio")

settings = dataclasses.replace(BASE, api_key=api_key or "", mock=demo)

# ---------- форма ----------
st.title("🛍️ Генератор описів товарів і хештегів")
st.write("Введіть дані про товар — Gemini створить заголовок, опис, хештеги й заклик до дії "
         "під обрану платформу. Результат автоматично перевіряється на довжину, хештеги та вигадані числа.")
if settings.mock:
    st.info("Увімкнено **демо-режим**: текст складається за шаблоном, без ШІ. "
            "Для реальної генерації введіть API-ключ у бічній панелі й вимкніть демо-режим.")

with st.form("product_form"):
    c1, c2 = st.columns(2)
    with c1:
        name = st.text_input("Назва товару", value="Термокружка Nord 450 мл", max_chars=120)
        features = st.text_area("Характеристики (кожна з нового рядка)", height=150,
                                value="Об'єм 450 мл\nТримає тепло 8 годин\nНержавіюча сталь\nГерметична кришка")
        audience = st.text_input("Цільова аудиторія (необов'язково)", value="студенти й офісні працівники",
                                 max_chars=200)
    with c2:
        platform = st.selectbox("Платформа", list(PLATFORMS), format_func=lambda k: PLATFORMS[k].label)
        language = st.selectbox("Мова тексту", list(LANGUAGES), format_func=lambda k: LANGUAGES[k][0])
        tone = st.selectbox("Тон", list(TONES), index=1)
        emoji = st.checkbox("Дозволити емодзі", value=False)
    submitted = st.form_submit_button("✨ Згенерувати", type="primary")

# ---------- генерація ----------
if submitted:
    if st.session_state["n_requests"] >= BASE.max_requests_per_session:
        st.error("Ліміт запитів для цієї сесії вичерпано. Оновіть сторінку, щоб почати нову сесію.")
    else:
        req = ProductRequest.from_form(name, features, audience, platform, language, tone, emoji)
        try:
            with st.spinner("Генерую текст…"):
                res = llm.generate(req, settings, model=model, temperature=temperature, use_cache=use_cache)
            if not res.from_cache and not res.mock:
                st.session_state["n_requests"] += 1
            st.session_state["last"] = (req, res)
            st.session_state["history"].insert(0, {
                "час": time.strftime("%H:%M:%S"), "товар": req.name,
                "платформа": PLATFORMS[req.platform].label, "заголовок": res.copy.title})
            del st.session_state["history"][10:]
        except CopygenError as e:
            st.error(str(e))

# ---------- результат ----------
last = st.session_state.get("last")
if last:
    req, res = last
    st.divider()
    st.subheader("Результат")
    tab_text, tab_checks, tab_tech = st.tabs(["📝 Текст", "✅ Перевірки", "🔧 Технічні деталі"])

    with tab_text:
        st.caption("Натисніть значок копіювання у правому куті кожного блоку.")
        st.markdown("**Заголовок**")
        st.code(res.copy.title, language=None)
        st.markdown("**Короткий опис**")
        st.code(res.copy.short_description, language=None)
        st.markdown("**Повний опис**")
        st.code(res.copy.long_description, language=None)
        st.markdown("**Хештеги**")
        st.code(" ".join(res.copy.hashtags), language=None)
        st.markdown("**Заклик до дії**")
        st.code(res.copy.call_to_action, language=None)
        st.markdown("**Ключові слова (SEO)**")
        st.code(", ".join(res.copy.keywords), language=None)
        st.download_button("⬇️ Завантажити JSON", mime="application/json", file_name="product_copy.json",
                           data=json.dumps({"request": req.to_dict(), "result": res.copy.to_dict()},
                                           ensure_ascii=False, indent=2))

    with tab_checks:
        for c in res.checks:
            icon = "✅" if c.ok else ("❌" if c.severity == "error" else "⚠️")
            st.write(f"{icon} **{c.name}** — {c.detail}")
        if res.repaired:
            st.info("Перша відповідь порушувала ліміти, тому модель отримала зворотний зв'язок і виправила текст.")
        if res.hard_errors:
            st.warning("Деякі жорсткі вимоги не виконано — відредагуйте текст вручну або згенеруйте ще раз.")
        st.caption("Перевірка «вигаданих чисел» — евристика: вона лише позначає цифри, яких немає у ваших даних.")

    with tab_tech:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Модель", res.model)
        m2.metric("Час, с", f"{res.latency_s:.2f}")
        m3.metric("Токени (вхід+вихід)", f"{res.prompt_tokens}+{res.output_tokens}")
        m4.metric("Звернень до API", res.attempts)
        st.write(f"Режим: {'демо (без ШІ)' if res.mock else 'Gemini API'} · "
                 f"з кешу: {'так' if res.from_cache else 'ні'} · самовиправлення: {'так' if res.repaired else 'ні'}")

if st.session_state["history"]:
    with st.expander("🕘 Історія (остання сесія)"):
        st.dataframe(st.session_state["history"], hide_index=True)
