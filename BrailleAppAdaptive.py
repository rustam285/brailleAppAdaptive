import pygame
from pygame.locals import *
import sys
import threading
import queue
import os
from datetime import date as dt_date
from resources import letters, images, all_words, words_for_dict
import pyttsx3
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from dictation_module import DictationModule
from dictionaries import sounds, play_sound, dictations, letter_code_map
import argparse

load_dotenv()

FPS    = 120
WHITE  = (255, 255, 255)
BLUE   = (0, 70, 225)
GRAY   = (200, 200, 200)
BLACK  = (0, 0, 0)
GREEN  = (0, 180, 0)

DB_URL = os.getenv("DATABASE_URL")

# ══════════════════════════════════════════════════════════════════
#  РАСКЛАДКИ БРАЙЛЯ
#
#  Физическое расположение точек Брайля (одинаково для всех режимов):
#
#      Левый столбец │ Правый столбец
#      ──────────────┼───────────────
#      точка 1 (верх)│ точка 4 (верх)
#      точка 2 (сред)│ точка 5 (сред)
#      точка 3 (низ) │ точка 6 (низ)
#
#  Кодировка pin (сумма): точка N → 10^(N-1)
#      1→1, 2→10, 3→100, 4→1000, 5→10000, 6→100000
#
#  circle_index — индекс кружка на экране (0-5):
#      0=верх-лево  3=верх-право
#      1=сред-лево  4=сред-право
#      2=низ-лево   5=низ-право
#
#  Режимы:
#    "numpad_normal"   — numpad, колонки сверху вниз:  7→1  8→4
#                                                       4→2  5→5
#                                                       1→3  2→6
#    "numpad_inverted" — numpad, колонки перевёрнуты:  8→4  7→1
#                                                       5→5  4→2
#                                                       2→6  1→3
#    "horizontal"      — буквенные клавиши:  s→1  j→4
#                                             d→2  k→5
#                                             f→3  l→6
# ══════════════════════════════════════════════════════════════════
BRAILLE_KEY_MAPS = {
    "numpad_normal": {
        K_KP7: (1,      0),   # точка 1
        K_KP4: (10,     1),   # точка 2
        K_KP1: (100,    2),   # точка 3
        K_KP8: (1000,   3),   # точка 4
        K_KP5: (10000,  4),   # точка 5
        K_KP2: (100000, 5),   # точка 6
    },
    "numpad_inverted": {
        K_KP8: (1,      0),   # точка 1  ← инвертировано
        K_KP5: (10,     1),   # точка 2
        K_KP2: (100,    2),   # точка 3
        K_KP7: (1000,   3),   # точка 4
        K_KP4: (10000,  4),   # точка 5
        K_KP1: (100000, 5),   # точка 6
    },
    "horizontal": {
        K_s: (1,      0),     # точка 1 — левая рука
        K_d: (10,     1),     # точка 2
        K_f: (100,    2),     # точка 3
        K_j: (1000,   3),     # точка 4 — правая рука
        K_k: (10000,  4),     # точка 5
        K_l: (100000, 5),     # точка 6
    },
}

INPUT_MODE_NAMES = {
    "numpad_normal":   "Обычный ввод с цифровой клавиатуры",
    "numpad_inverted": "Инвертированный ввод с цифровой клавиатуры",
    "horizontal":      "Горизонтальный ввод, клавиши S D F и J K L",
}
INPUT_MODE_ORDER = ["numpad_normal", "numpad_inverted", "horizontal"]


# ══════════════════════════════════════════════════════════════════
#  АСИНХРОННЫЙ СИНТЕЗ РЕЧИ
# ══════════════════════════════════════════════════════════════════
class TTSWorker:
    """
    Один постоянный фоновый поток с очередью.
    pyttsx3 инициализируется один раз — нет конфликта event loop.
    Новое сообщение вытесняет предыдущее из очереди (не копятся).
    """

    def __init__(self):
        self._queue  = queue.Queue()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        engine = pyttsx3.init()
        engine.setProperty("rate", 150)
        engine.setProperty("voice", "russian")
        while True:
            text = self._queue.get()   # ждём следующее сообщение
            if text is None:
                break
            engine.say(text)
            engine.runAndWait()

    def say(self, text: str):
        # Очищаем очередь — старые фразы уже не актуальны
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
        self._queue.put(text)


# ══════════════════════════════════════════════════════════════════
#  СОСТОЯНИЕ ТЕКУЩЕГО ВВОДА
# ══════════════════════════════════════════════════════════════════
class InputHandler:
    """Хранит состояние нажатых точек, изолирует логику от UI."""

    def __init__(self):
        self.pin: int = 0
        self._pressed: set = set()

    def press(self, key, key_map: dict):
        """
        Обрабатывает нажатие клавиши по текущей раскладке.
        Возвращает circle_index если клавиша брайлевская, иначе None.
        """
        if key in key_map and key not in self._pressed:
            pin_value, circle_idx = key_map[key]
            self.pin += pin_value
            self._pressed.add(key)
            return circle_idx
        return None

    def reset(self):
        self.pin = 0
        self._pressed.clear()


# ══════════════════════════════════════════════════════════════════
#  РАБОТА С POSTGRESQL (замена JSON)
# ══════════════════════════════════════════════════════════════════
class StudentDB:
    """
    Адаптер для PostgreSQL. Предоставляет тот же интерфейс, что
    раньше давал JSON-файл, так что DictationModule может
    работать без изменений через методы этого класса.
    """

    def __init__(self, db_url: str):
        self.db_url = db_url

    def _connect(self):
        return psycopg2.connect(self.db_url, connect_timeout=10)

    # ── Загрузка / создание ученика ───────────────────────────────
    def ensure_student(self, student_id: str):
        """Создаёт запись ученика если её нет."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO students (student_id) VALUES (%s) ON CONFLICT DO NOTHING",
                    (student_id,)
                )

    def student_exists(self, student_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM students WHERE student_id = %s", (student_id,))
                return cur.fetchone() is not None

    # ── Сохранение результата диктанта ───────────────────────────
    def save_result(self, student_id: str, dictation_name: str,
                    errors: int, mistakes: list, grade: int):
        """
        Сохраняет результат одного диктанта.
        Вызывается из DictationModule вместо записи в JSON.
        """
        today = dt_date.today().strftime("%d-%m-%Y")
        with self._connect() as conn:
            with conn.cursor() as cur:
                # Результат диктанта
                cur.execute(
                    """
                    INSERT INTO dictation_results
                        (student_id, date, dictation_name, errors, grade)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (student_id, today, dictation_name, errors, grade)
                )
                result_id = cur.fetchone()[0]

                # Слова с ошибками
                for word in mistakes:
                    cur.execute(
                        "INSERT INTO dictation_mistakes (result_id, word) VALUES (%s, %s)",
                        (result_id, word)
                    )

    # ── Чтение прогресса (для совместимости с DictationModule) ────
    def get_student_progress(self, student_id: str) -> dict:
        """
        Возвращает прогресс ученика в формате, аналогичном JSON:
        { "DD-MM-YYYY": { "Диктант": {"errors": N, "grade": N, "mistakes": [...]} } }
        Используется если DictationModule читает историю.
        """
        with self._connect() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
                cur.execute(
                    """
                    SELECT r.date, r.dictation_name, r.errors, r.grade,
                           COALESCE(
                               array_agg(m.word) FILTER (WHERE m.word IS NOT NULL), '{}'
                           ) AS mistakes
                    FROM dictation_results r
                    LEFT JOIN dictation_mistakes m ON m.result_id = r.id
                    WHERE r.student_id = %s
                    GROUP BY r.date, r.dictation_name, r.errors, r.grade, r.id
                    ORDER BY r.date
                    """,
                    (student_id,)
                )
                progress = {}
                for row in cur.fetchall():
                    d = row["date"]
                    if d not in progress:
                        progress[d] = {}
                    progress[d][row["dictation_name"]] = {
                        "errors":   row["errors"],
                        "grade":    row["grade"],
                        "mistakes": list(row["mistakes"]),
                    }
                return progress


# ══════════════════════════════════════════════════════════════════
#  ОСНОВНОЕ ПРИЛОЖЕНИЕ
# ══════════════════════════════════════════════════════════════════
class BrailleApp:
    def __init__(self):
        self._init_pygame()
        self._init_screen()
        self._init_variables()
        self.tts    = TTSWorker()
        self.input  = InputHandler()
        self.db     = StudentDB(DB_URL)

    # ── Инициализация ─────────────────────────────────────────────
    def _init_pygame(self):
        pygame.init()
        pygame.mixer.init()

    def _init_screen(self):
        info   = pygame.display.Info()
        self.W = int(info.current_w * 0.75)
        self.H = int(info.current_h * 0.8)
        self.sc    = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.font  = pygame.font.SysFont("arial", 32)
        self.font_small = pygame.font.SysFont("arial", 20)
        self._update_positions()

    def _init_variables(self):
        self.s_word: list            = []
        self.mode: str               = "free"
        self.input_mode: str         = "numpad_normal"   # текущая раскладка
        self.student_id: str | None  = None
        self.dictation_module        = None
        self.waiting_for_student_id  = False
        self.typed_id: str           = ""

    def _update_positions(self):
        self.circle_radius = int(self.W * 0.05)
        self.circle_positions = [
            (int(self.W * 0.09), int(self.H * 0.15)),   # 0 — точка 1
            (int(self.W * 0.09), int(self.H * 0.50)),   # 1 — точка 2
            (int(self.W * 0.09), int(self.H * 0.85)),   # 2 — точка 3
            (int(self.W * 0.27), int(self.H * 0.15)),   # 3 — точка 4
            (int(self.W * 0.27), int(self.H * 0.50)),   # 4 — точка 5
            (int(self.W * 0.27), int(self.H * 0.85)),   # 5 — точка 6
        ]
        self.letter_start_x = int(self.W * 0.35)
        self.letter_start_y = int(self.H * 0.01)

    # ── Переключение режима ввода ─────────────────────────────────
    def cycle_input_mode(self):
        """
        Переключает раскладку по кругу:
        numpad_normal → numpad_inverted → horizontal → numpad_normal
        Назначена на клавишу Tab.
        """
        idx = INPUT_MODE_ORDER.index(self.input_mode)
        self.input_mode = INPUT_MODE_ORDER[(idx + 1) % len(INPUT_MODE_ORDER)]
        self.input.reset()
        name = INPUT_MODE_NAMES[self.input_mode]
        self.tts.say(f"Режим ввода: {name}")
        self._show_input_mode_hint()

    def _show_input_mode_hint(self):
        """Отображает название текущей раскладки на экране 2 сек."""
        self._clear_screen()
        label = self.font_small.render(
            f"Режим: {INPUT_MODE_NAMES[self.input_mode]}", True, GREEN
        )
        self.sc.blit(label, (self.W // 2 - label.get_width() // 2, self.H // 2))
        pygame.display.update()

    # ── Режим диктанта ────────────────────────────────────────────
    def switch_mode(self):
        if self.mode == "free":
            self._enter_dictation_mode()
        else:
            self._enter_free_mode()

    def _enter_dictation_mode(self):
        self.mode = "dictation"
        self.waiting_for_student_id = True
        self.tts.say("Включён режим диктанта. Введите код ученика.")
        play_sound(sounds[7])
        pygame.time.delay(4000)
        play_sound(sounds[9])

    def _enter_free_mode(self):
        self.mode = "free"
        self.dictation_module = None
        self.student_id       = None
        self.input.reset()
        self.s_word.clear()
        self._clear_screen()
        self.tts.say("Включён свободный режим.")

    # ── Отрисовка ─────────────────────────────────────────────────
    def _clear_screen(self):
        self.sc.fill(GRAY)

    def _clear_braille_dots(self):
        for pos in self.circle_positions:
            pygame.draw.circle(self.sc, GRAY, pos, self.circle_radius)

    def _highlight_dot(self, circle_idx: int):
        pygame.draw.circle(
            self.sc, BLUE,
            self.circle_positions[circle_idx],
            self.circle_radius
        )

    def _draw_student_id_prompt(self):
        self.sc.fill(GRAY)
        prompt = self.font.render("Введите код ученика:", True, BLACK)
        entry  = self.font.render(self.typed_id + "|", True, BLACK)
        self.sc.blit(prompt, (self.W // 2 - prompt.get_width() // 2, self.H // 2 - 50))
        self.sc.blit(entry,  (self.W // 2 - entry.get_width()  // 2, self.H // 2))

    def _draw_word(self):
        self._clear_screen()
        x, y = self.letter_start_x, self.letter_start_y
        for img, _ in self.s_word:
            self.sc.blit(img, (x, y))
            w, h = img.get_size()
            x += w + 5
            if x > self.W - w:
                x, y = self.letter_start_x, y + h + 5

    # ── Работа с учеником ─────────────────────────────────────────
    def _load_student(self):
        """Создаёт ученика в БД если нет, затем запускает диктант."""
        self.db.ensure_student(self.student_id)
        # Передаём db в DictationModule — он будет писать через него
        self.dictation_module = DictationModule(self.student_id, self, self.db)
        self.dictation_module.next_letter()
        self._clear_screen()

    # ── Символы Брайля ────────────────────────────────────────────
    def get_letter_symbol(self, pin: int) -> str:
        letter_map = {
            1: 'А', 11: 'Б', 111010: 'В', 11011: 'Г', 11001: 'Д',
            10001: 'Е', 100001: 'Ё', 11010: 'Ж', 110101: 'З', 1010: 'И',
            101111: 'Й', 101: 'К', 111: 'Л', 1101: 'М', 11101: 'Н',
            10101: 'О', 1111: 'П', 10111: 'Р', 1110: 'С', 11110: 'Т',
            100101: 'У', 1011: 'Ф', 10011: 'Х', 1001: 'Ц', 11111: 'Ч',
            110001: 'Ш', 101101: 'Щ', 110111: 'Ъ', 101110: 'Ы', 111110: 'Ь',
            101010: 'Э', 110011: 'Ю', 101011: 'Я', 0: ' '
        }
        return letter_map.get(pin, '?')

    def _commit_letter(self):
        pin = self.input.pin
        if pin in letters:
            letters[pin].play_sound()
        else:
            letters[-1].play_sound()
            self._clear_braille_dots()
        self.input.reset()

    def _add_letter_to_word(self):
        pin = self.input.pin
        if pin not in letters:
            return
        letters[pin].play_sound()
        symbol = self.get_letter_symbol(pin)
        img    = images.get(pin)
        if img:
            self.s_word.append((img, symbol))
            self._draw_word()
        self.input.reset()

    def _delete_last_letter(self):
        """Удаляет последнюю добавленную букву из слова."""
        if self.s_word:
            self.s_word.pop()
            if self.s_word:
                self._draw_word()
            else:
                self._clear_screen()

    def _preview_current_letter(self):
        """Озвучивает букву по текущим нажатым точкам (не добавляя в слово)."""
        pin = self.input.pin
        if pin == 0:
            self.tts.say("Точки не выбраны")
            return
        if pin in letters:
            letters[pin].play_sound()
        else:
            self.tts.say("Неизвестная комбинация")

    def _speak_word(self):
        """Озвучивает всё слово которое уже набрано."""
        if not self.s_word:
            self.tts.say("Слово пустое")
            return
        self._output_phrase()

    def _clear_current_letter(self):
        """Сбрасывает текущую незавершённую букву (точки), слово не трогает."""
        self.input.reset()
        self._clear_braille_dots()
        # Перерисовываем слово чтобы восстановить экран
        if self.s_word:
            self._draw_word()

    def _output_phrase(self):
        phrase = "".join(char for _, char in self.s_word)
        if phrase.lower() in all_words:
            play_sound(words_for_dict[phrase.lower()])
        else:
            self.tts.say(phrase)

    def _check_dictation_word(self):
        if self.dictation_module:
            word = "".join(char for _, char in self.s_word).strip().lower()
            self.dictation_module.check_word(word)
            self.s_word.clear()

    # ── События ───────────────────────────────────────────────────
    def _handle_events(self) -> bool:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                sys.exit()
            elif event.type == VIDEORESIZE:
                self.W, self.H = event.w, event.h
                self.sc = pygame.display.set_mode((self.W, self.H), pygame.RESIZABLE)
                self._update_positions()
            elif event.type == pygame.KEYDOWN:
                self._on_keydown(event)
        return True

    def _on_keydown(self, event):
        # ── Ввод кода ученика ─────────────────────────────────────
        if self.waiting_for_student_id:
            if event.key == K_BACKSPACE:
                self.typed_id = self.typed_id[:-1]
            elif event.key == K_RETURN:
                self.student_id = self.typed_id
                self.typed_id   = ""
                self.waiting_for_student_id = False
                self._load_student()
            elif event.unicode.isprintable() and len(event.unicode) == 1:
                self.typed_id += event.unicode
            return

        # ── Переключение раскладки (Tab) — всегда ─────────────────
        if event.key == K_TAB:
            self.cycle_input_mode()
            return

        # ── Переключение режима диктант/свободный (Space) ─────────
        if event.key == K_SPACE:
            self.switch_mode()
            return

        # ── Брайлевские точки по текущей раскладке ────────────────
        current_map = BRAILLE_KEY_MAPS[self.input_mode]
        circle_idx  = self.input.press(event.key, current_map)
        if circle_idx is not None:
            self._highlight_dot(circle_idx)
            return

        # ══════════════════════════════════════════════════════════
        #  УПРАВЛЯЮЩИЕ КЛАВИШИ
        #
        #  Горизонтальный режим (s/d/f j/k/l):
        #    Enter        — добавить букву в слово
        #    Backspace    — удалить последнюю букву из слова
        #    Escape       — сбросить текущую незавершённую букву
        #    G            — прослушать текущую букву (по точкам)
        #    H            — прослушать всё набранное слово
        #    Numpad–      — отправить слово на проверку (диктант)
        #
        #  Numpad-режимы (7/4/1 8/5/2):
        #    KP_Enter     — прослушать текущую букву (по точкам)
        #    KP_Plus      — добавить букву в слово
        #    KP_Period    — прослушать всё набранное слово
        #    KP_Minus     — отправить слово на проверку (диктант)
        #    KP0          — полностью очистить (слово + точки)
        #    Backspace    — удалить последнюю букву из слова
        #    Escape       — сбросить текущую незавершённую букву
        # ══════════════════════════════════════════════════════════

        if self.input_mode == "horizontal":
            # ── Горизонтальный режим ──────────────────────────────
            if event.key == K_RETURN:
                self._add_letter_to_word()

            elif event.key == K_BACKSPACE:
                self._delete_last_letter()

            elif event.key == K_ESCAPE:
                self._clear_current_letter()

            elif event.key == K_g:
                self._preview_current_letter()

            elif event.key == K_h:
                self._speak_word()

            elif event.key == K_KP_MINUS:
                if self.mode == "free":
                    self._speak_word()
                elif self.mode == "dictation":
                    self._check_dictation_word()

        else:
            # ── Numpad-режимы (normal / inverted) ─────────────────
            if event.key == K_KP_ENTER:
                self._preview_current_letter()

            elif event.key == K_KP_PLUS:
                self._add_letter_to_word()

            elif event.key == K_KP_PERIOD:
                self._speak_word()

            elif event.key == K_KP_MINUS:
                if self.mode == "free":
                    self._speak_word()
                elif self.mode == "dictation":
                    self._check_dictation_word()

            elif event.key == K_KP0:
                self._clear_screen()
                self.s_word.clear()
                self.input.reset()

            elif event.key == K_BACKSPACE:
                self._delete_last_letter()

            elif event.key == K_ESCAPE:
                self._clear_current_letter()

    def _draw_controls_hint(self):
        """Рисует подсказку по клавишам внизу экрана в зависимости от раскладки."""
        if self.input_mode == "horizontal":
            hints = [
                "Enter — добавить букву  |  Backspace — удалить букву",
                "Escape — сбросить точки  |  G — прослушать букву  |  H — прослушать слово",
            ]
        else:
            hints = [
                "KP+ — добавить букву  |  Backspace — удалить букву",
                "KP_Enter — прослушать букву  |  KP. — прослушать слово  |  Esc — сбросить точки",
            ]
        y = self.H - len(hints) * 22 - 5
        for line in hints:
            surf = self.font_small.render(line, True, BLACK)
            self.sc.blit(surf, (self.W // 2 - surf.get_width() // 2, y))
            y += 22

    # ── Главный цикл ──────────────────────────────────────────────
    def run(self):
        self._clear_screen()
        while self._handle_events():
            if self.waiting_for_student_id:
                self._draw_student_id_prompt()
            else:
                self._draw_controls_hint()
            pygame.display.update()
            self.clock.tick(FPS)


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["free", "dictation"], default="free")
    args = parser.parse_args()

    app = BrailleApp()
    app.mode = args.mode
    if app.mode == "dictation":
        app.mode = "free"
        app.switch_mode()
    app.run()