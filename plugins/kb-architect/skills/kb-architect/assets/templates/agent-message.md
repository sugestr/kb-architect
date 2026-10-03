---
type: agent-message
message_id: <устойчивый уникальный идентификатор>
created_at: YYYY-MM-DDTHH:MM:SSZ
from_project: <проект/агент>
to_project: <проект/агент>
kind: <info | task | question | correction | reply>
reply_to: <message_id или пусто>
response_required: <true | false>
delivery_target: <точный inbox, project/thread id или имя владельца>
delivery_state: <prepared | delivered | acknowledged>
collector: <кто отвечает за внесение в канон адресата>
required_roles: <none | role ids, которые должен применить адресат>
role_coverage: <pending | covered | partial | unavailable>
evidence_receipt: <путь/id receipt либо none>
---

# Зачем это адресату

<Одно предложение: почему сообщение относится к его полномочиям или канону.>

## Дельта

- <Новый факт, источник, расхождение или риск. Не пересказ общего статуса.>

## Требуемое действие или вопрос

- <Конкретное действие/вопрос либо «нет».>

## Источники и вложения

- <Проверяемый адрес; неизвестное помечается TBD.>

## Граница полномочий

<Что разрешено сделать и что остаётся владельцу/другому проекту.>

## Покрытие ролями

<Какие роли применены; какой кусок остался вне scope; конфликт ролей не усреднять.>


Процедура и состояния доставки: `references/collaboration.md` → `messages`
установленного скилла. Поля заполняются по фактическому результату.
