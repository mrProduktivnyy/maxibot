### Инструкция по обновлению сертификатов Минцифры

Обновление необходимо выполнить до 19 июля 2026 года.
В противном случае возможны сбои при взаимодействии с API MAX.

### Причина обновления

GlobalSign (японский удостоверяющий центр) принудительно отзывает SSL/TLS-сертификаты у российских компаний в связи с санкционными ограничениями GMO.

Для обеспечения стабильной работы сервисов, чат-ботов и мини-приложений в мессенджере «МАКС» необходимо добавить сертификаты Минцифры в список доверенных.

**Шаг 1. Добавьте сертификат Минцифры**

[Скачайте](https://www.gosuslugi.ru/crt) корневой и промежуточный сертификаты Минцифры на Госуслугах, в блоке «Альтернативный способ».
Установите и добавьте сертификат в доверенные на стороне сервера или используемой среды (например, в хранилище сертификатов ОС или контейнера).

Russian Trusted Root CA / russian_trusted_root_ca.cer — корневой сертификат;

Russian Trusted Sub CA / russian_trusted_sub_ca.cer — промежуточный.

**Если у вас Linux-сервер:**
1. Скачайте сертификаты.
2. Проверьте формат сертификатов:


— Если файл открывается как текст и содержит строки вида -----BEGIN CERTIFICATE-----, это формат PEM. В этом случае его можно просто сохранить с расширением .crt:
```python
sudo cp russian_trusted_root_ca.cer russian_trusted_root_ca.crt
sudo cp russian_trusted_sub_ca.cer russian_trusted_sub_ca.crt
```


— Если сертификат в бинарном формате (DER), конвертируйте его в .crt:
```python
openssl x509 -inform DER -in russian_trusted_root_ca.cer -out russian_trusted_root_ca.crt
openssl x509 -inform DER -in russian_trusted_sub_ca.cer -out russian_trusted_sub_ca.crt
```

3. После этого добавьте сертификаты в системное хранилище:
```python
sudo cp russian_trusted_root_ca.crt /usr/local/share/ca-certificates/
sudo cp russian_trusted_sub_ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
```

**Если Windows / .NET:**

Откройте сертификат через контекстное меню файла.

Корневой сертификат установите в «Доверенные корневые центры сертификации», промежуточный — в «Промежуточные центры сертификации». Если приложение работает не на локальной машине, а в серверной среде или контейнере, обновляйте доверенное хранилище именно в этой среде.

В мастере импорта выберите текущего пользователя или локальный компьютер.

Укажите доверенное корневое хранилище.



Если контейнер:
Добавьте .crt/.pem файл сертификата в системное хранилище внутри образа.

Пересоберите образ и перезапустите контейнер/сервис.



Например:
```python
COPY russian_trusted_root_ca.crt /usr/local/share/ca-certificates/
COPY russian_trusted_sub_ca.crt /usr/local/share/ca-certificates/
RUN update-ca-certificates
```

Для Node.js и Python внутри контейнера задайте переменные окружения при необходимости (если приложение не видит системные сертификаты):
```python
ENV NODE_EXTRA_CA_CERTS=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
```

Шаг 3. Проверьте HTTPS-соединение
После обновления убедитесь, что запросы к новому адресу проходят без ошибок SSL/TLS.
Например:
```python
curl -v -H "Authorization: " https://platform-api2.max.ru/me
```

Ожидаемый результат: SSL certificate verify ok

Шаг 4. Протестируйте сценарии

Проверьте работу ваших чат-ботов и мини-приложений: авторизацию, отправку и получение данных.
