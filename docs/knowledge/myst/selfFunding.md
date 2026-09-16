# Коробка платит сама за себя: что проверено для Mysterium

Разведка 2026-09-17 под задачу «коробка для всех без покупки крипты»: `home` раздаёт канал
(provider) и заработанным оплачивает свой выход (consumer). Образец модели — Deeper Connect
владельца (Deeper-Wire-HW, прошивка 2.0.6.h3): в его панели пункт «Майнинг» рядом с «DPN».

Исходники — node 1.39.5, клон в `/Volumes/Storage/Caches/mysterium/node-1.39.5`
(https://github.com/mysteriumnetwork/node/tree/1.39.5). Живые ответы — TequilAPI
`myst-consumer` на коробке (10.77.0.20:4050).

## Регистрация: бесплатной сейчас нет, кроме реферального токена

- Цена с живой ноды, `GET /v2/transactor/fees`: регистрация 0.0954 MYST, вывод заработка
  (settlement) 0.0436 MYST, `hermes_percent` 0.20.
- `GET /identities/{id}/eligibility` (consumer коробки) → `{"eligible": false}`;
  `GET /identities/provider/eligibility` (общий пул бесплатных регистраций provider) →
  `{"eligible": false}`. Первый запрос дал 500 с EOF от `transactor.mysterium.network` —
  таймаут ретранслятора, повтор прошёл. Путь `/transactor/identities/{id}/eligibility` из
  swagger отвечает 404: настоящий маршрут — `/identities/:id/eligibility`
  (`tequilapi/endpoints/transactor.go`, группа `/identities`).
- `canRegisterForFree` (`tequilapi/endpoints/transactor.go`): при `referral_token` в теле
  `POST /identities/{id}/register` нода сразу считает регистрацию бесплатной и шлёт
  `identity/register/referer` с `fee = 0` (`identity/registry/transactor.go`,
  `registerIdentityWithReferralToken`); примет ли токен транзактор — решает сервер.
  Без токена — только по `eligibility`, иначе платно.
- Откуда токены: реферальная программа приложения Mysterium VPN — новый пользователь с кодом
  получал бесплатную регистрацию (https://github.com/mysteriumnetwork/node/issues/3615, 2021,
  тестовая сеть — могло измениться); партнёрская программа https://affiliate.mysterium.network/ ;
  у MystNodes — реферал «друг заработал 5 MYST → обоим по 5 MYST»
  (https://help.mystnodes.com/en/articles/8836815-how-does-the-friend-referral-system-work).
  По справке MystNodes первая нода регистрируется бесплатно через их онбординг
  (https://blog.mystnodes.com/blog/introducing-clickboarding — в самой статье про цену ничего нет).
  **Не проверено**, даёт ли какая-то из программ токен проекту для раздачи коробкам.

## Куда уходит заработок provider

- Заработок копится обещаниями в hermes и выводится settlement'ом на `beneficiary`
  автоматически с 5 MYST (https://help.mystnodes.com/en/articles/8005144-where-do-i-check-and-withdraw-my-earnings).
- **В канал той же identity нельзя:** `validateBeneficiary`
  (`session/pingpong/hermes_promise_settler.go`) при `beneficiary`, равном собственному каналу,
  возвращает ошибку «payment channel … is set as beneficiary, skip settling» — вывод не идёт.
- `SettleIntoStake` переводит заработок в залог provider, а не в баланс — для оплаты выхода не годится.
- **В канал другой identity код не запрещает:** проверка сравнивает только с каналами своей
  identity (`isBenenficiarySetToChannel`). Канал consumer коробки — его `channel_address`, а
  пополнение consumer и есть перевод MYST на этот адрес (knowledge `consumer.md`). Значит
  `beneficiary` provider = `channel_address` consumer замыкает круг без биржи.
  **Не проверено исполнением**: нужен зарегистрированный provider с заработком.
- С каждого вывода уходит 0.0436 MYST плюс доля hermes; при автоматическом выводе в 5 MYST — около 1 %.

## Что осталось неизвестным

- Сколько зарабатывает домашняя нода (Ростелеком, двойной NAT) и хватает ли этого на её же
  трафик — измеряется только работающей нодой: `GET /node/provider/series/earnings`.
- Юридическая сторона: чужой трафик выходит с домашнего адреса владельца коробки.
- Первую регистрацию кто-то должен оплатить или получить по токену — порочный круг
  «нечем платить, пока не заработал».
