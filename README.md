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

**При нестабильной работе ботов смотрите docs/cert.md**

## Быстрый старт
Необходимо установить библиотеку  
```sh
pip install maxibot
```
## Просто эхо-бот
Необходимо создать файл `echo_bot.py` и добавить в него следующий код.
Для начала надо проинициализировать бота, делается это следующим образом:
```python
from maxibot import MaxiBot

bot = maxibot.Maxibot("TOKEN")
```
После этой декларации нам нужно зарегистрировать так называемых обработчиков сообщений. Обработчики сообщений определяют фильтры, которые должно проходить сообщение. Если сообщение проходит через фильтр, вызывается декорированная функция и входящее сообщение передается в качестве аргумента.

Определите определим обработчик сообщений, который обрабатывает входящие `/start` и `/help` команды.
```python
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
	bot.send_message(message, "Привет! Как дела?")
```
Добавим ещё один обработчик сообщения, который будет повторять отправленный текст:
```python
@bot.message_handler(func=lambda m: True)
def echo_all(message):
	bot.send_message(message, message.text)
```
Для того, чтобы запустить бота, запустим полинг событий следующей командой:
```python
bot.polling()
```
Для простого эхо-бота это всё. Наш файл теперь выглядит так:
```python
from maxibot import MaxiBot

bot = maxibot.Maxibot("TOKEN")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
	bot.send_message(message, "Привет! Как дела?")

@bot.message_handler(func=lambda m: True)
def echo_all(message):
	bot.send_message(message, message.text)

bot.polling()
```
Чтобы запустить бота, просто откройте терминал и введите `python echo_bot.py`.  
Проверьте его, отправив команды (`/start` и `/help`) и произвольные текстовые сообщения.
