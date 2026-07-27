"""Юридические страницы ONCOUNT — /policy (план 2026-07-27, Фаза 2).

⚠️ ЧЕРНОВИК НА ПРОВЕРКУ ЮРИСТА. Текст написан по факту: что мы реально собираем
на квиз-лендингах и в кабинете партнёра и куда это уходит. Юридической экспертизы
не проходил — перед тем как ссылаться на него из формы согласия, показать юристу.

Почему не перенесли со старого сайта: на oncount.co (Тильда) под /policy лежит
политика сайта ggacadem.com, а под /oferta — договор GGO Consult LLC. Это чужой
проект и чужое юрлицо, ONCOUNT там не упоминается вовсе (проверено 2026-07-27).

Правило репо №1: текст живёт здесь, не в вёрстке.
"""
from __future__ import annotations

COMPANY = "PADVICE ACCOUNTING AND MANAGEMENT — FZCO"
LICENCE_NO = "37408"
CONTACT_EMAIL = "info@oncount.com"
UPDATED = "27 июля 2026"
UPDATED_EN = "27 July 2026"

POLICY = {
    "title": {"ru": "Политика конфиденциальности", "en": "Privacy policy"},
    "updated": {"ru": f"Действует с {UPDATED}", "en": f"Effective from {UPDATED_EN}"},
    "intro": {
        "ru": f"Эта политика описывает, какие данные собирает {COMPANY} "
              f"(торговая лицензия №{LICENCE_NO}, Дубай, ОАЭ; далее — ONCOUNT) на "
              "своих сайтах и в личном кабинете партнёра, зачем они нужны и кому "
              "передаются.",
        "en": f"This policy explains what data {COMPANY} (trade licence "
              f"No. {LICENCE_NO}, Dubai, UAE; hereinafter ONCOUNT) collects on its "
              "websites and in the partner dashboard, why we need it and with whom "
              "we share it.",
    },
    "sections": [
        {
            "h": {"ru": "Какие данные мы собираем", "en": "What we collect"},
            "p": {
                "ru": [
                    "Заявка с формы: имя и номер телефона, ответы на вопросы анкеты "
                    "(сфера бизнеса, задача, ситуация).",
                    "Партнёрский кабинет: имя, телефон, Telegram ID или email — то, "
                    "чем вы входите, — и данные о переданных вами клиентах.",
                    "Технические данные перехода: по какой ссылке пришли, с какой "
                    "страницы и когда. IP-адрес и содержимое адресной строки мы в "
                    "статистику переходов не пишем.",
                ],
                "en": [
                    "Form submissions: name and phone number, answers to the quiz "
                    "questions (business area, task, situation).",
                    "Partner dashboard: name, phone, Telegram ID or email you sign in "
                    "with, and data about the clients you refer.",
                    "Referral technical data: which link brought you, from which page "
                    "and when. We do not store IP addresses or query strings in link "
                    "statistics.",
                ],
            },
        },
        {
            "h": {"ru": "Зачем", "en": "Why"},
            "p": {
                "ru": [
                    "Связаться с вами по оставленной заявке и подготовиться к разговору.",
                    "Оказать услугу и вести по ней документы и отчётность.",
                    "Начислить и выплатить партнёрское вознаграждение, показать статусы "
                    "в кабинете.",
                    "Отправить материалы, которые вы запросили (чек-лист, запись "
                    "встречи, ссылку на Zoom).",
                ],
                "en": [
                    "To contact you about your request and prepare for the call.",
                    "To deliver the service and keep the related documents and reports.",
                    "To calculate and pay the partner reward and show statuses in the "
                    "dashboard.",
                    "To send the materials you asked for (checklist, recording, Zoom "
                    "link).",
                ],
            },
        },
        {
            "h": {"ru": "Кому передаём", "en": "Who we share with"},
            "p": {
                "ru": [
                    "Сервисам, через которые мы работаем: CRM (Kommo), мессенджеры "
                    "WhatsApp и Telegram через Wazzup24, почтовая рассылка (Resend), "
                    "хостинг (Railway). Каждый получает только то, что нужно для "
                    "своей задачи.",
                    "Государственным органам ОАЭ — если этого требует закон.",
                    "Мы не продаём и не передаём ваши данные третьим лицам для их "
                    "собственной рекламы.",
                ],
                "en": [
                    "To the services we run on: CRM (Kommo), WhatsApp and Telegram via "
                    "Wazzup24, email delivery (Resend), hosting (Railway). Each gets "
                    "only what it needs for its task.",
                    "To UAE authorities where required by law.",
                    "We do not sell or pass your data to third parties for their own "
                    "marketing.",
                ],
            },
        },
        {
            "h": {"ru": "Сколько храним", "en": "How long we keep it"},
            "p": {
                "ru": [
                    "Пока ведём с вами работу и пока этого требует бухгалтерское и "
                    "налоговое законодательство ОАЭ. Дальше — удаляем или "
                    "обезличиваем.",
                ],
                "en": [
                    "For as long as we work together and as long as UAE accounting and "
                    "tax law requires. After that we delete or anonymise the data.",
                ],
            },
        },
        {
            "h": {"ru": "Ваши права", "en": "Your rights"},
            "p": {
                "ru": [
                    f"Вы можете запросить, какие данные о вас у нас есть, попросить их "
                    f"исправить или удалить, отозвать согласие на обработку и отписаться "
                    f"от рассылок. Напишите на {CONTACT_EMAIL} — ответим.",
                ],
                "en": [
                    f"You can ask what data we hold about you, request a correction or "
                    f"deletion, withdraw your consent and unsubscribe. Write to "
                    f"{CONTACT_EMAIL} and we will respond.",
                ],
            },
        },
        {
            "h": {"ru": "Cookie", "en": "Cookies"},
            "p": {
                "ru": [
                    "Мы используем технические cookie: они держат вашу сессию в "
                    "кабинете и запоминают выбранный язык. Рекламных cookie нет.",
                ],
                "en": [
                    "We use technical cookies only: they keep your dashboard session "
                    "and remember the selected language. No advertising cookies.",
                ],
            },
        },
        {
            "h": {"ru": "Контакты", "en": "Contacts"},
            "p": {
                "ru": [
                    f"{COMPANY}, The One Tower, 15 floor, office 14, Sheikh Zayed Rd, "
                    f"Дубай, ОАЭ. Почта: {CONTACT_EMAIL}.",
                ],
                "en": [
                    f"{COMPANY}, The One Tower, 15 floor, office 14, Sheikh Zayed Rd, "
                    f"Dubai, UAE. Email: {CONTACT_EMAIL}.",
                ],
            },
        },
    ],
}
