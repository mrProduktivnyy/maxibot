### **Библиотека для мессенджера Max**<br>
Её главная цель — позволить разработчикам использовать знакомые методы и классы из pyTelegramBotAPI (telebot) без изменений. Это позволяет переводить существующего телеграм бота на Max, а также создавать нового бота, заменив import telebot на import maxibot.

![tg_to_max](https://github.com/mrProduktivnyy/maxibot/raw/main/maxibot/docs/tg_to_max.png)

[![PyPi Package Version](https://img.shields.io/pypi/v/maxibot.svg)](https://pypi.python.org/pypi/maxibot)
[![Supported Python versions](https://img.shields.io/pypi/pyversions/maxibot.svg)](https://pypi.python.org/pypi/maxibot)
[![Documentation Status](https://img.shields.io/badge/docs-passing-green)](https://github.com/mrProduktivnyy/maxibot/tree/main/maxibot/docs)
[![PyPi downloads](https://img.shields.io/pypi/dm/maxibot.svg)](https://pypi.org/project/maxibot/)
[![PyPi status](https://img.shields.io/pypi/status/maxibot.svg?style=flat-square)](https://pypi.python.org/pypi/maxibot)

### **Канал связи с разработчиками:** 
max: [Чат в Макс](https://max.ru/join/fCUIMAwLGdO_F1BY4rTdHQ54_D8PaZyjLnc7CdcW8gY)

tg: [t.me/maxibot_dev](https://t.me/maxibot_dev)

## Быстрый старт
Необходимо установить библиотеку  
```sh
pip install maxibot
```
## Режимы запуска

Maxibot поддерживает два режима получения обновлений:

| Режим | Когда использовать |
|---|---|
| **Long polling** | Разработка и тестирование на локальной машине |
| **Webhook** | Продакшен: бот работает на сервере с публичным HTTPS-адресом |

---

## Long polling — быстрый старт

Подходит для разработки. Бот сам опрашивает MAX API — публичный адрес не нужен.

Создайте файл `echo_bot.py`:

```python
from maxibot import MaxiBot

bot = MaxiBot("TOKEN")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Привет! Как дела?")

@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.send_message(message.chat.id, message.text)

bot.polling()
```

Запустите:

```sh
python echo_bot.py
```

Проверьте, отправив боту команды `/start`, `/help` и любой текст.

---

## Webhook — продакшен

MAX API требует публичный HTTPS-адрес на порту 443. На практике бот работает за reverse proxy (nginx, caddy), который принимает HTTPS снаружи и проксирует HTTP внутрь.

### Схема

```
Пользователь
    │
    ▼  HTTPS :443
[Nginx / Caddy]  ──── завершает TLS, проверяет сертификат
    │
    ▼  HTTP :8080
[Ваш бот]        ──── bot.start_webhook(port=8080, ...)
```

### Код бота (`bot.py`)

```python
from maxibot import MaxiBot

bot = MaxiBot("TOKEN")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.send_message(message.chat.id, "Привет! Как дела?")

@bot.message_handler(func=lambda m: True)
def echo_all(message):
    bot.send_message(message.chat.id, message.text)

bot.start_webhook(
    host="0.0.0.0",
    port=8080,
    secret="ваш-секрет",           # MAX будет проверять этот секрет в каждом запросе
    webhook_url="https://example.com/webhook"  # MAX зарегистрирует этот адрес автоматически
)
```

### Пример конфига Nginx

```nginx
server {
    listen 443 ssl;
    server_name example.com;

    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;

    location /webhook {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Запуск

```sh
python bot.py
```

После старта бот автоматически зарегистрирует webhook-адрес в MAX API через `POST /subscriptions`. MAX начнёт присылать обновления на `https://example.com/webhook`, Nginx перенаправит их на порт 8080, где слушает бот.

Чтобы отписаться от webhook (например, при переключении на polling):

```python
bot.delete_webhook("https://example.com/webhook")
```
