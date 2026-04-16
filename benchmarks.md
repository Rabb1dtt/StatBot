# Эталонные профили по позициям — система на доступных API-метриках

## Система оценки

### Доступные метрики и производные

Все значения нормируются **per 90 минут** через `minutesPlayed`. Минимум — 900 минут (10+ матчей).

**Ключевые вычислимые производные:**
- `npxG` = `expectedGoals` − `penaltyGoals` × 0.76 *(0.76 — среднее xG за пенальти в топ-5 лигах; вычитаем ожидаемый вклад пенальти из общего xG)*
- `npxG p90` = `npxG` / `minutesPlayed` × 90
- `Save %` = `saves` / (`saves` + `goalsConceded`) *(приближение: не учитывает удары мимо створа, но лучшее из доступного)*
- `Inside Box Save %` = `savedShotsFromInsideTheBox` / (`savedShotsFromInsideTheBox` + `goalsConcededInsideTheBox`)
- `xG/shot` = `expectedGoals` / `totalShots`
- `Shots on Target %` = `shotsOnTarget` / `totalShots`
- `Tackle Win %` = `tacklesWon` / `tackles`
- `xG+xA p90`, `G+A p90`, `Goals − xG` (перевыполнение)
- `Progressive Carry %` = `progressiveBallCarriesCount` / `ballCarriesCount` *(доля проносов, продвигающих мяч вперёд)*

### Метрики прогрессии и качества владения (per-match)

Эти метрики доступны в поматчевой статистике SofaScore и критически важны для оценки РЕАЛЬНОЙ полезности действий:

| API-поле | Что показывает | Ключ интерпретации |
|---|---|---|
| `progressiveBallCarriesCount` | Проносы мяча, продвигающие его ≥5м к чужим воротам | Высокое число = продвижение мяча; низкое + много `ballCarriesCount` = «пустые» проносы |
| `ballCarriesCount` | Все проносы мяча | Делитель для Progressive Carry % |
| `totalProgression` (м) | Общая прогрессивная дистанция (пасы + проносы) | Суммарный вклад в продвижение мяча |
| `totalProgressiveBallCarriesDistance` (м) | Дистанция только прогрессивных проносов | Качество проносов |
| `possessionLostCtrl` | Потери мяча (контролируемые) | ≥25 = тревога; вингер/AM может быть выше, но с поправкой на touches |
| `unsuccessfulTouch` | Неудачные касания | Технический брак под давлением |

**ПАТТЕРН «ПУСТОГО ДРИБЛИНГА»:** если `wonContest` высокий, но `progressiveBallCarriesCount` / `ballCarriesCount` < 30% и `possessionLostCtrl` > 20 — дриблинг не создаёт реальной угрозы. Игрок обводит в безопасных зонах и теряет мяч.

### Тепловая карта (per-match)

Из endpoint `/event/{id}/player/{id}/heatmap` приходит массив точек `{x, y}`:
- `x`: 0 = свои ворота, 100 = чужие ворота
- `y`: 0 = левый фланг, 100 = правый фланг

Вычисляемые зоны:
- **% в атакующей трети** (x ≥ 66): для нападающих и вингеров ожидается ≥ 55%
- **% в центре** (33 ≤ y < 66): для вингера > 25% = смещение с позиции, потеря ширины
- **Средняя позиция** (avg x, avg y): показывает реальную зону активности

### Физические метрики (per-match)

| API-поле | Что показывает | Примечание |
|---|---|---|
| `kilometersCovered` | Общий пробег (км) | Среднее в топ-5 лигах: 10.0–11.5 км |
| `numberOfSprints` | Количество спринтов | Вингер/FB ≥ 15, DM/CB ≥ 8 |
| `topSpeed` (км/ч) | Максимальная скорость | > 34 = элитный, > 32 = быстрый, < 30 = медленный |
| `metersCoveredSprintingKm` | Дистанция спринтов | Высокая = много рывков (вингер, FB) |
| `metersCoveredHighSpeedRunningKm` | Бег на высокой скорости | Ключ для оценки интенсивности |

### AI Value Scores (per-match, SofaScore)

SofaScore рассчитывает нормализованные оценки (0–1) по категориям:
- `dribbleValueNormalized`: ≥ 0.8 = выдающийся, 0.5–0.8 = хороший, < 0.3 = слабый
- `passValueNormalized`: ≥ 0.7 = отличный пасующий, < 0.3 = пассивный
- `shotValueNormalized`: ≥ 0.6 = опасный, < 0.2 = не угрожал
- `defensiveValueNormalized`: ≥ 0.5 = активный в обороне, < 0 = пассивный

### Уровни

| Уровень | Рейтинг | Описание |
|---|---|---|
| 🏆 Легенда | 9.0–10.0 | Пиковый сезон игрока мирового уровня |
| ⭐ Высокий | 7.5–8.9 | Твёрдый игрок основы топ-клуба |
| ✅ Средний | 6.0–7.4 | Добросовестный игрок топ-5 лиг |
| ⚠️ Слабый | < 6.0 | Ниже стандарта |

### Философия оценки

**РЕЗУЛЬТАТ ВАЖНЕЕ МЕТОДА.** Дриблинг, пасы, кроссы — это методы доставки. Голы, ассисты, xG+xA — это результат. Если игрок забивает 26 голов с 1.2 обводки p90 — дриблинг не проблема. Если делает 5 обводок p90 и 3 гола за сезон — обводки бесполезны.

**ПРОВЕРКА СИЛЫ СОПЕРНИКА.** Результат (голы, G+A) ОБЯЗАТЕЛЬНО проверяется по силе соперника:
- ТОП (1-4 место в топ-5 лиге) — стабильно результативен?
- СРЕДНИЙ (5-12 место) — не проседает?
- СЛАБЫЙ (13+ место или не из топ-5 лиги) — не набивает только на них?
- ЛЧ/кубки ≠ автоматически «топ»: Славия, Карабах, Копенгаген в ЛЧ — слабые соперники. Оценивай КОНКРЕТНОГО соперника, не название турнира.
Если 80% голов сделаны на слабых — это минус, даже если общая цифра красивая.

**КАЧЕСТВО УДАРА > КОЛИЧЕСТВО.** 3 точных удара с высокой конверсией >> 10 ударов в угловой флаг. xGOT − xG показывает размещение: положительный = бьёт точнее среднего.

### Веса влияния

| Влияние | Вес | Что входит |
|---|---|---|
| 🔴 Ключевые | 35–40% | Результат: голы, G+A, xG+xA (для атакующих). Определяют суть роли. |
| 🟠 Важные | 25–30% | Качество: конверсия, xGOT-xG, keyPasses, bigChances. Дифференцируют уровень. |
| 🟡 Средние | 20–25% | Метод: дриблинг, кроссы, прогрессия, зона активности. Дополняют профиль. |
| 🟢 Низкие | 10–15% | Контекст: физика, объём, вспомогательные метрики. |

**Штраф:** если ключевая метрика < 30th percentile позиционного пула — итоговый балл ×0.85.

***

## 1. Вратарь (GK)

**Эталоны:** 🏆 Alisson 2018–19 | ⭐ Ter Stegen пик | ✅ Медиана топ-5 | ⚠️ Ниже медианы

### 🔴 Ключевые метрики (40%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `saves` / (`saves` + `goalsConceded`) | Save % | ≥ 74% [^1] | 72–74% | 69–72% | < 65% |
| `savedShotsFromInsideTheBox` / (`savedShotsFromInsideTheBox` + `goalsConcededInsideTheBox`) | Inside Box Save % | ≥ 68% | 62–68% | 55–62% | < 55% |
| `cleanSheet` / `appearances` | Clean Sheet % | ≥ 50% [^2] | 40–50% | 30–40% | < 30% |

### 🟠 Важные метрики (25%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `highClaims` p90 | Перехваты крестов p90 | ≥ 1.5 | 1.0–1.5 | 0.6–1.0 | < 0.6 |
| `successfulRunsOut` / `runsOut` | Sweeper Success % | ≥ 80% | 70–80% | 60–70% | < 60% |
| `runsOut` p90 | Sweeper Actions p90 | ≥ 1.8 | 1.2–1.8 | 0.8–1.2 | < 0.8 |

### 🟡 Средние метрики (22%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `accuratePassesPercentage` | Pass Completion % | ≥ 72% | 62–72% | 52–62% | < 52% |
| `accurateLongBallsPercentage` | Long Pass % | ≥ 62% | 55–62% | 47–55% | < 47% |
| `saves` p90 | Saves p90 (контекст: много = команда пропускает) | ≥ 3.5 | 2.8–3.5 | 2.0–2.8 | < 2.0 |

### 🟢 Низкие метрики (13%)

| API-поле | Примечание |
|---|---|
| `penaltySave` / `penaltyFaced` | Малая выборка — высокая случайность |
| `crossesNotClaimed` p90 | Ошибки при крестах — штрафной маркер |
| `punches` p90 | Стилистический маркер |
| `goalsConcededInsideTheBox` p90 | Дополнительный бонус |

***

## 2. Центральный защитник (CB)

**Эталоны:** 🏆 Van Dijk 2018–19 | ⭐ Van Dijk 2024–25 | ✅ Типичный CB | ⚠️ Нестабильный CB

### 🔴 Ключевые метрики (38%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `aerialDuelsWonPercentage` | Aerial Duel Win % | ≥ 74% [^3] | 65–74% | 55–65% | < 50% |
| `aerialDuelsWon` p90 | Aerial Won p90 | ≥ 4.5 | 3.5–4.5 | 2.5–3.5 | < 2.5 |
| `tackles` + `interceptions` p90 | Tackles+Int p90 | ≥ 3.0 | 2.3–3.0 | 1.5–2.3 | < 1.5 |
| `errorLeadToShot` + `errorLeadToGoal` p90 | Errors p90 | ≤ 0.05 | 0.05–0.12 | 0.12–0.20 | > 0.20 |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `accuratePassesPercentage` | Pass Completion % | ≥ 92% [^4] | 88–92% | 82–88% | < 80% |
| `accurateLongBalls` p90 | Long Balls p90 | ≥ 5.0 | 3.5–5.0 | 2.0–3.5 | < 2.0 |
| `accurateLongBallsPercentage` | Long Ball % | ≥ 65% | 58–65% | 50–58% | < 50% |
| `ballRecovery` p90 | Ball Recoveries p90 | ≥ 7.0 | 5.0–7.0 | 3.5–5.0 | < 3.5 |

### 🟡 Средние метрики (22%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `clearances` p90 | Clearances p90 | ≥ 6.0 | 4.5–6.0 | 3.0–4.5 | < 3.0 |
| `outfielderBlocks` p90 | Blocks p90 | ≥ 1.2 | 0.8–1.2 | 0.5–0.8 | < 0.5 |
| `groundDuelsWonPercentage` | Ground Duel Win % | ≥ 70% | 62–70% | 54–62% | < 54% |
| `tacklesWonPercentage` | Tackle Win % | ≥ 70% | 62–70% | 52–62% | < 52% |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `fouls` p90 | ≤ 1.2 = дисциплина |
| `yellowCards`, `redCards` | Дисциплина |
| `xG` p90 (Understat) | Угроза со стандартов — бонус |
| `possessionWonAttThird` p90 | Прессинг в чужой зоне |
| `xGBuildup` p90 (Understat) | Вовлечённость в розыгрыш из глубины |

### 🟢 Физика (per-match, контекстная)

| API-поле | Ожидание CB | Тревога |
|---|---|---|
| `kilometersCovered` | ≥ 9.5 км | < 8.5 км |
| `topSpeed` | ≥ 30 км/ч | < 27 км/ч — медленный CB = проблема против контратак |

***

## 3А. Атакующий фланговый защитник (FB-Attack)

**Эталоны:** 🏆 TAA 2019–20 / Cancelo 2021–22 | ⭐ TAA 2024–25 | ✅ Типичный атак. FB | ⚠️ Без атак. вклада

### 🔴 Ключевые метрики (36%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `accurateFinalThirdPasses` p90 | Final Third Passes p90 | ≥ 8.0 [^5] | 5.0–8.0 | 3.0–5.0 | < 3.0 |
| `xA` p90 | xA p90 | ≥ 0.25 | 0.15–0.25 | 0.08–0.15 | < 0.08 |
| `accurateCrosses` p90 | Accurate Crosses p90 | ≥ 3.0 | 1.8–3.0 | 1.0–1.8 | < 1.0 |
| `accurateCrossesPercentage` | Cross Accuracy % | ≥ 35% | 28–35% | 22–28% | < 22% |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `assists` + `xA` p90 | Суммарный атак. вклад p90 | ≥ 0.35 | 0.22–0.35 | 0.12–0.22 | < 0.12 |
| `successfulDribbles` p90 | Dribbles p90 | ≥ 1.8 | 1.2–1.8 | 0.7–1.2 | < 0.7 |
| `groundDuelsWonPercentage` | Ground Duel Win % | ≥ 62% | 55–62% | 48–55% | < 48% |
| `keyPasses` p90 | Key Passes p90 | ≥ 1.8 | 1.2–1.8 | 0.7–1.2 | < 0.7 |

### 🟡 Средние метрики (24%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `tackles` + `interceptions` p90 | Tackles+Int p90 | ≥ 3.0 | 2.2–3.0 | 1.5–2.2 | < 1.5 |
| `accuratePassesPercentage` | Pass Completion % | ≥ 82% | 78–82% | 73–78% | < 73% |
| `bigChancesCreated` p90 | Big Chances Created p90 | ≥ 0.25 | 0.15–0.25 | 0.08–0.15 | < 0.08 |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `aerialDuelsWonPercentage` | Ситуативно при навесах соперника |
| `xG` p90 | Голевая угроза — бонус для инвертированного FB |
| `fouls` p90 | Дисциплина |
| `xGBuildup` p90 (Understat) | Вовлечённость в розыгрыш |

### 🟢 Качество и физика (контекстная)

| API-поле | Хорошо | Тревога |
|---|---|---|
| `progressiveBallCarriesCount` / `ballCarriesCount` | ≥ 30% | < 20% — атак. FB должен продвигать мяч |
| `possessionLostCtrl` p90 | ≤ 14 | > 20 |
| `kilometersCovered` | ≥ 10.5 км | < 9.5 км — FB-A один из самых бегущих |
| `numberOfSprints` | ≥ 18 | < 12 |
| `topSpeed` | ≥ 32 км/ч | < 29 км/ч |

***

## 3Б. Оборонительный/сбалансированный фланговый защитник (FB-Defense)

**Эталоны:** 🏆 Kyle Walker 2018–23 | ⭐ Walker 2023–24 | ✅ Стандартный обор. FB | ⚠️ Медленный, слабый в дуэлях

### 🔴 Ключевые метрики (40%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `totalDuelsWonPercentage` | Total Duel Win % | ≥ 65% | 60–65% | 52–60% | < 52% |
| `tackles` p90 | Tackles p90 | ≥ 2.5 | 2.0–2.5 | 1.5–2.0 | < 1.5 |
| `aerialDuelsWonPercentage` | Aerial Win % | ≥ 60% [^6] | 55–60% | 48–55% | < 48% |
| `tacklesWonPercentage` | Tackle Win % | ≥ 72% | 64–72% | 55–64% | < 55% |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `interceptions` p90 | Interceptions p90 | ≥ 1.8 | 1.3–1.8 | 0.8–1.3 | < 0.8 |
| `clearances` p90 | Clearances p90 | ≥ 4.5 | 3.5–4.5 | 2.5–3.5 | < 2.5 |
| `ballRecovery` p90 | Ball Recoveries p90 | ≥ 6.5 | 5.0–6.5 | 3.5–5.0 | < 3.5 |
| `groundDuelsWonPercentage` | Ground Duel Win % | ≥ 65% | 58–65% | 50–58% | < 50% |

### 🟡 Средние метрики (22%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `accuratePassesPercentage` | Pass Completion % | ≥ 88% [^7] | 83–88% | 78–83% | < 78% |
| `accurateCrosses` p90 | Accurate Crosses p90 | ≥ 1.5 | 1.0–1.5 | 0.5–1.0 | < 0.5 |
| `successfulDribbles` p90 | Dribbles p90 | ≥ 1.0 | 0.7–1.0 | 0.4–0.7 | < 0.4 |

### 🟢 Низкие метрики (10%)

| API-поле | Примечание |
|---|---|
| `xA` p90 | Атакующий вклад — бонус |
| `fouls` p90 | Дисциплина при агрессивном прессинге |

### 🟢 Физика (per-match, контекстная)

| API-поле | Ожидание FB-D | Тревога |
|---|---|---|
| `kilometersCovered` | ≥ 10.0 км | < 9.0 км |
| `numberOfSprints` | ≥ 15 | < 10 |
| `topSpeed` | ≥ 33 км/ч | < 30 км/ч — скорость критична для обор. FB |

***

## 4. Опорный полузащитник (DM/CDM)

**Эталоны:** 🏆 Rodri 2023–24 | ⭐ Ugarte 2023–24 | ✅ Ndidi уровень | ⚠️ Ниже стандарта

> **Контекстная поправка:** Rodri играет в системе ~65% владения — его `tackles` p90 (~2.2) ниже чем у Угарте (~4.7). Это норма стиля. Для определения стиля: если `accuratePassesPercentage` ≥ 90% и `ballRecovery` p90 ≥ 9.0 — команда владения (нижний порог tackles). Иначе — прессинг-система (верхний порог).[^8][^9]

### 🔴 Ключевые метрики (40%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `accuratePassesPercentage` | Pass Completion % | ≥ 92% [^8] | 88–92% | 84–88% | < 82% |
| `tackles` + `interceptions` p90 | Tackles+Int p90 (см. контекст выше) | ≥ 5.0 (пресс.) / ≥ 3.0 (влад.) | 3.5–5.0 | 2.2–3.5 | < 2.2 |
| `tacklesWonPercentage` | Tackle Win % | ≥ 68% | 60–68% | 52–60% | < 52% |
| `ballRecovery` p90 | Ball Recoveries p90 | ≥ 10.0 [^8] | 7.5–10.0 | 5.5–7.5 | < 5.5 |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `accurateFinalThirdPasses` p90 | Final Third Passes p90 | ≥ 6.0 | 4.0–6.0 | 2.5–4.0 | < 2.5 |
| `accurateLongBalls` p90 | Long Balls p90 | ≥ 5.0 | 3.5–5.0 | 2.0–3.5 | < 2.0 |
| `possessionWonAttThird` p90 | Press Won in Att. 3rd p90 | ≥ 1.5 | 1.0–1.5 | 0.5–1.0 | < 0.5 |
| `aerialDuelsWonPercentage` | Aerial Win % | ≥ 58% | 50–58% | 42–50% | < 42% |

### 🟡 Средние метрики (20%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `xA` p90 | xA p90 | ≥ 0.15 | 0.08–0.15 | 0.03–0.08 | < 0.03 |
| `fouls` p90 | Fouls p90 | ≤ 1.2 | 1.2–1.8 | 1.8–2.5 | > 2.5 |
| `totalDuelsWonPercentage` | Total Duel Win % | ≥ 60% | 54–60% | 47–54% | < 47% |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `xG` p90 | Голевой вклад не приоритет |
| `touches` p90 | Объём касаний — косвенный маркер активности |
| `yellowCards` | Дисциплина |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |
| `xGBuildup` p90 (Understat) | Роль в розыгрыше до момента удара |

### 🟢 Качество владения и физика (контекстная)

| API-поле | Хорошо | Тревога |
|---|---|---|
| `possessionLostCtrl` p90 | ≤ 12 | > 18 — для опорника потери критичны |
| `totalProgression` (match) | ≥ 180 | < 100 |
| `kilometersCovered` | ≥ 10.5 км | < 9.5 км — DM покрывает максимум площади |
| `numberOfSprints` | ≥ 10 | < 6 |

***

## 5. Центральный полузащитник / Восьмёрка (CM)

**Эталоны:** 🏆 Modrić пик / Pedri 2023–24 | ⭐ Pedri/Gavi | ✅ Henderson 2019–20 | ⚠️ Ротационный CM

### 🔴 Ключевые метрики (35%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `keyPasses` p90 | Key Passes p90 | ≥ 2.0 [^10] | 1.5–2.0 | 1.0–1.5 | < 1.0 |
| `xG` + `xA` p90 | xG+xA p90 | ≥ 0.35 | 0.25–0.35 | 0.15–0.25 | < 0.15 |
| `accurateFinalThirdPasses` p90 | Final Third Passes p90 | ≥ 8.0 | 6.0–8.0 | 4.0–6.0 | < 4.0 |

### 🟠 Важные метрики (30%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `tackles` + `interceptions` p90 | Tackles+Int p90 | ≥ 3.5 | 2.5–3.5 | 1.5–2.5 | < 1.5 |
| `bigChancesCreated` p90 | Big Chances Created p90 | ≥ 0.30 | 0.18–0.30 | 0.08–0.18 | < 0.08 |
| `accuratePassesPercentage` | Pass Completion % | ≥ 90% | 86–90% | 82–86% | < 80% |
| `successfulDribbles` p90 | Dribbles p90 | ≥ 1.5 | 1.0–1.5 | 0.6–1.0 | < 0.6 |

### 🟡 Средние метрики (23%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `accurateOppositionHalfPasses` p90 | Opp. Half Passes p90 | ≥ 20 | 15–20 | 10–15 | < 10 |
| `ballRecovery` p90 | Ball Recoveries p90 | ≥ 7.5 | 5.5–7.5 | 4.0–5.5 | < 4.0 |
| `aerialDuelsWonPercentage` | Aerial Win % | ≥ 50% | 44–50% | 37–44% | < 37% |
| `fouls` p90 | Fouls p90 | ≤ 1.2 | 1.2–1.8 | 1.8–2.5 | > 2.5 |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `wasFouled` p90 | Зарабатывание штрафных |
| `totalShots` p90 | Угроза из средней зоны |
| `dispossessed` p90 | Потери под давлением — обратная метрика |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки — маркер «двигателя» |
| `xGBuildup` p90 (Understat) | Роль в розыгрыше до удара |

### 🟢 Качество владения и физика (контекстная)

| API-поле | Хорошо | Тревога |
|---|---|---|
| `possessionLostCtrl` p90 | ≤ 15 | > 22 |
| `totalProgression` (match) | ≥ 200 | < 120 |
| `kilometersCovered` | ≥ 10.5 км | < 9.0 км — CM должен покрывать большую площадь |
| `numberOfSprints` | ≥ 12 | < 8 |

***

## 6А. Атакующий полузащитник — Плеймейкер (AM / CAM — KDB-профиль)

**Эталоны:** 🏆 KDB 2019–20 (рекорд АПЛ[^11]) | ⭐ Cole Palmer 2024–25 | ✅ Bruno Fernandes типичный | ⚠️ AM без стабильного создания

### 🔴 Ключевые метрики (38%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `keyPasses` p90 | Key Passes p90 | ≥ 3.5 [^11] | 1.8–3.5 | 1.2–1.8 | < 1.0 |
| `xA` p90 | xA p90 | ≥ 0.35 | 0.20–0.35 | 0.12–0.20 | < 0.10 |
| `xG` p90 | xG p90 | ≥ 0.25 | 0.18–0.25 | 0.10–0.18 | < 0.10 |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `bigChancesCreated` p90 | Big Chances Created p90 | ≥ 0.45 | 0.28–0.45 | 0.15–0.28 | < 0.15 |
| `assists` / season | Assists / сезон | ≥ 18 [^11] | 10–18 [^12] | 5–10 | < 5 |
| `accurateFinalThirdPasses` p90 | Final Third Passes p90 | ≥ 9.0 | 6.5–9.0 | 4.0–6.5 | < 4.0 |
| `successfulDribbles` p90 | Dribbles p90 | ≥ 2.0 | 1.5–2.0 | 1.0–1.5 | < 1.0 |

### 🟡 Средние метрики (22%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `accuratePassesPercentage` | Pass Completion % | ≥ 85% | 79–85% | 72–79% | < 72% |
| `shotsOnTarget` p90 | Shots on Target p90 | ≥ 1.2 | 0.9–1.2 | 0.6–0.9 | < 0.6 |
| `passToAssist` p90 | Pre-Assist p90 | ≥ 0.50 | 0.30–0.50 | 0.15–0.30 | < 0.15 |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `tackles` + `interceptions` p90 | Оборона при высоком прессинге |
| `wasFouled` p90 | Зарабатывание штрафных |
| `totalAttemptAssist` p90 | Объём ассист-попыток (дополняет `xA`) |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |
| `xGBuildup` p90 (Understat) | Роль в розыгрыше до удара |

### 🟢 Качество владения (контекстная)

| API-поле | Хорошо | Тревога |
|---|---|---|
| `possessionLostCtrl` p90 | ≤ 18 | > 25 |
| `totalProgression` (match) | ≥ 200 | < 120 |

***

## 6Б. Атакующий полузащитник — Дриблёр (AM / CAM — Neymar-профиль)

**Эталоны:** 🏆 Neymar 2016–18 (28Г+17А в 28 матчах[^14], xA 0.40 p90[^13]) | ⭐ Neymar 2014–15 | ✅ Дриблёр-десятка середняка | ⚠️ Без стабильного влияния

### 🔴 Ключевые метрики — РЕЗУЛЬТАТ (38%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `xG` + `xA` p90 | xG+xA p90 | ≥ 0.70 | 0.48–0.70 | 0.30–0.48 | < 0.30 |
| `goals` + `assists` / season | G+A / сезон | ≥ 40 [^15] | 28–40 | 18–28 | < 18 |
| `xA` p90 | xA p90 | ≥ 0.30 [^13] | 0.20–0.30 | 0.12–0.20 | < 0.12 |

### 🟠 Важные метрики — КАЧЕСТВО И ДРИБЛИНГ (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `successfulDribbles` p90 | Dribbles p90 | ≥ 5.0 [^13] | 3.5–5.0 | 2.0–3.5 | < 2.0 |
| `successfulDribblesPercentage` | Dribble Success % | ≥ 60% | 52–60% | 44–52% | < 44% |
| `keyPasses` p90 | Key Passes p90 | ≥ 2.5 | 1.8–2.5 | 1.2–1.8 | < 1.2 |
| `wasFouled` p90 | Was Fouled p90 | ≥ 4.0 | 2.5–4.0 | 1.5–2.5 | < 1.5 |

### 🟡 Средние метрики — КАЧЕСТВО УДАРА И МЕТОД (22%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `shotsOnTarget` p90 | Shots on Target p90 | ≥ 2.0 | 1.4–2.0 | 0.9–1.4 | < 0.9 |
| `bigChancesCreated` p90 | Big Chances p90 | ≥ 0.35 | 0.22–0.35 | 0.12–0.22 | < 0.12 |
| `dispossessed` p90 | Dispossessed p90 (меньше = лучше) | ≤ 1.5 | 1.5–2.2 | 2.2–3.0 | > 3.0 |

### 🟡 Качество и прогрессия (включено в 22%)

| API-поле | Хорошо | Тревога | Как читать |
|---|---|---|---|
| `progressiveBallCarriesCount` / `ballCarriesCount` | ≥ 35% | < 25% | Ключевой индикатор: обводит ли вперёд или «в пустую» |
| `possessionLostCtrl` p90 | ≤ 20 | > 28 | Дриблёр теряет чаще, но > 28 = расточительно |
| `totalProgression` (match) | ≥ 200 | < 120 | Суммарное продвижение мяча |

⚠️ **ПАТТЕРН «ПУСТОГО ДРИБЛИНГА»:** высокий wonContest + Progressive Carry% < 25% + possessionLostCtrl > 28 = обводит без угрозы. Минус к оценке.

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `tackles` + `interceptions` p90 | Оборонительная работа |
| `aerialDuelsWonPercentage` | Как правило, не приоритет |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |

### 🟢 Физика (per-match)

| API-поле | Ожидание AM-D | Тревога |
|---|---|---|
| `kilometersCovered` | ≥ 9.5 км | < 8.0 км |
| `numberOfSprints` | ≥ 12 | < 8 |
| `topSpeed` | ≥ 31 км/ч | контекстно |

***

## 7. Вингер (W / WF)

**Эталоны:**
- 🏆 Ronaldo 2017–18: 26 голов Ла Лига + 15 ЛЧ, 1.22 обводки p90 — результат без объёма дриблинга[^18]
- 🏆 Messi 2011–12: 1.76 G+A p90, 73 гола — абсолютный результат[^16][^17]
- 🏆 Olise 2025–26: 12Г+18А Бундеслига — обводка у штрафной → удар в девятку
- ⭐ Vinícius 2023–24 | ✅ Salah 2024–25 | ⚠️ Без стабильного влияния

### 🔴 Ключевые метрики — РЕЗУЛЬТАТ (37%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `goals` p90 | Goals p90 | ≥ 0.80 | 0.50–0.80 | 0.28–0.50 | < 0.28 |
| `goals` + `assists` p90 | G+A p90 | ≥ 1.20 [^17] | 0.55–1.20 | 0.28–0.55 | < 0.28 |
| `xG` + `xA` p90 | xG+xA p90 | ≥ 0.80 | 0.50–0.80 | 0.28–0.50 | < 0.28 |
| `npxG` p90 | npxG p90 | ≥ 0.70 | 0.45–0.70 | 0.25–0.45 | < 0.25 |

### 🟠 Важные метрики — КАЧЕСТВО УДАРА И СОЗДАНИЕ (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `goalConversionPercentage` | Goal Conversion % | ≥ 22% | 16–22% | 10–16% | < 10% |
| `shotsOnTarget` / `totalShots` | Shot on Target % | ≥ 45% | 38–45% | 30–38% | < 30% |
| `keyPasses` p90 | Key Passes p90 | ≥ 2.3 [^16] | 1.5–2.3 | 1.0–1.5 | < 1.0 |
| `bigChancesCreated` p90 | Big Chances p90 | ≥ 0.40 | 0.25–0.40 | 0.12–0.25 | < 0.12 |

### 🟡 Средние метрики — МЕТОД (дриблинг, прогрессия, зона) (23%)

Дриблинг — МЕТОД доставки, не результат. Высокие обводки без голов = пусто. Мало обводок + много голов = эффективно.

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `successfulDribbles` p90 | Dribbles p90 | ≥ 3.8 [^16] | 2.5–3.8 | 1.5–2.5 | < 1.5 |
| `successfulDribblesPercentage` | Dribble Success % | ≥ 58% | 50–58% | 42–50% | < 42% |
| `accurateCrossesPercentage` | Cross Accuracy % | ≥ 35% | 28–35% | 20–28% | < 20% |
| `wasFouled` p90 | Was Fouled p90 | ≥ 3.5 | 2.0–3.5 | 1.2–2.0 | < 1.2 |

### 🟡 Качество и прогрессия (включено в 23%)

| API-поле | Производная | Хорошо | Тревога | Как читать |
|---|---|---|---|---|
| `progressiveBallCarriesCount` / `ballCarriesCount` | Progressive Carry % | ≥ 35% | < 25% | Низкий % + много обводок = «пустой дриблинг» |
| `possessionLostCtrl` p90 | Possession Lost p90 | ≤ 18 | > 25 | Поправка: у топ-вингера больше touches → больше потерь |
| `totalProgression` (match) | Прогрессия, метры | ≥ 250 | < 150 | Суммарное продвижение мяча (пасы + проносы) |

⚠️ **ПАТТЕРН «ПУСТОГО ДРИБЛИНГА»:** высокий wonContest + Progressive Carry% < 25% + possessionLostCtrl > 20 = обводит в безопасных зонах без угрозы. Минус к оценке.

### 🟡 Позиционирование — тепловая карта (per-match)

| Зона | Ожидание для W | Тревога |
|---|---|---|
| % в атакующей трети (x ≥ 66) | ≥ 55% | < 40% — слишком глубоко |
| % на своём фланге (left или right) | ≥ 60% | < 45% — покидает фланг |
| % в центре (33 ≤ y < 66) | ≤ 25% | > 35% — забирает ширину у команды |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `dispossessed` p90 | Потери — обратная метрика |
| `aerialDuelsWonPercentage` | Редко значимо для вингера |
| `fouls` p90 | Дисциплина при потере |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |
| `xGBuildup` p90 (Understat) | Участие в розыгрыше до момента удара |
| `accurateFinalThirdPasses` p90 | Пасы в финальную треть — продвижение мяча |

### 🟢 Физика (per-match, контекстная)

| API-поле | Ожидание W | Тревога |
|---|---|---|
| `kilometersCovered` | ≥ 10.0 км | < 8.5 км |
| `numberOfSprints` | ≥ 15 | < 10 |
| `topSpeed` | ≥ 32 км/ч | < 29 км/ч |

***

## 8А. Центральный нападающий — Чистый финишёр (ST Pure)

**Эталоны:** 🏆 Haaland 2022–23 (36 голов — рекорд АПЛ[^21]) | ⭐ Haaland 2025–26 | ✅ Качественный ST | ⚠️ Низкая реализация

### 🔴 Ключевые метрики (40%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `npxG` p90 | npxG p90 | ≥ 0.80 [^22] | 0.55–0.80 | 0.35–0.55 | < 0.25 |
| `goals` p90 | Goals p90 | ≥ 0.90 [^21] | 0.60–0.90 | 0.35–0.60 | < 0.25 |
| `goals` / `expectedGoals` | Goals/xG ratio | ≥ 1.10 | 0.95–1.10 | 0.80–0.95 | < 0.75 |
| `goalConversionPercentage` | Goal Conversion % | ≥ 22% | 16–22% | 10–16% | < 8% |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `shotsOnTarget` / `totalShots` | Shot on Target % | ≥ 47% [^23] | 40–47% | 33–40% | < 30% |
| `shotsFromInsideTheBox` p90 | Inside Box Shots p90 | ≥ 3.5 | 2.5–3.5 | 1.5–2.5 | < 1.5 |
| `aerialDuelsWonPercentage` | Aerial Win % | ≥ 58% | 50–58% | 42–50% | < 42% |
| `totalDuelsWonPercentage` | Total Duel Win % | ≥ 58% | 50–58% | 42–50% | < 42% |

### 🟡 Средние метрики (20%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `goalsFromInsideTheBox` / `goals` | % голов из штрафной | ≥ 88% | 80–88% | 72–80% | < 72% |
| `offsides` p90 | Offsides p90 (ниже = точнее откр.) | ≤ 1.5 | 1.5–2.2 | 2.2–3.0 | > 3.0 |
| `bigChancesMissed` p90 | BCM p90 (меньше = лучше) | ≤ 0.30 | 0.30–0.50 | 0.50–0.80 | > 0.80 |

### 🟡 Качество и прогрессия (включено в 20%)

| API-поле | Хорошо | Тревога | Как читать |
|---|---|---|---|
| `possessionLostCtrl` p90 | ≤ 12 | > 18 | ST-P теряет реже — меньше touches |
| `totalProgression` (match) | ≥ 80 | < 40 | ST-P не обязан продвигать, но рывки за спину дают прогрессию |

### 🟡 Позиционирование — тепловая карта (per-match)

| Зона | Ожидание для ST-P | Тревога |
|---|---|---|
| % в атакующей трети (x ≥ 66) | ≥ 65% | < 50% — слишком глубоко, не в штрафной |
| % в центре (33 ≤ y < 66) | ≥ 50% | < 30% — слишком фланговый для финишёра |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `xA` p90 | Голевые передачи — важны для ложной 9-ки, бонус для ST |
| `headedGoals` / `goals` | Воздушная угроза в % от всех голов |
| `hitWoodwork` | Косвенный маркер остроты |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |

### 🟢 Физика (per-match)

| API-поле | Ожидание ST-P | Тревога |
|---|---|---|
| `numberOfSprints` | ≥ 10 | < 6 — не делает рывков |
| `topSpeed` | ≥ 30 км/ч | контекстно (Haaland ~35, Giroud ~28) |

***

## 8Б. Центральный нападающий — Плеймейкер (ST Link-up / Kane-профиль)

**Эталоны:** 🏆 Kane 2023–24 Bayern (xA 0.23 p90, 36 шансов за 26 матчей[^24][^25]) | ⭐ Kane 2021–22 Tottenham | ✅ Хороший link-up CF | ⚠️ CF без паса

### 🔴 Ключевые метрики (36%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `npxG` p90 | npxG p90 | ≥ 0.55 | 0.40–0.55 | 0.25–0.40 | < 0.20 |
| `xA` p90 | xA p90 | ≥ 0.23 [^25] | 0.15–0.23 | 0.08–0.15 | < 0.08 |
| `goals` + `assists` p90 | G+A p90 | ≥ 1.0 | 0.70–1.0 | 0.45–0.70 | < 0.35 |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `keyPasses` p90 | Key Passes p90 | ≥ 1.5 | 1.0–1.5 | 0.6–1.0 | < 0.6 |
| `bigChancesCreated` p90 | Big Chances Created p90 | ≥ 0.28 | 0.18–0.28 | 0.08–0.18 | < 0.08 |
| `accuratePassesPercentage` | Pass Completion % | ≥ 82% | 78–82% | 73–78% | < 72% |
| `aerialDuelsWonPercentage` | Aerial Win % | ≥ 55% | 50–55% | 44–50% | < 44% |

### 🟡 Средние метрики (24%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `shotsOnTarget` / `totalShots` | Shot on Target % | ≥ 45% | 38–45% | 32–38% | < 32% |
| `goalConversionPercentage` | Goal Conversion % | ≥ 18% | 13–18% | 8–13% | < 8% |
| `totalDuelsWonPercentage` | Total Duel Win % | ≥ 55% | 48–55% | 42–48% | < 42% |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `offsides` p90 | Ниже чем у pure ST — играет глубже |
| `passToAssist` p90 | Pre-assist цепочки |
| `wasFouled` p90 | Зарабатывание штрафных |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |
| `xGBuildup` p90 (Understat) | Роль в розыгрыше — ключевой маркер link-up |

### 🟡 Качество и прогрессия (включено в 24%)

| API-поле | Хорошо | Тревога | Как читать |
|---|---|---|---|
| `progressiveBallCarriesCount` / `ballCarriesCount` | ≥ 30% | < 20% | ST-L опускается за мячом → проносы должны быть прогрессивными |
| `possessionLostCtrl` p90 | ≤ 15 | > 22 | Больше чем у ST-P из-за link-up, но меньше чем у AM |
| `totalProgression` (match) | ≥ 150 | < 80 | Выше чем у ST-P — продвигает мяч пасами и проносами |

### 🟡 Позиционирование — тепловая карта (per-match)

| Зона | Ожидание для ST-L | Тревога |
|---|---|---|
| % в атакующей трети (x ≥ 66) | ≥ 45% | < 30% — слишком глубоко для CF |
| % в средней трети (33-66) | 25–45% | > 50% — играет как CM, не CF |

### 🟢 Физика (per-match)

| API-поле | Ожидание ST-L | Примечание |
|---|---|---|
| `kilometersCovered` | ≥ 9.5 км | Link-up CF бегает больше, чем pure ST |
| `numberOfSprints` | ≥ 8 | Меньше чем у W, но рывки для открываний |

***

## Матрица профилей и API-приоритеты

| Позиция | Профиль | Ключевые API-поля | Качественные индикаторы |
|---|---|---|---|
| GK | Вратарь | `saves`, `cleanSheet`, `runsOut`, `highClaims`, `goalsConceded` | — |
| CB | Защитник | `aerialDuelsWonPercentage`, `tackles`, `interceptions`, `clearances`, `errorLeadToShot` | `topSpeed`, `km` |
| FB-A | Атак. фланг | `accurateFinalThirdPasses`, `xA`, `accurateCrosses`, `keyPasses` | `progCarry%`, `possLost`, `km`, `sprints`, `topSpeed` |
| FB-D | Обор. фланг | `totalDuelsWonPercentage`, `tackles`, `aerialDuelsWonPercentage`, `clearances` | `topSpeed`, `sprints` |
| DM | Опорник | `accuratePassesPercentage`, `ballRecovery`, `tackles`+`interceptions`, `accurateFinalThirdPasses` | `possLost`, `progression`, `km` |
| CM | Восьмёрка | `keyPasses`, `xG`+`xA`, `accurateFinalThirdPasses`, `tackles`+`interceptions` | `possLost`, `progression`, `km`, `sprints` |
| AM-P | Пасовщик | `keyPasses`, `xA`, `bigChancesCreated`, `accurateFinalThirdPasses` | `possLost`, `progression` |
| AM-D | Дриблёр | `xG`+`xA`, `G+A`, `xA`, `successfulDribbles`, `keyPasses` | `progCarry%`, `possLost`, `progression` |
| W | Вингер | `goals`, `G+A`, `xG`+`xA`, `npxG`, `goalConversion%`, `keyPasses` | `progCarry%`, `possLost`, `heatmap (фланг%)`, `sprints`, `topSpeed` |
| ST-P | Финишёр | `npxG`, `goals`/`xG`, `goalConversionPercentage`, `shotsOnTarget`% | `heatmap (атак.треть%)`, `sprints` |
| ST-L | Плеймейкер CF | `npxG`, `xA`, `keyPasses`, `bigChancesCreated`, `accuratePassesPercentage` | `progCarry%`, `possLost`, `progression`, `km` |

***

## Вычислимые производные — формулы

```
npxG           = expectedGoals - (penaltyGoals × 0.76)
                 // 0.76 — среднее xG за пенальти в топ-5 лигах.
                 // Вычитаем ожидаемый вклад пенальти из общего xG.
npxG_p90       = npxG / minutesPlayed × 90
Save_pct       = saves / (saves + goalsConceded)
                 // Приближение: не учитывает удары мимо створа.
InsideBox_Save = savedShotsFromInsideTheBox / (savedShotsFromInsideTheBox + goalsConcededInsideTheBox)
xG_per_shot    = expectedGoals / totalShots
SoT_pct        = shotsOnTarget / totalShots
tackle_win_pct = tacklesWon / tackles
xGxA_p90       = (expectedGoals + expectedAssists) / minutesPlayed × 90
GA_p90         = (goals + assists) / minutesPlayed × 90
Goals_minus_xG = goals - expectedGoals   // перевыполнение/недовыполнение
dribble_pct    = successfulDribbles / totalContest
long_ball_pct  = accurateLongBalls / totalLongBalls
cross_pct      = accurateCrosses / totalCross
prog_carry_pct = progressiveBallCarriesCount / ballCarriesCount   // per-match
poss_lost_p90  = possessionLostCtrl / minutesPlayed × 90          // per-match (или possessionLost для сезона)
```

---

## References

[^1]: [Alisson saving points in Liverpool's title bid](https://www.premierleague.com/en/news/1197918)
[^2]: [Five years of Alisson Becker — Liverpool FC](https://www.liverpoolfc.com/news/first-team/461691-five-years-of-alisson-becker-trophies-big-saves-and-that-unforgettable-header)
[^3]: [Van Dijk dominating centre backs — Anfield Watch](https://anfieldwatch.co.uk/virgil-van-dijk-is-still-dominating-when-compared-to-other-premier-league-centre-backs/)
[^4]: [Van Dijk Career statistics — FootballCritic](https://www.footballcritic.com/virgil-van-dijk/career-stats/16233)
[^5]: [How Cancelo became Man City's most important player](https://www.premierleague.com/news/2355130)
[^6]: [Kyle Walker Stats 2025/2026](https://one-versus-one.com/en/players/Kyle-Walker-368)
[^7]: [Kyle Walker Season Stats — OneFootball](https://onefootball.com/en/player/kyle-walker-3147/stats)
[^8]: [Rodri Career statistics — FootballCritic](https://www.footballcritic.com/rodri/career-stats/97027)
[^9]: [Rodri Stats for 2024 Ballon d'Or — SI](https://www.si.com/soccer/rodri-stats-for-2024-ballon-d-or-why-the-man-city-midfielder-won)
[^10]: [Pedri Stats 2025/2026](https://one-versus-one.com/en/players/Pedri-53386)
[^11]: [Most Key Passes Per 90 In A Season — StatMuse](https://www.statmuse.com/fc/ask/most-key-passes-per-90-in-a-season?l=pl)
[^12]: [Cole Palmer 2024/25 season stats](https://www.facebook.com/DAZNFootball/posts/730371776418510/)
[^13]: [Neymar Stats — FootyStats](https://footystats.org/players/brazil/neymar)
[^14]: [PSG Neymar vs Barcelona Neymar](https://www.footballtransfers.com/en/transfer-news/2020/12/psg-neymar-vs-barcelona-neymar-the-stats)
[^15]: [Neymar Jr Stats for Barcelona](https://www.facebook.com/SportPremiHQ/posts/743928438140681/)
[^16]: [Leo Messi's Insane 2012](https://www.thefootballnotebook.com/post/leo-messi-s-insane-2012)
[^17]: [73 Goals in 60 Games: Remembering the Season of Messi](https://theanalyst.com/articles/lionel-messi-barcelona-73-goal-2011-12-season)
[^18]: [Cristiano Ronaldo stats in 2007/08 season](https://www.facebook.com/100087124711323/posts/880695484844601/)
[^19]: [Ronaldo Statistical Masterclass 2008](https://explore.st-aug.edu/exp/in-2008-cristiano-ronaldo-wrote-his-name-in-history-with-a-statistical-masterclass)
[^20]: [Who's the better player? — BigSoccer](https://www.bigsoccer.com/threads/who%E2%80%99s-the-better-player.2111012/)
[^21]: [How Many Goals Has Haaland Scored? — Opta Analyst](https://theanalyst.com/articles/how-many-goals-has-erling-haaland-scored-in-2022-23)
[^22]: [Haaland npxG Per 90 — StatMuse](https://www.statmuse.com/fc/ask/haaland-npxg-per-90-premier-league)
[^23]: [Haaland xG Per 90 22/23 — StatMuse](https://www.statmuse.com/fc/ask?q=Erling+Haaland+xg+per+90+22%2F23)
[^24]: [Harry Kane — FotMob](https://www.fotmob.com/players/194165/harry-kane)
[^25]: [Harry Kane Stats — FootyStats](https://footystats.org/players/england/harry-kane)
