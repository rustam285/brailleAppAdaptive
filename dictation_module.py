import datetime
import threading
import random
import pygame
import pyttsx3
from collections import OrderedDict

from dictionaries import letters_for_dictations, dictations, letter_code_map, sounds, play_sound
from resources import words_for_dict, letters


class DictationModule:
    """
    Модуль диктанта.

    Изменения относительно оригинала:
    ─────────────────────────────────
    1. Принимает `db` (StudentDB) вместо работы с JSON-файлом напрямую.
    2. Результаты диктанта сохраняются в PostgreSQL один раз — когда
       диктант по букве завершён (а не после каждого слова).
    3. Исправлен баг: при неправильном ответе ошибка теперь
       действительно записывается.
    4. say_phrase теперь асинхронный — не блокирует UI.
    5. clear_win совместим с новым InputHandler (braille_app.input.reset()).
    """

    def __init__(self, student_id: str, braille_app, db):
        self.student_id   = student_id
        self.braille_app  = braille_app
        self.db           = db                                      # StudentDB
        self.today        = datetime.date.today().strftime("%d-%m-%Y")

        self._init_tts()
        self._load_progress()

        self.current_letter: str | None = None
        self.current_word:   str | None = None
        self.word_queue                 = None
        self.words_history: list        = []

        # Накопитель результата текущего диктанта (сбрасывается при смене буквы)
        self._current_result: dict | None = None

        self.dictation_queue = self._get_today_dictations()

    # ── TTS ───────────────────────────────────────────────────────
    def _init_tts(self):
        self._tts_lock  = threading.Lock()
        self.engine     = pyttsx3.init()
        self.engine.setProperty("rate", 120)
        self.engine.setProperty("voice", "russian")

    def say_phrase(self, phrase: str):
        """Произносит фразу асинхронно — UI не зависает."""
        def _run():
            with self._tts_lock:
                self.engine.say(phrase)
                self.engine.runAndWait()
        threading.Thread(target=_run, daemon=True).start()

    # ── Работа с БД ───────────────────────────────────────────────
    def _load_progress(self):
        """
        Читает прогресс из PostgreSQL в тот же формат что раньше давал JSON,
        чтобы get_today_dictations() работал без изменений.
        """
        self.student_data = {
            self.student_id: self.db.get_student_progress(self.student_id)
        }
        # Убеждаемся что сегодняшняя запись существует
        if self.today not in self.student_data[self.student_id]:
            self.student_data[self.student_id][self.today] = {}

    def _save_current_dictation(self):
        """
        Сохраняет результат текущего диктанта в PostgreSQL.
        Вызывается когда диктант по букве завершён.
        """
        if self.current_letter is None or self._current_result is None:
            return

        self.db.save_result(
            student_id      = self.student_id,
            dictation_name  = self.current_letter,
            errors          = self._current_result["errors"],
            mistakes        = self._current_result["mistakes"],
            grade           = self._current_result["grade"],
        )
        # Обновляем локальный кэш чтобы get_today_dictations не повторял
        self.student_data[self.student_id][self.today][self.current_letter] = (
            self._current_result.copy()
        )
        self._current_result = None

    # ── Очередь диктантов ─────────────────────────────────────────
    def _get_today_dictations(self):
        completed = self.student_data[self.student_id][self.today].keys()
        available = []

        if "Начальный диктант" not in completed:
            available.append("Начальный диктант")

        available.extend(
            letter for letter in letters_for_dictations
            if letter != "Начальный диктант" and letter not in completed
        )
        return iter(available)

    # ── Слова для диктанта ────────────────────────────────────────
    def get_words_for_dictation(self, current_letter: str) -> list:
        main_words = dictations[current_letter].copy()

        if current_letter == "Начальный диктант":
            self.words_history.extend(main_words)
            self.words_history = list(OrderedDict.fromkeys(self.words_history))
            return main_words[:10]

        needed_words = 10 - len(main_words)
        if needed_words > 0:
            current_index  = letters_for_dictations.index(current_letter)
            previous_words = []
            for letter in letters_for_dictations[:current_index]:
                previous_words.extend(dictations[letter])
            previous_words  = list(OrderedDict.fromkeys(previous_words))
            available_words = [w for w in previous_words if w not in main_words]
            additional      = random.sample(
                available_words, min(needed_words, len(available_words))
            )
            main_words.extend(additional)

        self.words_history.extend(main_words)
        self.words_history = list(OrderedDict.fromkeys(self.words_history))
        return main_words[:10]

    # ── Навигация ─────────────────────────────────────────────────
    def clear_win(self):
        """Сбрасывает экран и состояние ввода в BrailleApp."""
        self.braille_app._clear_screen()
        self.braille_app.s_word.clear()
        self.braille_app.input.reset()   # совместимо с новым InputHandler

    def next_letter(self):
        # Сохраняем результат завершённого диктанта перед переходом
        self._save_current_dictation()

        try:
            self.current_letter  = next(self.dictation_queue)
            words                = self.get_words_for_dictation(self.current_letter)

            # Инициализируем накопитель для нового диктанта
            self._current_result = {"errors": 0, "mistakes": [], "grade": 10}

            if self.current_letter == "Начальный диктант":
                play_sound(sounds[8])
                pygame.time.delay(5500)
            else:
                play_sound(sounds[6])
                pygame.time.delay(4500)
                letters[letter_code_map[self.current_letter.lower()]].play_sound()

            self.word_queue = iter(words)
            self.next_word()

        except StopIteration:
            # Все диктанты сегодня пройдены
            self.clear_win()
            play_sound(sounds[0])
            self.current_letter  = None
            self.current_word    = None
            self._current_result = None

    def next_word(self):
        if self.word_queue is None:
            self.next_letter()
            return
        try:
            self.current_word = next(self.word_queue)
            pygame.time.delay(2500)
            play_sound(sounds[2])
            pygame.time.delay(2500)
            play_sound(words_for_dict[self.current_word])
        except StopIteration:
            self.next_letter()

    # ── Проверка ответа ───────────────────────────────────────────
    def check_word(self, user_word: str):
        if user_word.lower() == "стоп":
            self._save_current_dictation()
            play_sound(sounds[0])
            self.clear_win()
            self.current_letter  = None
            self.current_word    = None
            self._current_result = None
            return

        if not self.current_word:
            return

        if user_word == self.current_word:
            play_sound(sounds[5])
            # Правильный ответ — ничего не меняем в счётчике, просто идём дальше
        else:
            play_sound(sounds[4])
            # ── ИСПРАВЛЕНО: ошибка теперь записывается ──────────
            self._record_mistake(self.current_word)

        self.clear_win()
        self.next_word()

    def _record_mistake(self, word: str):
        """Фиксирует ошибку в накопителе текущего диктанта."""
        if self._current_result is None:
            return
        self._current_result["errors"] += 1
        self._current_result["mistakes"].append(word)
        self._current_result["grade"] = max(
            1, self._current_result["grade"] - 1
        )