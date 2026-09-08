# Что не переносится из Telegram и почему

В MAX Bot API нет целых платформ Telegram: опросов, платежей, игр, стикерпаков, форумов, реакций, бустов, инлайн-режима, invite-ссылок как объектов, заявок на вступление, кнопки меню. Соответствующие методы telebot **существуют в maxibot как заглушки** — перенесённый код никогда не падает с `AttributeError`:

* **Действия** (`send_poll`, `create_forum_topic`, …) бросают `NotImplementedError` с объяснением — код падает с понятной причиной, а не тихо делает вид, что опрос отправлен. Заглушки принимают любые аргументы (не бывает `TypeError` из-за сигнатуры).
* **Регистрация обработчиков** несуществующих событий (`@bot.poll_handler(...)`, `register_...`, `add_...`, `process_new_...`) — предупреждение в лог и no-op: **бот запускается**, остальные обработчики работают, а событие просто никогда не придёт.

Ниже — полный список по фичам.

## Опросы (polls)
В MAX нет ни метода отправки опроса, ни обновлений `poll`/`poll_answer`.
Действия: `send_poll`, `stop_poll`. Обработчики: `poll_handler`, `poll_answer_handler` + их `add_`/`register_`/`process_new_`-варианты.

## Платежи и инвойсы (payments)
Платёжной платформы в MAX нет: ни инвойсов, ни Stars, ни событий `shipping_query`/`pre_checkout_query`.
Действия: `send_invoice`, `create_invoice_link`, `answer_shipping_query`, `answer_pre_checkout_query`. Обработчики: `pre_checkout_query_handler`, `shipping_query_handler` + `add_`/`register_`/`process_new_`.

## Игры и кости (games, dice)
HTML5-игр и анимированных костей в MAX нет.
Действия: `send_game`, `set_game_score`, `get_game_high_scores`, `send_dice` (эмодзи можно отправить обычным сообщением — без анимации и выпавшего значения).

## Стикерпаки (sticker sets)
Управления наборами стикеров в MAX нет — стикер отправляется только **готовым кодом**: `bot.send_sticker(chat_id, code)` (код приходит в сообщении со стикером от пользователя).
Действия: `create_new_sticker_set`, `add_sticker_to_set`, `delete_sticker_from_set`, `delete_sticker_set`, `get_sticker_set`, `get_custom_emoji_stickers`, `upload_sticker_file`, `set_sticker_emoji_list`, `set_sticker_keywords`, `set_sticker_mask_position`, `set_sticker_position_in_set`, `set_sticker_set_thumb`, `set_sticker_set_thumbnail`, `set_sticker_set_title`, `set_custom_emoji_sticker_set_thumbnail`, `set_chat_sticker_set`, `delete_chat_sticker_set`.

## Форумы / топики (forums)
Супергрупп и тем в MAX не существует (групповой чат один, см. `chat.type == 'group'`).
Действия: `create_forum_topic`, `edit_forum_topic`, `close_forum_topic`, `reopen_forum_topic`, `delete_forum_topic`, `unpin_all_forum_topic_messages`, `edit_general_forum_topic`, `close_general_forum_topic`, `reopen_general_forum_topic`, `hide_general_forum_topic`, `unhide_general_forum_topic`, `unpin_all_general_forum_topic_messages`, `get_forum_topic_icon_stickers`. Параметр `message_thread_id` в send_*-методах принимается и игнорируется.

## Реакции (reactions)
Реакций в MAX Bot API нет: ни метода, ни обновлений `message_reaction`/`message_reaction_count`.
Действия: `set_message_reaction`. Обработчики: `message_reaction_handler`, `message_reaction_count_handler` + `add_`/`register_`/`process_new_`.

## Бусты (boosts)
Бустов в MAX нет.
Действия: `get_user_chat_boosts`. Обработчики: `chat_boost_handler`, `removed_chat_boost_handler` + `add_`/`register_`/`process_new_`.

## Инлайн-режим (inline mode)
Обновлений `inline_query`/`chosen_inline_result` в MAX не существует. Альтернативы: inline-клавиатуры (`InlineKeyboardMarkup`) и reply-клавиатуры на сообщениях бота.
Действия: `answer_inline_query`, `answer_web_app_query`. Обработчики: `inline_handler`, `chosen_inline_handler` + `add_`/`register_`/`process_new_`-варианты.

## Invite-ссылки и заявки (invite links, join requests)
Именованных invite-ссылок как объектов в MAX нет — есть только постоянная ссылка чата: `bot.get_chat(chat_id).invite_link`. Заявок на вступление (`chat_join_request`) тоже нет.
Действия: `create_chat_invite_link`, `edit_chat_invite_link`, `revoke_chat_invite_link`, `approve_chat_join_request`, `decline_chat_join_request` (`export_chat_invite_link` реализован — отдаёт постоянную ссылку). Обработчики: `chat_join_request_handler` + `add_`/`register_`/`process_new_`.

## Разбан (unban)
`ban_chat_member` в MAX необратим со стороны бота — снять блокировку может только администратор вручную, поэтому `unban_chat_member` бросает `NotImplementedError`. Телеграмный приём «кикнуть с правом вернуться» (ban + unban) в MAX делается одним вызовом `bot.api.remove_chat_member(chat_id, user_id)` без блокировки. Временных банов (`until_date`) в MAX тоже нет — параметр игнорируется с предупреждением.

## Права и ограничения (permissions)
Общечатовых ограничений (`ChatPermissions`) в MAX нет — права выдаются только администраторам при назначении (`promote_chat_member`).
Действия: `set_chat_permissions`, `get_my_default_administrator_rights`, `set_my_default_administrator_rights`.

## Анонимные отправители-чаты (sender chats)
`sender_chat` в MAX не существует (`message.sender_chat` всегда None).
Действия: `ban_chat_sender_chat`, `unban_chat_sender_chat`.

## Кнопка меню (menu button)
Кнопки меню в MAX нет — используйте команды (`set_my_commands`) и клавиатуры.
Действия: `set_chat_menu_button`, `get_chat_menu_button`.

## Локальный Bot API сервер (log_out, close)
У MAX нет локального Bot API сервера, поэтому `log_out` и `close` не нужны и невозможны.

## Пока не реализовано в maxibot (но эмулируемо)
Эти два метода бросают `NotImplementedError` с пометкой «пока не реализован» — фича в MAX выразима, руки не дошли:
* `get_user_profile_photos` — истории аватарок с file_id в MAX нет; текущая аватарка доступна уже сейчас: `bot.get_chat_member(chat_id, user_id).avatar_url` / `.full_avatar_url`;
* `restrict_chat_member` — прямого API ограничений в MAX нет; мьют эмулируется реестром с авто-удалением сообщений (в планах). Исключить из чата: `ban_chat_member` (с блокировкой) или `bot.api.remove_chat_member(chat_id, user_id)` (без).

Отдельно: `setup_middleware` (телеботовский class-based middleware на `BaseMiddleware`) не портирован — используйте функциональный `@bot.middleware_handler` (`apihelper.ENABLE_MIDDLEWARE = True`).

## Что при этом РАБОТАЕТ
Часто принимаемое за невозможное, но реализованное в maxibot: `set_my_name`, `set_my_description`, `set_my_short_description` (PATCH /me), `send_sticker` (готовым кодом), `export_chat_invite_link` (постоянная ссылка), `ban_chat_member`/`kick_chat_member`, `promote_chat_member`, `delete_messages` (циклом — пакетного DELETE в MAX нет; неудалившиеся пропускаются, как в Telegram), история чата и список чатов (`get_chat_history`, `get_chats` — этого нет в Telegram), комментарии каналов (`comment_handler`, `send_comment` — этого тоже нет в Telegram).
