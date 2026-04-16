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

### Уровни

| Уровень | Рейтинг | Описание |
|---|---|---|
| 🏆 Легенда | 9.0–10.0 | Пиковый сезон игрока мирового уровня |
| ⭐ Высокий | 7.5–8.9 | Твёрдый игрок основы топ-клуба |
| ✅ Средний | 6.0–7.4 | Добросовестный игрок топ-5 лиг |
| ⚠️ Слабый | < 6.0 | Ниже стандарта |

### Веса влияния

| Влияние | Вес | API-поля |
|---|---|---|
| 🔴 Ключевые | 35–40% | Определяют суть роли |
| 🟠 Важные | 25–30% | Сильно дифференцируют уровень |
| 🟡 Средние | 20–25% | Дополняют профиль |
| 🟢 Низкие | 10–15% | Стиль, нюансы |

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

***

## 6Б. Атакующий полузащитник — Дриблёр (AM / CAM — Neymar-профиль)

**Эталоны:** 🏆 Neymar 2016–18 (xA 0.40 p90[^13]; 28Г+17А в 28 матчах[^14]) | ⭐ Neymar 2014–15 | ✅ Дриблёр-десятка середняка | ⚠️ Без стабильного влияния

### 🔴 Ключевые метрики (38%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `successfulDribbles` p90 | Dribbles p90 | ≥ 5.0 [^13] | 3.5–5.0 | 2.0–3.5 | < 2.0 |
| `successfulDribblesPercentage` | Dribble Success % | ≥ 60% | 52–60% | 44–52% | < 44% |
| `xA` p90 | xA p90 | ≥ 0.30 [^13] | 0.20–0.30 | 0.12–0.20 | < 0.12 |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `xG` p90 | xG p90 | ≥ 0.40 | 0.28–0.40 | 0.18–0.28 | < 0.18 |
| `keyPasses` p90 | Key Passes p90 | ≥ 2.5 | 1.8–2.5 | 1.2–1.8 | < 1.2 |
| `goals` + `assists` / season | G+A / сезон | ≥ 40 [^15] | 28–40 | 18–28 | < 18 |
| `wasFouled` p90 | Was Fouled p90 | ≥ 4.0 | 2.5–4.0 | 1.5–2.5 | < 1.5 |

### 🟡 Средние метрики (22%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `shotsOnTarget` p90 | Shots on Target p90 | ≥ 2.0 | 1.4–2.0 | 0.9–1.4 | < 0.9 |
| `bigChancesCreated` p90 | Big Chances p90 | ≥ 0.35 | 0.22–0.35 | 0.12–0.22 | < 0.12 |
| `dispossessed` p90 | Dispossessed p90 (меньше = лучше) | ≤ 1.5 | 1.5–2.2 | 2.2–3.0 | > 3.0 |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `tackles` + `interceptions` p90 | Оборонительная работа |
| `aerialDuelsWonPercentage` | Как правило, не приоритет |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |

***

## 7. Вингер (W / WF)

**Эталоны:**
- 🏆 Messi 2011–12: 1.76 G+A p90, 222 dribbles, 3.8 take-ons p90[^16][^17]
- 🏆 Ronaldo 2007–08: 0.92 goals p90, 5.2 shots on target p90[^18][^19]
- 🏆 Ronaldinho пик: 5.06 dribbles p90, 2.07 key passes p90[^20]
- ⭐ Vinícius 2023–24 | ✅ Salah 2024–25 | ⚠️ Без стабильного влияния

### 🔴 Ключевые метрики (37%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `successfulDribbles` p90 | Dribbles p90 | ≥ 3.8 [^16] | 2.5–3.8 | 1.5–2.5 | < 1.5 |
| `successfulDribblesPercentage` | Dribble Success % | ≥ 58% | 50–58% | 42–50% | < 42% |
| `xG` + `xA` p90 | xG+xA p90 | ≥ 0.80 | 0.50–0.80 | 0.28–0.50 | < 0.28 |
| `goals` + `assists` p90 | G+A p90 | ≥ 1.20 [^17] | 0.55–1.20 | 0.28–0.55 | < 0.28 |

### 🟠 Важные метрики (28%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `keyPasses` p90 | Key Passes p90 | ≥ 2.3 [^16] | 1.5–2.3 | 1.0–1.5 | < 1.0 |
| `shotsOnTarget` p90 | Shots on Target p90 | ≥ 2.5 [^19] | 1.5–2.5 | 0.8–1.5 | < 0.8 |
| `bigChancesCreated` p90 | Big Chances p90 | ≥ 0.40 | 0.25–0.40 | 0.12–0.25 | < 0.12 |
| `goalConversionPercentage` | Goal Conversion % | ≥ 22% | 16–22% | 10–16% | < 10% |

### 🟡 Средние метрики (23%)

| API-поле | Производная | 🏆 Легенда | ⭐ Высокий | ✅ Средний | ⚠️ Слабый |
|---|---|---|---|---|---|
| `npxG` p90 | npxG p90 | ≥ 0.70 | 0.45–0.70 | 0.25–0.45 | < 0.25 |
| `shotsOnTarget` / `totalShots` | Shot on Target % | ≥ 45% | 38–45% | 30–38% | < 30% |
| `wasFouled` p90 | Was Fouled p90 | ≥ 3.5 | 2.0–3.5 | 1.2–2.0 | < 1.2 |
| `accurateCrossesPercentage` | Cross Accuracy % (широкий профиль) | ≥ 35% | 28–35% | 20–28% | < 20% |

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `dispossessed` p90 | Потери — обратная метрика |
| `aerialDuelsWonPercentage` | Редко значимо для вингера |
| `fouls` p90 | Дисциплина при потере |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |
| `xGBuildup` p90 (Understat) | Участие в розыгрыше до момента удара |
| `accurateFinalThirdPasses` p90 | Пасы в финальную треть — продвижение мяча |
| `accurateOppositionHalfPasses` p90 | Пасы на чужой половине — доминирование в зоне |

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

### 🟢 Низкие метрики (12%)

| API-поле | Примечание |
|---|---|
| `xA` p90 | Голевые передачи — важны для ложной 9-ки, бонус для ST |
| `headedGoals` / `goals` | Воздушная угроза в % от всех голов |
| `hitWoodwork` | Косвенный маркер остроты |
| `xGChain` p90 (Understat) | Вовлечённость в голевые цепочки |

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

***

## Матрица профилей и API-приоритеты

| Позиция | Профиль | Ключевые API-поля |
|---|---|---|
| GK | Вратарь | `saves`, `cleanSheet`, `runsOut`, `highClaims`, `goalsConceded` |
| CB | Защитник | `aerialDuelsWonPercentage`, `tackles`, `interceptions`, `clearances`, `errorLeadToShot` |
| FB-A | Атак. фланг | `accurateFinalThirdPasses`, `xA`, `accurateCrosses`, `keyPasses` |
| FB-D | Обор. фланг | `totalDuelsWonPercentage`, `tackles`, `aerialDuelsWonPercentage`, `clearances` |
| DM | Опорник | `accuratePassesPercentage`, `ballRecovery`, `tackles`+`interceptions`, `accurateFinalThirdPasses` |
| CM | Восьмёрка | `keyPasses`, `xG`+`xA`, `accurateFinalThirdPasses`, `tackles`+`interceptions` |
| AM-P | Пасовщик | `keyPasses`, `xA`, `bigChancesCreated`, `accurateFinalThirdPasses` |
| AM-D | Дриблёр | `successfulDribbles`, `successfulDribblesPercentage`, `xA`, `wasFouled` |
| W | Вингер | `successfulDribbles`, `xG`+`xA`, `keyPasses`, `shotsOnTarget`, `goals`+`assists` |
| ST-P | Финишёр | `npxG`, `goals`/`xG`, `goalConversionPercentage`, `shotsOnTarget`% |
| ST-L | Плеймейкер CF | `npxG`, `xA`, `keyPasses`, `bigChancesCreated`, `accuratePassesPercentage` |

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
