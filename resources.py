import pygame
import os
import sys
from dictionaries import letter_code_map, dictations

pygame.init()
pygame.mixer.init()


def resource_path(relative_path: str) -> str:
    """Корректный путь к ресурсам и в режиме скрипта, и в exe (PyInstaller)."""
    if getattr(sys, "frozen", False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, relative_path)


# ── Класс буквы Брайля ────────────────────────────────────────────
class BrailleLetter:
    def __init__(self, image_path: str | None, sound_path: str):
        self.image = (
            pygame.image.load(resource_path(image_path))
            if image_path else None
        )
        self.sound = pygame.mixer.Sound(resource_path(sound_path))

    def play_sound(self):
        self.sound.play()


# ── Загрузка букв из папки images ────────────────────────────────
images_dir = "images"
sounds_dir = "sounds"

letters_data: dict = {}

for image_file in os.listdir(images_dir):
    if not image_file.endswith(".png"):
        continue

    letter_name = image_file.split("_")[-1].split(".")[0]
    image_path  = os.path.join(images_dir, image_file)
    sound_path  = os.path.join(sounds_dir, f"{letter_name}.ogg")

    if os.path.exists(resource_path(sound_path)):
        letter_code = letter_code_map.get(letter_name, -1)
        letters_data[letter_code] = (image_path, sound_path)
    else:
        print(f"⚠ Звук буквы «{letter_name}» не найден: {sound_path}")

# Специальный случай — перенабор
letters_data[-1] = (None, os.path.join(sounds_dir, "набрать букву заново.ogg"))

letters = {
    pin: BrailleLetter(img, snd)
    for pin, (img, snd) in letters_data.items()
}

images = {pin: letter.image for pin, letter in letters.items() if letter.image}

# Пробел
if 0 not in images:
    space_path = resource_path(os.path.join("images", "пробел.png"))
    if os.path.exists(space_path):
        images[0] = pygame.image.load(space_path)


# ── Загрузка звуков слов ──────────────────────────────────────────
words_sounds_dir = os.path.join(sounds_dir, "words")

# Плоский список всех слов из диктантов
all_words: list = []
for letter_words in dictations.values():
    all_words.extend(letter_words)

# Заглушка — тихий звук длиной 0.1 сек, чтобы не падать при None
def _silent_sound() -> pygame.mixer.Sound:
    """Возвращает пустой звук — используется как fallback."""
    buf = pygame.sndarray.make_sound(
        pygame.surfarray.array2d(
            pygame.Surface((1, 1))
        ).astype("int16") * 0
    )
    return buf

words_for_dict: dict = {}

for word in all_words:
    sound_path    = os.path.join(words_sounds_dir, f"{word}.ogg")
    full_path     = resource_path(sound_path)
    if os.path.exists(full_path):
        words_for_dict[word] = pygame.mixer.Sound(full_path)
    else:
        print(f"⚠ Звук слова «{word}» не найден — используется заглушка")
        # Сохраняем заглушку вместо None — play() не упадёт
        words_for_dict[word] = pygame.mixer.Sound(
            buffer=bytes(44)   # минимальный валидный буфер
        )