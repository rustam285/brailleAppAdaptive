import pygame
import serial
import serial.tools.list_ports
from resources import letters
from dictionaries import letter_map, play_sound

WIDTH, HEIGHT = 1000, 800
WHITE  = (255, 255, 255)
BLACK  = (0,   0,   0)
GRAY   = (200, 200, 200)
RED    = (200, 50,  50)

BAUD_RATE   = 9600
COM_PORT    = "COM3"


class BrailleDisplay:
    """Отрисовывает 6 точек Брайля. Создаётся один раз."""

    def __init__(self, screen):
        self.screen = screen
        self._update(screen.get_width(), screen.get_height())

    def _update(self, w: int, h: int):
        self.W = w
        self.H = h
        self.radius = int(w * 0.05)
        self.positions = [
            (int(w * 0.09), int(h * 0.15)),
            (int(w * 0.09), int(h * 0.50)),
            (int(w * 0.09), int(h * 0.85)),
            (int(w * 0.27), int(h * 0.15)),
            (int(w * 0.27), int(h * 0.50)),
            (int(w * 0.27), int(h * 0.85)),
        ]

    def on_resize(self, w: int, h: int):
        self._update(w, h)

    def draw(self, pattern: str):
        """
        pattern — строка из 6 символов '0'/'1'.
        Закрашивает кружки для единиц.
        """
        for i, bit in enumerate(pattern.ljust(6, "0")):
            color = BLACK if bit == "1" else GRAY
            pygame.draw.circle(self.screen, color, self.positions[i], self.radius)


def find_serial_port() -> str | None:
    """Пытается автоматически найти Arduino среди доступных портов."""
    for port in serial.tools.list_ports.comports():
        if "Arduino" in (port.description or "") or "CH340" in (port.description or ""):
            return port.device
    return None


def open_serial(port: str) -> serial.Serial | None:
    try:
        s = serial.Serial(port, BAUD_RATE, timeout=0.1)  # timeout=0.1 → неблокирующий
        print(f"✅ Подключено к {port}")
        return s
    except serial.SerialException as e:
        print(f"❌ Не удалось открыть {port}: {e}")
        return None


def main():
    pygame.init()
    screen = pygame.display.set_mode((WIDTH, HEIGHT), pygame.RESIZABLE)
    pygame.display.set_caption("Матрица герконов — считывание Брайля")
    clock  = pygame.time.Clock()
    font   = pygame.font.SysFont("Arial", 100)
    font_s = pygame.font.SysFont("Arial", 28)

    braille = BrailleDisplay(screen)    # создаётся ОДИН раз

    # Открываем порт
    port = find_serial_port() or COM_PORT
    ser  = open_serial(port)

    last_letter_text = ""
    current_pattern  = "000000"
    serial_error     = "" if ser else f"Порт {port} недоступен"

    running = True
    while running:
        w = screen.get_width()
        h = screen.get_height()
        screen.fill(WHITE)

        # ── Обработка событий ─────────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.VIDEORESIZE:
                screen = pygame.display.set_mode(
                    (event.w, event.h), pygame.RESIZABLE
                )
                braille.on_resize(event.w, event.h)

        # ── Чтение Serial (неблокирующее) ─────────────────────────
        if ser and ser.is_open:
            try:
                if ser.in_waiting > 0:          # данные есть — читаем
                    line = ser.readline().decode("utf-8").strip()
                    if line and line != "0":
                        # Arduino шлёт число вида "100010"
                        # переворачиваем для правильного порядка точек
                        current_pattern  = line[::-1]
                        decimal_number   = int(line)
                        if decimal_number in letter_map:
                            play_sound(letters[decimal_number].sound)
                            last_letter_text = f"Буква {letter_map[decimal_number]}"
                        else:
                            last_letter_text = ""
                    else:
                        last_letter_text = ""
                        current_pattern  = "000000"
                serial_error = ""
            except (ValueError, UnicodeDecodeError):
                last_letter_text = "Ошибка данных"
                current_pattern  = "000000"
            except serial.SerialException as e:
                serial_error     = f"Ошибка порта: {e}"
                ser              = None

        # ── Отрисовка точек ───────────────────────────────────────
        braille.draw(current_pattern)

        # ── Текст буквы ───────────────────────────────────────────
        if last_letter_text:
            surf = font.render(last_letter_text, True, BLACK)
            screen.blit(surf, surf.get_rect(center=(w // 2 + 150, h // 2)))

        # ── Сообщение об ошибке порта ─────────────────────────────
        if serial_error:
            err_surf = font_s.render(serial_error, True, RED)
            screen.blit(err_surf, (20, h - 40))

        pygame.display.flip()
        clock.tick(30)

    if ser and ser.is_open:
        ser.close()
    pygame.quit()


if __name__ == "__main__":
    main()