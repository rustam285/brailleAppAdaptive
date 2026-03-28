import pygame
import sys
import subprocess
import os
import webbrowser

pygame.init()

WIDTH, HEIGHT = 600, 450
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Главное меню — Брайль")

FONT       = pygame.font.SysFont("arial", 24)
FONT_SMALL = pygame.font.SysFont("arial", 16)
WHITE      = (255, 255, 255)
BLACK      = (0,   0,   0)
GRAY       = (200, 200, 200)
BLUE       = (100, 149, 237)
DARK_BLUE  = (70,  120, 200)
GREEN      = (60,  160, 80)
DARK_GREEN = (40,  120, 60)

base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

def launch(script: str, *args):
    """Запускает python-скрипт в отдельном процессе."""
    subprocess.Popen([sys.executable, os.path.join(base_dir, script), *args])

buttons = [
    {
        "label":  "1. Матрица герконов",
        "action": lambda: launch("arduino.py"),
        "color":  BLUE,
        "hover":  DARK_BLUE,
    },
    {
        "label":  "2. Цифровая клавиатура",
        "action": lambda: launch("BrailleAppAdaptive.py"),
        "color":  BLUE,
        "hover":  DARK_BLUE,
    },
    {
        "label":  "3. Модуль диктантов",
        "action": lambda: launch("BrailleAppAdaptive.py", "--mode", "dictation"),
        "color":  BLUE,
        "hover":  DARK_BLUE,
    },
    {
        "label":  "4. Прогресс учеников (VK)",
        "action": lambda: webbrowser.open("https://vk.com/brailleadaptive"),
        "color":  GREEN,
        "hover":  DARK_GREEN,
    },
]

BTN_W, BTN_H = 370, 52
START_Y      = 60
SPACING      = 72

button_rects = [
    pygame.Rect((WIDTH - BTN_W) // 2, START_Y + i * SPACING, BTN_W, BTN_H)
    for i in range(len(buttons))
]

# Подсказка внизу экрана
hint = FONT_SMALL.render(
    "Tab — смена раскладки Брайля  |  Пробел — режим диктанта", True, GRAY
)

running = True
while running:
    screen.fill(WHITE)

    for i, rect in enumerate(button_rects):
        hovered = rect.collidepoint(pygame.mouse.get_pos())
        color   = buttons[i]["hover"] if hovered else buttons[i]["color"]
        pygame.draw.rect(screen, color, rect, border_radius=12)
        surf = FONT.render(buttons[i]["label"], True, WHITE)
        screen.blit(surf, surf.get_rect(center=rect.center))

    # Подсказка
    screen.blit(hint, hint.get_rect(center=(WIDTH // 2, HEIGHT - 20)))

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            for i, rect in enumerate(button_rects):
                if rect.collidepoint(event.pos):
                    buttons[i]["action"]()

    pygame.display.flip()

pygame.quit()
sys.exit()