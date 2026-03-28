"""
Панель администратора — управление учениками в PostgreSQL.
Запуск: python admin.py
Зависимости: pip install psycopg2-binary python-dotenv pygame
"""

import pygame
import sys
import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
import re

load_dotenv()
DB_URL = os.getenv("DATABASE_URL")

pygame.init()

# ── Размер окна ───────────────────────────────────────────────────
W, H = 960, 640
FPS  = 60

# ── Палитра ───────────────────────────────────────────────────────
C = {
    "bg":           (15,  17,  23),   # почти чёрный фон
    "panel":        (24,  27,  38),   # тёмно-синяя панель
    "panel_border": (40,  46,  66),   # граница панели
    "accent":       (82,  130, 255),  # синий акцент
    "accent_dark":  (55,  90,  200),  # тёмный акцент (hover)
    "danger":       (220, 70,  70),   # красный для удаления
    "danger_dark":  (170, 40,  40),
    "success":      (60,  190, 100),  # зелёный
    "text":         (220, 225, 240),  # основной текст
    "text_dim":     (110, 120, 150),  # приглушённый текст
    "text_bright":  (255, 255, 255),  # яркий текст
    "selected":     (35,  50,  90),   # выделенная строка
    "hover":        (28,  33,  50),   # hover строки
    "separator":    (35,  40,  58),   # разделитель
    "confirm_bg":   (20,  22,  32),   # фон диалога
    "grade_good":   (60,  200, 110),
    "grade_mid":    (240, 190, 60),
    "grade_bad":    (220, 80,  80),
    "scrollbar":    (50,  58,  85),
    "scrollbar_th": (80,  95,  140),
}

# ── Шрифты ────────────────────────────────────────────────────────
pygame.font.init()

def load_font(size, bold=False):
    for name in ["Segoe UI", "Arial", "Liberation Sans", "DejaVu Sans"]:
        try:
            return pygame.font.SysFont(name, size, bold=bold)
        except Exception:
            pass
    return pygame.font.Font(None, size)

F_TITLE  = load_font(28, bold=True)
F_HEAD   = load_font(20, bold=True)
F_BODY   = load_font(17)
F_SMALL  = load_font(14)
F_BADGE  = load_font(13, bold=True)

# ── Области ───────────────────────────────────────────────────────
LEFT_W   = 300
HEADER_H = 60
LIST_TOP = HEADER_H + 8
ROW_H    = 46
PADDING  = 16


# ══════════════════════════════════════════════════════════════════
#  РАБОТА С БД
# ══════════════════════════════════════════════════════════════════
def db_connect():
    return psycopg2.connect(DB_URL, connect_timeout=10)


def db_load_students() -> list[dict]:
    """Возвращает список учеников с агрегированной статистикой."""
    with db_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT
                    s.student_id,
                    COUNT(r.id)              AS total_dictations,
                    COALESCE(SUM(r.errors), 0) AS total_errors,
                    ROUND(AVG(r.grade), 1)   AS avg_grade,
                    MAX(r.date)              AS last_date,
                    COUNT(DISTINCT r.date)   AS total_sessions
                FROM students s
                LEFT JOIN dictation_results r ON r.student_id = s.student_id
                GROUP BY s.student_id
                ORDER BY s.student_id
            """)
            rows = [dict(r) for r in cur.fetchall()]

    # Числовая сортировка: "Ученик 2" < "Ученик 10"
    rows.sort(key=lambda r: int(re.search(r'\d+', r["student_id"]).group())
              if re.search(r'\d+', r["student_id"]) else 0)
    return rows


def db_load_details(student_id: str) -> list[dict]:
    """Все диктанты ученика по датам."""
    with db_connect() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
            cur.execute("""
                SELECT r.date, r.dictation_name, r.errors, r.grade,
                       COALESCE(array_agg(m.word)
                           FILTER (WHERE m.word IS NOT NULL), '{}') AS mistakes
                FROM dictation_results r
                LEFT JOIN dictation_mistakes m ON m.result_id = r.id
                WHERE r.student_id = %s
                GROUP BY r.date, r.dictation_name, r.errors, r.grade, r.id
                ORDER BY r.date, r.id
            """, (student_id,))
            return [dict(r) for r in cur.fetchall()]


def db_delete_student(student_id: str):
    """Удаляет ученика и все его данные (CASCADE)."""
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM students WHERE student_id = %s", (student_id,))


# ══════════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ОТРИСОВКИ
# ══════════════════════════════════════════════════════════════════
def draw_rect_rounded(surf, color, rect, radius=8):
    pygame.draw.rect(surf, color, rect, border_radius=radius)


def draw_text(surf, text, font, color, x, y, max_w=None):
    if max_w:
        # Обрезаем текст с многоточием если не влезает
        while font.size(text)[0] > max_w and len(text) > 3:
            text = text[:-4] + "…"
    s = font.render(text, True, color)
    surf.blit(s, (x, y))
    return s.get_width()


def draw_text_center(surf, text, font, color, rect):
    s   = font.render(text, True, color)
    pos = (rect.x + (rect.w - s.get_width()) // 2,
           rect.y + (rect.h - s.get_height()) // 2)
    surf.blit(s, pos)


def grade_color(grade):
    if grade is None:
        return C["text_dim"]
    g = float(grade)
    if g >= 9:
        return C["grade_good"]
    elif g >= 7:
        return C["grade_mid"]
    return C["grade_bad"]


def grade_icon(grade):
    if grade is None:
        return "—"
    g = float(grade)
    if g >= 9:
        return "●"
    elif g >= 7:
        return "◑"
    return "○"


# ══════════════════════════════════════════════════════════════════
#  КНОПКА
# ══════════════════════════════════════════════════════════════════
class Button:
    def __init__(self, rect, label, color, hover_color, font=None, radius=8):
        self.rect        = pygame.Rect(rect)
        self.label       = label
        self.color       = color
        self.hover_color = hover_color
        self.font        = font or F_BODY
        self.radius      = radius

    def draw(self, surf, mouse_pos):
        hovered = self.rect.collidepoint(mouse_pos)
        color   = self.hover_color if hovered else self.color
        draw_rect_rounded(surf, color, self.rect, self.radius)
        draw_text_center(surf, self.label, self.font, C["text_bright"], self.rect)

    def is_clicked(self, pos):
        return self.rect.collidepoint(pos)


# ══════════════════════════════════════════════════════════════════
#  ДИАЛОГ ПОДТВЕРЖДЕНИЯ УДАЛЕНИЯ
# ══════════════════════════════════════════════════════════════════
class ConfirmDialog:
    def __init__(self, student_id: str):
        self.student_id = student_id
        dw, dh          = 420, 190
        self.rect        = pygame.Rect((W - dw) // 2, (H - dh) // 2, dw, dh)
        bw, bh           = 150, 40
        by               = self.rect.bottom - bh - 20
        self.btn_yes     = Button(
            (self.rect.x + 30, by, bw, bh),
            "Удалить", C["danger"], C["danger_dark"], radius=6
        )
        self.btn_no      = Button(
            (self.rect.right - 30 - bw, by, bw, bh),
            "Отмена", C["panel_border"], C["selected"], radius=6
        )

    def draw(self, surf, mouse_pos):
        # Затемнение фона
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 160))
        surf.blit(overlay, (0, 0))

        # Окно
        draw_rect_rounded(surf, C["confirm_bg"], self.rect, 12)
        pygame.draw.rect(surf, C["danger"], self.rect, 2, border_radius=12)

        # Текст
        draw_text(surf, "Подтвердите удаление", F_HEAD, C["text_bright"],
                  self.rect.x + 24, self.rect.y + 22)
        msg = f"Удалить «{self.student_id}»?"
        draw_text(surf, msg, F_BODY, C["text"],
                  self.rect.x + 24, self.rect.y + 62)
        draw_text(surf, "Все диктанты и ошибки будут удалены навсегда.",
                  F_SMALL, C["text_dim"],
                  self.rect.x + 24, self.rect.y + 90)

        self.btn_yes.draw(surf, mouse_pos)
        self.btn_no.draw(surf, mouse_pos)

    def handle_click(self, pos) -> str:
        """Возвращает 'yes', 'no' или ''."""
        if self.btn_yes.is_clicked(pos):
            return "yes"
        if self.btn_no.is_clicked(pos):
            return "no"
        return ""


# ══════════════════════════════════════════════════════════════════
#  ГЛАВНОЕ ПРИЛОЖЕНИЕ
# ══════════════════════════════════════════════════════════════════
class AdminPanel:
    def __init__(self):
        self.screen  = pygame.display.set_mode((W, H), pygame.RESIZABLE)
        pygame.display.set_caption("Панель администратора — Брайль")
        self.clock   = pygame.time.Clock()

        self.students: list[dict] = []
        self.selected_id: str | None = None
        self.details:  list[dict] = []

        self.list_scroll   = 0    # пиксельный сдвиг списка учеников
        self.detail_scroll = 0    # пиксельный сдвиг правой панели

        self.confirm_dialog: ConfirmDialog | None = None
        self.status_msg  = ""
        self.status_color = C["success"]
        self.status_timer = 0

        self._build_buttons()
        self._reload()

    # ── Кнопки ────────────────────────────────────────────────────
    def _build_buttons(self):
        self.btn_refresh = Button(
            (W - 200, 12, 90, 36),
            "⟳  Обновить", C["accent"], C["accent_dark"], radius=8
        )
        self.btn_delete = Button(
            (W - 105, 12, 90, 36),
            "Удалить", C["danger"], C["danger_dark"], radius=8
        )

    # ── Загрузка данных ───────────────────────────────────────────
    def _reload(self):
        try:
            self.students = db_load_students()
            self._set_status(f"Загружено учеников: {len(self.students)}", C["success"])
            # Если выбранный ученик исчез — снимаем выбор
            ids = {s["student_id"] for s in self.students}
            if self.selected_id not in ids:
                self.selected_id = None
                self.details     = []
        except Exception as e:
            self._set_status(f"Ошибка БД: {e}", C["danger"])

    def _load_details(self, student_id: str):
        try:
            self.details       = db_load_details(student_id)
            self.detail_scroll = 0
        except Exception as e:
            self._set_status(f"Ошибка загрузки деталей: {e}", C["danger"])

    def _set_status(self, msg: str, color):
        self.status_msg   = msg
        self.status_color = color
        self.status_timer = FPS * 4   # показываем 4 сек

    # ── Главный цикл ──────────────────────────────────────────────
    def run(self):
        while True:
            dt = self.clock.tick(FPS)
            if self.status_timer > 0:
                self.status_timer -= 1

            mouse = pygame.mouse.get_pos()

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

                elif event.type == pygame.VIDEORESIZE:
                    global W, H
                    W, H = event.w, event.h
                    self.screen = pygame.display.set_mode(
                        (W, H), pygame.RESIZABLE
                    )
                    self._build_buttons()

                elif event.type == pygame.MOUSEWHEEL:
                    if mouse[0] < LEFT_W:
                        # Прокрутка списка учеников
                        self.list_scroll = max(
                            0, min(
                                self.list_scroll - event.y * ROW_H,
                                max(0, len(self.students) * ROW_H - (H - LIST_TOP - 40))
                            )
                        )
                    else:
                        # Прокрутка деталей справа
                        self.detail_scroll = max(
                            0, self.detail_scroll - event.y * 24
                        )

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    self._handle_click(event.pos)

            self._draw(mouse)
            pygame.display.flip()

    # ── Клики ─────────────────────────────────────────────────────
    def _handle_click(self, pos):
        # Диалог подтверждения — приоритет
        if self.confirm_dialog:
            result = self.confirm_dialog.handle_click(pos)
            if result == "yes":
                self._do_delete(self.confirm_dialog.student_id)
                self.confirm_dialog = None
            elif result == "no":
                self.confirm_dialog = None
            return

        # Кнопка Обновить
        if self.btn_refresh.is_clicked(pos):
            self._reload()
            return

        # Кнопка Удалить
        if self.btn_delete.is_clicked(pos) and self.selected_id:
            self.confirm_dialog = ConfirmDialog(self.selected_id)
            return

        # Клик по строке ученика в левой панели
        if pos[0] < LEFT_W:
            idx = (pos[1] - LIST_TOP + self.list_scroll) // ROW_H
            if 0 <= idx < len(self.students):
                sid = self.students[idx]["student_id"]
                if sid == self.selected_id:
                    # Повторный клик — снимаем выбор
                    self.selected_id = None
                    self.details     = []
                else:
                    self.selected_id = sid
                    self._load_details(sid)

    def _do_delete(self, student_id: str):
        try:
            db_delete_student(student_id)
            self._set_status(f"Ученик «{student_id}» удалён.", C["success"])
            if self.selected_id == student_id:
                self.selected_id = None
                self.details     = []
            self._reload()
        except Exception as e:
            self._set_status(f"Ошибка удаления: {e}", C["danger"])

    # ── Отрисовка ─────────────────────────────────────────────────
    def _draw(self, mouse):
        self.screen.fill(C["bg"])
        self._draw_header(mouse)
        self._draw_left_panel(mouse)
        self._draw_right_panel()
        self._draw_status()

        if self.confirm_dialog:
            self.confirm_dialog.draw(self.screen, mouse)

    def _draw_header(self, mouse):
        # Полоса заголовка
        draw_rect_rounded(self.screen, C["panel"],
                          pygame.Rect(0, 0, W, HEADER_H), 0)
        pygame.draw.line(self.screen, C["panel_border"],
                         (0, HEADER_H), (W, HEADER_H), 1)

        draw_text(self.screen, "Панель администратора", F_TITLE,
                  C["text_bright"], PADDING, 16)

        total = len(self.students)
        badge_txt = f"{total} учеников"
        bw = F_BADGE.size(badge_txt)[0] + 20
        bx = PADDING + F_TITLE.size("Панель администратора")[0] + 16
        badge_rect = pygame.Rect(bx, 20, bw, 22)
        draw_rect_rounded(self.screen, C["accent"], badge_rect, 11)
        draw_text_center(self.screen, badge_txt, F_BADGE, C["text_bright"], badge_rect)

        self.btn_refresh.draw(self.screen, mouse)
        if self.selected_id:
            self.btn_delete.draw(self.screen, mouse)

    def _draw_left_panel(self, mouse):
        panel_rect = pygame.Rect(0, HEADER_H, LEFT_W, H - HEADER_H)
        draw_rect_rounded(self.screen, C["panel"], panel_rect, 0)
        pygame.draw.line(self.screen, C["panel_border"],
                         (LEFT_W, HEADER_H), (LEFT_W, H), 1)

        # Заголовок колонки
        draw_text(self.screen, "УЧЕНИКИ", F_BADGE, C["text_dim"],
                  PADDING, HEADER_H - 10)
        pygame.draw.line(self.screen, C["separator"],
                         (0, LIST_TOP - 2), (LEFT_W, LIST_TOP - 2), 1)

        # Клип-зона списка
        list_h  = H - LIST_TOP - 30
        clip    = pygame.Rect(0, LIST_TOP, LEFT_W - 10, list_h)
        self.screen.set_clip(clip)

        for i, s in enumerate(self.students):
            y   = LIST_TOP + i * ROW_H - self.list_scroll
            if y + ROW_H < LIST_TOP or y > H:
                continue
            row_rect = pygame.Rect(4, y, LEFT_W - 18, ROW_H - 2)
            sid = s["student_id"]
            is_sel = sid == self.selected_id
            is_hov = row_rect.collidepoint(mouse) and not is_sel

            if is_sel:
                draw_rect_rounded(self.screen, C["selected"], row_rect, 8)
                # Акцентная полоска слева
                pygame.draw.rect(self.screen, C["accent"],
                                 pygame.Rect(4, y + 6, 3, ROW_H - 14),
                                 border_radius=2)
            elif is_hov:
                draw_rect_rounded(self.screen, C["hover"], row_rect, 8)

            # Имя ученика
            draw_text(self.screen, sid, F_BODY,
                      C["text_bright"] if is_sel else C["text"],
                      22, y + 8, max_w=LEFT_W - 80)

            # Средняя оценка (маленький бейдж справа)
            avg = s["avg_grade"]
            if avg:
                avg_str = f"{float(avg):.1f}"
                gc      = grade_color(avg)
                draw_text(self.screen, avg_str, F_SMALL, gc,
                          LEFT_W - 44, y + 14)

            # Разделитель
            if not is_sel:
                pygame.draw.line(self.screen, C["separator"],
                                 (PADDING, y + ROW_H - 1),
                                 (LEFT_W - PADDING, y + ROW_H - 1), 1)

        self.screen.set_clip(None)

        # Скроллбар
        total_h = len(self.students) * ROW_H
        if total_h > list_h:
            sb_h   = max(30, list_h * list_h // total_h)
            sb_y   = LIST_TOP + self.list_scroll * list_h // total_h
            draw_rect_rounded(self.screen, C["scrollbar"],
                              pygame.Rect(LEFT_W - 6, LIST_TOP, 4, list_h), 2)
            draw_rect_rounded(self.screen, C["scrollbar_th"],
                              pygame.Rect(LEFT_W - 6, sb_y, 4, sb_h), 2)

    def _draw_right_panel(self):
        rx = LEFT_W + PADDING
        rw = W - LEFT_W - PADDING * 2

        if not self.selected_id:
            # Заглушка если никто не выбран
            msg1 = "Выберите ученика"
            msg2 = "из списка слева"
            cy   = H // 2 - 20
            draw_text(self.screen, msg1, F_HEAD, C["text_dim"],
                      rx + (rw - F_HEAD.size(msg1)[0]) // 2, cy)
            draw_text(self.screen, msg2, F_BODY, C["text_dim"],
                      rx + (rw - F_BODY.size(msg2)[0]) // 2, cy + 34)
            return

        # Находим данные выбранного ученика
        student = next((s for s in self.students
                        if s["student_id"] == self.selected_id), None)
        if not student:
            return

        # ── Шапка правой панели ───────────────────────────────────
        y = HEADER_H + PADDING

        draw_text(self.screen, self.selected_id, F_TITLE,
                  C["text_bright"], rx, y)
        y += 36

        # Карточки со статистикой
        stats = [
            ("Сессий",    str(student["total_sessions"] or 0), C["accent"]),
            ("Диктантов", str(student["total_dictations"] or 0), C["accent"]),
            ("Ошибок",    str(student["total_errors"] or 0),   C["grade_bad"]),
            ("Ср. оценка",
             f"{float(student['avg_grade']):.1f}" if student["avg_grade"] else "—",
             grade_color(student["avg_grade"])),
            ("Последняя сессия",
             student["last_date"] or "—", C["text_dim"]),
        ]
        card_w = min(130, (rw - PADDING * (len(stats) - 1)) // len(stats))
        cx     = rx
        for label, val, color in stats:
            card = pygame.Rect(cx, y, card_w, 64)
            draw_rect_rounded(self.screen, C["panel"], card, 8)
            pygame.draw.rect(self.screen, C["panel_border"], card, 1, border_radius=8)
            draw_text(self.screen, val, F_HEAD, color,
                      cx + 10, y + 10, max_w=card_w - 14)
            draw_text(self.screen, label, F_SMALL, C["text_dim"],
                      cx + 10, y + 38, max_w=card_w - 14)
            cx += card_w + PADDING
        y += 76

        # ── Список диктантов ──────────────────────────────────────
        draw_text(self.screen, "ИСТОРИЯ ДИКТАНТОВ", F_BADGE,
                  C["text_dim"], rx, y)
        y += 22

        pygame.draw.line(self.screen, C["separator"],
                         (rx, y), (W - PADDING, y), 1)
        y += 8

        # Клип-зона деталей
        detail_top = y
        clip_h     = H - detail_top - 30
        self.screen.set_clip(pygame.Rect(LEFT_W, detail_top, W - LEFT_W, clip_h))

        dy = detail_top - self.detail_scroll
        max_scroll = 0

        # Группируем по дате
        by_date: dict[str, list] = {}
        for r in self.details:
            by_date.setdefault(r["date"], []).append(r)

        for date, rows in by_date.items():
            # Дата-заголовок
            draw_rect_rounded(self.screen, C["panel"],
                              pygame.Rect(rx, dy, rw, 26), 6)
            draw_text(self.screen, f"📅 {date}", F_SMALL, C["accent"],
                      rx + 10, dy + 5)
            dy += 32

            for r in rows:
                grade  = r["grade"]
                errors = r["errors"]
                name   = r["dictation_name"]
                mis    = r["mistakes"] or []

                # Строка диктанта
                row_rect = pygame.Rect(rx, dy, rw, 28)
                draw_rect_rounded(self.screen, C["panel"], row_rect, 6)

                # Иконка оценки
                icon = grade_icon(grade)
                draw_text(self.screen, icon, F_BODY, grade_color(grade),
                          rx + 10, dy + 5)

                # Название диктанта
                draw_text(self.screen, name, F_BODY, C["text"],
                          rx + 30, dy + 5, max_w=rw // 2)

                # Оценка
                draw_text(self.screen, f"Оценка: {grade}", F_SMALL,
                          grade_color(grade), rx + rw // 2, dy + 8)

                # Ошибки
                err_txt = f"Ошибок: {errors}"
                draw_text(self.screen, err_txt, F_SMALL,
                          C["grade_bad"] if errors > 0 else C["text_dim"],
                          rx + rw // 2 + 120, dy + 8)
                dy += 32

                # Слова с ошибками
                if mis:
                    mis_txt = "Ошибки в словах: " + ", ".join(mis)
                    draw_text(self.screen, mis_txt, F_SMALL,
                              C["text_dim"], rx + 30, dy, max_w=rw - 40)
                    dy += 22

            dy += 8
            pygame.draw.line(self.screen, C["separator"],
                             (rx, dy), (W - PADDING, dy), 1)
            dy += 8

        max_scroll = max(0, dy + self.detail_scroll - H + 30)
        self.detail_scroll = min(self.detail_scroll, max_scroll)

        self.screen.set_clip(None)

        # Скроллбар деталей
        if max_scroll > 0:
            content_h = dy + self.detail_scroll - detail_top
            sb_h = max(30, clip_h * clip_h // content_h)
            sb_y = detail_top + self.detail_scroll * clip_h // content_h
            draw_rect_rounded(self.screen, C["scrollbar"],
                              pygame.Rect(W - 8, detail_top, 4, clip_h), 2)
            draw_rect_rounded(self.screen, C["scrollbar_th"],
                              pygame.Rect(W - 8, sb_y, 4, sb_h), 2)

    def _draw_status(self):
        if not self.status_msg or self.status_timer <= 0:
            return
        alpha  = min(255, self.status_timer * 4)
        surf   = F_SMALL.render(self.status_msg, True, self.status_color)
        surf.set_alpha(alpha)
        self.screen.blit(surf, (LEFT_W + PADDING, H - 22))


# ══════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    panel = AdminPanel()
    panel.run()